import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from psycopg.types.json import Jsonb

from quantgres.db import connect, query_text
from quantgres.experiments.search_documents import run_search_document_smoke

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MEMORY_SQL_DIR = PROJECT_ROOT / "sql" / "memory"
AGENT_MEMORY_SCHEMA_SQL = MEMORY_SQL_DIR / "001_agent_memory_schema.sql"

EMBEDDING_DIMENSIONS = 16
TOKEN_PATTERN = re.compile(r"[a-z0-9_]+")
DOMAIN_TOKEN_BUCKETS = {
    "pancakeswap": 0,
    "swap": 1,
    "bnb": 2,
    "chain": 3,
    "binance": 4,
    "kline": 5,
    "btcusdt": 6,
    "candle": 7,
    "market": 8,
}

SELECT_SEARCH_DOCUMENTS_SQL = """
SELECT
    source,
    external_id,
    observed_at,
    title,
    document_text,
    metadata
FROM search.search_documents
ORDER BY observed_at DESC, source, external_id
LIMIT %(limit)s
"""

UPSERT_MEMORY_CHUNK_SQL = """
INSERT INTO memory.agent_memory_chunks (
    source,
    external_id,
    observed_at,
    title,
    chunk_text,
    metadata,
    embedding
)
VALUES (
    %(source)s,
    %(external_id)s,
    %(observed_at)s,
    %(title)s,
    %(chunk_text)s,
    %(metadata)s,
    %(embedding)s::vector
)
ON CONFLICT (source, external_id) DO UPDATE
SET observed_at = EXCLUDED.observed_at,
    title = EXCLUDED.title,
    chunk_text = EXCLUDED.chunk_text,
    metadata = EXCLUDED.metadata,
    embedding = EXCLUDED.embedding,
    ingested_at = now()
"""

SIMILARITY_SEARCH_SQL = """
SELECT
    source,
    external_id,
    title,
    left(chunk_text, 180) AS preview,
    1 - (embedding <=> %(query_embedding)s::vector) AS cosine_similarity
FROM memory.agent_memory_chunks
ORDER BY embedding <=> %(query_embedding)s::vector
LIMIT %(limit)s
"""

EXPLAIN_SIMILARITY_SEARCH_SQL = f"""
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
{SIMILARITY_SEARCH_SQL}
"""

COUNT_MEMORY_CHUNKS_SQL = """
SELECT count(*)::integer
FROM memory.agent_memory_chunks
"""


@dataclass(frozen=True)
class SearchDocumentForMemory:
    source: str
    external_id: str
    observed_at: object
    title: str
    document_text: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class MemorySearchResult:
    source: str
    external_id: str
    title: str
    preview: str
    cosine_similarity: float


@dataclass(frozen=True)
class VectorPlanSummary:
    root_node_type: str
    index_names: tuple[str, ...]
    planning_time_ms: float
    execution_time_ms: float


@dataclass(frozen=True)
class VectorMemorySmokeResult:
    projected_chunks: int
    total_chunks: int
    query_text: str
    results: tuple[MemorySearchResult, ...]
    plan: VectorPlanSummary


def read_sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def ensure_agent_memory_schema(database_url: str | None = None) -> None:
    with connect(database_url) as connection:
        connection.execute(query_text(read_sql(AGENT_MEMORY_SCHEMA_SQL)))


def tokenize(text: str) -> tuple[str, ...]:
    return tuple(TOKEN_PATTERN.findall(text.lower()))


def embed_text(text: str, dimensions: int = EMBEDDING_DIMENSIONS) -> tuple[float, ...]:
    if dimensions <= 0:
        raise ValueError("dimensions must be positive.")

    values = [0.0 for _ in range(dimensions)]
    tokens = tokenize(text)
    if not tokens:
        tokens = ("empty",)

    hash_bucket_count = max(1, dimensions - len(DOMAIN_TOKEN_BUCKETS))
    for token in tokens:
        domain_bucket = DOMAIN_TOKEN_BUCKETS.get(token)
        if domain_bucket is not None and domain_bucket < dimensions:
            values[domain_bucket] += 1.0
            continue

        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = len(DOMAIN_TOKEN_BUCKETS) + (digest[0] % hash_bucket_count)
        if bucket >= dimensions:
            bucket = digest[0] % dimensions
        sign = 1.0 if digest[1] % 2 == 0 else -1.0
        values[bucket] += sign

    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        values[0] = 1.0
        norm = 1.0

    return tuple(value / norm for value in values)


def vector_literal(values: tuple[float, ...]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in values) + "]"


