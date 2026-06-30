from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from quantgres.db import connect, query_text
from quantgres.experiments.binance_candles import (
    BINANCE_SOURCE,
    BinanceCandleIngestionResult,
    fetch_and_store_binance_klines,
)
from quantgres.experiments.bnb_swap_projection import (
    PANCAKESWAP_V2,
    PANCAKESWAP_V2_WBNB_USDT_PAIR,
    BnbSwapProjectionSmokeResult,
    run_bnb_swap_projection_smoke,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CACHE_SQL_DIR = PROJECT_ROOT / "sql" / "cache"
MARKET_ONCHAIN_SUMMARY_SQL = CACHE_SQL_DIR / "001_market_onchain_summary.sql"

DEFAULT_MARKET_SUMMARY_KEY = "market:BTCUSDT"
DEFAULT_ONCHAIN_SUMMARY_KEY = "onchain:pancakeswap_v2:bnb-usdt"

BASE_SUMMARY_LOOKUP_SQL = """
WITH market_summary AS (
    SELECT
        concat('market:', symbol) AS summary_key,
        'market' AS summary_kind,
        max(ts) AS latest_observed_at,
        jsonb_build_object(
            'symbol', symbol,
            'source', source,
            'candle_count', count(*),
            'first_ts', min(ts),
            'last_ts', max(ts),
            'latest_close', (array_agg(close_price ORDER BY ts DESC))[1]::text,
            'vwap', (sum(close_price * volume) / nullif(sum(volume), 0))::text,
            'base_volume', sum(volume)::text,
            'quote_volume', sum(quote_volume)::text
        ) AS metrics
    FROM time_series.candles_1m
    WHERE source = %(binance_source)s
    GROUP BY symbol, source
),
onchain_summary AS (
    SELECT
        concat('onchain:', dex, ':bnb-usdt') AS summary_key,
        'onchain' AS summary_kind,
        max(projected_at) AS latest_observed_at,
        jsonb_build_object(
            'chain_id', chain_id,
            'dex', dex,
            'pair_address', pair_address,
            'swap_count', count(*),
            'block_count', count(DISTINCT block_number),
            'first_block', min(block_number),
            'last_block', max(block_number),
            'amount0_in_sum', sum(amount0_in)::text,
            'amount1_in_sum', sum(amount1_in)::text,
            'amount0_out_sum', sum(amount0_out)::text,
            'amount1_out_sum', sum(amount1_out)::text
        ) AS metrics
    FROM defi.swap_events
    WHERE chain_id = 56
      AND dex = %(dex)s
      AND pair_address = %(pair_address)s
    GROUP BY chain_id, dex, pair_address
),
combined AS (
    SELECT summary_key, summary_kind, latest_observed_at, metrics
    FROM market_summary
    UNION ALL
    SELECT summary_key, summary_kind, latest_observed_at, metrics
    FROM onchain_summary
)
SELECT
    summary_key,
    summary_kind,
    latest_observed_at,
    metrics
FROM combined
WHERE summary_key = %(summary_key)s
"""

CACHE_SUMMARY_LOOKUP_SQL = """
SELECT
    summary_key,
    summary_kind,
    latest_observed_at,
    metrics
FROM cache.market_onchain_summary
WHERE summary_key = %(summary_key)s
"""

LIST_CACHE_SUMMARIES_SQL = """
SELECT
    summary_key,
    summary_kind,
    latest_observed_at,
    metrics
FROM cache.market_onchain_summary
ORDER BY summary_key
"""

COUNT_CACHE_SUMMARIES_SQL = """
SELECT count(*)::integer
FROM cache.market_onchain_summary
"""

REFRESH_MARKET_ONCHAIN_SUMMARY_SQL = """
REFRESH MATERIALIZED VIEW cache.market_onchain_summary
"""

EXPLAIN_BASE_SUMMARY_LOOKUP_SQL = f"""
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
{BASE_SUMMARY_LOOKUP_SQL}
"""

EXPLAIN_CACHE_SUMMARY_LOOKUP_SQL = f"""
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
{CACHE_SUMMARY_LOOKUP_SQL}
"""


@dataclass(frozen=True)
class CacheSummaryRow:
    summary_key: str
    summary_kind: str
    latest_observed_at: object
    metrics: dict[str, Any]


@dataclass(frozen=True)
class CachePlanSummary:
    root_node_type: str
    index_names: tuple[str, ...]
    planning_time_ms: float
    execution_time_ms: float
    shared_hit_blocks: int
    shared_read_blocks: int


@dataclass(frozen=True)
class CacheSummarySmokeResult:
    binance_ingestion: BinanceCandleIngestionResult
    swap_projection: BnbSwapProjectionSmokeResult
    refreshed_rows: int
    selected_summary: CacheSummaryRow
    base_plan: CachePlanSummary
    cache_plan: CachePlanSummary


def read_sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def ensure_cache_summary_schema(database_url: str | None = None) -> None:
    with connect(database_url) as connection:
        connection.execute(query_text(read_sql(MARKET_ONCHAIN_SUMMARY_SQL)))


def refresh_market_onchain_summary(database_url: str | None = None) -> int:
    ensure_cache_summary_schema(database_url)
    with connect(database_url) as connection:
        connection.execute(query_text(REFRESH_MARKET_ONCHAIN_SUMMARY_SQL))

    return count_cache_summaries(database_url)


def count_cache_summaries(database_url: str | None = None) -> int:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(query_text(COUNT_CACHE_SUMMARIES_SQL))
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("Cache summary count returned no row.")

    return int(row[0])


def coerce_metrics(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError("Expected summary metrics to be a JSON object.")

    return cast("dict[str, Any]", value)


def row_to_summary(row: tuple[Any, ...]) -> CacheSummaryRow:
    return CacheSummaryRow(
        summary_key=str(row[0]),
        summary_kind=str(row[1]),
        latest_observed_at=row[2],
        metrics=coerce_metrics(row[3]),
    )


def load_cache_summaries(database_url: str | None = None) -> tuple[CacheSummaryRow, ...]:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(query_text(LIST_CACHE_SUMMARIES_SQL))
        rows = cursor.fetchall()

    return tuple(row_to_summary(row) for row in rows)


def lookup_cache_summary(
    *,
    summary_key: str,
    database_url: str | None = None,
) -> CacheSummaryRow:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(query_text(CACHE_SUMMARY_LOOKUP_SQL), {"summary_key": summary_key})
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError(f"Cache summary {summary_key!r} was not found.")

    return row_to_summary(row)


def plan_params(summary_key: str) -> dict[str, object]:
    return {
        "summary_key": summary_key,
        "binance_source": BINANCE_SOURCE,
        "dex": PANCAKESWAP_V2,
        "pair_address": PANCAKESWAP_V2_WBNB_USDT_PAIR,
    }


def run_explain(
    *,
    sql: str,
    params: dict[str, object],
    force_index_probe: bool = False,
    database_url: str | None = None,
) -> list[dict[str, Any]]:
    with (
        connect(database_url) as connection,
        connection.transaction(),
        connection.cursor() as cursor,
    ):
        if force_index_probe:
            cursor.execute(query_text("SET LOCAL enable_seqscan = off"))
        cursor.execute(query_text(sql), params)
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("EXPLAIN did not return a plan.")

    plan = row[0]
    if not isinstance(plan, list):
        raise TypeError("Expected EXPLAIN FORMAT JSON to return a list.")

    return plan


def iter_plan_nodes(plan_node: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    children = plan_node.get("Plans", [])
    if not isinstance(children, list):
        children = []

    nodes = [plan_node]
    for child in children:
        if isinstance(child, dict):
            nodes.extend(iter_plan_nodes(child))

    return tuple(nodes)


def summarize_plan(plan: list[dict[str, Any]]) -> CachePlanSummary:
    if not plan:
        raise ValueError("EXPLAIN plan is empty.")

    root = plan[0]
    plan_node = root["Plan"]
    if not isinstance(plan_node, dict):
        raise TypeError("Expected EXPLAIN root Plan to be an object.")

    nodes = iter_plan_nodes(plan_node)
    return CachePlanSummary(
        root_node_type=str(plan_node["Node Type"]),
        index_names=tuple(
            str(node["Index Name"]) for node in nodes if isinstance(node.get("Index Name"), str)
        ),
        planning_time_ms=float(root["Planning Time"]),
        execution_time_ms=float(root["Execution Time"]),
        shared_hit_blocks=sum(int(node.get("Shared Hit Blocks", 0)) for node in nodes),
        shared_read_blocks=sum(int(node.get("Shared Read Blocks", 0)) for node in nodes),
    )


def run_cache_summary_smoke(
    *,
    symbol: str = "BTCUSDT",
    binance_limit: int = 500,
    summary_key: str = DEFAULT_ONCHAIN_SUMMARY_KEY,
    database_url: str | None = None,
) -> CacheSummarySmokeResult:
    binance_ingestion = fetch_and_store_binance_klines(
        symbol=symbol,
        interval="1m",
        limit=binance_limit,
        database_url=database_url,
    )
    swap_projection = run_bnb_swap_projection_smoke(database_url=database_url)
    refreshed_rows = refresh_market_onchain_summary(database_url)
    selected_summary = lookup_cache_summary(summary_key=summary_key, database_url=database_url)
    params = plan_params(summary_key)

    return CacheSummarySmokeResult(
        binance_ingestion=binance_ingestion,
        swap_projection=swap_projection,
        refreshed_rows=refreshed_rows,
        selected_summary=selected_summary,
        base_plan=summarize_plan(
            run_explain(
                sql=EXPLAIN_BASE_SUMMARY_LOOKUP_SQL,
                params=params,
                database_url=database_url,
            )
        ),
        cache_plan=summarize_plan(
            run_explain(
                sql=EXPLAIN_CACHE_SUMMARY_LOOKUP_SQL,
                params={"summary_key": summary_key},
                force_index_probe=True,
                database_url=database_url,
            )
        ),
    )
