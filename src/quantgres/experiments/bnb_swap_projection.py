from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from psycopg.types.json import Jsonb

from quantgres.db import connect, query_text
from quantgres.experiments.bnb_raw_logs import BnbLogIngestionResult, fetch_and_store_bnb_logs
from quantgres.onchain.bnb_rpc import BNB_CHAIN_ID, DEFAULT_BNB_RPC_URL

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFI_SQL_DIR = PROJECT_ROOT / "sql" / "defi"
SWAP_EVENTS_SCHEMA_SQL = DEFI_SQL_DIR / "001_swap_events_schema.sql"

PANCAKESWAP_V2 = "pancakeswap_v2"
PANCAKESWAP_V2_WBNB_USDT_PAIR = "0x16b9a82891338f9ba80e2d6970fdda79d1eb0dae"
PANCAKESWAP_V2_SWAP_TOPIC0 = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"
PANCAKESWAP_SAMPLE_BLOCK = 107270817
UINT256_HEX_WIDTH = 64
SWAP_AMOUNT_WORD_COUNT = 4

SELECT_RAW_SWAP_LOGS_SQL = """
SELECT
    chain_id,
    address,
    block_number,
    block_hash,
    transaction_hash,
    transaction_index,
    log_index,
    data,
    topics,
    raw_log
FROM onchain.raw_logs
WHERE chain_id = %(chain_id)s
  AND address = %(pair_address)s
  AND topics ->> 0 = %(topic0)s
  AND block_number BETWEEN %(from_block)s AND %(to_block)s
ORDER BY block_number, log_index
"""

UPSERT_SWAP_EVENT_SQL = """
INSERT INTO defi.swap_events (
    chain_id,
    dex,
    pair_address,
    block_number,
    block_hash,
    transaction_hash,
    transaction_index,
    log_index,
    sender,
    recipient,
    amount0_in,
    amount1_in,
    amount0_out,
    amount1_out,
    raw_log
)
VALUES (
    %(chain_id)s,
    %(dex)s,
    %(pair_address)s,
    %(block_number)s,
    %(block_hash)s,
    %(transaction_hash)s,
    %(transaction_index)s,
    %(log_index)s,
    %(sender)s,
    %(recipient)s,
    %(amount0_in)s,
    %(amount1_in)s,
    %(amount0_out)s,
    %(amount1_out)s,
    %(raw_log)s
)
ON CONFLICT (chain_id, transaction_hash, log_index) DO UPDATE
SET dex = EXCLUDED.dex,
    pair_address = EXCLUDED.pair_address,
    block_number = EXCLUDED.block_number,
    block_hash = EXCLUDED.block_hash,
    transaction_index = EXCLUDED.transaction_index,
    sender = EXCLUDED.sender,
    recipient = EXCLUDED.recipient,
    amount0_in = EXCLUDED.amount0_in,
    amount1_in = EXCLUDED.amount1_in,
    amount0_out = EXCLUDED.amount0_out,
    amount1_out = EXCLUDED.amount1_out,
    raw_log = EXCLUDED.raw_log,
    projected_at = now()
"""

SELECT_SWAP_EVENTS_SQL = """
SELECT
    chain_id,
    dex,
    pair_address,
    block_number,
    transaction_hash,
    log_index,
    sender,
    recipient,
    amount0_in,
    amount1_in,
    amount0_out,
    amount1_out
FROM defi.swap_events
WHERE chain_id = %(chain_id)s
  AND dex = %(dex)s
  AND pair_address = %(pair_address)s
  AND block_number BETWEEN %(from_block)s AND %(to_block)s
ORDER BY block_number, log_index
LIMIT %(limit)s
"""


@dataclass(frozen=True)
class SwapAmounts:
    amount0_in: Decimal
    amount1_in: Decimal
    amount0_out: Decimal
    amount1_out: Decimal


@dataclass(frozen=True)
class RawSwapLogRow:
    chain_id: int
    pair_address: str
    block_number: int
    block_hash: str
    transaction_hash: str
    transaction_index: int
    log_index: int
    data: str
    topics: tuple[str, ...]
    raw_log: dict[str, Any]


