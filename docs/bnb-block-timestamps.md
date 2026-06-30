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

## Backfill Policy

For larger ranges, the smoke treats `onchain.blocks` as a local metadata cache:

- collect distinct swap block numbers from `defi.swap_events`
- reuse block numbers already stored in `onchain.blocks`
- fetch only missing blocks with `eth_getBlockByNumber`
- retry each missing block with a bounded retry policy
- fail loudly with block number, attempt count, and error type when retries are
  exhausted

The default retry policy is intentionally small: three attempts with short
linear backoff. It protects against transient public RPC failures without hiding
provider instability or turning a smoke run into an unbounded crawler.

CLI options:

- `--block-fetch-attempts`: maximum attempts per missing block, default `3`
- `--block-fetch-retry-sleep`: base backoff seconds, default `0.25`

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
- Skips block metadata that is already cached in `onchain.blocks`.
- Stores the block timestamp in `onchain.blocks`.
- Updates `defi.swap_events.block_timestamp`.
- Prints requested, cached, missing, fetched, stored, and enriched counts plus
  sample enriched swap events.
