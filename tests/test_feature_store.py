from decimal import Decimal

from quantgres.experiments.feature_store import (
    ASOF_INDEX_NAME,
    FeatureSourceRow,
    feature_metadata,
    summarize_plan,
)


def test_feature_metadata_records_source_and_feature_set():
    row = FeatureSourceRow(
        symbol="BTCUSDT",
        event_ts="2026-01-01T00:00:00Z",
        feature_ts="2026-01-01T00:01:00Z",
        close_price=Decimal("1"),
        previous_close_price=None,
        return_bps=None,
        rolling_5_return_bps=None,
        volume=Decimal("2"),
        quote_volume=Decimal("3"),
        swap_count=4,
        refreshed_at="2026-01-01T00:02:00Z",
        candle_source="binance_spot_klines",
    )

    metadata = feature_metadata(row=row, feature_set="market_return_v1")

    assert metadata == {
        "feature_set": "market_return_v1",
        "source": "analytics.market_return_panel",
        "candle_source": "binance_spot_klines",
        "panel_refreshed_at": "2026-01-01T00:02:00Z",
    }


def test_summarize_plan_extracts_asof_index_and_buffer_summary():
    plan = [
        {
            "Plan": {
                "Node Type": "Limit",
                "Shared Hit Blocks": 1,
                "Shared Read Blocks": 0,
                "Plans": [
                    {
                        "Node Type": "Index Scan",
                        "Index Name": ASOF_INDEX_NAME,
                        "Shared Hit Blocks": 3,
                        "Shared Read Blocks": 1,
                    }
                ],
            },
            "Planning Time": 0.2,
            "Execution Time": 0.4,
        }
    ]

    summary = summarize_plan(plan)

    assert summary.root_node_type == "Limit"
    assert summary.index_names == (ASOF_INDEX_NAME,)
    assert summary.planning_time_ms == 0.2
    assert summary.execution_time_ms == 0.4
    assert summary.shared_hit_blocks == 4
    assert summary.shared_read_blocks == 1
