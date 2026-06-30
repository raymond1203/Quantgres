import pytest

from quantgres.onchain.bnb_rpc import hex_to_int, normalize_log, parse_block_arg


def test_parse_block_arg_accepts_decimal_and_hex():
    assert parse_block_arg("107270817") == 107270817
    assert parse_block_arg("0x664d2a1") == 107270817


def test_hex_to_int_rejects_non_hex_quantity():
    with pytest.raises(ValueError, match="Expected hex quantity"):
        hex_to_int("107270817")


def test_normalize_log_maps_json_rpc_log_fields():
    raw_log = {
        "address": "0x16B9A82891338F9BA80E2D6970FDDA79D1EB0DAE",
        "topics": [
            "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822",
            "0x00000000000000000000000010ed43c718714eb63d5aa57b78b54704e256024e",
        ],
        "data": "0x00",
        "blockNumber": "0x664d2a1",
        "transactionHash": "0x3634a043db0f5f0f1693793cfad1341400aeef12b762d3e8bc5dee48398ac485",
        "transactionIndex": "0x29",
        "blockHash": "0xdaf74e4e92e21c0ae12113fdbb53138f3b654d824b4ced2a056a8c78721424b0",
        "logIndex": "0x90",
        "removed": False,
    }

    log = normalize_log(
        raw_log=raw_log,
        chain_id=56,
        rpc_url="https://bsc-mainnet.public.blastapi.io",
        from_block=107270817,
        to_block=107270817,
    )

    assert log.chain_id == 56
    assert log.address == "0x16b9a82891338f9ba80e2d6970fdda79d1eb0dae"
    assert log.block_number == 107270817
    assert log.transaction_index == 41
    assert log.log_index == 144
    assert log.topics[0] == raw_log["topics"][0]
    assert log.raw_log == raw_log
