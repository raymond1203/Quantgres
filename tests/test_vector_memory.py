import math

from quantgres.experiments.vector_memory import (
    SELECT_SEARCH_DOCUMENTS_SQL,
    SIMILARITY_SEARCH_SQL,
    embed_text,
    summarize_vector_plan,
    tokenize,
    vector_literal,
)


def cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return sum(
        left_value * right_value for left_value, right_value in zip(left, right, strict=True)
    )


def test_embed_text_is_deterministic_and_unit_length():
    first = embed_text("BNB Chain PancakeSwap swap")
    second = embed_text("BNB Chain PancakeSwap swap")

    assert first == second
    assert len(first) == 16
    assert math.isclose(math.sqrt(sum(value * value for value in first)), 1.0)


def test_tokenize_extracts_lowercase_alphanumeric_tokens():
    assert tokenize("BTCUSDT, PancakeSwap V2!") == ("btcusdt", "pancakeswap", "v2")


def test_domain_tokens_make_pancakeswap_query_closer_to_bnb_text():
    query = embed_text("pancakeswap swap bnb chain corpus")
    bnb_text = embed_text("bnb chain pancakeswap swap corpus enriched event time")
    raw_log_text = embed_text("bnb chain pancakeswap swap rpc log")
    binance_text = embed_text("binance kline market candle btcusdt")

    assert cosine(query, bnb_text) > cosine(query, binance_text)
    assert cosine(query, bnb_text) > cosine(query, raw_log_text)


def test_vector_literal_formats_pgvector_literal():
    assert vector_literal((0.5, -0.25)) == "[0.50000000,-0.25000000]"


def test_summarize_vector_plan_extracts_hnsw_index_name():
    plan = [
        {
            "Plan": {
                "Node Type": "Limit",
                "Plans": [
                    {
                        "Node Type": "Index Scan",
                        "Index Name": "agent_memory_chunks_embedding_hnsw_idx",
                    }
                ],
            },
            "Planning Time": 0.2,
            "Execution Time": 0.4,
        }
    ]

    summary = summarize_vector_plan(plan)

    assert summary.root_node_type == "Limit"
    assert summary.index_names == ("agent_memory_chunks_embedding_hnsw_idx",)
    assert summary.planning_time_ms == 0.2
    assert summary.execution_time_ms == 0.4


def test_vector_queries_filter_to_current_corpus_sources():
    for sql in (SELECT_SEARCH_DOCUMENTS_SQL, SIMILARITY_SEARCH_SQL):
        assert "source IN ('binance_kline', 'bnb_swap_corpus')" in sql
    assert "CASE WHEN source = 'bnb_swap_corpus' THEN 0 ELSE 1 END" in SELECT_SEARCH_DOCUMENTS_SQL
