from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from quantgres.db import connect, query_text
from quantgres.experiments.binance_candles import (
    BinanceCandleIngestionResult,
    fetch_and_store_binance_klines,
)
from quantgres.experiments.bnb_swap_corpus import (
    BnbSwapCorpusSmokeResult,
    run_bnb_swap_corpus_smoke,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ANALYTICS_SQL_DIR = PROJECT_ROOT / "sql" / "analytics"
MARKET_RETURN_PANEL_SQL = ANALYTICS_SQL_DIR / "001_market_return_panel.sql"
DEFAULT_KLINE_ALIGNMENT_PADDING_MINUTES = 5

REFRESH_MARKET_RETURN_PANEL_SQL = """
REFRESH MATERIALIZED VIEW analytics.market_return_panel
"""

COUNT_MARKET_RETURN_PANEL_SQL = """
SELECT count(*)::integer
FROM analytics.market_return_panel
"""

LATEST_MARKET_RETURN_PANEL_SQL = """
SELECT
    symbol,
    ts,
    close_price,
    previous_close_price,
    return_bps,
    rolling_5_return_bps,
    volume,
    quote_volume,
    swap_count
FROM analytics.market_return_panel
WHERE symbol = %(symbol)s
ORDER BY ts DESC
LIMIT %(limit)s
"""

SWAP_ALIGNED_MARKET_RETURN_PANEL_SQL = """
SELECT
    symbol,
    ts,
    close_price,
    previous_close_price,
    return_bps,
    rolling_5_return_bps,
    volume,
    quote_volume,
    swap_count
FROM analytics.market_return_panel
WHERE symbol = %(symbol)s
  AND swap_count > 0
ORDER BY ts
LIMIT %(limit)s
"""

EXPLAIN_LATEST_MARKET_RETURN_PANEL_SQL = f"""
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
{LATEST_MARKET_RETURN_PANEL_SQL}
"""


@dataclass(frozen=True)
class MarketReturnPanelRow:
    symbol: str
    ts: object
    close_price: Decimal
    previous_close_price: Decimal | None
    return_bps: Decimal | None
    rolling_5_return_bps: Decimal | None
    volume: Decimal
    quote_volume: Decimal
    swap_count: int


@dataclass(frozen=True)
class OlapPlanSummary:
    root_node_type: str
    index_names: tuple[str, ...]
    planning_time_ms: float
    execution_time_ms: float
    shared_hit_blocks: int
    shared_read_blocks: int


@dataclass(frozen=True)
class OlapReturnPanelSmokeResult:
    binance_ingestion: BinanceCandleIngestionResult
    swap_corpus: BnbSwapCorpusSmokeResult
    panel_rows: int
    latest_rows: tuple[MarketReturnPanelRow, ...]
    swap_aligned_rows: tuple[MarketReturnPanelRow, ...]
    plan: OlapPlanSummary


def read_sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def ensure_market_return_panel_schema(database_url: str | None = None) -> None:
    with connect(database_url) as connection:
        connection.execute(query_text(read_sql(MARKET_RETURN_PANEL_SQL)))


def refresh_market_return_panel(database_url: str | None = None) -> int:
    ensure_market_return_panel_schema(database_url)
    with connect(database_url) as connection:
        connection.execute(query_text(REFRESH_MARKET_RETURN_PANEL_SQL))

    return count_market_return_panel_rows(database_url)


def require_datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("Expected datetime value.")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def floor_minute(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(second=0, microsecond=0)


def datetime_to_milliseconds(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def build_binance_kline_window_ms(
    timestamps: tuple[object, ...],
    *,
    padding_minutes: int = DEFAULT_KLINE_ALIGNMENT_PADDING_MINUTES,
) -> tuple[int | None, int | None]:
    if padding_minutes < 0:
        raise ValueError("padding_minutes must be non-negative.")
    if not timestamps:
        return None, None

    datetimes = tuple(require_datetime(timestamp) for timestamp in timestamps)
    start = floor_minute(min(datetimes)) - timedelta(minutes=padding_minutes)
    end = floor_minute(max(datetimes)) + timedelta(minutes=padding_minutes + 1)
    return datetime_to_milliseconds(start), datetime_to_milliseconds(end)


def count_market_return_panel_rows(database_url: str | None = None) -> int:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(query_text(COUNT_MARKET_RETURN_PANEL_SQL))
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("Market return panel count returned no row.")

    return int(row[0])


def row_to_panel(row: tuple[Any, ...]) -> MarketReturnPanelRow:
    return MarketReturnPanelRow(
        symbol=str(row[0]),
        ts=row[1],
        close_price=row[2],
        previous_close_price=row[3],
        return_bps=row[4],
        rolling_5_return_bps=row[5],
        volume=row[6],
        quote_volume=row[7],
        swap_count=int(row[8]),
    )


def load_latest_panel_rows(
    *,
    symbol: str,
    limit: int,
    database_url: str | None = None,
) -> tuple[MarketReturnPanelRow, ...]:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            query_text(LATEST_MARKET_RETURN_PANEL_SQL),
            {"symbol": symbol.upper(), "limit": limit},
        )
        rows = cursor.fetchall()

    return tuple(row_to_panel(row) for row in rows)


def load_swap_aligned_panel_rows(
    *,
    symbol: str,
    limit: int,
    database_url: str | None = None,
) -> tuple[MarketReturnPanelRow, ...]:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            query_text(SWAP_ALIGNED_MARKET_RETURN_PANEL_SQL),
            {"symbol": symbol.upper(), "limit": limit},
        )
        rows = cursor.fetchall()

    return tuple(row_to_panel(row) for row in rows)


def run_explain(
    *,
    symbol: str,
    limit: int,
    database_url: str | None = None,
) -> list[dict[str, Any]]:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            query_text(EXPLAIN_LATEST_MARKET_RETURN_PANEL_SQL),
            {"symbol": symbol.upper(), "limit": limit},
        )
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


