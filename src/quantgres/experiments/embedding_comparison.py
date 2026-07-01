import importlib
import json
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, SupportsFloat, cast

from psycopg.types.json import Jsonb

from quantgres.db import connect, query_text
from quantgres.experiments.vector_memory import (
    SIMILARITY_SEARCH_SQL,
    MemorySearchResult,
    SearchDocumentForMemory,
    VectorMemorySmokeResult,
    VectorPlanSummary,
    ensure_agent_memory_schema,
    load_search_documents_for_memory,
    run_vector_memory_smoke,
    summarize_vector_plan,
    vector_literal,
)
from quantgres.reports import WrittenReport, default_generated_reports_dir
from quantgres.runtime import DatabaseRuntimeInfo, load_runtime_info

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MEMORY_SQL_DIR = PROJECT_ROOT / "sql" / "memory"
MODEL_MEMORY_SCHEMA_SQL = MEMORY_SQL_DIR / "002_agent_memory_model_chunks.sql"

DEFAULT_FASTEMBED_MODEL = "BAAI/bge-small-en-v1.5"
FASTEMBED_MODEL_DIMENSIONS = 384
MODEL_VECTOR_INDEX_NAME = "agent_memory_model_chunks_embedding_hnsw_idx"

UPSERT_MODEL_MEMORY_CHUNK_SQL = """
INSERT INTO memory.agent_memory_model_chunks (
    embedding_model,
    source,
    external_id,
    observed_at,
    title,
    chunk_text,
    metadata,
    embedding
)
VALUES (
    %(embedding_model)s,
    %(source)s,
    %(external_id)s,
    %(observed_at)s,
    %(title)s,
    %(chunk_text)s,
    %(metadata)s,
    %(embedding)s::vector
)
ON CONFLICT (embedding_model, source, external_id) DO UPDATE
SET observed_at = EXCLUDED.observed_at,
    title = EXCLUDED.title,
    chunk_text = EXCLUDED.chunk_text,
    metadata = EXCLUDED.metadata,
    embedding = EXCLUDED.embedding,
    ingested_at = now()
"""

MODEL_SIMILARITY_SEARCH_SQL = """
SELECT
    source,
    external_id,
    title,
    left(chunk_text, 180) AS preview,
    1 - (embedding <=> %(query_embedding)s::vector) AS cosine_similarity
FROM memory.agent_memory_model_chunks
WHERE embedding_model = %(embedding_model)s
  AND source IN ('binance_kline', 'bnb_swap_corpus')
ORDER BY embedding <=> %(query_embedding)s::vector
LIMIT %(limit)s
"""

EXPLAIN_MODEL_SIMILARITY_SEARCH_SQL = f"""
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
{MODEL_SIMILARITY_SEARCH_SQL}
"""

COUNT_MODEL_MEMORY_CHUNKS_SQL = """
SELECT count(*)::integer
FROM memory.agent_memory_model_chunks
WHERE embedding_model = %(embedding_model)s
"""


class TextEmbeddingModel(Protocol):
    def embed(self, documents: Sequence[str]) -> Iterable[Sequence[SupportsFloat]]:
        """Return one embedding per input document."""


class TextEmbeddingFactory(Protocol):
    def __call__(self, *, model_name: str) -> TextEmbeddingModel: ...


@dataclass(frozen=True)
class EmbeddingComparisonSmokeResult:
    vector_projection: VectorMemorySmokeResult
    embedding_model: str
    embedding_dimensions: int
    projected_model_chunks: int
    total_model_chunks: int
    query_text: str
    deterministic_results: tuple[MemorySearchResult, ...]
    model_results: tuple[MemorySearchResult, ...]
    top_overlap_count: int
    plan: VectorPlanSummary


@dataclass(frozen=True)
class VectorRetrievalBenchmarkResult:
    comparison: EmbeddingComparisonSmokeResult
    report: WrittenReport


def read_sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def ensure_model_memory_schema(database_url: str | None = None) -> None:
    ensure_agent_memory_schema(database_url)
    with connect(database_url) as connection:
        connection.execute(query_text(read_sql(MODEL_MEMORY_SCHEMA_SQL)))


def load_fastembed_model(model_name: str = DEFAULT_FASTEMBED_MODEL) -> TextEmbeddingModel:
    fastembed_module = importlib.import_module("fastembed")
    text_embedding_class = cast("TextEmbeddingFactory", fastembed_module.TextEmbedding)
    return text_embedding_class(model_name=model_name)


