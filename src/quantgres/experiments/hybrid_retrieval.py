from dataclasses import dataclass
from typing import Any

from quantgres.db import connect, query_text
from quantgres.experiments.vector_memory import (
    VectorMemorySmokeResult,
    embed_text,
    run_vector_memory_smoke,
    vector_literal,
)

TEXT_SCORE_WEIGHT = 0.45
TRIGRAM_SCORE_WEIGHT = 0.15
VECTOR_SCORE_WEIGHT = 0.40

SEARCH_VECTOR_INDEX_NAME = "search_documents_vector_idx"
TRIGRAM_INDEX_NAME = "search_documents_fuzzy_key_trgm_idx"
VECTOR_INDEX_NAME = "agent_memory_chunks_embedding_hnsw_idx"

HYBRID_RETRIEVAL_SQL = f"""
WITH text_candidates AS (
    SELECT
        source,
        external_id,
        title,
        observed_at,
        ts_rank_cd(
            search_vector,
            websearch_to_tsquery('english', %(query)s),
            32
        )::double precision AS text_rank
    FROM search.search_documents
    WHERE search_vector @@ websearch_to_tsquery('english', %(query)s)
    ORDER BY text_rank DESC, observed_at DESC
    LIMIT %(candidate_limit)s
),
trigram_candidates AS (
    SELECT
        source,
        external_id,
        title,
        observed_at,
        fuzzy_key,
        similarity(fuzzy_key, %(fuzzy_query)s)::double precision AS trigram_similarity
    FROM search.search_documents
    WHERE fuzzy_key %% %(fuzzy_query)s
    ORDER BY trigram_similarity DESC, observed_at DESC
    LIMIT %(candidate_limit)s
),
vector_candidates AS (
    SELECT
        source,
        external_id,
        title,
        observed_at,
        left(chunk_text, 180) AS preview,
        greatest(
            0::double precision,
            (1 - (embedding <=> %(query_embedding)s::vector))::double precision
        ) AS vector_similarity
    FROM memory.agent_memory_chunks
    ORDER BY embedding <=> %(query_embedding)s::vector
    LIMIT %(candidate_limit)s
),
candidate_keys AS (
    SELECT source, external_id
    FROM text_candidates
    UNION
    SELECT source, external_id
    FROM trigram_candidates
    UNION
    SELECT source, external_id
    FROM vector_candidates
),
scored AS (
    SELECT
        keys.source,
        keys.external_id,
        coalesce(text.title, vector.title, trigram.title) AS title,
        coalesce(vector.preview, text.title, trigram.fuzzy_key) AS preview,
        text.text_rank,
        trigram.trigram_similarity,
        vector.vector_similarity,
        (
            {TEXT_SCORE_WEIGHT} * coalesce(text.text_rank, 0) +
            {TRIGRAM_SCORE_WEIGHT} * coalesce(trigram.trigram_similarity, 0) +
            {VECTOR_SCORE_WEIGHT} * coalesce(vector.vector_similarity, 0)
        ) AS hybrid_score,
        greatest(
            coalesce(text.observed_at, '-infinity'::timestamptz),
            coalesce(trigram.observed_at, '-infinity'::timestamptz),
            coalesce(vector.observed_at, '-infinity'::timestamptz)
        ) AS observed_at
    FROM candidate_keys AS keys
    LEFT JOIN text_candidates AS text
      ON text.source = keys.source
     AND text.external_id = keys.external_id
    LEFT JOIN trigram_candidates AS trigram
      ON trigram.source = keys.source
     AND trigram.external_id = keys.external_id
    LEFT JOIN vector_candidates AS vector
      ON vector.source = keys.source
     AND vector.external_id = keys.external_id
)
SELECT
    source,
    external_id,
    title,
    preview,
    coalesce(text_rank, 0)::double precision AS text_rank,
    coalesce(trigram_similarity, 0)::double precision AS trigram_similarity,
    coalesce(vector_similarity, 0)::double precision AS vector_similarity,
    hybrid_score::double precision,
    observed_at
FROM scored
WHERE hybrid_score > 0
ORDER BY hybrid_score DESC, observed_at DESC, source, external_id
LIMIT %(result_limit)s
"""

EXPLAIN_HYBRID_RETRIEVAL_SQL = f"""
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
{HYBRID_RETRIEVAL_SQL}
"""


@dataclass(frozen=True)
class HybridRetrievalRow:
    source: str
    external_id: str
    title: str
    preview: str
    text_rank: float
    trigram_similarity: float
    vector_similarity: float
    hybrid_score: float
    observed_at: object


@dataclass(frozen=True)
class HybridRetrievalPlanSummary:
    root_node_type: str
    index_names: tuple[str, ...]
    planning_time_ms: float
    execution_time_ms: float
    shared_hit_blocks: int
    shared_read_blocks: int


@dataclass(frozen=True)
class HybridRetrievalSmokeResult:
    vector_projection: VectorMemorySmokeResult
    query: str
    fuzzy_query: str
    candidate_limit: int
    results: tuple[HybridRetrievalRow, ...]
    plan: HybridRetrievalPlanSummary


