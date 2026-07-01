from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from psycopg.types.json import Jsonb

from quantgres.db import connect, query_text
from quantgres.experiments.olap_return_panel import (
    OlapReturnPanelSmokeResult,
    run_olap_return_panel_smoke,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FEATURE_STORE_SQL_DIR = PROJECT_ROOT / "sql" / "feature_store"
QUANT_FEATURE_SNAPSHOTS_SQL = FEATURE_STORE_SQL_DIR / "001_quant_feature_snapshots.sql"

DEFAULT_FEATURE_SET = "market_return_v1"
FEATURE_SOURCE = "analytics.market_return_panel"
BINANCE_CANDLE_SOURCE = "binance_spot_klines"
ASOF_INDEX_NAME = "quant_feature_snapshots_symbol_asof_idx"
FEATURE_SOURCE_ORDER_BY_SQL = "ORDER BY (panel.swap_count > 0) DESC, panel.ts DESC"

FEATURE_SOURCE_ROWS_SQL = f"""
SELECT
    panel.symbol,
    panel.ts AS event_ts,
    candle.close_ts AS feature_ts,
    panel.close_price,
    panel.previous_close_price,
    panel.return_bps,
    panel.rolling_5_return_bps,
    panel.volume,
    panel.quote_volume,
    panel.swap_count,
    panel.refreshed_at,
    candle.source AS candle_source
FROM analytics.market_return_panel AS panel
JOIN time_series.candles_1m AS candle
  ON candle.symbol = panel.symbol
 AND candle.ts = panel.ts
WHERE panel.symbol = %(symbol)s
  AND candle.source = %(candle_source)s
{FEATURE_SOURCE_ORDER_BY_SQL}
LIMIT %(limit)s
"""

UPSERT_FEATURE_SNAPSHOT_SQL = """
INSERT INTO feature_store.quant_feature_snapshots (
    feature_set,
    symbol,
    event_ts,
    feature_ts,
    close_price,
    previous_close_price,
    return_bps,
    rolling_5_return_bps,
    volume,
    quote_volume,
    swap_count,
    metadata
)
VALUES (
    %(feature_set)s,
    %(symbol)s,
    %(event_ts)s,
    %(feature_ts)s,
    %(close_price)s,
    %(previous_close_price)s,
    %(return_bps)s,
    %(rolling_5_return_bps)s,
    %(volume)s,
    %(quote_volume)s,
    %(swap_count)s,
    %(metadata)s
)
ON CONFLICT (feature_set, symbol, feature_ts) DO UPDATE
SET event_ts = EXCLUDED.event_ts,
    close_price = EXCLUDED.close_price,
    previous_close_price = EXCLUDED.previous_close_price,
    return_bps = EXCLUDED.return_bps,
    rolling_5_return_bps = EXCLUDED.rolling_5_return_bps,
    volume = EXCLUDED.volume,
    quote_volume = EXCLUDED.quote_volume,
    swap_count = EXCLUDED.swap_count,
    metadata = EXCLUDED.metadata,
    computed_at = now(),
    updated_at = now()
"""

COUNT_FEATURE_SNAPSHOTS_SQL = """
SELECT count(*)::integer
FROM feature_store.quant_feature_snapshots
WHERE feature_set = %(feature_set)s
"""

ASOF_FEATURE_SQL = """
SELECT
    feature_set,
    symbol,
    event_ts,
    feature_ts,
    close_price,
    previous_close_price,
    return_bps,
    rolling_5_return_bps,
    volume,
    quote_volume,
    swap_count,
    metadata,
    computed_at
FROM feature_store.quant_feature_snapshots
WHERE feature_set = %(feature_set)s
  AND symbol = %(symbol)s
  AND feature_ts <= %(as_of_ts)s::timestamptz
ORDER BY feature_ts DESC
LIMIT 1
"""

EXPLAIN_ASOF_FEATURE_SQL = f"""
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
{ASOF_FEATURE_SQL}
"""


@dataclass(frozen=True)
class FeatureSourceRow:
    symbol: str
    event_ts: object
    feature_ts: object
    close_price: Decimal
    previous_close_price: Decimal | None
    return_bps: Decimal | None
    rolling_5_return_bps: Decimal | None
    volume: Decimal
    quote_volume: Decimal
    swap_count: int
    refreshed_at: object
    candle_source: str


@dataclass(frozen=True)
class FeatureSnapshotRow:
    feature_set: str
    symbol: str
    event_ts: object
    feature_ts: object
    close_price: Decimal
    previous_close_price: Decimal | None
    return_bps: Decimal | None
    rolling_5_return_bps: Decimal | None
    volume: Decimal
    quote_volume: Decimal
    swap_count: int
    metadata: dict[str, Any]
    computed_at: object


@dataclass(frozen=True)
class FeatureStorePlanSummary:
    root_node_type: str
    index_names: tuple[str, ...]
    planning_time_ms: float
    execution_time_ms: float
    shared_hit_blocks: int
    shared_read_blocks: int


@dataclass(frozen=True)
class FeatureStoreSmokeResult:
    olap_result: OlapReturnPanelSmokeResult
    feature_set: str
    source_rows: int
    upserted_snapshots: int
    total_snapshots: int
    as_of_ts: object
    as_of_feature: FeatureSnapshotRow
    plan: FeatureStorePlanSummary


def read_sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def ensure_feature_store_schema(database_url: str | None = None) -> None:
    with connect(database_url) as connection:
        connection.execute(query_text(read_sql(QUANT_FEATURE_SNAPSHOTS_SQL)))


def iso_value(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def coerce_metadata(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError("Expected feature metadata to be a JSON object.")
    return cast("dict[str, Any]", value)


def row_to_source(row: tuple[Any, ...]) -> FeatureSourceRow:
    return FeatureSourceRow(
        symbol=str(row[0]),
        event_ts=row[1],
        feature_ts=row[2],
        close_price=row[3],
        previous_close_price=row[4],
        return_bps=row[5],
        rolling_5_return_bps=row[6],
        volume=row[7],
        quote_volume=row[8],
        swap_count=int(row[9]),
        refreshed_at=row[10],
        candle_source=str(row[11]),
    )


def row_to_snapshot(row: tuple[Any, ...]) -> FeatureSnapshotRow:
    return FeatureSnapshotRow(
        feature_set=str(row[0]),
        symbol=str(row[1]),
        event_ts=row[2],
        feature_ts=row[3],
        close_price=row[4],
        previous_close_price=row[5],
        return_bps=row[6],
        rolling_5_return_bps=row[7],
        volume=row[8],
        quote_volume=row[9],
        swap_count=int(row[10]),
        metadata=coerce_metadata(row[11]),
        computed_at=row[12],
    )


def load_feature_source_rows(
    *,
    symbol: str,
    limit: int,
    database_url: str | None = None,
) -> tuple[FeatureSourceRow, ...]:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            query_text(FEATURE_SOURCE_ROWS_SQL),
            {
                "symbol": symbol.upper(),
                "limit": limit,
                "candle_source": BINANCE_CANDLE_SOURCE,
            },
        )
        rows = cursor.fetchall()

    return tuple(row_to_source(row) for row in rows)


def feature_metadata(*, row: FeatureSourceRow, feature_set: str) -> dict[str, Any]:
    return {
        "feature_set": feature_set,
        "source": FEATURE_SOURCE,
        "candle_source": row.candle_source,
        "panel_refreshed_at": iso_value(row.refreshed_at),
    }


def source_row_to_params(
    *,
    row: FeatureSourceRow,
    feature_set: str,
) -> dict[str, object]:
    return {
        "feature_set": feature_set,
        "symbol": row.symbol,
        "event_ts": row.event_ts,
        "feature_ts": row.feature_ts,
        "close_price": row.close_price,
        "previous_close_price": row.previous_close_price,
        "return_bps": row.return_bps,
        "rolling_5_return_bps": row.rolling_5_return_bps,
        "volume": row.volume,
        "quote_volume": row.quote_volume,
        "swap_count": row.swap_count,
        "metadata": Jsonb(feature_metadata(row=row, feature_set=feature_set)),
    }


def upsert_feature_snapshots(
    *,
    rows: tuple[FeatureSourceRow, ...],
    feature_set: str,
    database_url: str | None = None,
) -> int:
    ensure_feature_store_schema(database_url)
    if not rows:
        return 0

    upserted = 0
    with connect(database_url) as connection, connection.cursor() as cursor:
        for row in rows:
            cursor.execute(
                query_text(UPSERT_FEATURE_SNAPSHOT_SQL),
                source_row_to_params(row=row, feature_set=feature_set),
            )
            upserted += cursor.rowcount

    return upserted


def count_feature_snapshots(
    *,
    feature_set: str,
    database_url: str | None = None,
) -> int:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            query_text(COUNT_FEATURE_SNAPSHOTS_SQL),
            {"feature_set": feature_set},
        )
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("Feature snapshot count returned no row.")

    return int(row[0])


def load_asof_feature(
    *,
    feature_set: str,
    symbol: str,
    as_of_ts: object,
    database_url: str | None = None,
) -> FeatureSnapshotRow:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            query_text(ASOF_FEATURE_SQL),
            {
                "feature_set": feature_set,
                "symbol": symbol.upper(),
                "as_of_ts": as_of_ts,
            },
        )
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError(f"No feature snapshot found for {symbol} as of {as_of_ts}.")

    return row_to_snapshot(row)


