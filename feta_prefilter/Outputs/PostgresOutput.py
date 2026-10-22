import logging
import time

import psycopg2
from psycopg2.extras import Json

from feta_prefilter.Outputs.BaseOutput import BaseOutput

logger = logging.getLogger(__name__)

# 10 parameters per origin row; staying at 1000 keeps each INSERT far below the
# 65535-parameter limit of the protocol.
ORIGIN_BATCH_ROWS = 1000

# The Connect source connector re-emits a row when updated_at moves. A domain that is
# seen in every collect window would otherwise rewrite its Mongo document every few
# seconds, so updated_at advances at most once per interval.
ORIGIN_BUMP_INTERVAL = "1 hour"

ORIGIN_ERROR_LOG_INTERVAL_S = 300

_ORIGIN_INSERT = """
        INSERT INTO "domain_origin" (
            "domain", "source_id", "source_type", "source_url", "origin_url",
            "threat_type", "label_derived_from", "external_id", "context",
            "sent_to_pipeline"
        )
        VALUES
            {values}
        ON CONFLICT ("domain", "source_id", "external_id")
        DO UPDATE SET
            last_seen = NOW(),
            sent_to_pipeline = EXCLUDED.sent_to_pipeline,
            source_type = EXCLUDED.source_type,
            source_url = COALESCE(EXCLUDED.source_url, domain_origin.source_url),
            origin_url = COALESCE(EXCLUDED.origin_url, domain_origin.origin_url),
            threat_type = COALESCE(EXCLUDED.threat_type, domain_origin.threat_type),
            label_derived_from = COALESCE(
                EXCLUDED.label_derived_from, domain_origin.label_derived_from
            ),
            context = COALESCE(EXCLUDED.context, domain_origin.context),
            updated_at = CASE
                WHEN domain_origin.last_seen < NOW() - INTERVAL '{bump_interval}'
                    THEN NOW()
                ELSE domain_origin.updated_at
            END;
        """


class PostgresOutput(BaseOutput):
    def __init__(
            self, host: str, port: int, username: str, password: str, database: str
    ):
        self.db_connection_info = {
            "database": database,
            "host": host,
            "port": port,
            "user": username,
            "password": password,
        }
        self._origin_error_next_log = 0.0

    def output(self, domains: list[dict]) -> list[str]:
        ret = []
        if not domains:
            return ret
        command, param_list = None, None
        try:
            command, param_list = self.build_query(domains)
            with psycopg2.connect(**self.db_connection_info) as conn:
                logger.debug("Connected")
                with conn.cursor() as curr:
                    curr.execute(command, param_list)
                    rows = curr.fetchall()
                    ret = [row[0] for row in rows]
                    # A domain reaches the pipeline only while its *stored* filter_output
                    # is NULL (Connect reads exactly that), so the stored value decides
                    # whether its origins are sent downstream, not this batch's result.
                    sent = {row[0]: row[1] is None for row in rows}
                    self.write_origins(curr, domains, sent)
                    logger.debug("Executed %s", command)
        except Exception:
            logger.exception("Exception raised while sending data to postgres")
            logger.error("Postgres command: %s", command)
            logger.error("Postgres command params: %s values", len(param_list or []))
        return ret

    def write_origins(
        self, curr, domains: list[dict], sent_to_pipeline: dict[str, bool]
    ) -> None:
        """Write the provenance registry in the same transaction as domains_input.

        A failure here (the table not deployed yet, one bad row) must never stop the
        domains themselves: every statement runs in a savepoint that is rolled back on
        error, so the batch still commits without provenance instead of being lost.
        """
        chunks = self.build_origin_queries(domains, sent_to_pipeline)
        for command, param_list in chunks:
            curr.execute("SAVEPOINT domain_origin")
            try:
                curr.execute(command, param_list)
                curr.execute("RELEASE SAVEPOINT domain_origin")
            except Exception:
                curr.execute("ROLLBACK TO SAVEPOINT domain_origin")
                self._log_origin_error()

    def _log_origin_error(self) -> None:
        now = time.monotonic()
        if now < self._origin_error_next_log:
            return
        self._origin_error_next_log = now + ORIGIN_ERROR_LOG_INTERVAL_S
        logger.exception(
            "Failed to write domain origins, ingest continues without provenance"
        )

    def build_query(self, domains: list[dict]) -> tuple[str, list]:
        str_list = []
        param_list = []
        for domain_info in domains:
            domain = domain_info["domain"]
            domain_data = domain_info["f_results"]
            if domain_data:
                str_list.append(r"(%s, NOW(), %s)")
                param_list.extend([domain, Json(domain_data)])
            else:
                str_list.append(r"(%s, NOW(), NULL)")
                param_list.extend([domain])

        domains_to_insert = ",\n".join(str_list)
        command = f"""
        INSERT INTO "domains_input" ("domain", "last_seen", "filter_output")
        VALUES
            {domains_to_insert}
        ON CONFLICT ("domain")
        DO UPDATE SET
            last_seen = NOW()
        RETURNING "domain", "filter_output";
        """
        return command, param_list

    def build_origin_queries(
        self, domains: list[dict], sent_to_pipeline: dict[str, bool]
    ) -> list[tuple[str, list]]:
        """INSERT statements for the origin registry, batched by ORIGIN_BATCH_ROWS."""
        value_rows = []
        param_list = []
        for domain_info in domains:
            domain = domain_info["domain"]
            origins = domain_info.get("origins") or []
            if not origins:
                continue
            for origin in origins:
                value_rows.append("(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)")
                param_list.extend(
                    [
                        domain,
                        origin["sourceId"],
                        origin.get("sourceType") or "unknown",
                        origin.get("sourceUrl"),
                        origin.get("originUrl"),
                        origin.get("threatType"),
                        origin.get("labelDerivedFrom"),
                        origin.get("externalId") or "",
                        Json(origin["context"]) if origin.get("context") else None,
                        sent_to_pipeline.get(domain, False),
                    ]
                )

        commands = []
        params_per_row = 10
        for start in range(0, len(value_rows), ORIGIN_BATCH_ROWS):
            batch = value_rows[start:start + ORIGIN_BATCH_ROWS]
            params = param_list[
                start * params_per_row:(start + ORIGIN_BATCH_ROWS) * params_per_row
            ]
            commands.append(
                (
                    _ORIGIN_INSERT.format(
                        values=",\n".join(batch), bump_interval=ORIGIN_BUMP_INTERVAL
                    ),
                    params,
                )
            )
        return commands
