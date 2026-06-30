from datetime import UTC, datetime

from quantgres.onchain.bnb_rpc import normalize_block


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