def run_explain(
    *,
    feature_set: str,
    symbol: str,
    as_of_ts: object,
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
        cursor.execute(
            query_text(EXPLAIN_ASOF_FEATURE_SQL),
            {
                "feature_set": feature_set,
                "symbol": symbol.upper(),
                "as_of_ts": as_of_ts,
            },
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


def summarize_plan(plan: list[dict[str, Any]]) -> FeatureStorePlanSummary:
    if not plan:
        raise ValueError("EXPLAIN plan is empty.")

    root = plan[0]
    plan_node = root["Plan"]
    if not isinstance(plan_node, dict):
        raise TypeError("Expected EXPLAIN root Plan to be an object.")

    nodes = iter_plan_nodes(plan_node)
    return FeatureStorePlanSummary(
        root_node_type=str(plan_node["Node Type"]),
        index_names=tuple(
            str(node["Index Name"]) for node in nodes if isinstance(node.get("Index Name"), str)
        ),
        planning_time_ms=float(root["Planning Time"]),
        execution_time_ms=float(root["Execution Time"]),
        shared_hit_blocks=sum(int(node.get("Shared Hit Blocks", 0)) for node in nodes),
        shared_read_blocks=sum(int(node.get("Shared Read Blocks", 0)) for node in nodes),
    )


def run_feature_store_smoke(
    *,
    symbol: str = "BTCUSDT",
    feature_set: str = DEFAULT_FEATURE_SET,
    binance_limit: int = 500,
    source_limit: int = 100,
    as_of_ts: object | None = None,
    database_url: str | None = None,
) -> FeatureStoreSmokeResult:
    olap_result = run_olap_return_panel_smoke(
        symbol=symbol,
        binance_limit=binance_limit,
        result_limit=5,
        database_url=database_url,
    )
    source_rows = load_feature_source_rows(
        symbol=symbol,
        limit=source_limit,
        database_url=database_url,
    )
    upserted = upsert_feature_snapshots(
        rows=source_rows,
        feature_set=feature_set,
        database_url=database_url,
    )
    total_snapshots = count_feature_snapshots(
        feature_set=feature_set,
        database_url=database_url,
    )

    if not source_rows:
        raise RuntimeError("Expected at least one feature source row.")

    selected_as_of_ts = as_of_ts if as_of_ts is not None else source_rows[0].feature_ts
    as_of_feature = load_asof_feature(
        feature_set=feature_set,
        symbol=symbol,
        as_of_ts=selected_as_of_ts,
        database_url=database_url,
    )

    return FeatureStoreSmokeResult(
        olap_result=olap_result,
        feature_set=feature_set,
        source_rows=len(source_rows),
        upserted_snapshots=upserted,
        total_snapshots=total_snapshots,
        as_of_ts=selected_as_of_ts,
        as_of_feature=as_of_feature,
        plan=summarize_plan(
            run_explain(
                feature_set=feature_set,
                symbol=symbol,
                as_of_ts=selected_as_of_ts,
                force_index_probe=True,
                database_url=database_url,
            )
        ),
    )
