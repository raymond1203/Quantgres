from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from quantgres.db import connect, query_text
from quantgres.experiments.jsonb_documents import run_jsonb_document_smoke

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SEARCH_SQL_DIR = PROJECT_ROOT / "sql" / "search"
SEARCH_DOCUMENTS_SCHEMA_SQL = SEARCH_SQL_DIR / "001_search_documents_schema.sql"

UPSERT_SEARCH_DOCUMENTS_SQL = """
WITH source_documents AS (
    SELECT *
    FROM documents.raw_payloads
    WHERE source IN ('binance_kline', 'bnb_rpc_log')
),
projected AS (
    SELECT
        source,
        external_id,
        observed_at,
        CASE
            WHEN source = 'binance_kline'
                THEN concat(payload ->> 'symbol', ' Binance 1m kline')
            WHEN source = 'bnb_rpc_log'
                THEN concat('BNB Chain PancakeSwap swap log ', payload ->> 'transactionHash')
            ELSE concat(source, ' ', external_id)
        END AS title,
        CASE
            WHEN source = 'binance_kline' THEN concat_ws(
                ' ',
                'binance kline market candle',
                payload ->> 'symbol',
                payload ->> 'source',
                'open', payload ->> 'open_price',
                'close', payload ->> 'close_price',
                'volume', payload ->> 'volume'
            )
            WHEN source = 'bnb_rpc_log' THEN concat_ws(
                ' ',
                'bnb chain pancakeswap swap rpc log',
                payload ->> 'address',
                payload ->> 'transactionHash',
                payload -> 'topics' ->> 0
            )
            ELSE payload::text
        END AS document_text,
        CASE
            WHEN source = 'binance_kline' THEN coalesce(payload ->> 'symbol', external_id)
            WHEN source = 'bnb_rpc_log' THEN coalesce(payload ->> 'address', external_id)
            ELSE external_id
        END AS fuzzy_key,
        jsonb_build_object(
            'source', source,
            'external_id', external_id
        ) AS metadata
    FROM source_documents
)
INSERT INTO search.search_documents (
    source,
    external_id,
    observed_at,
    title,
    document_text,
    fuzzy_key,
    metadata
)
SELECT
    source,
    external_id,
    observed_at,
    title,
    document_text,
    fuzzy_key,
    metadata
FROM projected
ON CONFLICT (source, external_id) DO UPDATE
SET observed_at = EXCLUDED.observed_at,
    title = EXCLUDED.title,
    document_text = EXCLUDED.document_text,
    fuzzy_key = EXCLUDED.fuzzy_key,
    metadata = EXCLUDED.metadata,
    ingested_at = now()
"""

FULL_TEXT_SEARCH_SQL = """
SELECT
    source,
    external_id,
    title,
    ts_rank(search_vector, websearch_to_tsquery('english', %s)) AS rank
FROM search.search_documents
WHERE search_vector @@ websearch_to_tsquery('english', %s)
ORDER BY rank DESC, observed_at DESC
LIMIT %s
"""

EXPLAIN_FULL_TEXT_SEARCH_SQL = f"""
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
{FULL_TEXT_SEARCH_SQL}
"""

TRIGRAM_SEARCH_SQL = """
SELECT
    source,
    external_id,
    fuzzy_key,
    similarity(fuzzy_key, %s) AS similarity_score
FROM search.search_documents
WHERE fuzzy_key %% %s
ORDER BY similarity_score DESC, observed_at DESC
LIMIT %s
"""

EXPLAIN_TRIGRAM_SEARCH_SQL = f"""
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
{TRIGRAM_SEARCH_SQL}
"""


@dataclass(frozen=True)
class SearchResultRow:
    source: str
    external_id: str
    title: str
    score: Decimal


@dataclass(frozen=True)
class TrigramResultRow:
    source: str
    external_id: str
    fuzzy_key: str
    score: float


@dataclass(frozen=True)
class SearchPlanSummary:
    root_node_type: str
    execution_time_ms: float
    planning_time_ms: float


@dataclass(frozen=True)
class SearchDocumentSmokeResult:
    projected_documents: int
    full_text_results: tuple[SearchResultRow, ...]
    trigram_results: tuple[TrigramResultRow, ...]
    full_text_plan: SearchPlanSummary
    trigram_plan: SearchPlanSummary


def read_sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def ensure_search_schema(database_url: str | None = None) -> None:
    with connect(database_url) as connection:
        connection.execute(query_text(read_sql(SEARCH_DOCUMENTS_SCHEMA_SQL)))


def refresh_search_documents(database_url: str | None = None) -> int:
    ensure_search_schema(database_url)
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(query_text(UPSERT_SEARCH_DOCUMENTS_SQL))
        return cursor.rowcount


def load_full_text_results(
    *,
    query: str,
    limit: int,
    database_url: str | None = None,
) -> tuple[SearchResultRow, ...]:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(query_text(FULL_TEXT_SEARCH_SQL), (query, query, limit))
        rows = cursor.fetchall()

    return tuple(
        SearchResultRow(
            source=str(row[0]),
            external_id=str(row[1]),
            title=str(row[2]),
            score=row[3],
        )
        for row in rows
    )


def load_trigram_results(
    *,
    query: str,
    limit: int,
    database_url: str | None = None,
) -> tuple[TrigramResultRow, ...]:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(query_text(TRIGRAM_SEARCH_SQL), (query, query, limit))
        rows = cursor.fetchall()

    return tuple(
        TrigramResultRow(
            source=str(row[0]),
            external_id=str(row[1]),
            fuzzy_key=str(row[2]),
            score=float(row[3]),
        )
        for row in rows
    )


def load_plan(
    *,
    sql: str,
    params: tuple[object, ...],
    database_url: str | None = None,
) -> SearchPlanSummary:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(query_text(sql), params)
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("EXPLAIN did not return a plan.")

    plan = row[0]
    if not isinstance(plan, list) or not plan:
        raise TypeError("Expected EXPLAIN FORMAT JSON to return a non-empty list.")

    root: dict[str, Any] = plan[0]
    plan_node = root["Plan"]
    return SearchPlanSummary(
        root_node_type=str(plan_node["Node Type"]),
        planning_time_ms=float(root["Planning Time"]),
        execution_time_ms=float(root["Execution Time"]),
    )


def run_search_document_smoke(
    *,
    full_text_query: str = "pancakeswap swap",
    fuzzy_query: str = "0x16b9a82891338f9b",
    limit: int = 5,
    database_url: str | None = None,
) -> SearchDocumentSmokeResult:
    run_jsonb_document_smoke(database_url=database_url)
    projected_documents = refresh_search_documents(database_url)
    return SearchDocumentSmokeResult(
        projected_documents=projected_documents,
        full_text_results=load_full_text_results(
            query=full_text_query,
            limit=limit,
            database_url=database_url,
        ),
        trigram_results=load_trigram_results(
            query=fuzzy_query,
            limit=limit,
            database_url=database_url,
        ),
        full_text_plan=load_plan(
            sql=EXPLAIN_FULL_TEXT_SEARCH_SQL,
            params=(full_text_query, full_text_query, limit),
            database_url=database_url,
        ),
        trigram_plan=load_plan(
            sql=EXPLAIN_TRIGRAM_SEARCH_SQL,
            params=(fuzzy_query, fuzzy_query, limit),
            database_url=database_url,
        ),
    )
