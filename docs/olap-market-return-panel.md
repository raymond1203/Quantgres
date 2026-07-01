# OLAP Market Return Panel

This experiment uses PostgreSQL as an OLAP-style analytics backend for a
market return panel enriched with on-chain aggregate metrics.

## Study Question

How far can PostgreSQL window functions and materialized views go for
quant-style return panel analysis before introducing a separate OLAP engine?

## Source Data

The smoke refreshes real upstream data first:

- Binance public 1m klines in `time_series.candles_1m`
- BNB Chain PancakeSwap V2 Swap corpus in `defi.swap_events`

It then refreshes:

- `analytics.market_return_panel`

## Analytics

The panel uses PostgreSQL window functions:

- `lag(close_price) over (partition by symbol order by ts)` for previous close
- `return_bps = (close / previous_close - 1) * 10000`
- 5-row rolling average return with `ROWS BETWEEN 4 PRECEDING AND CURRENT ROW`

On-chain swap metrics are attached by event-time minute bucket:

- swap count
- block count
- raw amount in/out sums

The panel keeps all candle rows with a `LEFT JOIN`; minutes without observed BNB
Swap events receive zero swap metrics. The smoke fetches Binance klines around
the enriched BNB corpus timestamps so at least one panel row demonstrates a real
event-time match.

## Verification

Run:

```powershell
uv run quantgres olap-return-panel-smoke
```

Expected behavior:

- Refreshes real BNB swap corpus data.
- Fetches real Binance klines around the BNB corpus event-time window.
- Refreshes `analytics.market_return_panel`.
- Prints latest panel rows with return bps and rolling return.
- Prints sample rows where `swap_count > 0`.
- Prints a plan summary for latest-row lookup.

This experiment does not require wallet keys, exchange keys, paid analytics
services, or live trading.
