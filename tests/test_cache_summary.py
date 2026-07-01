from datetime import UTC, datetime

import pytest

from quantgres.experiments.bnb_block_timestamps import EnrichedSwapEventRow
from quantgres.experiments.bnb_raw_logs import BnbLogWindowResult, BnbWindowedLogIngestionResult
from quantgres.experiments.bnb_swap_corpus import BnbSwapCorpusSmokeResult
from quantgres.experiments.cache_summary import (
    BASE_SUMMARY_LOOKUP_SQL,
    MARKET_ONCHAIN_SUMMARY_SQL,
    read_sql,
    require_enriched_swap_corpus,
    summarize_plan,
)
from quantgres.reports import WrittenReport


def make_swap_corpus(tmp_path, *, enriched_swaps: int = 1) -> BnbSwapCorpusSmokeResult:
    return BnbSwapCorpusSmokeResult(
        windowed_ingestion=BnbWindowedLogIngestionResult(
            rpc_url="https://example.invalid",
            chain_id=56,
            from_block=100,
            to_block=109,
            address="0xpair",
            topic0="0xtopic",
            window_size=10,
            windows=(
                BnbLogWindowResult(from_block=100, to_block=109, rows_fetched=1, rows_upserted=1),
            ),
        ),
        projected_events=1,
        requested_block_numbers=(100,),
        cached_block_numbers=(100,),
        missing_block_numbers=(),
        fetched_blocks=(),
        upserted_blocks=0,
        updated_swaps=enriched_swaps,
        enriched_swaps=enriched_swaps,
        sample_events=(
            EnrichedSwapEventRow(
                chain_id=56,
                dex="pancakeswap_v2",
                pair_address="0xpair",
                block_number=100,
                block_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                transaction_hash="0xtx",
                log_index=1,
            ),
        )
        if enriched_swaps
        else (),
        report=WrittenReport(
            json_path=tmp_path / "bnb-swap-corpus.json",
            markdown_path=tmp_path / "bnb-swap-corpus.md",
        ),
    )


def test_cache_summary_sql_uses_enriched_swap_event_time():
    schema_sql = read_sql(MARKET_ONCHAIN_SUMMARY_SQL)

    for sql in (BASE_SUMMARY_LOOKUP_SQL, schema_sql):
        assert "max(block_timestamp) AS latest_observed_at" in sql
        assert "'enriched_swap_count', count(*)" in sql
        assert "'first_block_timestamp', min(block_timestamp)" in sql
        assert "'last_block_timestamp', max(block_timestamp)" in sql
        assert "AND block_timestamp IS NOT NULL" in sql


def test_require_enriched_swap_corpus_rejects_empty_enrichment(tmp_path):
    with pytest.raises(RuntimeError, match="non-empty enriched BNB swap corpus"):
        require_enriched_swap_corpus(make_swap_corpus(tmp_path, enriched_swaps=0))


def test_require_enriched_swap_corpus_accepts_sample_event(tmp_path):
    require_enriched_swap_corpus(make_swap_corpus(tmp_path))


def test_summarize_plan_extracts_index_names_and_buffers():
    plan = [
        {
            "Plan": {
                "Node Type": "Index Scan",
                "Index Name": "market_onchain_summary_key_idx",
                "Shared Hit Blocks": 3,
                "Shared Read Blocks": 0,
                "Plans": [
                    {
                        "Node Type": "Bitmap Index Scan",
                        "Index Name": "swap_events_pair_block_idx",
                        "Shared Hit Blocks": 5,
                        "Shared Read Blocks": 2,
                    }
                ],
            },
            "Planning Time": 0.11,
            "Execution Time": 0.22,
        }
    ]

    summary = summarize_plan(plan)

    assert summary.root_node_type == "Index Scan"
    assert summary.index_names == (
        "market_onchain_summary_key_idx",
        "swap_events_pair_block_idx",
    )
    assert summary.planning_time_ms == 0.11
    assert summary.execution_time_ms == 0.22
    assert summary.shared_hit_blocks == 8
    assert summary.shared_read_blocks == 2
