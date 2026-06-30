import math
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from quantgres.experiments.embedding_comparison import (
    FASTEMBED_MODEL_DIMENSIONS,
    MODEL_VECTOR_INDEX_NAME,
    EmbeddingComparisonSmokeResult,
    TextEmbeddingModel,
    build_vector_retrieval_markdown,
    build_vector_retrieval_report,
    coerce_embedding,
    count_top_overlap,
    embed_texts,
    write_vector_retrieval_report,
)
from quantgres.experiments.vector_memory import (
    MemorySearchResult,
    VectorMemorySmokeResult,
    VectorPlanSummary,
    summarize_vector_plan,
)
from quantgres.runtime import DatabaseRuntimeInfo, ExtensionStatus


class FakeEmbeddingModel:
    def embed(self, documents: Sequence[str]) -> tuple[tuple[float, float, float], ...]:
        return tuple((float(len(document)), 1.0, 0.0) for document in documents)


def test_embed_texts_uses_one_model_embedding_per_text():
    model: TextEmbeddingModel = FakeEmbeddingModel()

    embeddings = embed_texts(model, ("alpha", "bnb"), expected_dimensions=3)

    assert embeddings == ((5.0, 1.0, 0.0), (3.0, 1.0, 0.0))


def test_coerce_embedding_rejects_bad_dimensions():
    with pytest.raises(ValueError, match="Expected 3 embedding dimensions"):
        coerce_embedding((1.0, 2.0), expected_dimensions=3)


def test_coerce_embedding_rejects_non_finite_values():
    with pytest.raises(ValueError, match="finite"):
        coerce_embedding((1.0, math.inf, 3.0), expected_dimensions=3)


def test_coerce_embedding_rejects_zero_vector():
    with pytest.raises(ValueError, match="must not be zero"):
        coerce_embedding((0.0, 0.0, 0.0), expected_dimensions=3)


def test_count_top_overlap_uses_source_and_external_id():
    baseline = (
        MemorySearchResult("search", "a", "A", "preview", 0.9),
        MemorySearchResult("search", "b", "B", "preview", 0.8),
    )
    model = (
        MemorySearchResult("search", "b", "B", "preview", 0.7),
        MemorySearchResult("search", "c", "C", "preview", 0.6),
    )

    assert count_top_overlap(baseline, model) == 1


def test_model_plan_summary_extracts_real_embedding_hnsw_index_name():
    plan = [
        {
            "Plan": {
                "Node Type": "Limit",
                "Plans": [
                    {
                        "Node Type": "Index Scan",
                        "Index Name": MODEL_VECTOR_INDEX_NAME,
                    }
                ],
            },
            "Planning Time": 0.3,
            "Execution Time": 0.5,
        }
    ]

    summary = summarize_vector_plan(plan)

    assert summary.index_names == (MODEL_VECTOR_INDEX_NAME,)


def build_comparison_result() -> EmbeddingComparisonSmokeResult:
    plan = VectorPlanSummary(
        root_node_type="Limit",
        index_names=(MODEL_VECTOR_INDEX_NAME,),
        planning_time_ms=0.1,
        execution_time_ms=0.2,
    )
    deterministic_result = MemorySearchResult(
        source="bnb_rpc_log",
        external_id="tx-1",
        title="BNB Chain PancakeSwap swap log",
        preview="bnb chain pancakeswap swap rpc log",
        cosine_similarity=0.9,
    )
    model_result = MemorySearchResult(
        source="bnb_rpc_log",
        external_id="tx-1",
        title="BNB Chain PancakeSwap swap log",
        preview="bnb chain pancakeswap swap rpc log",
        cosine_similarity=0.8,
    )
    return EmbeddingComparisonSmokeResult(
        vector_projection=VectorMemorySmokeResult(
            projected_chunks=1,
            total_chunks=2,
            query_text="pancakeswap swap bnb chain",
            results=(deterministic_result,),
            plan=plan,
        ),
        embedding_model="BAAI/bge-small-en-v1.5",
        embedding_dimensions=FASTEMBED_MODEL_DIMENSIONS,
        projected_model_chunks=1,
        total_model_chunks=2,
        query_text="pancakeswap swap bnb chain",
        deterministic_results=(deterministic_result,),
        model_results=(model_result,),
        top_overlap_count=1,
        plan=plan,
    )


def build_runtime_info() -> DatabaseRuntimeInfo:
    return DatabaseRuntimeInfo(
        server_version="PostgreSQL 18.4 on test",
        server_version_num=180004,
        database_name="quantgres",
        user_name="quantgres",
        extensions=(
            ExtensionStatus(name="pg_trgm", version="1.6"),
            ExtensionStatus(name="vector", version="0.8.3"),
        ),
    )


def test_build_vector_retrieval_report_includes_results_and_runtime():
    report = build_vector_retrieval_report(
        comparison=build_comparison_result(),
        runtime=build_runtime_info(),
        source_limit=20,
        result_limit=5,
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert report["title"] == "VectorDB Retrieval Benchmark"
    assert report["parameters"]["source_limit"] == 20
    assert report["postgresql"]["server_version_num"] == 180004
    assert report["dataset_sizes"]["model_total_chunks"] == 2
    assert report["retrieval"]["top_overlap_count"] == 1
    assert report["retrieval"]["deterministic_result_count"] == 1
    assert report["retrieval"]["model_result_count"] == 1
    assert report["retrieval"]["model_results"][0]["external_id"] == "tx-1"
    assert report["plan_summary"]["real_embedding"]["index_names"] == [MODEL_VECTOR_INDEX_NAME]


def test_build_vector_retrieval_markdown_includes_required_sections():
    report = build_vector_retrieval_report(
        comparison=build_comparison_result(),
        runtime=build_runtime_info(),
        source_limit=20,
        result_limit=5,
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    markdown = build_vector_retrieval_markdown(report)

    assert "## Dataset" in markdown
    assert "## Retrieval Comparison" in markdown
    assert "### Real Embedding Results" in markdown
    assert MODEL_VECTOR_INDEX_NAME in markdown


def test_write_vector_retrieval_report_creates_json_and_markdown(tmp_path: Path):
    report = build_vector_retrieval_report(
        comparison=build_comparison_result(),
        runtime=build_runtime_info(),
        source_limit=20,
        result_limit=5,
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    written = write_vector_retrieval_report(report, tmp_path)

    assert written.json_path.exists()
    assert written.markdown_path.exists()
    assert "VectorDB Retrieval Benchmark" in written.markdown_path.read_text(encoding="utf-8")
