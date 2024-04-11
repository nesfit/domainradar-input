import psycopg2

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

    def output(self, domains: list[str]) -> list[str]:
        ret = []
        with psycopg2.connect(**self.db_connection_info) as conn:
            with conn.cursor() as curr:
                domains_to_insert = ",\n".join(
                    [f"('{domain}', NOW())" for domain in domains]
                )
                command = f"""
                INSERT INTO "domains_input" ("domain", "added")
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
