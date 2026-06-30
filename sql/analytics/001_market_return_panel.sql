CREATE SCHEMA IF NOT EXISTS analytics;

CREATE MATERIALIZED VIEW IF NOT EXISTS analytics.market_return_panel AS
WITH candle_returns AS (
    SELECT
        symbol,
        ts,
        close_price,
        volume,
        quote_volume,
        lag(close_price) OVER (
            PARTITION BY symbol
            ORDER BY ts
        ) AS previous_close_price
    FROM time_series.candles_1m
    WHERE source = 'binance_spot_klines'
),
return_panel AS (
    SELECT
        symbol,
        ts,
        close_price,
        previous_close_price,
        CASE
            WHEN previous_close_price IS NULL OR previous_close_price = 0 THEN NULL
            ELSE ((close_price / previous_close_price) - 1) * 10000
        END AS return_bps,
        volume,
        quote_volume
    FROM candle_returns
),
rolling_panel AS (
    SELECT
        symbol,
        ts,
        close_price,
        previous_close_price,
        return_bps,
        avg(return_bps) OVER (
            PARTITION BY symbol
            ORDER BY ts
            ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
        ) AS rolling_5_return_bps,
        volume,
        quote_volume
    FROM return_panel
),
swap_summary AS (
    SELECT
        count(*)::integer AS swap_count,
        coalesce(sum(amount0_in), 0)::numeric(78,0) AS amount0_in_sum,
        coalesce(sum(amount1_in), 0)::numeric(78,0) AS amount1_in_sum,
        coalesce(sum(amount0_out), 0)::numeric(78,0) AS amount0_out_sum,
        coalesce(sum(amount1_out), 0)::numeric(78,0) AS amount1_out_sum
    FROM defi.swap_events
    WHERE chain_id = 56
      AND dex = 'pancakeswap_v2'
      AND pair_address = '0x16b9a82891338f9ba80e2d6970fdda79d1eb0dae'
)
SELECT
    panel.symbol,
    panel.ts,
    panel.close_price,
    panel.previous_close_price,
    panel.return_bps,
    panel.rolling_5_return_bps,
    panel.volume,
    panel.quote_volume,
    swaps.swap_count,
    swaps.amount0_in_sum,
    swaps.amount1_in_sum,
    swaps.amount0_out_sum,
    swaps.amount1_out_sum,
    now() AS refreshed_at
FROM rolling_panel AS panel
CROSS JOIN swap_summary AS swaps
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS market_return_panel_symbol_ts_idx
    ON analytics.market_return_panel (symbol, ts DESC);
