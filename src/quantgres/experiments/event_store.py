import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from psycopg.types.json import Jsonb

from quantgres.db import connect, query_text
from quantgres.experiments.feature_batches import (
    FeatureBatchItemRow,
    FeatureBatchSmokeResult,
    run_feature_batch_smoke,
)
from quantgres.experiments.olap_return_panel import (
    MarketReturnPanelRow,
    OlapReturnPanelSmokeResult,
    run_olap_return_panel_smoke,
)
from quantgres.experiments.vector_memory import (
    MemorySearchResult,
    VectorMemorySmokeResult,
    run_vector_memory_smoke,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
EVENT_STORE_SQL_DIR = PROJECT_ROOT / "sql" / "event_store"
AGENT_EVENTS_SCHEMA_SQL = EVENT_STORE_SQL_DIR / "001_agent_events_schema.sql"

INSERT_AGENT_EVENT_SQL = """
INSERT INTO event_store.agent_events (
    event_id,
    event_type,
    subject_type,
    subject_id,
    occurred_at,
    source,
    payload
)
VALUES (
    %(event_id)s,
    %(event_type)s,
    %(subject_type)s,
    %(subject_id)s,
    %(occurred_at)s,
    %(source)s,
    %(payload)s
)
ON CONFLICT (event_id) DO NOTHING
"""

SUBJECT_EVENTS_SQL = """
SELECT
    event_id,
    event_type,
    subject_type,
    subject_id,
    occurred_at,
    source,
    payload
FROM event_store.agent_events
WHERE subject_type = %(subject_type)s
  AND subject_id = %(subject_id)s
ORDER BY occurred_at DESC, created_at DESC
LIMIT %(limit)s
"""

PAYLOAD_CONTAINMENT_SQL = """
SELECT count(*)::integer
FROM event_store.agent_events
WHERE payload @> %(payload_filter)s::jsonb
"""

EXPLAIN_SUBJECT_EVENTS_SQL = f"""
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
{SUBJECT_EVENTS_SQL}
"""

EXPLAIN_PAYLOAD_CONTAINMENT_SQL = f"""
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
{PAYLOAD_CONTAINMENT_SQL}
"""


@dataclass(frozen=True)
class AgentEventDraft:
    event_type: str
    subject_type: str
    subject_id: str
    occurred_at: object
    source: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class AgentEventRow:
    event_id: str
    event_type: str
    subject_type: str
    subject_id: str
    occurred_at: object
    source: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class EventStorePlanSummary:
    root_node_type: str
    index_names: tuple[str, ...]
    planning_time_ms: float
    execution_time_ms: float
    shared_hit_blocks: int
    shared_read_blocks: int


@dataclass(frozen=True)
class EventStoreSmokeResult:
    inserted_events: int
    skipped_events: int
    subject_events: tuple[AgentEventRow, ...]
    payload_match_count: int
    subject_plan: EventStorePlanSummary
    payload_plan: EventStorePlanSummary


def read_sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def ensure_agent_events_schema(database_url: str | None = None) -> None:
    with connect(database_url) as connection:
        connection.execute(query_text(read_sql(AGENT_EVENTS_SCHEMA_SQL)))


def json_default(value: object) -> str:
    if isinstance(value, datetime | Path):
        return value.isoformat() if isinstance(value, datetime) else str(value)
    return str(value)


def canonical_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=json_default)


