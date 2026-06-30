WITH fixture_symbols AS (
    SELECT *
    FROM (
        VALUES
            ('BTCUSDT'::text, 60000.0000000000::numeric),
            ('ETHUSDT'::text, 3000.0000000000::numeric)
    ) AS symbols(symbol, base_price)
),
fixture_minutes AS (
    SELECT generate_series(
        '2026-01-01T00:00:00Z'::timestamptz,
        '2026-01-02T23:59:00Z'::timestamptz,
        '1 minute'::interval
    ) AS ts
),
fixture_candles AS (
    SELECT
        fixture_symbols.symbol,
        fixture_minutes.ts,
        row_number() OVER (
            PARTITION BY fixture_symbols.symbol
            ORDER BY fixture_minutes.ts
        ) - 1 AS minute_index,
        fixture_symbols.base_price
    FROM fixture_symbols
    CROSS JOIN fixture_minutes
)
INSERT INTO time_series.candles_1m (
    symbol,
    ts,
    open_price,
    high_price,
    low_price,
    close_price,
    volume,
    trade_count,
    source
)
SELECT
    symbol,
    ts,
    base_price + (minute_index * 0.1000000000) AS open_price,
    base_price + (minute_index * 0.1000000000) + 5.0000000000 AS high_price,
    base_price + (minute_index * 0.1000000000) - 5.0000000000 AS low_price,
    base_price + (minute_index * 0.1000000000)
        + CASE WHEN minute_index % 2 = 0 THEN 1.0000000000 ELSE -1.0000000000 END AS close_price,
    10.0000000000 + (minute_index % 100) AS volume,
    100 + (minute_index % 50) AS trade_count,
    'fixture' AS source
FROM fixture_candles
ON CONFLICT (symbol, ts) DO UPDATE
SET open_price = EXCLUDED.open_price,
    high_price = EXCLUDED.high_price,
    low_price = EXCLUDED.low_price,
    close_price = EXCLUDED.close_price,
    volume = EXCLUDED.volume,
    trade_count = EXCLUDED.trade_count,
    source = EXCLUDED.source;
