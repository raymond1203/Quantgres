from datetime import UTC, datetime

import pytest

from quantgres.experiments.olap_return_panel import (
    build_binance_kline_window_ms,
    datetime_to_milliseconds,
    summarize_plan,
)


def test_build_binance_kline_window_ms_pads_event_minute_range():
    start_ms, end_ms = build_binance_kline_window_ms(
        (
            datetime(2026, 6, 30, 14, 41, 44, tzinfo=UTC),
            datetime(2026, 6, 30, 14, 42, 12, tzinfo=UTC),
        ),
        padding_minutes=5,
    )

    assert start_ms == datetime_to_milliseconds(datetime(2026, 6, 30, 14, 36, tzinfo=UTC))
    assert end_ms == datetime_to_milliseconds(datetime(2026, 6, 30, 14, 48, tzinfo=UTC))


def test_build_binance_kline_window_ms_allows_empty_timestamp_set():
    assert build_binance_kline_window_ms(()) == (None, None)


def test_build_binance_kline_window_ms_rejects_bad_inputs():
    with pytest.raises(ValueError, match="padding_minutes"):
        build_binance_kline_window_ms((), padding_minutes=-1)

    with pytest.raises(TypeError, match="datetime"):
        build_binance_kline_window_ms(("2026-06-30T14:41:44Z",))


def test_summarize_plan_extracts_index_and_buffer_summary():
    plan = [
        {
            "Plan": {
                "Node Type": "Limit",
                "Shared Hit Blocks": 1,
                "Shared Read Blocks": 0,
                "Plans": [
                    {
                        "Node Type": "Index Scan",
                        "Index Name": "market_return_panel_symbol_ts_idx",
                        "Shared Hit Blocks": 4,
                        "Shared Read Blocks": 2,
                    }
                ],
            },
            "Planning Time": 0.3,
            "Execution Time": 0.5,
        }
    ]

    summary = summarize_plan(plan)

    assert summary.root_node_type == "Limit"
    assert summary.index_names == ("market_return_panel_symbol_ts_idx",)
    assert summary.planning_time_ms == 0.3
    assert summary.execution_time_ms == 0.5
    assert summary.shared_hit_blocks == 5
    assert summary.shared_read_blocks == 2
