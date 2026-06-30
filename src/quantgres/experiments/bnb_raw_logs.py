from dataclasses import dataclass
from pathlib import Path

from psycopg.types.json import Jsonb

from quantgres.db import connect, query_text
from quantgres.onchain.bnb_rpc import (
    BNB_CHAIN_ID,
    DEFAULT_BNB_RPC_URL,
    BnbRawLog,
    get_logs,
    load_bnb_rpc_info,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ONCHAIN_SQL_DIR = PROJECT_ROOT / "sql" / "onchain"
RAW_LOGS_SCHEMA_SQL = ONCHAIN_SQL_DIR / "001_raw_logs_schema.sql"

UPSERT_RAW_LOG_SQL = """
INSERT INTO onchain.raw_logs (
    chain_id,
    rpc_url,
    address,
    block_number,
    block_hash,
    transaction_hash,
    transaction_index,
    log_index,
    data,
    topics,
    raw_log,
    from_block,
    to_block
)
VALUES (
    %(chain_id)s,
    %(rpc_url)s,
    %(address)s,
    %(block_number)s,
    %(block_hash)s,
    %(transaction_hash)s,
    %(transaction_index)s,
    %(log_index)s,
    %(data)s,
    %(topics)s,
    %(raw_log)s,
    %(from_block)s,
    %(to_block)s
)
ON CONFLICT (chain_id, transaction_hash, log_index) DO UPDATE
SET rpc_url = EXCLUDED.rpc_url,
    address = EXCLUDED.address,
    block_number = EXCLUDED.block_number,
    block_hash = EXCLUDED.block_hash,
    transaction_index = EXCLUDED.transaction_index,
    data = EXCLUDED.data,
    topics = EXCLUDED.topics,
    raw_log = EXCLUDED.raw_log,
    from_block = EXCLUDED.from_block,
    to_block = EXCLUDED.to_block,
    ingested_at = now()
"""


@dataclass(frozen=True)
class BnbLogIngestionResult:
    rpc_url: str
    chain_id: int
    from_block: int
    to_block: int
    address: str | None
    topic0: str | None
    rows_fetched: int
    rows_upserted: int


def read_sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def ensure_raw_logs_schema(database_url: str | None = None) -> None:
    with connect(database_url) as connection:
        connection.execute(query_text(read_sql(RAW_LOGS_SCHEMA_SQL)))


def raw_log_to_params(log: BnbRawLog) -> dict[str, object]:
    return {
        "chain_id": log.chain_id,
        "rpc_url": log.rpc_url,
        "address": log.address,
        "block_number": log.block_number,
        "block_hash": log.block_hash,
        "transaction_hash": log.transaction_hash,
        "transaction_index": log.transaction_index,
        "log_index": log.log_index,
        "data": log.data,
        "topics": Jsonb(list(log.topics)),
        "raw_log": Jsonb(log.raw_log),
        "from_block": log.from_block,
        "to_block": log.to_block,
    }


def upsert_raw_logs(
    logs: tuple[BnbRawLog, ...],
    database_url: str | None = None,
) -> int:
    ensure_raw_logs_schema(database_url)
    if not logs:
        return 0

    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.executemany(
            query_text(UPSERT_RAW_LOG_SQL),
            [raw_log_to_params(log) for log in logs],
        )

    return len(logs)


def fetch_and_store_bnb_logs(
    *,
    from_block: int,
    to_block: int,
    address: str | None = None,
    topic0: str | None = None,
    rpc_url: str = DEFAULT_BNB_RPC_URL,
    database_url: str | None = None,
) -> BnbLogIngestionResult:
    info = load_bnb_rpc_info(rpc_url=rpc_url)
    if info.chain_id != BNB_CHAIN_ID:
        raise RuntimeError(f"Expected BNB Chain id {BNB_CHAIN_ID}, got {info.chain_id}.")

    logs = get_logs(
        rpc_url=rpc_url,
        chain_id=info.chain_id,
        from_block=from_block,
        to_block=to_block,
        address=address,
        topic0=topic0,
    )
    rows_upserted = upsert_raw_logs(logs, database_url)

    return BnbLogIngestionResult(
        rpc_url=rpc_url,
        chain_id=info.chain_id,
        from_block=from_block,
        to_block=to_block,
        address=address,
        topic0=topic0,
        rows_fetched=len(logs),
        rows_upserted=rows_upserted,
    )
