from dataclasses import dataclass
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

from quantgres.db import connect, query_text
from quantgres.experiments.binance_candles import BINANCE_SOURCE, fetch_and_store_binance_klines
from quantgres.experiments.bnb_swap_corpus import run_bnb_swap_corpus_smoke
from quantgres.experiments.olap_return_panel import build_binance_kline_window_ms

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DOCUMENT_SQL_DIR = PROJECT_ROOT / "sql" / "documents"
RAW_PAYLOADS_SCHEMA_SQL = DOCUMENT_SQL_DIR / "001_raw_payloads_schema.sql"

PANCAKESWAP_V2_WBNB_USDT_PAIR = "0x16b9a82891338f9ba80e2d6970fdda79d1eb0dae"
PANCAKESWAP_V2_SWAP_TOPIC0 = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"
PANCAKESWAP_SAMPLE_BLOCK = 107270817
PANCAKESWAP_V2 = "pancakeswap_v2"

INSERT_BINANCE_DOCUMENTS_SQL = """
WITH latest_candles AS (
    SELECT *
    FROM time_series.candles_1m
    WHERE source = %(source)s
      AND symbol = %(symbol)s
    ORDER BY ts DESC
    LIMIT %(limit)s
)
INSERT INTO documents.raw_payloads (
    source,
    external_id,
    observed_at,
    symbol,
    chain_id,
    payload
)
SELECT
    'binance_kline',
    concat(symbol, ':', extract(epoch from ts)::bigint::text),
    ts,
    symbol,
    NULL,
    jsonb_build_object(
        'source', source,
        'symbol', symbol,
        'ts', ts,
        'close_ts', close_ts,
        'open_price', open_price::text,
        'high_price', high_price::text,
        'low_price', low_price::text,
        'close_price', close_price::text,
        'volume', volume::text,
        'quote_volume', quote_volume::text,
        'trade_count', trade_count,
        'taker_buy_base_volume', taker_buy_base_volume::text,
        'taker_buy_quote_volume', taker_buy_quote_volume::text
    )
FROM latest_candles
ON CONFLICT (source, external_id) DO UPDATE
SET observed_at = EXCLUDED.observed_at,
    symbol = EXCLUDED.symbol,
    chain_id = EXCLUDED.chain_id,
    payload = EXCLUDED.payload,
    ingested_at = now()
"""

INSERT_BNB_LOG_DOCUMENTS_SQL = """
WITH latest_logs AS (
    SELECT *
    FROM onchain.raw_logs
    WHERE chain_id = %(chain_id)s
      AND address = %(address)s
      AND topics ->> 0 = %(topic0)s
    ORDER BY block_number DESC, log_index DESC
    LIMIT %(limit)s
)
INSERT INTO documents.raw_payloads (
    source,
    external_id,
    observed_at,
    symbol,
    chain_id,
    payload
)
SELECT
    'bnb_rpc_log',
    concat(chain_id::text, ':', transaction_hash, ':', log_index::text),
    ingested_at,
    NULL,
    chain_id,
    raw_log
        || jsonb_build_object(
            'source', 'bnb_rpc_log',
            'chain_id', chain_id,
            'from_block', from_block,
            'to_block', to_block
        )
FROM latest_logs
ON CONFLICT (source, external_id) DO UPDATE
SET observed_at = EXCLUDED.observed_at,
    symbol = EXCLUDED.symbol,
    chain_id = EXCLUDED.chain_id,
    payload = EXCLUDED.payload,
    ingested_at = now()
"""

INSERT_BNB_SWAP_CORPUS_DOCUMENTS_SQL = """
WITH latest_swaps AS (
    SELECT *
    FROM defi.swap_events
    WHERE chain_id = %(chain_id)s
      AND dex = %(dex)s
      AND pair_address = %(pair_address)s
      AND block_timestamp IS NOT NULL
    ORDER BY block_timestamp DESC, block_number DESC, log_index DESC
    LIMIT %(limit)s
)
INSERT INTO documents.raw_payloads (
    source,
    external_id,
    observed_at,
    symbol,
    chain_id,
    payload
)
SELECT
    'bnb_swap_corpus',
    concat(chain_id::text, ':', transaction_hash, ':', log_index::text),
    block_timestamp,
    NULL,
    chain_id,
    jsonb_build_object(
        'source', 'bnb_swap_corpus',
        'chain_id', chain_id,
        'dex', dex,
        'pair_address', pair_address,
        'block_number', block_number,
        'block_hash', block_hash,
        'block_timestamp', block_timestamp,
        'transaction_hash', transaction_hash,
        'transaction_index', transaction_index,
        'log_index', log_index,
        'sender', sender,
        'recipient', recipient,
        'amount0_in', amount0_in::text,
        'amount1_in', amount1_in::text,
        'amount0_out', amount0_out::text,
        'amount1_out', amount1_out::text
    )
FROM latest_swaps
ON CONFLICT (source, external_id) DO UPDATE
SET observed_at = EXCLUDED.observed_at,
    symbol = EXCLUDED.symbol,
    chain_id = EXCLUDED.chain_id,
    payload = EXCLUDED.payload,
    ingested_at = now()
"""

