from decimal import Decimal

from quantgres.experiments.feature_batches import build_batch_id, summarize_plan
from quantgres.experiments.feature_store import FeatureSourceRow


def source_row(close_price: str) -> FeatureSourceRow:
    return FeatureSourceRow(
        symbol="BTCUSDT",
        event_ts="2026-01-01T00:00:00Z",
        feature_ts="2026-01-01T00:01:00Z",
        close_price=Decimal(close_price),
        previous_close_price=None,
        return_bps=None,
        rolling_5_return_bps=None,
        volume=Decimal("1"),
        quote_volume=Decimal("2"),
        swap_count=0,
        refreshed_at="2026-01-01T00:02:00Z",
        candle_source="binance_spot_klines",
    )


def test_build_batch_id_changes_when_source_rows_change():
    left = build_batch_id(
        feature_set="market_return_v1",
        run_key="default",
        rows=(source_row("10"),),
    )
    right = build_batch_id(
        feature_set="market_return_v1",
        run_key="default",
        rows=(source_row("11"),),
    )

    assert left != right


def test_summarize_plan_extracts_batch_asof_index():
    plan = [
        {
            "Plan": {
                "Node Type": "Limit",
                "Plans": [
                    {
                        "Node Type": "Index Scan",
                        "Index Name": "quant_feature_batch_items_symbol_asof_idx",
                    }
                ],
            },
            "Planning Time": 0.1,
            "Execution Time": 0.2,
        }
    ]

    summary = summarize_plan(plan)

    assert summary.root_node_type == "Limit"
    assert summary.index_names == ("quant_feature_batch_items_symbol_asof_idx",)
