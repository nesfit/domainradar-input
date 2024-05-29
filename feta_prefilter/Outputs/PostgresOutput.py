import psycopg2
import json

from feta_prefilter.Outputs.BaseOutput import BaseOutput


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
        with psycopg2.connect(**self.db_connection_info) as conn:
            with conn.cursor() as curr:
                str_list = []
                for domain_info in domains:
                    domain = domain_info["domain"]
                    domain_data = domain_info["f_results"]
                    str_list.append(f"('{domain}', NOW(), '{json.dumps(domain_data)}')")

                domains_to_insert = ",\n".join(str_list)
                command = f"""
                INSERT INTO "domains_input" ("domain", "added", "filter_output")
                VALUES
                    {domains_to_insert}
                ON CONFLICT ("domain")
                DO UPDATE SET
                    added = NOW()
                RETURNING *;
                """
                curr.execute(command)
                ret = [row[1] for row in curr.fetchall()]
        return ret
