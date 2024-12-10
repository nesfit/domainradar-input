import logging
from urllib.parse import urlparse

import psycopg2
from psycopg2 import sql

from feta_prefilter.Filters.BaseFilter import FilterAction
from feta_prefilter.Filters.BaseFilter import BaseFilter

logger = logging.getLogger(__name__)


class CustomPostgresFilter(BaseFilter):
    def __init__(
        self,
        filter_name: str,
        host: str,
        port: int,
        username: str,
        password: str,
        database: str,
        filter_table_name: str,
        domains_table_name: str,
        filter_result_action=FilterAction.DROP,
    ):
        super().__init__(filter_name, filter_result_action)
        self.db_connection_info = {
            "database": database,
            "host": host,
            "port": port,
            "user": username,
            "password": password,
        }
        self.filter_table_name = filter_table_name
        self.domains_table_name = domains_table_name

        domains = self.load_domains()

        for domain in domains:
            reversed_domain = ".".join(reversed(domain.strip().split(".")))
            self.suffix_trie.add(reversed_domain.lower())

    def load_domains(self):
        try:
            command, param_list = self.build_query()
            with psycopg2.connect(**self.db_connection_info) as conn:
                with conn.cursor() as curr:
                    curr.execute(
                        sql.SQL(command).format(
                            dt=sql.Identifier(self.domains_table_name),
                            ft=sql.Identifier(self.filter_table_name),
                        ),
                        param_list,
                    )
                    ret = [row[0] for row in curr.fetchall()]
                    return ret
        except Exception:
            logger.exception("Exception raised while sending data to postgres")
            logger.error(f"Postgres command: {command}")
            logger.error(f"Postgres command params: {param_list}")

    def build_query(self) -> tuple[str, list]:
        param_list = [self.filter_name]

        command = """
        SELECT dt.domain_name
        FROM {dt} AS dt
        JOIN {ft} as ft
            ON dt.custom_prefilter_id = ft.id
        WHERE
            ft.name = %s
            AND ft.enabled = false
        """
        return command, param_list
