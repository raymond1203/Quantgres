import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from psycopg.types.json import Jsonb

from quantgres.db import connect, query_text
from quantgres.experiments.feature_store import (
    DEFAULT_FEATURE_SET,
    FEATURE_SOURCE,
    FeatureSourceRow,
    feature_metadata,
    iso_value,
    load_feature_source_rows,
)
from quantgres.experiments.olap_return_panel import run_olap_return_panel_smoke

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FEATURE_STORE_SQL_DIR = PROJECT_ROOT / "sql" / "feature_store"
FEATURE_BATCH_SCHEMA_SQL = FEATURE_STORE_SQL_DIR / "002_quant_feature_batches.sql"

BATCH_SOURCE = "quantgres.feature_store.batch"
BATCH_ASOF_INDEX_NAME = "quant_feature_batch_items_symbol_asof_idx"

INSERT_BATCH_SQL = """
INSERT INTO feature_store.quant_feature_batches (
    batch_id,
    feature_set,
    source,
    source_row_count,
    metadata
)
VALUES (
    %(batch_id)s,
    %(feature_set)s,
    %(source)s,
    %(source_row_count)s,
    %(metadata)s
)
ON CONFLICT (batch_id) DO NOTHING
"""

INSERT_BATCH_ITEM_SQL = """
INSERT INTO feature_store.quant_feature_batch_items (
    batch_id,
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
    %(batch_id)s,
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
ON CONFLICT (batch_id, symbol, feature_ts) DO NOTHING
"""

COUNT_BATCH_ITEMS_SQL = """
SELECT count(*)::integer
FROM feature_store.quant_feature_batch_items
WHERE batch_id = %(batch_id)s
"""

BATCH_ASOF_SQL = """
SELECT
    batch_id,
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
FROM feature_store.quant_feature_batch_items
WHERE batch_id = %(batch_id)s
  AND symbol = %(symbol)s
  AND feature_ts <= %(as_of_ts)s::timestamptz
ORDER BY feature_ts DESC
LIMIT 1
"""

EXPLAIN_BATCH_ASOF_SQL = f"""
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
{BATCH_ASOF_SQL}
"""


@dataclass(frozen=True)
class FeatureBatchItemRow:
    batch_id: str
    symbol: str
    event_ts: object
    feature_ts: object
    close_price: object
    previous_close_price: object
    return_bps: object
    rolling_5_return_bps: object
    volume: object
    quote_volume: object
    swap_count: int
    metadata: dict[str, Any]


@dataclass(frozen=True)
class FeatureBatchPlanSummary:
    root_node_type: str
    index_names: tuple[str, ...]
    planning_time_ms: float
    execution_time_ms: float


@dataclass(frozen=True)
class FeatureBatchSmokeResult:
    batch_id: str
    feature_set: str
    source_rows: int
    inserted_batch: int
    inserted_items: int
    total_batch_items: int
    as_of_ts: object
    as_of_item: FeatureBatchItemRow
    plan: FeatureBatchPlanSummary


def read_sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def ensure_feature_batch_schema(database_url: str | None = None) -> None:
    with connect(database_url) as connection:
        connection.execute(query_text(read_sql(FEATURE_BATCH_SCHEMA_SQL)))


def canonical_row(row: FeatureSourceRow) -> dict[str, object]:
    return {
        "symbol": row.symbol,
        "event_ts": iso_value(row.event_ts),
        "feature_ts": iso_value(row.feature_ts),
        "close_price": str(row.close_price),
        "previous_close_price": None
        if row.previous_close_price is None
        else str(row.previous_close_price),
        "return_bps": None if row.return_bps is None else str(row.return_bps),
        "rolling_5_return_bps": None
        if row.rolling_5_return_bps is None
        else str(row.rolling_5_return_bps),
        "volume": str(row.volume),
        "quote_volume": str(row.quote_volume),
        "swap_count": row.swap_count,
    }


def build_batch_id(
    *,
    feature_set: str,
    run_key: str,
    rows: tuple[FeatureSourceRow, ...],
) -> str:
    material = {
        "feature_set": feature_set,
        "run_key": run_key,
        "rows": [canonical_row(row) for row in rows],
    }
    body = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def insert_batch(
    *,
    batch_id: str,
    feature_set: str,
    source_row_count: int,
    run_key: str,
    database_url: str | None = None,
) -> int:
    ensure_feature_batch_schema(database_url)
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            query_text(INSERT_BATCH_SQL),
            {
                "batch_id": batch_id,
                "feature_set": feature_set,
                "source": BATCH_SOURCE,
                "source_row_count": source_row_count,
                "metadata": Jsonb(
                    {
                        "run_key": run_key,
                        "source": FEATURE_SOURCE,
                    }
                ),
            },
        )
        return cursor.rowcount


