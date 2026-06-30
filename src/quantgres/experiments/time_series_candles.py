from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from quantgres.db import connect, query_text

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SQL_DIR = PROJECT_ROOT / "sql" / "time_series"

SCHEMA_SQL = SQL_DIR / "001_candles_schema.sql"
FIXTURE_SQL = SQL_DIR / "002_candles_fixture.sql"

RANGE_START = "2026-01-01T00:00:00Z"
RANGE_END = "2026-01-01T01:00:00Z"

SUMMARY_QUERY = """
SELECT
    symbol,
    count(*)::integer AS candle_count,
    min(ts) AS first_ts,
    max(ts) AS last_ts,
    min(low_price) AS min_low,
    max(high_price) AS max_high,
    sum(close_price * volume) / sum(volume) AS vwap
FROM time_series.candles_1m
WHERE symbol = %s
  AND ts >= %s::timestamptz
  AND ts < %s::timestamptz
GROUP BY symbol
"""

EXPLAIN_SUMMARY_QUERY = f"""
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
{SUMMARY_QUERY}
"""


@dataclass(frozen=True)
class CandleRangeSummary:
    symbol: str
    candle_count: int
    first_ts: str
    last_ts: str
    min_low: Decimal
    max_high: Decimal
    vwap: Decimal


@dataclass(frozen=True)
class CandlePlanSummary:
    root_node_type: str
    execution_time_ms: float
    planning_time_ms: float


@dataclass(frozen=True)
class CandleSmokeResult:
    summary: CandleRangeSummary
    plan: CandlePlanSummary


def read_sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def apply_schema_and_fixture(database_url: str | None = None) -> None:
    with connect(database_url) as connection:
        connection.execute(query_text(read_sql(SCHEMA_SQL)))
        connection.execute(query_text(read_sql(FIXTURE_SQL)))


def load_summary(symbol: str = "BTCUSDT", database_url: str | None = None) -> CandleRangeSummary:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(query_text(SUMMARY_QUERY), (symbol, RANGE_START, RANGE_END))
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError(f"No candle summary rows returned for {symbol}.")

    return CandleRangeSummary(
        symbol=str(row[0]),
        candle_count=int(row[1]),
        first_ts=str(row[2]),
        last_ts=str(row[3]),
        min_low=row[4],
        max_high=row[5],
        vwap=row[6],
    )


def load_plan_summary(
    symbol: str = "BTCUSDT", database_url: str | None = None
) -> CandlePlanSummary:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(query_text(EXPLAIN_SUMMARY_QUERY), (symbol, RANGE_START, RANGE_END))
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("EXPLAIN did not return a plan.")

    plan = row[0]
    if not isinstance(plan, list) or not plan:
        raise TypeError("Expected EXPLAIN FORMAT JSON to return a non-empty list.")

    root: dict[str, Any] = plan[0]
    plan_node = root["Plan"]

    return CandlePlanSummary(
        root_node_type=str(plan_node["Node Type"]),
        planning_time_ms=float(root["Planning Time"]),
        execution_time_ms=float(root["Execution Time"]),
    )


def run_smoke(symbol: str = "BTCUSDT", database_url: str | None = None) -> CandleSmokeResult:
    apply_schema_and_fixture(database_url)
    return CandleSmokeResult(
        summary=load_summary(symbol, database_url),
        plan=load_plan_summary(symbol, database_url),
    )