def summarize_plan(plan: list[dict[str, Any]]) -> OlapPlanSummary:
    if not plan:
        raise ValueError("EXPLAIN plan is empty.")

    root = plan[0]
    plan_node = root["Plan"]
    if not isinstance(plan_node, dict):
        raise TypeError("Expected EXPLAIN root Plan to be an object.")

    nodes = iter_plan_nodes(plan_node)
    return OlapPlanSummary(
        root_node_type=str(plan_node["Node Type"]),
        index_names=tuple(
            str(node["Index Name"]) for node in nodes if isinstance(node.get("Index Name"), str)
        ),
        planning_time_ms=float(root["Planning Time"]),
        execution_time_ms=float(root["Execution Time"]),
        shared_hit_blocks=sum(int(node.get("Shared Hit Blocks", 0)) for node in nodes),
        shared_read_blocks=sum(int(node.get("Shared Read Blocks", 0)) for node in nodes),
    )


def run_olap_return_panel_smoke(
    *,
    symbol: str = "BTCUSDT",
    binance_limit: int = 500,
    result_limit: int = 5,
    database_url: str | None = None,
) -> OlapReturnPanelSmokeResult:
    swap_corpus = run_bnb_swap_corpus_smoke(
        result_limit=max(result_limit, 10),
        database_url=database_url,
    )
    start_time_ms, end_time_ms = build_binance_kline_window_ms(
        tuple(event.block_timestamp for event in swap_corpus.sample_events)
    )
    binance_ingestion = fetch_and_store_binance_klines(
        symbol=symbol,
        interval="1m",
        limit=binance_limit,
        start_time_ms=start_time_ms,
        end_time_ms=end_time_ms,
        database_url=database_url,
    )
    panel_rows = refresh_market_return_panel(database_url)

    return OlapReturnPanelSmokeResult(
        binance_ingestion=binance_ingestion,
        swap_corpus=swap_corpus,
        panel_rows=panel_rows,
        latest_rows=load_latest_panel_rows(
            symbol=symbol,
            limit=result_limit,
            database_url=database_url,
        ),
        swap_aligned_rows=load_swap_aligned_panel_rows(
            symbol=symbol,
            limit=result_limit,
            database_url=database_url,
        ),
        plan=summarize_plan(
            run_explain(
                symbol=symbol,
                limit=result_limit,
                database_url=database_url,
            )
        ),
    )
