CREATE SCHEMA IF NOT EXISTS cache;

CREATE MATERIALIZED VIEW IF NOT EXISTS cache.market_onchain_summary AS
WITH market_summary AS (
    SELECT
        concat('market:', symbol) AS summary_key,
        'market' AS summary_kind,
        max(ts) AS latest_observed_at,
        jsonb_build_object(
            'symbol', symbol,
            'source', source,
            'candle_count', count(*),
            'first_ts', min(ts),
            'last_ts', max(ts),
            'latest_close', (array_agg(close_price ORDER BY ts DESC))[1]::text,
            'vwap', (sum(close_price * volume) / nullif(sum(volume), 0))::text,
            'base_volume', sum(volume)::text,
            'quote_volume', sum(quote_volume)::text
        ) AS metrics
    FROM time_series.candles_1m
    WHERE source = 'binance_spot_klines'
    GROUP BY symbol, source
),
onchain_summary AS (
    SELECT
        concat('onchain:', dex, ':bnb-usdt') AS summary_key,
        'onchain' AS summary_kind,
        max(projected_at) AS latest_observed_at,
        jsonb_build_object(
            'chain_id', chain_id,
            'dex', dex,
            'pair_address', pair_address,
            'swap_count', count(*),
            'block_count', count(DISTINCT block_number),
            'first_block', min(block_number),
            'last_block', max(block_number),
            'amount0_in_sum', sum(amount0_in)::text,
            'amount1_in_sum', sum(amount1_in)::text,
            'amount0_out_sum', sum(amount0_out)::text,
            'amount1_out_sum', sum(amount1_out)::text
        ) AS metrics
    FROM defi.swap_events
    WHERE chain_id = 56
      AND dex = 'pancakeswap_v2'
      AND pair_address = '0x16b9a82891338f9ba80e2d6970fdda79d1eb0dae'
    GROUP BY chain_id, dex, pair_address
)
SELECT
    summary_key,
    summary_kind,
    latest_observed_at,
    metrics,
    now() AS refreshed_at
FROM market_summary
UNION ALL
SELECT
    summary_key,
    summary_kind,
    latest_observed_at,
    metrics,
    now() AS refreshed_at
FROM onchain_summary
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS market_onchain_summary_key_idx
    ON cache.market_onchain_summary (summary_key);

CREATE INDEX IF NOT EXISTS market_onchain_summary_kind_observed_idx
    ON cache.market_onchain_summary (summary_kind, latest_observed_at DESC);
