import math
from collections.abc import Sequence

import pytest

from quantgres.experiments.embedding_comparison import (
    MODEL_VECTOR_INDEX_NAME,
    TextEmbeddingModel,
    coerce_embedding,
    count_top_overlap,
    embed_texts,
)
from quantgres.experiments.vector_memory import MemorySearchResult, summarize_vector_plan


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
