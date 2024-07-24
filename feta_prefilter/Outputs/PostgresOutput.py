import json
import logging

import psycopg2
from psycopg2.extras import Json

from feta_prefilter.Outputs.BaseOutput import BaseOutput

logger = logging.getLogger(__name__)

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

    def output(self, domains: list[dict]) -> list[str]:
        ret = []
        if not domains:
            return ret
        try:
            command, param_list = self.build_query(domains)
            with psycopg2.connect(**self.db_connection_info) as conn:
                with conn.cursor() as curr:
                    curr.execute(command, param_list)
                    ret = [row[1] for row in curr.fetchall()]
        except Exception:
            logger.exception("Exception raised while sending data to postgres")
            logger.error(f"Postgres command: {command}")
            logger.error(f"Postgres command params: {param_list}")
        return ret

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
        RETURNING *;
        """
        return command, param_list
