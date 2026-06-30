from dataclasses import dataclass

from quantgres.db import connect

REQUIRED_EXTENSIONS = ("vector", "pg_trgm")


@dataclass(frozen=True)
class ExtensionStatus:
    name: str
    version: str


@dataclass(frozen=True)
class DatabaseRuntimeInfo:
    server_version: str
    server_version_num: int
    database_name: str
    user_name: str
    extensions: tuple[ExtensionStatus, ...]

    def missing_extensions(
        self,
        required_extensions: tuple[str, ...] = REQUIRED_EXTENSIONS,
    ) -> tuple[str, ...]:
        installed = {extension.name for extension in self.extensions}
        return tuple(name for name in required_extensions if name not in installed)


def load_runtime_info(database_url: str | None = None) -> DatabaseRuntimeInfo:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                version(),
                current_setting('server_version_num')::integer,
                current_database(),
                current_user
            """
        )
        runtime_row = cursor.fetchone()

        if runtime_row is None:
            raise RuntimeError("PostgreSQL did not return runtime metadata.")

        cursor.execute(
            """
            SELECT extname, extversion
            FROM pg_extension
            WHERE extname IN ('vector', 'pg_trgm')
            ORDER BY extname
            """
        )
        extension_rows = cursor.fetchall()

    return DatabaseRuntimeInfo(
        server_version=str(runtime_row[0]),
        server_version_num=int(runtime_row[1]),
        database_name=str(runtime_row[2]),
        user_name=str(runtime_row[3]),
        extensions=tuple(
            ExtensionStatus(name=str(row[0]), version=str(row[1])) for row in extension_rows
        ),
    )