def iso_occurred_at(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def build_event_id(draft: AgentEventDraft) -> str:
    material = "|".join(
        (
            draft.event_type,
            draft.subject_type,
            draft.subject_id,
            iso_occurred_at(draft.occurred_at),
            canonical_payload(draft.payload),
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def event_to_params(draft: AgentEventDraft) -> dict[str, object]:
    return {
        "event_id": build_event_id(draft),
        "event_type": draft.event_type,
        "subject_type": draft.subject_type,
        "subject_id": draft.subject_id,
        "occurred_at": draft.occurred_at,
        "source": draft.source,
        "payload": Jsonb(draft.payload),
    }


def decimal_or_none(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def olap_event_payload(row: MarketReturnPanelRow) -> dict[str, Any]:
    return {
        "symbol": row.symbol,
        "ts": iso_occurred_at(row.ts),
        "close_price": str(row.close_price),
        "previous_close_price": decimal_or_none(row.previous_close_price),
        "return_bps": decimal_or_none(row.return_bps),
        "rolling_5_return_bps": decimal_or_none(row.rolling_5_return_bps),
        "volume": str(row.volume),
        "quote_volume": str(row.quote_volume),
        "swap_count": row.swap_count,
    }


def vector_result_payload(result: MemorySearchResult) -> dict[str, Any]:
    return {
        "source": result.source,
        "external_id": result.external_id,
        "title": result.title,
        "preview": result.preview,
        "cosine_similarity": result.cosine_similarity,
    }


def bnb_swap_corpus_payload(olap_result: OlapReturnPanelSmokeResult) -> dict[str, Any]:
    corpus = olap_result.swap_corpus
    ingestion = corpus.windowed_ingestion
    return {
        "pipeline": "bnb_swap_corpus",
        "stage": "onchain_ingestion",
        "chain_id": ingestion.chain_id,
        "pair_address": ingestion.address,
        "from_block": ingestion.from_block,
        "to_block": ingestion.to_block,
        "window_size": ingestion.window_size,
        "windows": len(ingestion.windows),
        "rows_fetched": ingestion.rows_fetched,
        "rows_upserted": ingestion.rows_upserted,
        "projected_swaps": corpus.projected_events,
        "requested_blocks": len(corpus.requested_block_numbers),
        "fetched_blocks": len(corpus.fetched_blocks),
        "enriched_swaps": corpus.enriched_swaps,
        "report_json": str(corpus.report.json_path),
        "report_markdown": str(corpus.report.markdown_path),
    }


def feature_batch_item_payload(item: FeatureBatchItemRow) -> dict[str, Any]:
    return {
        "pipeline": "bnb_swap_corpus",
        "stage": "feature_batch",
        "batch_id": item.batch_id,
        "symbol": item.symbol,
        "event_ts": iso_occurred_at(item.event_ts),
        "feature_ts": iso_occurred_at(item.feature_ts),
        "close_price": str(item.close_price),
        "return_bps": decimal_or_none(item.return_bps),
        "rolling_5_return_bps": decimal_or_none(item.rolling_5_return_bps),
        "swap_count": item.swap_count,
    }


def build_event_drafts(
    *,
    olap_result: OlapReturnPanelSmokeResult,
    feature_batch_result: FeatureBatchSmokeResult,
    vector_result: VectorMemorySmokeResult,
) -> tuple[AgentEventDraft, ...]:
    if not olap_result.swap_aligned_rows:
        raise RuntimeError("Expected at least one swap-aligned OLAP panel row.")
    if not vector_result.results:
        raise RuntimeError("Expected at least one vector memory result.")
    if feature_batch_result.as_of_item.swap_count == 0:
        raise RuntimeError("Expected feature batch event to include swap_count > 0.")
    if not olap_result.swap_corpus.sample_events:
        raise RuntimeError("Expected BNB swap corpus sample events.")

    aligned_panel = olap_result.swap_aligned_rows[0]
    occurred_at = aligned_panel.ts
    first_corpus_event = olap_result.swap_corpus.sample_events[0]
    return (
        AgentEventDraft(
            event_type="bnb_swap_corpus_ingested",
            subject_type="onchain_pair",
            subject_id=str(olap_result.swap_corpus.windowed_ingestion.address),
            occurred_at=first_corpus_event.block_timestamp,
            source="quantgres.bnb_swap_corpus",
            payload=bnb_swap_corpus_payload(olap_result),
        ),
        AgentEventDraft(
            event_type="olap_swap_aligned_observed",
            subject_type="symbol",
            subject_id=aligned_panel.symbol,
            occurred_at=occurred_at,
            source="quantgres.olap_return_panel",
            payload={
                "pipeline": "bnb_swap_corpus",
                "stage": "olap_event_time_alignment",
                **olap_event_payload(aligned_panel),
            },
        ),
        AgentEventDraft(
            event_type="feature_batch_item_observed",
            subject_type="symbol",
            subject_id=feature_batch_result.as_of_item.symbol,
            occurred_at=feature_batch_result.as_of_item.feature_ts,
            source="quantgres.feature_batches",
            payload=feature_batch_item_payload(feature_batch_result.as_of_item),
        ),
        AgentEventDraft(
            event_type="vector_memory_retrieval_observed",
            subject_type="query",
            subject_id=vector_result.query_text,
            occurred_at=occurred_at,
            source="quantgres.vector_memory",
            payload={
                "query": vector_result.query_text,
                "results": [vector_result_payload(result) for result in vector_result.results],
            },
        ),
    )


def append_events(
    drafts: tuple[AgentEventDraft, ...],
    database_url: str | None = None,
) -> tuple[int, int]:
    ensure_agent_events_schema(database_url)
    inserted = 0
    skipped = 0
    with connect(database_url) as connection, connection.cursor() as cursor:
        for draft in drafts:
            cursor.execute(query_text(INSERT_AGENT_EVENT_SQL), event_to_params(draft))
            if cursor.rowcount == 1:
                inserted += 1
            else:
                skipped += 1

    return inserted, skipped


def coerce_payload(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError("Expected event payload to be a JSON object.")
    return cast("dict[str, Any]", value)


def row_to_event(row: tuple[Any, ...]) -> AgentEventRow:
    return AgentEventRow(
        event_id=str(row[0]),
        event_type=str(row[1]),
        subject_type=str(row[2]),
        subject_id=str(row[3]),
        occurred_at=row[4],
        source=str(row[5]),
        payload=coerce_payload(row[6]),
    )


def load_subject_events(
    *,
    subject_type: str,
    subject_id: str,
    limit: int,
    database_url: str | None = None,
) -> tuple[AgentEventRow, ...]:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            query_text(SUBJECT_EVENTS_SQL),
            {
                "subject_type": subject_type,
                "subject_id": subject_id,
                "limit": limit,
            },
        )
        rows = cursor.fetchall()

    return tuple(row_to_event(row) for row in rows)


def count_payload_matches(
    *,
    payload_filter: dict[str, Any],
    database_url: str | None = None,
) -> int:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            query_text(PAYLOAD_CONTAINMENT_SQL),
            {"payload_filter": Jsonb(payload_filter)},
        )
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("Payload containment count returned no row.")

    return int(row[0])


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


def summarize_plan(plan: list[dict[str, Any]]) -> EventStorePlanSummary:
    if not plan:
        raise ValueError("EXPLAIN plan is empty.")

    root = plan[0]
    plan_node = root["Plan"]
    if not isinstance(plan_node, dict):
        raise TypeError("Expected EXPLAIN root Plan to be an object.")

    nodes = iter_plan_nodes(plan_node)
    return EventStorePlanSummary(
        root_node_type=str(plan_node["Node Type"]),
        index_names=tuple(
            str(node["Index Name"]) for node in nodes if isinstance(node.get("Index Name"), str)
        ),
        planning_time_ms=float(root["Planning Time"]),
        execution_time_ms=float(root["Execution Time"]),
        shared_hit_blocks=sum(int(node.get("Shared Hit Blocks", 0)) for node in nodes),
        shared_read_blocks=sum(int(node.get("Shared Read Blocks", 0)) for node in nodes),
    )


def run_event_store_smoke(
    *,
    query: str = "pancakeswap swap bnb chain",
    database_url: str | None = None,
) -> EventStoreSmokeResult:
    olap_result = run_olap_return_panel_smoke(database_url=database_url)
    feature_batch_result = run_feature_batch_smoke(source_limit=5, database_url=database_url)
    vector_result = run_vector_memory_smoke(query=query, database_url=database_url)
    drafts = build_event_drafts(
        olap_result=olap_result,
        feature_batch_result=feature_batch_result,
        vector_result=vector_result,
    )
    inserted, skipped = append_events(drafts, database_url)

    subject_events = load_subject_events(
        subject_type="symbol",
        subject_id=olap_result.swap_aligned_rows[0].symbol,
        limit=5,
        database_url=database_url,
    )
    payload_filter = {"pipeline": "bnb_swap_corpus"}
    payload_match_count = count_payload_matches(
        payload_filter=payload_filter,
        database_url=database_url,
    )

    return EventStoreSmokeResult(
        inserted_events=inserted,
        skipped_events=skipped,
        subject_events=subject_events,
        payload_match_count=payload_match_count,
        subject_plan=summarize_plan(
            run_explain(
                sql=EXPLAIN_SUBJECT_EVENTS_SQL,
                params={
                    "subject_type": "symbol",
                    "subject_id": olap_result.swap_aligned_rows[0].symbol,
                    "limit": 5,
                },
                database_url=database_url,
            )
        ),
        payload_plan=summarize_plan(
            run_explain(
                sql=EXPLAIN_PAYLOAD_CONTAINMENT_SQL,
                params={"payload_filter": Jsonb(payload_filter)},
                force_index_probe=True,
                database_url=database_url,
            )
        ),
    )
