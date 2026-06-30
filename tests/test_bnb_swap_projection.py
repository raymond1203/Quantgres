from decimal import Decimal

import pytest

from quantgres.experiments.bnb_swap_projection import (
    PANCAKESWAP_V2_SWAP_TOPIC0,
    RawSwapLogRow,
    decode_raw_swap_log,
    decode_swap_amounts,
    topic_to_address,
)


def word(value: int) -> str:
    return f"{value:064x}"


def address_topic(address: str) -> str:
    return "0x" + ("0" * 24) + address.removeprefix("0x")


def test_topic_to_address_uses_last_20_bytes():
    assert (
        topic_to_address(address_topic("0x10ed43c718714eb63d5aa57b78b54704e256024e"))
        == "0x10ed43c718714eb63d5aa57b78b54704e256024e"
    )


def test_decode_swap_amounts_reads_four_uint256_words():
    amounts = decode_swap_amounts("0x" + word(1) + word(2) + word(3) + word(4))

    assert amounts.amount0_in == Decimal(1)
    assert amounts.amount1_in == Decimal(2)
    assert amounts.amount0_out == Decimal(3)
    assert amounts.amount1_out == Decimal(4)


def test_decode_swap_amounts_rejects_wrong_word_count():
    with pytest.raises(ValueError, match="Expected hex body length"):
        decode_swap_amounts("0x" + word(1))


def test_decode_raw_swap_log_rejects_unexpected_topic0():
    raw_log = RawSwapLogRow(
        chain_id=56,
        pair_address="0x16b9a82891338f9ba80e2d6970fdda79d1eb0dae",
        block_number=107270817,
        block_hash="0xblock",
        transaction_hash="0xtx",
        transaction_index=1,
        log_index=2,
        data="0x" + word(1) + word(2) + word(3) + word(4),
        topics=(
            "0x" + "0" * 64,
            address_topic("0x10ed43c718714eb63d5aa57b78b54704e256024e"),
            address_topic("0x0000000000000000000000000000000000000001"),
        ),
        raw_log={"address": "0x16b9a82891338f9ba80e2d6970fdda79d1eb0dae"},
    )

    with pytest.raises(ValueError, match="Unexpected Swap topic0"):
        decode_raw_swap_log(raw_log)


def test_decode_raw_swap_log_maps_topics_and_amounts():
    raw_log = RawSwapLogRow(
        chain_id=56,
        pair_address="0x16b9a82891338f9ba80e2d6970fdda79d1eb0dae",
        block_number=107270817,
        block_hash="0xblock",
        transaction_hash="0xtx",
        transaction_index=1,
        log_index=2,
        data="0x" + word(10) + word(20) + word(30) + word(40),
        topics=(
            PANCAKESWAP_V2_SWAP_TOPIC0,
            address_topic("0x10ed43c718714eb63d5aa57b78b54704e256024e"),
            address_topic("0x0000000000000000000000000000000000000001"),
        ),
        raw_log={"address": "0x16b9a82891338f9ba80e2d6970fdda79d1eb0dae"},
    )

    decoded = decode_raw_swap_log(raw_log)

    assert decoded["sender"] == "0x10ed43c718714eb63d5aa57b78b54704e256024e"
    assert decoded["recipient"] == "0x0000000000000000000000000000000000000001"
    assert decoded["amount0_in"] == Decimal(10)
    assert decoded["amount1_in"] == Decimal(20)
    assert decoded["amount0_out"] == Decimal(30)
    assert decoded["amount1_out"] == Decimal(40)