def hybrid_query_params(
    *,
    query: str,
    fuzzy_query: str,
    candidate_limit: int,
    result_limit: int,
) -> dict[str, object]:
    return {
        "query": query,
        "fuzzy_query": fuzzy_query,
        "query_embedding": vector_literal(embed_text(query)),
        "candidate_limit": candidate_limit,
        "result_limit": result_limit,
    }


def weighted_hybrid_score(
    *,
    text_rank: float | None,
    trigram_similarity: float | None,
    vector_similarity: float | None,
) -> float:
    return (
        TEXT_SCORE_WEIGHT * (text_rank or 0)
        + TRIGRAM_SCORE_WEIGHT * (trigram_similarity or 0)
        + VECTOR_SCORE_WEIGHT * (vector_similarity or 0)
    )


def row_to_hybrid_result(row: tuple[Any, ...]) -> HybridRetrievalRow:
    return HybridRetrievalRow(
        source=str(row[0]),
        external_id=str(row[1]),
        title=str(row[2]),
        preview=str(row[3]),
        text_rank=float(row[4]),
        trigram_similarity=float(row[5]),
        vector_similarity=float(row[6]),
        hybrid_score=float(row[7]),
        observed_at=row[8],
    )


def search_hybrid(
    *,
    query: str,
    fuzzy_query: str,
    candidate_limit: int,
    result_limit: int,
    database_url: str | None = None,
) -> tuple[HybridRetrievalRow, ...]:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            query_text(HYBRID_RETRIEVAL_SQL),
            hybrid_query_params(
                query=query,
                fuzzy_query=fuzzy_query,
                candidate_limit=candidate_limit,
                result_limit=result_limit,
            ),
        )
        rows = cursor.fetchall()

    return tuple(row_to_hybrid_result(row) for row in rows)


def iter_plan_nodes(plan_node: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    children = plan_node.get("Plans", [])
    if not isinstance(children, list):
        children = []

    nodes = [plan_node]
    for child in children:
        if isinstance(child, dict):
            nodes.extend(iter_plan_nodes(child))

    return tuple(nodes)


def summarize_plan(plan: list[dict[str, Any]]) -> HybridRetrievalPlanSummary:
    if not plan:
        raise ValueError("EXPLAIN plan is empty.")

    root = plan[0]
    plan_node = root["Plan"]
    if not isinstance(plan_node, dict):
        raise TypeError("Expected EXPLAIN root Plan to be an object.")

    nodes = iter_plan_nodes(plan_node)
    return HybridRetrievalPlanSummary(
        root_node_type=str(plan_node["Node Type"]),
        index_names=tuple(
            str(node["Index Name"]) for node in nodes if isinstance(node.get("Index Name"), str)
        ),
        planning_time_ms=float(root["Planning Time"]),
        execution_time_ms=float(root["Execution Time"]),
        shared_hit_blocks=sum(int(node.get("Shared Hit Blocks", 0)) for node in nodes),
        shared_read_blocks=sum(int(node.get("Shared Read Blocks", 0)) for node in nodes),
    )


def load_hybrid_plan(
    *,
    query: str,
    fuzzy_query: str,
    candidate_limit: int,
    result_limit: int,
    database_url: str | None = None,
) -> HybridRetrievalPlanSummary:
    with (
        connect(database_url) as connection,
        connection.transaction(),
        connection.cursor() as cursor,
    ):
        cursor.execute(query_text("SET LOCAL enable_seqscan = off"))
        cursor.execute(
            query_text(EXPLAIN_HYBRID_RETRIEVAL_SQL),
            hybrid_query_params(
                query=query,
                fuzzy_query=fuzzy_query,
                candidate_limit=candidate_limit,
                result_limit=result_limit,
            ),
        )
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("EXPLAIN did not return a plan.")

    plan = row[0]
    if not isinstance(plan, list):
        raise TypeError("Expected EXPLAIN FORMAT JSON to return a list.")

    return summarize_plan(plan)


def run_hybrid_retrieval_smoke(
    *,
    query: str = "pancakeswap swap bnb chain",
    fuzzy_query: str = "0x16b9a82891338f9b",
    source_limit: int = 1000,
    candidate_limit: int = 100,
    result_limit: int = 5,
    database_url: str | None = None,
) -> HybridRetrievalSmokeResult:
    vector_projection = run_vector_memory_smoke(
        query=query,
        source_limit=source_limit,
        result_limit=min(candidate_limit, result_limit),
        database_url=database_url,
    )
    return HybridRetrievalSmokeResult(
        vector_projection=vector_projection,
        query=query,
        fuzzy_query=fuzzy_query,
        candidate_limit=candidate_limit,
        results=search_hybrid(
            query=query,
            fuzzy_query=fuzzy_query,
            candidate_limit=candidate_limit,
            result_limit=result_limit,
            database_url=database_url,
        ),
        plan=load_hybrid_plan(
            query=query,
            fuzzy_query=fuzzy_query,
            candidate_limit=candidate_limit,
            result_limit=result_limit,
            database_url=database_url,
        ),
    )
