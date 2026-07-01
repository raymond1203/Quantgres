import pytest

from quantgres.experiments.bnb_raw_logs import (
    BnbLogWindowResult,
    BnbWindowedLogIngestionResult,
    build_block_windows,
)


def test_build_block_windows_splits_inclusive_range():
    windows = build_block_windows(from_block=10, to_block=25, window_size=10)

    assert [(window.from_block, window.to_block) for window in windows] == [
        (10, 19),
        (20, 25),
    ]


def test_build_block_windows_rejects_invalid_range():
    with pytest.raises(ValueError, match="to_block"):
        build_block_windows(from_block=20, to_block=10, window_size=10)


def test_build_block_windows_rejects_non_positive_window_size():
    with pytest.raises(ValueError, match="positive"):
        build_block_windows(from_block=10, to_block=20, window_size=0)


def test_windowed_log_ingestion_result_aggregates_window_rows():
    result = BnbWindowedLogIngestionResult(
        rpc_url="https://example.invalid",
        chain_id=56,
        from_block=10,
        to_block=25,
        address=None,
        topic0=None,
        window_size=10,
        windows=(
            BnbLogWindowResult(
                from_block=10,
                to_block=19,
                rows_fetched=2,
                rows_upserted=2,
            ),
            BnbLogWindowResult(
                from_block=20,
                to_block=25,
                rows_fetched=3,
                rows_upserted=3,
            ),
        ),
    )

    assert result.rows_fetched == 5
    assert result.rows_upserted == 5