def coerce_embedding(
    values: Iterable[SupportsFloat],
    *,
    expected_dimensions: int = FASTEMBED_MODEL_DIMENSIONS,
) -> tuple[float, ...]:
    embedding = tuple(float(value) for value in values)
    if len(embedding) != expected_dimensions:
        raise ValueError(
            f"Expected {expected_dimensions} embedding dimensions, got {len(embedding)}."
        )
    if not all(math.isfinite(value) for value in embedding):
        raise ValueError("Embedding values must be finite.")
    if math.sqrt(sum(value * value for value in embedding)) == 0:
        raise ValueError("Embedding vector must not be zero.")

    return embedding


def embed_texts(
    model: TextEmbeddingModel,
    texts: Sequence[str],
    *,
    expected_dimensions: int = FASTEMBED_MODEL_DIMENSIONS,
) -> tuple[tuple[float, ...], ...]:
    embeddings = tuple(
        coerce_embedding(values, expected_dimensions=expected_dimensions)
        for values in model.embed(texts)
    )
    if len(embeddings) != len(texts):
        raise ValueError(f"Expected {len(texts)} embeddings, got {len(embeddings)}.")

    return embeddings


def model_memory_chunk_params(
    *,
    document: SearchDocumentForMemory,
    embedding: tuple[float, ...],
    model_name: str,
) -> dict[str, object]:
    return {
        "embedding_model": model_name,
        "source": document.source,
        "external_id": document.external_id,
        "observed_at": document.observed_at,
        "title": document.title,
        "chunk_text": document.document_text,
        "metadata": Jsonb(
            {
                **document.metadata,
                "embedding_model": model_name,
                "embedding_dimensions": len(embedding),
            }
        ),
        "embedding": vector_literal(embedding),
    }


def upsert_model_memory_chunks(
    *,
    documents: tuple[SearchDocumentForMemory, ...],
    embeddings: tuple[tuple[float, ...], ...],
    model_name: str,
    database_url: str | None = None,
) -> int:
    ensure_model_memory_schema(database_url)
    if len(documents) != len(embeddings):
        raise ValueError(f"Expected {len(documents)} embeddings, got {len(embeddings)}.")
    if not documents:
        return 0

    params = [
        model_memory_chunk_params(
            document=document,
            embedding=embedding,
            model_name=model_name,
        )
        for document, embedding in zip(documents, embeddings, strict=True)
    ]
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.executemany(query_text(UPSERT_MODEL_MEMORY_CHUNK_SQL), params)

    return len(documents)


def count_model_memory_chunks(
    *,
    model_name: str,
    database_url: str | None = None,
) -> int:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            query_text(COUNT_MODEL_MEMORY_CHUNKS_SQL),
            {"embedding_model": model_name},
        )
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("Model memory chunk count returned no row.")

    return int(row[0])


