# BNB Block Timestamps

This experiment enriches BNB Chain swap projections with block timestamps so
on-chain events can be aligned to market candles.

## Study Question

How should Quantgres turn block-number ordered DeFi logs into event-time data
that can be joined with Binance candles and point-in-time feature snapshots?

## Source Data

The smoke uses real upstream data:

- PancakeSwap V2 Swap logs from BNB JSON-RPC
- block metadata from `eth_getBlockByNumber`

Block metadata is stored in:

- `onchain.blocks`

Swap events are enriched in:

- `defi.swap_events.block_timestamp`

## Time Semantics

`eth_getBlockByNumber` returns the block `timestamp` as a hex quantity Unix
timestamp. Quantgres converts it to `timestamptz` and stores it once per block.

The swap projection keeps block number and log index for deterministic chain
ordering, while `block_timestamp` enables event-time joins against candles,
features, and analytics panels.

## Verification

Run:

```powershell
uv run quantgres bnb-block-timestamp-smoke
```

Expected behavior:

- Fetches and projects the real PancakeSwap sample swap logs.
- Fetches the corresponding BNB block metadata.
- Stores the block timestamp in `onchain.blocks`.
- Updates `defi.swap_events.block_timestamp`.
- Prints sample enriched swap events.
