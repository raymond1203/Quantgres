SELECT
    symbol,
    ts,
    open_price,
    high_price,
    low_price,
    close_price,
    volume
FROM time_series.candles_1m
WHERE symbol = 'BTCUSDT'
  AND ts >= '2026-01-01T00:00:00Z'::timestamptz
  AND ts < '2026-01-01T01:00:00Z'::timestamptz
ORDER BY ts;

SELECT
    symbol,
    count(*) AS candle_count,
    min(ts) AS first_ts,
    max(ts) AS last_ts,
    sum(close_price * volume) / sum(volume) AS vwap
FROM time_series.candles_1m
WHERE symbol = 'BTCUSDT'
  AND ts >= '2026-01-01T00:00:00Z'::timestamptz
  AND ts < '2026-01-01T01:00:00Z'::timestamptz
GROUP BY symbol;

EXPLAIN (ANALYZE, BUFFERS)
SELECT
    symbol,
    count(*) AS candle_count,
    sum(close_price * volume) / sum(volume) AS vwap
FROM time_series.candles_1m
WHERE symbol = 'BTCUSDT'
  AND ts >= '2026-01-01T00:00:00Z'::timestamptz
  AND ts < '2026-01-01T01:00:00Z'::timestamptz
GROUP BY symbol;
