from dataclasses import dataclass
from os import getenv
from urllib.parse import urlsplit, urlunsplit

DEFAULT_DATABASE_URL = "postgresql://quantgres:quantgres@localhost:55432/quantgres"


@dataclass(frozen=True)
class Settings:
    app_env: str
    database_url: str


def load_settings() -> Settings:
    return Settings(
        app_env=getenv("QUANTGRES_ENV", "local"),
        database_url=getenv("QUANTGRES_DATABASE_URL", DEFAULT_DATABASE_URL),
    )


def mask_database_url(database_url: str) -> str:
    parsed = urlsplit(database_url)
    if parsed.password is None:
        return database_url

    username = parsed.username or ""
    hostname = parsed.hostname or ""
    netloc = f"{username}:***@{hostname}"

    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"

    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