COUNT_DOCUMENTS_SQL = """
SELECT source, count(*)::integer
FROM documents.raw_payloads
GROUP BY source
ORDER BY source
"""

BNB_CONTAINMENT_QUERY = """
SELECT count(*)::integer
FROM documents.raw_payloads
WHERE source = 'bnb_swap_corpus'
  AND payload @> %s::jsonb
"""

BNB_CONTAINMENT_FILTER = {"pair_address": PANCAKESWAP_V2_WBNB_USDT_PAIR}

EXPLAIN_BNB_CONTAINMENT_QUERY = f"""
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
{BNB_CONTAINMENT_QUERY}
"""


@dataclass(frozen=True)
class JsonbPlanSummary:
    root_node_type: str
    execution_time_ms: float
    planning_time_ms: float


@dataclass(frozen=True)
class JsonbDocumentSmokeResult:
    binance_documents_upserted: int
    bnb_documents_upserted: int
    source_counts: tuple[tuple[str, int], ...]
    bnb_containment_count: int
    plan: JsonbPlanSummary


def read_sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def ensure_document_schema(database_url: str | None = None) -> None:
    with connect(database_url) as connection:
        connection.execute(query_text(read_sql(RAW_PAYLOADS_SCHEMA_SQL)))


def upsert_binance_documents(
    *,
    symbol: str,
    limit: int,
    database_url: str | None = None,
) -> int:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            query_text(INSERT_BINANCE_DOCUMENTS_SQL),
            {"source": BINANCE_SOURCE, "symbol": symbol.upper(), "limit": limit},
        )
        return cursor.rowcount


def upsert_bnb_log_documents(
    *,
    limit: int,
    database_url: str | None = None,
) -> int:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            query_text(INSERT_BNB_LOG_DOCUMENTS_SQL),
            {
                "chain_id": 56,
                "address": PANCAKESWAP_V2_WBNB_USDT_PAIR,
                "topic0": PANCAKESWAP_V2_SWAP_TOPIC0,
                "limit": limit,
            },
        )
        return cursor.rowcount


def upsert_bnb_swap_corpus_documents(
    *,
    limit: int,
    database_url: str | None = None,
) -> int:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            query_text(INSERT_BNB_SWAP_CORPUS_DOCUMENTS_SQL),
            {
                "chain_id": 56,
                "dex": PANCAKESWAP_V2,
                "pair_address": PANCAKESWAP_V2_WBNB_USDT_PAIR,
                "limit": limit,
            },
        )
        return cursor.rowcount


def load_source_counts(database_url: str | None = None) -> tuple[tuple[str, int], ...]:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(query_text(COUNT_DOCUMENTS_SQL))
        rows = cursor.fetchall()

    return tuple((str(row[0]), int(row[1])) for row in rows)


def load_bnb_containment_count(database_url: str | None = None) -> int:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            query_text(BNB_CONTAINMENT_QUERY),
            (Jsonb(BNB_CONTAINMENT_FILTER),),
        )
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("JSONB containment query returned no row.")

    return int(row[0])


def load_bnb_containment_plan(database_url: str | None = None) -> JsonbPlanSummary:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            query_text(EXPLAIN_BNB_CONTAINMENT_QUERY),
            (Jsonb({"address": PANCAKESWAP_V2_WBNB_USDT_PAIR}),),
        )
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("EXPLAIN did not return a plan.")

    plan = row[0]
    if not isinstance(plan, list) or not plan:
        raise TypeError("Expected EXPLAIN FORMAT JSON to return a non-empty list.")

    root: dict[str, Any] = plan[0]
    plan_node = root["Plan"]
    return JsonbPlanSummary(
        root_node_type=str(plan_node["Node Type"]),
        planning_time_ms=float(root["Planning Time"]),
        execution_time_ms=float(root["Execution Time"]),
    )


def run_jsonb_document_smoke(
    *,
    symbol: str = "BTCUSDT",
    document_limit: int = 10,
    database_url: str | None = None,
) -> JsonbDocumentSmokeResult:
    ensure_document_schema(database_url)
    swap_corpus = run_bnb_swap_corpus_smoke(
        result_limit=max(document_limit, 10),
        database_url=database_url,
    )
    start_time_ms, end_time_ms = build_binance_kline_window_ms(
        tuple(event.block_timestamp for event in swap_corpus.sample_events)
    )
    fetch_and_store_binance_klines(
        symbol=symbol,
        interval="1m",
        limit=60,
        start_time_ms=start_time_ms,
        end_time_ms=end_time_ms,
        database_url=database_url,
    )
    binance_documents_upserted = upsert_binance_documents(
        symbol=symbol,
        limit=document_limit,
        database_url=database_url,
    )
    bnb_documents_upserted = upsert_bnb_swap_corpus_documents(
        limit=document_limit,
        database_url=database_url,
    )

    return JsonbDocumentSmokeResult(
        binance_documents_upserted=binance_documents_upserted,
        bnb_documents_upserted=bnb_documents_upserted,
        source_counts=load_source_counts(database_url),
        bnb_containment_count=load_bnb_containment_count(database_url),
        plan=load_bnb_containment_plan(database_url),
    )
