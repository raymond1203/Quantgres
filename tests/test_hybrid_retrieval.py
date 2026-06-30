from quantgres.experiments.hybrid_retrieval import (
    SEARCH_VECTOR_INDEX_NAME,
    VECTOR_INDEX_NAME,
    summarize_plan,
    weighted_hybrid_score,
)


def test_weighted_hybrid_score_uses_missing_scores_as_zero():
    score = weighted_hybrid_score(
        text_rank=0.5,
        trigram_similarity=None,
        vector_similarity=0.25,
    )

    assert score == 0.45 * 0.5 + 0.40 * 0.25


def test_summarize_plan_extracts_nested_hybrid_indexes():
    plan = [
        {
            "Plan": {
                "Node Type": "Limit",
                "Shared Hit Blocks": 1,
                "Shared Read Blocks": 0,
                "Plans": [
                    {
                        "Node Type": "Bitmap Index Scan",
                        "Index Name": SEARCH_VECTOR_INDEX_NAME,
                        "Shared Hit Blocks": 2,
                        "Shared Read Blocks": 0,
                    },
                    {
                        "Node Type": "Index Scan",
                        "Index Name": VECTOR_INDEX_NAME,
                        "Shared Hit Blocks": 3,
                        "Shared Read Blocks": 1,
                    },
                ],
            },
            "Planning Time": 0.8,
            "Execution Time": 1.2,
        }
    ]

    summary = summarize_plan(plan)

    assert summary.root_node_type == "Limit"
    assert summary.index_names == (SEARCH_VECTOR_INDEX_NAME, VECTOR_INDEX_NAME)
    assert summary.planning_time_ms == 0.8
    assert summary.execution_time_ms == 1.2
    assert summary.shared_hit_blocks == 6
    assert summary.shared_read_blocks == 1
