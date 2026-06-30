# Feature Store Point-in-Time Features

This experiment uses PostgreSQL as a small Feature Store for quant research and
paper-agent inputs.

## Study Question

How should Quantgres store typed feature snapshots so a strategy can ask,
"what did we know as of this timestamp?" without leaking future candle data?

## Source Data

The smoke uses real upstream workflow outputs:

- public Binance klines stored in `time_series.candles_1m`
- OLAP features refreshed in `analytics.market_return_panel`

It then upserts feature rows into:

- `feature_store.quant_feature_snapshots`

## Time Semantics

Each row separates:

- `event_ts`: source candle open time
- `feature_ts`: candle close time, used for point-in-time availability
- `computed_at`: local time when PostgreSQL wrote or refreshed the snapshot

The as-of lookup uses:

```sql
WHERE feature_set = $1
  AND symbol = $2
  AND feature_ts <= $3
ORDER BY feature_ts DESC
LIMIT 1
```

This avoids using a candle's close-derived features before the candle is
available.

## Feature Set

The first feature set is `market_return_v1` and includes:

- close price
- previous close price
- one-minute return in basis points
- rolling five-candle return in basis points
- base and quote volume
- PancakeSwap sample swap count from the current DeFi projection

Metadata stays in JSONB, but model-facing values are typed columns so query
plans, constraints, and downstream casts remain visible.

## Verification

Run:

```powershell
uv run quantgres feature-store-smoke
```

Expected behavior:

- Refreshes the real OLAP workflow.
- Upserts typed feature snapshots.
- Reads the latest feature row as of a timestamp.
- Prints the as-of query plan and index names.

The `EXPLAIN` step uses `SET LOCAL enable_seqscan = off` so a tiny local table
still proves the composite index lookup path. Normal lookup behavior can still
use PostgreSQL's default planner choice.