def search_model_memory(
    *,
    query_embedding: tuple[float, ...],
    model_name: str,
    limit: int,
    database_url: str | None = None,
) -> tuple[MemorySearchResult, ...]:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            query_text(MODEL_SIMILARITY_SEARCH_SQL),
            {
                "query_embedding": vector_literal(query_embedding),
                "embedding_model": model_name,
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


def load_model_similarity_plan(
    *,
    query_embedding: tuple[float, ...],
    model_name: str,
    limit: int,
    database_url: str | None = None,
) -> VectorPlanSummary:
    with (
        connect(database_url) as connection,
        connection.transaction(),
        connection.cursor() as cursor,
    ):
        cursor.execute(query_text("SET LOCAL enable_seqscan = off"))
        cursor.execute(query_text("SET LOCAL enable_sort = off"))
        cursor.execute(
            query_text(EXPLAIN_MODEL_SIMILARITY_SEARCH_SQL),
            {
                "query_embedding": vector_literal(query_embedding),
                "embedding_model": model_name,
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


def memory_result_key(result: MemorySearchResult) -> tuple[str, str]:
    return result.source, result.external_id


def count_top_overlap(
    baseline_results: tuple[MemorySearchResult, ...],
    model_results: tuple[MemorySearchResult, ...],
) -> int:
    baseline_keys = {memory_result_key(result) for result in baseline_results}
    model_keys = {memory_result_key(result) for result in model_results}
    return len(baseline_keys.intersection(model_keys))


def memory_result_to_dict(result: MemorySearchResult, *, rank: int) -> dict[str, object]:
    return {
        "rank": rank,
        "source": result.source,
        "external_id": result.external_id,
        "title": result.title,
        "preview": result.preview,
        "cosine_similarity": result.cosine_similarity,
    }


def plan_summary_to_dict(plan: VectorPlanSummary) -> dict[str, object]:
    return {
        "root_node_type": plan.root_node_type,
        "index_names": list(plan.index_names),
        "planning_time_ms": plan.planning_time_ms,
        "execution_time_ms": plan.execution_time_ms,
    }


def runtime_to_dict(runtime: DatabaseRuntimeInfo) -> dict[str, object]:
    return {
        "server_version": runtime.server_version,
        "server_version_num": runtime.server_version_num,
        "database_name": runtime.database_name,
        "user_name": runtime.user_name,
        "extensions": [
            {"name": extension.name, "version": extension.version}
            for extension in runtime.extensions
        ],
    }


def build_vector_retrieval_report(
    *,
    comparison: EmbeddingComparisonSmokeResult,
    runtime: DatabaseRuntimeInfo,
    source_limit: int,
    result_limit: int,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated = generated_at or datetime.now(UTC)
    return {
        "title": "VectorDB Retrieval Benchmark",
        "slug": "vector-retrieval-benchmark",
        "generated_at": generated.isoformat(),
        "track": "Vector DB / pgvector Agent Memory",
        "query_name": "deterministic hash vs fastembed cosine retrieval",
        "parameters": {
            "query": comparison.query_text,
            "source_limit": source_limit,
            "result_limit": result_limit,
            "embedding_model": comparison.embedding_model,
            "embedding_dimensions": comparison.embedding_dimensions,
        },
        "schema_files": [
            "sql/memory/001_agent_memory_schema.sql",
            "sql/memory/002_agent_memory_model_chunks.sql",
        ],
        "queries": {
            "deterministic_hash": SIMILARITY_SEARCH_SQL,
            "real_embedding": MODEL_SIMILARITY_SEARCH_SQL,
        },
        "dataset_sizes": {
            "deterministic_projected_chunks": comparison.vector_projection.projected_chunks,
            "deterministic_total_chunks": comparison.vector_projection.total_chunks,
            "model_projected_chunks": comparison.projected_model_chunks,
            "model_total_chunks": comparison.total_model_chunks,
        },
        "retrieval": {
            "top_overlap_count": comparison.top_overlap_count,
            "deterministic_result_count": len(comparison.deterministic_results),
            "model_result_count": len(comparison.model_results),
            "deterministic_results": [
                memory_result_to_dict(result, rank=rank)
                for rank, result in enumerate(comparison.deterministic_results, start=1)
            ],
            "model_results": [
                memory_result_to_dict(result, rank=rank)
                for rank, result in enumerate(comparison.model_results, start=1)
            ],
        },
        "plan_summary": {
            "deterministic_hash": plan_summary_to_dict(comparison.vector_projection.plan),
            "real_embedding": plan_summary_to_dict(comparison.plan),
        },
        "postgresql": runtime_to_dict(runtime),
        "interpretation": (
            "This benchmark records retrieval evidence for the same real SearchDB "
            "documents projected into two pgvector tables. The deterministic hash "
            "embedding is a reproducible baseline for schema and operator mechanics; "
            "the fastembed projection is a local CPU semantic embedding comparison. "
            "Small local datasets can make absolute timings noisy, so compare result "
            "sets, overlap, plan shape, and index usage before treating timing as a "
            "performance claim."
        ),
    }


def markdown_cell(value: object) -> str:
    return str(value).replace("\n", " ").replace("|", "\\|")


def append_result_table(lines: list[str], results: Sequence[dict[str, Any]]) -> None:
    lines.extend(
        [
            "| Rank | Source | Title | Similarity | External ID |",
            "|---:|---|---|---:|---|",
        ]
    )
    for result in results:
        lines.append(
            "| "
            f"{result['rank']} | "
            f"`{markdown_cell(result['source'])}` | "
            f"{markdown_cell(result['title'])} | "
            f"{float(result['cosine_similarity']):.6f} | "
            f"`{markdown_cell(result['external_id'])}` |"
        )


def build_vector_retrieval_markdown(report: dict[str, Any]) -> str:
    parameters = report["parameters"]
    dataset_sizes = report["dataset_sizes"]
    retrieval = report["retrieval"]
    plan_summary = report["plan_summary"]

    lines = [
        f"# {report['title']}",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Track: `{report['track']}`",
        f"- Query: `{parameters['query']}`",
        f"- Embedding model: `{parameters['embedding_model']}`",
        f"- Embedding dimensions: `{parameters['embedding_dimensions']}`",
        f"- PostgreSQL: `{report['postgresql']['server_version']}`",
        "",
        "## Dataset",
        "",
        f"- Source limit: `{parameters['source_limit']}`",
        f"- Result limit: `{parameters['result_limit']}`",
    ]

    for name, row_count in dataset_sizes.items():
        lines.append(f"- `{name}`: {row_count}")

    lines.extend(
        [
            "",
            "## Retrieval Comparison",
            "",
            (
                f"- Top overlap: `{retrieval['top_overlap_count']}/"
                f"{retrieval['deterministic_result_count']} deterministic results`"
            ),
            "",
            "### Deterministic Hash Results",
            "",
        ]
    )
    append_result_table(lines, retrieval["deterministic_results"])

    lines.extend(["", "### Real Embedding Results", ""])
    append_result_table(lines, retrieval["model_results"])

    lines.extend(
        [
            "",
            "## Plan Summary",
            "",
            "| Path | Root node | Index names | Planning ms | Execution ms |",
            "|---|---|---|---:|---:|",
        ]
    )

    for path_name, plan in plan_summary.items():
        lines.append(
            "| "
            f"`{path_name}` | "
            f"`{plan['root_node_type']}` | "
            f"`{', '.join(plan['index_names'])}` | "
            f"{plan['planning_time_ms']} | "
            f"{plan['execution_time_ms']} |"
        )

    lines.extend(
        [
            "",
            "## Query",
            "",
            "### Deterministic Hash",
            "",
            "```sql",
            report["queries"]["deterministic_hash"].strip(),
            "```",
            "",
            "### Real Embedding",
            "",
            "```sql",
            report["queries"]["real_embedding"].strip(),
            "```",
            "",
            "## Interpretation",
            "",
            report["interpretation"],
            "",
        ]
    )
    return "\n".join(lines)


def json_default(value: object) -> str:
    if isinstance(value, datetime | Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def write_vector_retrieval_report(report: dict[str, Any], output_dir: Path) -> WrittenReport:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "vector-retrieval-benchmark.json"
    markdown_path = output_dir / "vector-retrieval-benchmark.md"

    json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, default=json_default),
        encoding="utf-8",
    )
    markdown_path.write_text(build_vector_retrieval_markdown(report), encoding="utf-8")

    return WrittenReport(json_path=json_path, markdown_path=markdown_path)


def run_vector_retrieval_benchmark(
    *,
    query: str = "pancakeswap swap bnb chain corpus",
    model_name: str = DEFAULT_FASTEMBED_MODEL,
    source_limit: int = 100,
    result_limit: int = 5,
    output_dir: Path | None = None,
    database_url: str | None = None,
) -> VectorRetrievalBenchmarkResult:
    comparison = run_embedding_comparison_smoke(
        query=query,
        model_name=model_name,
        source_limit=source_limit,
        result_limit=result_limit,
        database_url=database_url,
    )
    report = build_vector_retrieval_report(
        comparison=comparison,
        runtime=load_runtime_info(database_url),
        source_limit=source_limit,
        result_limit=result_limit,
    )
    report_dir = output_dir or (default_generated_reports_dir() / "vector")
    written = write_vector_retrieval_report(report, report_dir)
    return VectorRetrievalBenchmarkResult(comparison=comparison, report=written)


def run_embedding_comparison_smoke(
    *,
    query: str = "pancakeswap swap bnb chain corpus",
    model_name: str = DEFAULT_FASTEMBED_MODEL,
    source_limit: int = 100,
    result_limit: int = 5,
    model: TextEmbeddingModel | None = None,
    database_url: str | None = None,
) -> EmbeddingComparisonSmokeResult:
    embedding_model = model or load_fastembed_model(model_name)
    vector_projection = run_vector_memory_smoke(
        query=query,
        source_limit=source_limit,
        result_limit=result_limit,
        database_url=database_url,
    )
    documents = load_search_documents_for_memory(
        limit=source_limit,
        database_url=database_url,
    )
    document_embeddings = embed_texts(
        embedding_model,
        tuple(document.document_text for document in documents),
    )
    projected_model_chunks = upsert_model_memory_chunks(
        documents=documents,
        embeddings=document_embeddings,
        model_name=model_name,
        database_url=database_url,
    )
    query_embedding = embed_texts(embedding_model, (query,))[0]
    model_results = search_model_memory(
        query_embedding=query_embedding,
        model_name=model_name,
        limit=result_limit,
        database_url=database_url,
    )
    plan = load_model_similarity_plan(
        query_embedding=query_embedding,
        model_name=model_name,
        limit=result_limit,
        database_url=database_url,
    )

    return EmbeddingComparisonSmokeResult(
        vector_projection=vector_projection,
        embedding_model=model_name,
        embedding_dimensions=FASTEMBED_MODEL_DIMENSIONS,
        projected_model_chunks=projected_model_chunks,
        total_model_chunks=count_model_memory_chunks(
            model_name=model_name,
            database_url=database_url,
        ),
        query_text=query,
        deterministic_results=vector_projection.results,
        model_results=model_results,
        top_overlap_count=count_top_overlap(vector_projection.results, model_results),
        plan=plan,
    )
