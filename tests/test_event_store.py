from datetime import UTC, datetime
from decimal import Decimal

from quantgres.experiments.binance_candles import BinanceCandleIngestionResult
from quantgres.experiments.bnb_block_timestamps import EnrichedSwapEventRow
from quantgres.experiments.bnb_raw_logs import BnbLogWindowResult, BnbWindowedLogIngestionResult
from quantgres.experiments.bnb_swap_corpus import BnbSwapCorpusSmokeResult
from quantgres.experiments.event_store import (
    AgentEventDraft,
    build_event_drafts,
    build_event_id,
    summarize_plan,
)
from quantgres.experiments.feature_batches import (
    FeatureBatchItemRow,
    FeatureBatchPlanSummary,
    FeatureBatchSmokeResult,
)
from quantgres.experiments.olap_return_panel import (
    MarketReturnPanelRow,
    OlapPlanSummary,
    OlapReturnPanelSmokeResult,
)
from quantgres.experiments.vector_memory import (
    MemorySearchResult,
    VectorMemorySmokeResult,
    VectorPlanSummary,
)
from quantgres.reports import WrittenReport


def test_build_event_id_is_stable_for_canonical_payload_order():
    left = AgentEventDraft(
        event_type="olap_return_panel_observed",
        subject_type="symbol",
        subject_id="BTCUSDT",
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        source="test",
        payload={"b": 2, "a": 1},
    )
    right = AgentEventDraft(
        event_type="olap_return_panel_observed",
        subject_type="symbol",
        subject_id="BTCUSDT",
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        source="test",
        payload={"a": 1, "b": 2},
    )

    assert build_event_id(left) == build_event_id(right)


def make_olap_result(tmp_path) -> OlapReturnPanelSmokeResult:
    event_ts = datetime(2026, 6, 30, 14, 42, tzinfo=UTC)
    corpus = BnbSwapCorpusSmokeResult(
        windowed_ingestion=BnbWindowedLogIngestionResult(
            rpc_url="https://example.invalid",
            chain_id=56,
            from_block=107270717,
            to_block=107270817,
            address="0x16b9a82891338f9ba80e2d6970fdda79d1eb0dae",
            topic0="0xtopic",
            window_size=10,
            windows=(
                BnbLogWindowResult(
                    from_block=107270717,
                    to_block=107270726,
                    rows_fetched=2,
                    rows_upserted=2,
                ),
            ),
        ),
        projected_events=41,
        requested_block_numbers=(107270817,),
        cached_block_numbers=(107270817,),
        missing_block_numbers=(),
        fetched_blocks=(),
        upserted_blocks=0,
        updated_swaps=41,
        enriched_swaps=41,
        sample_events=(
            EnrichedSwapEventRow(
                chain_id=56,
                dex="pancakeswap_v2",
                pair_address="0x16b9a82891338f9ba80e2d6970fdda79d1eb0dae",
                block_number=107270817,
                block_timestamp=event_ts,
                transaction_hash="0xtx",
                log_index=1,
            ),
        ),
        report=WrittenReport(
            json_path=tmp_path / "bnb-swap-corpus.json",
            markdown_path=tmp_path / "bnb-swap-corpus.md",
        ),
    )
    row = MarketReturnPanelRow(
        symbol="BTCUSDT",
        ts=event_ts,
        close_price=Decimal("58706.53"),
        previous_close_price=Decimal("58698.01"),
        return_bps=Decimal("1.45"),
        rolling_5_return_bps=Decimal("-1.47"),
        volume=Decimal("1"),
        quote_volume=Decimal("2"),
        swap_count=31,
    )
    return OlapReturnPanelSmokeResult(
        binance_ingestion=BinanceCandleIngestionResult(
            symbol="BTCUSDT",
            interval="1m",
            source="binance_spot_klines",
            rows_fetched=12,
            rows_upserted=12,
            first_ts=event_ts,
            last_ts=event_ts,
        ),
        swap_corpus=corpus,
        panel_rows=100,
        latest_rows=(row,),
        swap_aligned_rows=(row,),
        plan=OlapPlanSummary(
            root_node_type="Limit",
            index_names=("market_return_panel_symbol_ts_idx",),
            planning_time_ms=0.1,
            execution_time_ms=0.2,
            shared_hit_blocks=1,
            shared_read_blocks=0,
        ),
    )