def coerce_metadata(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError("Expected metadata to be a JSON object.")
    return cast("dict[str, Any]", value)


def row_to_search_document(row: tuple[Any, ...]) -> SearchDocumentForMemory:
    return SearchDocumentForMemory(
        source=str(row[0]),
        external_id=str(row[1]),
        observed_at=row[2],
        title=str(row[3]),
        document_text=str(row[4]),
        metadata=coerce_metadata(row[5]),
    )


def load_search_documents_for_memory(
    *,
    limit: int,
    database_url: str | None = None,
) -> tuple[SearchDocumentForMemory, ...]:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(query_text(SELECT_SEARCH_DOCUMENTS_SQL), {"limit": limit})
        rows = cursor.fetchall()

    return tuple(row_to_search_document(row) for row in rows)


def memory_chunk_params(document: SearchDocumentForMemory) -> dict[str, object]:
    return {
        "source": document.source,
        "external_id": document.external_id,
        "observed_at": document.observed_at,
        "title": document.title,
        "chunk_text": document.document_text,
        "metadata": Jsonb(
            {
                **document.metadata,
                "embedding_model": "deterministic_hash_v1",
                "embedding_dimensions": EMBEDDING_DIMENSIONS,
            }
        ),
        "embedding": vector_literal(embed_text(document.document_text)),
    }


def upsert_memory_chunks(
    documents: tuple[SearchDocumentForMemory, ...],
    database_url: str | None = None,
) -> int:
    ensure_agent_memory_schema(database_url)
    if not documents:
        return 0

    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.executemany(
            query_text(UPSERT_MEMORY_CHUNK_SQL),
            [memory_chunk_params(document) for document in documents],
        )

    return len(documents)


def count_memory_chunks(database_url: str | None = None) -> int:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(query_text(COUNT_MEMORY_CHUNKS_SQL))
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("Memory chunk count returned no row.")

    return int(row[0])


def search_memory(
    *,
    query: str,
    limit: int,
    database_url: str | None = None,
) -> tuple[MemorySearchResult, ...]:
    query_embedding = vector_literal(embed_text(query))
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            query_text(SIMILARITY_SEARCH_SQL),
            {
                "query_embedding": query_embedding,
                "limit": limit,
            },
        )
        rows = cursor.fetchall()

    return tuple(
        MemorySearchResult(
            source=str(row[0]),
            external_id=str(row[1]),
            title=str(row[2]),
            preview=str(row[3]),
            cosine_similarity=float(row[4]),
        )
        for row in rows
    )


def iter_plan_nodes(plan_node: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    children = plan_node.get("Plans", [])
    if not isinstance(children, list):
        children = []

    nodes = [plan_node]
    for child in children:
        if isinstance(child, dict):
            nodes.extend(iter_plan_nodes(child))

    return tuple(nodes)


def summarize_vector_plan(plan: list[dict[str, Any]]) -> VectorPlanSummary:
    if not plan:
        raise ValueError("EXPLAIN plan is empty.")

    root = plan[0]
    plan_node = root["Plan"]
    if not isinstance(plan_node, dict):
        raise TypeError("Expected EXPLAIN root Plan to be an object.")

    nodes = iter_plan_nodes(plan_node)
    index_names = tuple(
        str(node["Index Name"]) for node in nodes if isinstance(node.get("Index Name"), str)
    )
    return VectorPlanSummary(
        root_node_type=str(plan_node["Node Type"]),
        index_names=index_names,
        planning_time_ms=float(root["Planning Time"]),
        execution_time_ms=float(root["Execution Time"]),
    )


def load_similarity_plan(
    *,
    query: str,
    limit: int,
    database_url: str | None = None,
) -> VectorPlanSummary:
    query_embedding = vector_literal(embed_text(query))
    with (
        connect(database_url) as connection,
        connection.transaction(),
        connection.cursor() as cursor,
    ):
        cursor.execute(query_text("SET LOCAL enable_seqscan = off"))
        cursor.execute(
            query_text(EXPLAIN_SIMILARITY_SEARCH_SQL),
            {
                "query_embedding": query_embedding,
                "limit": limit,
            },
        )
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("EXPLAIN did not return a plan.")

    plan = row[0]
    if not isinstance(plan, list):
        raise TypeError("Expected EXPLAIN FORMAT JSON to return a list.")

    return summarize_vector_plan(plan)


def run_vector_memory_smoke(
    *,
    query: str = "pancakeswap swap bnb chain",
    source_limit: int = 1000,
    result_limit: int = 5,
    database_url: str | None = None,
) -> VectorMemorySmokeResult:
    run_search_document_smoke(database_url=database_url)
    documents = load_search_documents_for_memory(
        limit=source_limit,
        database_url=database_url,
    )
    projected_chunks = upsert_memory_chunks(documents, database_url)
    return VectorMemorySmokeResult(
        projected_chunks=projected_chunks,
        total_chunks=count_memory_chunks(database_url),
        query_text=query,
        results=search_memory(query=query, limit=result_limit, database_url=database_url),
        plan=load_similarity_plan(query=query, limit=result_limit, database_url=database_url),
    )