def batch_item_params(
    *,
    batch_id: str,
    feature_set: str,
    row: FeatureSourceRow,
) -> dict[str, object]:
    return {
        "batch_id": batch_id,
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


def insert_batch_items(
    *,
    batch_id: str,
    feature_set: str,
    rows: tuple[FeatureSourceRow, ...],
    database_url: str | None = None,
) -> int:
    ensure_feature_batch_schema(database_url)
    inserted = 0
    with connect(database_url) as connection, connection.cursor() as cursor:
        for row in rows:
            cursor.execute(
                query_text(INSERT_BATCH_ITEM_SQL),
                batch_item_params(batch_id=batch_id, feature_set=feature_set, row=row),
            )
            inserted += cursor.rowcount

    return inserted


def count_batch_items(
    *,
    batch_id: str,
    database_url: str | None = None,
) -> int:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(query_text(COUNT_BATCH_ITEMS_SQL), {"batch_id": batch_id})
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("Feature batch item count returned no row.")

    return int(row[0])


def coerce_metadata(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError("Expected feature batch item metadata to be a JSON object.")
    return cast("dict[str, Any]", value)


def row_to_batch_item(row: tuple[Any, ...]) -> FeatureBatchItemRow:
    return FeatureBatchItemRow(
        batch_id=str(row[0]),
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
    )


def load_batch_asof_item(
    *,
    batch_id: str,
    symbol: str,
    as_of_ts: object,
    database_url: str | None = None,
) -> FeatureBatchItemRow:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            query_text(BATCH_ASOF_SQL),
            {
                "batch_id": batch_id,
                "symbol": symbol.upper(),
                "as_of_ts": as_of_ts,
            },
        )
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError(f"No feature batch item found for {symbol} as of {as_of_ts}.")

    return row_to_batch_item(row)


def iter_plan_nodes(plan_node: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    children = plan_node.get("Plans", [])
    if not isinstance(children, list):
        children = []

    nodes = [plan_node]
    for child in children:
        if isinstance(child, dict):
            nodes.extend(iter_plan_nodes(child))

    return tuple(nodes)


def summarize_plan(plan: list[dict[str, Any]]) -> FeatureBatchPlanSummary:
    if not plan:
        raise ValueError("EXPLAIN plan is empty.")

    root = plan[0]
    plan_node = root["Plan"]
    if not isinstance(plan_node, dict):
        raise TypeError("Expected EXPLAIN root Plan to be an object.")

    nodes = iter_plan_nodes(plan_node)
    return FeatureBatchPlanSummary(
        root_node_type=str(plan_node["Node Type"]),
        index_names=tuple(
            str(node["Index Name"]) for node in nodes if isinstance(node.get("Index Name"), str)
        ),
        planning_time_ms=float(root["Planning Time"]),
        execution_time_ms=float(root["Execution Time"]),
    )


def load_batch_asof_plan(
    *,
    batch_id: str,
    symbol: str,
    as_of_ts: object,
    database_url: str | None = None,
) -> FeatureBatchPlanSummary:
    with (
        connect(database_url) as connection,
        connection.transaction(),
        connection.cursor() as cursor,
    ):
        cursor.execute(query_text("SET LOCAL enable_seqscan = off"))
        cursor.execute(
            query_text(EXPLAIN_BATCH_ASOF_SQL),
            {
                "batch_id": batch_id,
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

    return summarize_plan(plan)


def run_feature_batch_smoke(
    *,
    symbol: str = "BTCUSDT",
    feature_set: str = DEFAULT_FEATURE_SET,
    run_key: str = "default",
    binance_limit: int = 500,
    source_limit: int = 50,
    database_url: str | None = None,
) -> FeatureBatchSmokeResult:
    run_olap_return_panel_smoke(
        symbol=symbol,
        binance_limit=binance_limit,
        result_limit=5,
        database_url=database_url,
    )
    rows = load_feature_source_rows(
        symbol=symbol,
        limit=source_limit,
        database_url=database_url,
    )
    if not rows:
        raise RuntimeError("Expected at least one feature source row.")

    batch_id = build_batch_id(feature_set=feature_set, run_key=run_key, rows=rows)
    inserted_batch = insert_batch(
        batch_id=batch_id,
        feature_set=feature_set,
        source_row_count=len(rows),
        run_key=run_key,
        database_url=database_url,
    )
    inserted_items = insert_batch_items(
        batch_id=batch_id,
        feature_set=feature_set,
        rows=rows,
        database_url=database_url,
    )
    as_of_ts = rows[0].feature_ts

    return FeatureBatchSmokeResult(
        batch_id=batch_id,
        feature_set=feature_set,
        source_rows=len(rows),
        inserted_batch=inserted_batch,
        inserted_items=inserted_items,
        total_batch_items=count_batch_items(batch_id=batch_id, database_url=database_url),
        as_of_ts=as_of_ts,
        as_of_item=load_batch_asof_item(
            batch_id=batch_id,
            symbol=symbol,
            as_of_ts=as_of_ts,
            database_url=database_url,
        ),
        plan=load_batch_asof_plan(
            batch_id=batch_id,
            symbol=symbol,
            as_of_ts=as_of_ts,
            database_url=database_url,
        ),
    )
