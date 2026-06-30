# OLAP Market Return Panel

This experiment uses PostgreSQL as an OLAP-style analytics backend for a
market return panel enriched with on-chain aggregate metrics.

## Study Question

How far can PostgreSQL window functions and materialized views go for
quant-style return panel analysis before introducing a separate OLAP engine?

## Source Data

The smoke refreshes real upstream data first:

- Binance public 1m klines in `time_series.candles_1m`
- BNB Chain PancakeSwap V2 Swap projection in `defi.swap_events`

It then refreshes:

- `analytics.market_return_panel`

## Analytics

The panel uses PostgreSQL window functions:

- `lag(close_price) over (partition by symbol order by ts)` for previous close
- `return_bps = (close / previous_close - 1) * 10000`
- 5-row rolling average return with `ROWS BETWEEN 4 PRECEDING AND CURRENT ROW`

On-chain swap metrics are attached as current sample-level aggregates:

- swap count
- block count
- raw amount in/out sums

Block timestamp enrichment is intentionally left for a later on-chain
enrichment loop, so this first OLAP panel does not claim event-time alignment.

## Verification

Run:

```powershell
uv run quantgres olap-return-panel-smoke
```

Expected behavior:

- Refreshes real Binance and BNB data.
- Refreshes `analytics.market_return_panel`.
- Prints latest panel rows with return bps and rolling return.
- Prints a plan summary for latest-row lookup.

This experiment does not require wallet keys, exchange keys, paid analytics
services, or live trading.
