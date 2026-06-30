from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg

from quantgres.config import load_settings


@contextmanager
def connect(database_url: str | None = None) -> Iterator[psycopg.Connection[Any]]:
    url = database_url or load_settings().database_url
    with psycopg.connect(url) as connection:
        yield connection


def ping(database_url: str | None = None) -> str:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT version()")
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("PostgreSQL did not return a version row.")

    return str(row[0])