@dataclass(frozen=True)
class SwapEventRow:
    chain_id: int
    dex: str
    pair_address: str
    block_number: int
    transaction_hash: str
    log_index: int
    sender: str
    recipient: str
    amount0_in: Decimal
    amount1_in: Decimal
    amount0_out: Decimal
    amount1_out: Decimal


@dataclass(frozen=True)
class BnbSwapProjectionSmokeResult:
    ingestion: BnbLogIngestionResult
    projected_events: int
    sample_events: tuple[SwapEventRow, ...]


def read_sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def ensure_swap_events_schema(database_url: str | None = None) -> None:
    with connect(database_url) as connection:
        connection.execute(query_text(read_sql(SWAP_EVENTS_SCHEMA_SQL)))


def normalize_hex(value: str, *, expected_body_length: int) -> str:
    normalized = value.lower()
    if not normalized.startswith("0x"):
        raise ValueError(f"Expected 0x-prefixed hex value, got {value!r}.")

    body = normalized[2:]
    if len(body) != expected_body_length:
        raise ValueError(f"Expected hex body length {expected_body_length}, got {len(body)}.")

    if not all(character in "0123456789abcdef" for character in body):
        raise ValueError(f"Expected hex value, got {value!r}.")

    return normalized


def topic_to_address(topic: str) -> str:
    normalized = normalize_hex(topic, expected_body_length=UINT256_HEX_WIDTH)
    return "0x" + normalized[-40:]


def decode_swap_amounts(data: str) -> SwapAmounts:
    normalized = normalize_hex(
        data,
        expected_body_length=UINT256_HEX_WIDTH * SWAP_AMOUNT_WORD_COUNT,
    )
    body = normalized[2:]
    words = [
        Decimal(int(body[index : index + UINT256_HEX_WIDTH], 16))
        for index in range(0, len(body), UINT256_HEX_WIDTH)
    ]

    if len(words) != SWAP_AMOUNT_WORD_COUNT:
        raise ValueError(f"Expected {SWAP_AMOUNT_WORD_COUNT} Swap amount words.")

    return SwapAmounts(
        amount0_in=words[0],
        amount1_in=words[1],
        amount0_out=words[2],
        amount1_out=words[3],
    )


def coerce_topics(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(topic, str) for topic in value):
        raise TypeError("Expected raw log topics to be a list of strings.")

    return tuple(cast("list[str]", value))


def coerce_raw_log(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError("Expected raw_log to be a JSON object.")

    return cast("dict[str, Any]", value)


def row_to_raw_swap_log(row: tuple[Any, ...]) -> RawSwapLogRow:
    return RawSwapLogRow(
        chain_id=int(row[0]),
        pair_address=str(row[1]).lower(),
        block_number=int(row[2]),
        block_hash=str(row[3]),
        transaction_hash=str(row[4]),
        transaction_index=int(row[5]),
        log_index=int(row[6]),
        data=str(row[7]),
        topics=coerce_topics(row[8]),
        raw_log=coerce_raw_log(row[9]),
    )


def decode_raw_swap_log(
    raw_log: RawSwapLogRow,
    *,
    dex: str = PANCAKESWAP_V2,
    topic0: str = PANCAKESWAP_V2_SWAP_TOPIC0,
) -> dict[str, object]:
    if len(raw_log.topics) < 3:
        raise ValueError("Swap log must include topic0, indexed sender, and indexed recipient.")

    if raw_log.topics[0].lower() != topic0.lower():
        raise ValueError(f"Unexpected Swap topic0 {raw_log.topics[0]!r}.")

    amounts = decode_swap_amounts(raw_log.data)
    return {
        "chain_id": raw_log.chain_id,
        "dex": dex,
        "pair_address": raw_log.pair_address,
        "block_number": raw_log.block_number,
        "block_hash": raw_log.block_hash,
        "transaction_hash": raw_log.transaction_hash,
        "transaction_index": raw_log.transaction_index,
        "log_index": raw_log.log_index,
        "sender": topic_to_address(raw_log.topics[1]),
        "recipient": topic_to_address(raw_log.topics[2]),
        "amount0_in": amounts.amount0_in,
        "amount1_in": amounts.amount1_in,
        "amount0_out": amounts.amount0_out,
        "amount1_out": amounts.amount1_out,
        "raw_log": Jsonb(raw_log.raw_log),
    }


def load_raw_swap_logs(
    *,
    from_block: int,
    to_block: int,
    pair_address: str = PANCAKESWAP_V2_WBNB_USDT_PAIR,
    topic0: str = PANCAKESWAP_V2_SWAP_TOPIC0,
    chain_id: int = BNB_CHAIN_ID,
    database_url: str | None = None,
) -> tuple[RawSwapLogRow, ...]:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            query_text(SELECT_RAW_SWAP_LOGS_SQL),
            {
                "chain_id": chain_id,
                "pair_address": pair_address.lower(),
                "topic0": topic0.lower(),
                "from_block": from_block,
                "to_block": to_block,
            },
        )
        rows = cursor.fetchall()

    return tuple(row_to_raw_swap_log(row) for row in rows)