def make_feature_batch_result() -> FeatureBatchSmokeResult:
    item = FeatureBatchItemRow(
        batch_id="batch-1",
        symbol="BTCUSDT",
        event_ts=datetime(2026, 6, 30, 14, 42, tzinfo=UTC),
        feature_ts=datetime(2026, 6, 30, 14, 42, 59, tzinfo=UTC),
        close_price=Decimal("58706.53"),
        previous_close_price=Decimal("58698.01"),
        return_bps=Decimal("1.45"),
        rolling_5_return_bps=Decimal("-1.47"),
        volume=Decimal("1"),
        quote_volume=Decimal("2"),
        swap_count=31,
        metadata={"source": "analytics.market_return_panel"},
    )
    return FeatureBatchSmokeResult(
        batch_id="batch-1",
        feature_set="market_return_v1",
        config_hash="config",
        code_hash="code",
        dependency_hash="dependency",
        runtime_hash="runtime",
        source_rows=5,
        inserted_batch=1,
        inserted_items=5,
        total_batch_items=5,
        as_of_ts=item.feature_ts,
        as_of_item=item,
        plan=FeatureBatchPlanSummary(
            root_node_type="Limit",
            index_names=("quant_feature_batch_items_symbol_asof_idx",),
            planning_time_ms=0.1,
            execution_time_ms=0.2,
        ),
    )


def make_vector_result() -> VectorMemorySmokeResult:
    return VectorMemorySmokeResult(
        projected_chunks=1,
        total_chunks=1,
        query_text="pancakeswap swap bnb chain",
        results=(
            MemorySearchResult(
                source="bnb_rpc_log",
                external_id="log-1",
                title="BNB Chain PancakeSwap swap log",
                preview="pancakeswap swap bnb chain",
                cosine_similarity=0.9,
            ),
        ),
        plan=VectorPlanSummary(
            root_node_type="Limit",
            index_names=("agent_memory_chunks_embedding_idx",),
            planning_time_ms=0.1,
            execution_time_ms=0.2,
        ),
    )


def test_build_event_drafts_records_pipeline_evidence(tmp_path):
    drafts = build_event_drafts(
        olap_result=make_olap_result(tmp_path),
        feature_batch_result=make_feature_batch_result(),
        vector_result=make_vector_result(),
    )

    event_types = tuple(draft.event_type for draft in drafts)

    assert event_types == (
        "bnb_swap_corpus_ingested",
        "olap_swap_aligned_observed",
        "feature_batch_item_observed",
        "vector_memory_retrieval_observed",
    )
    assert drafts[0].payload["pipeline"] == "bnb_swap_corpus"
    assert drafts[0].payload["rows_fetched"] == 2
    assert drafts[1].payload["stage"] == "olap_event_time_alignment"
    assert drafts[1].payload["swap_count"] == 31
    assert drafts[2].payload["stage"] == "feature_batch"
    assert drafts[2].payload["batch_id"] == "batch-1"
    assert drafts[3].subject_type == "query"


def test_summarize_plan_extracts_event_store_indexes():
    plan = [
        {
            "Plan": {
                "Node Type": "Bitmap Heap Scan",
                "Shared Hit Blocks": 2,
                "Shared Read Blocks": 0,
                "Plans": [
                    {
                        "Node Type": "Bitmap Index Scan",
                        "Index Name": "agent_events_payload_gin_idx",
                        "Shared Hit Blocks": 3,
                        "Shared Read Blocks": 1,
                    }
                ],
            },
            "Planning Time": 0.4,
            "Execution Time": 0.7,
        }
    ]

    summary = summarize_plan(plan)

    assert summary.root_node_type == "Bitmap Heap Scan"
    assert summary.index_names == ("agent_events_payload_gin_idx",)
    assert summary.planning_time_ms == 0.4
    assert summary.execution_time_ms == 0.7
    assert summary.shared_hit_blocks == 5
    assert summary.shared_read_blocks == 1
