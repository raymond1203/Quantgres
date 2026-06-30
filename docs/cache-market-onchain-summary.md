# CacheDB Market / On-Chain Summary

This experiment uses a PostgreSQL materialized view as a cache layer for
repeated market and on-chain summary lookups.

## Study Question

When is a PostgreSQL materialized view useful as a cache for expensive
quant/agent summary queries?

## Source Data

The smoke refreshes real upstream data first:

- Binance public klines in `time_series.candles_1m`
- BNB Chain PancakeSwap V2 Swap projection in `defi.swap_events`

It then refreshes:

- `cache.market_onchain_summary`

## Cached Rows

The first two summary keys are:

- `market:BTCUSDT`
- `onchain:pancakeswap_v2:bnb-usdt`

Each row stores:

- `summary_key`
- `summary_kind`
- `latest_observed_at`
- `metrics` JSONB
- `refreshed_at`

## Tradeoff

A materialized view separates read latency from refresh cost. The cached lookup
can use a small indexed relation, but it can be stale until the next refresh.
This first loop uses plain `REFRESH MATERIALIZED VIEW`; concurrent refresh,
TTL tables, and unlogged cache tables are left for later CacheDB loops.

The smoke uses `SET LOCAL enable_seqscan = off` only for the cache lookup
`EXPLAIN` step so a tiny local materialized view still proves the indexed lookup
path. Normal planner behavior can prefer a sequential scan when the cache has
only a few rows.

## Verification

Run:

```powershell
uv run quantgres cache-summary-smoke
```

Expected behavior:

- Refreshes real Binance and BNB data.
- Refreshes `cache.market_onchain_summary`.
- Prints the selected summary row.
- Prints base aggregate and cache lookup plan summaries.

This experiment does not require wallet keys, exchange keys, paid cache
services, or live trading.