def upsert_swap_events(
    raw_logs: tuple[RawSwapLogRow, ...],
    *,
    dex: str = PANCAKESWAP_V2,
    topic0: str = PANCAKESWAP_V2_SWAP_TOPIC0,
    database_url: str | None = None,
) -> int:
    ensure_swap_events_schema(database_url)
    if not raw_logs:
        return 0

    params = [decode_raw_swap_log(raw_log, dex=dex, topic0=topic0) for raw_log in raw_logs]
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.executemany(query_text(UPSERT_SWAP_EVENT_SQL), params)

    return len(params)


def load_swap_events(
    *,
    from_block: int,
    to_block: int,
    pair_address: str = PANCAKESWAP_V2_WBNB_USDT_PAIR,
    dex: str = PANCAKESWAP_V2,
    chain_id: int = BNB_CHAIN_ID,
    limit: int = 5,
    database_url: str | None = None,
) -> tuple[SwapEventRow, ...]:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            query_text(SELECT_SWAP_EVENTS_SQL),
            {
                "chain_id": chain_id,
                "dex": dex,
                "pair_address": pair_address.lower(),
                "from_block": from_block,
                "to_block": to_block,
                "limit": limit,
            },
        )
        rows = cursor.fetchall()

    return tuple(
        SwapEventRow(
            chain_id=int(row[0]),
            dex=str(row[1]),
            pair_address=str(row[2]),
            block_number=int(row[3]),
            transaction_hash=str(row[4]),
            log_index=int(row[5]),
            sender=str(row[6]),
            recipient=str(row[7]),
            amount0_in=row[8],
            amount1_in=row[9],
            amount0_out=row[10],
            amount1_out=row[11],
        )
        for row in rows
    )


def run_bnb_swap_projection_smoke(
    *,
    from_block: int = PANCAKESWAP_SAMPLE_BLOCK,
    to_block: int = PANCAKESWAP_SAMPLE_BLOCK,
    pair_address: str = PANCAKESWAP_V2_WBNB_USDT_PAIR,
    topic0: str = PANCAKESWAP_V2_SWAP_TOPIC0,
    rpc_url: str = DEFAULT_BNB_RPC_URL,
    database_url: str | None = None,
) -> BnbSwapProjectionSmokeResult:
    ingestion = fetch_and_store_bnb_logs(
        from_block=from_block,
        to_block=to_block,
        address=pair_address,
        topic0=topic0,
        rpc_url=rpc_url,
        database_url=database_url,
    )
    raw_logs = load_raw_swap_logs(
        from_block=from_block,
        to_block=to_block,
        pair_address=pair_address,
        topic0=topic0,
        chain_id=ingestion.chain_id,
        database_url=database_url,
    )
    projected_events = upsert_swap_events(
        raw_logs,
        topic0=topic0,
        database_url=database_url,
    )

    return BnbSwapProjectionSmokeResult(
        ingestion=ingestion,
        projected_events=projected_events,
        sample_events=load_swap_events(
            from_block=from_block,
            to_block=to_block,
            pair_address=pair_address,
            chain_id=ingestion.chain_id,
            database_url=database_url,
        ),
    )
