from datetime import UTC, datetime

import pytest

from quantgres.experiments.bnb_block_timestamps import (
    BlockFetchPolicy,
    BlockFetchRetryError,
    fetch_block_with_retries,
    fetch_blocks,
    select_missing_block_numbers,
)
from quantgres.onchain.bnb_rpc import BnbBlock, normalize_block


def make_block(block_number: int) -> BnbBlock:
    return BnbBlock(
        chain_id=56,
        rpc_url="https://example.invalid",
        block_number=block_number,
        block_hash=f"0x{block_number:x}",
        parent_hash=f"0x{block_number - 1:x}",
        block_timestamp=datetime.fromtimestamp(block_number, tz=UTC),
        raw_block={"number": hex(block_number), "timestamp": hex(block_number)},
    )


def test_normalize_block_parses_hex_timestamp():
    block = normalize_block(
        raw_block={
            "number": "0x65",
            "hash": "0xabc",
            "parentHash": "0xdef",
            "timestamp": "0x5",
        },
        chain_id=56,
        rpc_url="https://example.invalid",
    )

    assert block.block_number == 101
    assert block.block_timestamp == datetime.fromtimestamp(5, tz=UTC)
    assert block.block_hash == "0xabc"


def test_select_missing_block_numbers_preserves_requested_order():
    assert select_missing_block_numbers(
        requested_block_numbers=(105, 101, 103),
        cached_block_numbers=(101,),
    ) == (105, 103)


def test_fetch_block_with_retries_returns_after_transient_failure():
    calls: list[int] = []
    sleeps: list[float] = []

    def flaky_fetcher(
        *,
        rpc_url: str,
        chain_id: int,
        block_number: int,
        include_transactions: bool = False,
    ) -> BnbBlock:
        calls.append(block_number)
        if len(calls) == 1:
            raise TimeoutError("temporary RPC timeout")
        assert include_transactions is False
        return make_block(block_number)

    block = fetch_block_with_retries(
        block_number=101,
        rpc_url="https://example.invalid",
        chain_id=56,
        policy=BlockFetchPolicy(max_attempts=2, retry_sleep_seconds=0.5),
        fetcher=flaky_fetcher,
        sleeper=sleeps.append,
    )

    assert block.block_number == 101
    assert calls == [101, 101]
    assert sleeps == [0.5]


def test_fetch_blocks_raises_aggregated_retry_failures():
    calls: list[int] = []

    def failing_fetcher(
        *,
        rpc_url: str,
        chain_id: int,
        block_number: int,
        include_transactions: bool = False,
    ) -> BnbBlock:
        calls.append(block_number)
        raise TimeoutError("RPC timeout")

    with pytest.raises(BlockFetchRetryError) as error:
        fetch_blocks(
            block_numbers=(101, 102),
            rpc_url="https://example.invalid",
            chain_id=56,
            policy=BlockFetchPolicy(max_attempts=2, retry_sleep_seconds=0),
            fetcher=failing_fetcher,
            sleeper=lambda _: None,
        )

    failures = error.value.failures
    assert tuple(failure.block_number for failure in failures) == (101, 102)
    assert tuple(failure.attempts for failure in failures) == (2, 2)
    assert tuple(failure.error_type for failure in failures) == ("TimeoutError", "TimeoutError")
    assert calls == [101, 101, 102, 102]
