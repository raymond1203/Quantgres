CREATE SCHEMA IF NOT EXISTS time_series;

CREATE TABLE IF NOT EXISTS time_series.candles_1m (
    symbol text NOT NULL,
    ts timestamptz NOT NULL,
    open_price numeric(28, 10) NOT NULL,
    high_price numeric(28, 10) NOT NULL,
    low_price numeric(28, 10) NOT NULL,
    close_price numeric(28, 10) NOT NULL,
    volume numeric(28, 10) NOT NULL,
    trade_count integer NOT NULL,
    source text NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, ts),
    CHECK (symbol <> ''),
    CHECK (high_price >= open_price),
    CHECK (high_price >= close_price),
    CHECK (low_price <= open_price),
    CHECK (low_price <= close_price),
    CHECK (volume >= 0),
    CHECK (trade_count >= 0),
    CHECK (source <> '')
);

CREATE INDEX IF NOT EXISTS candles_1m_symbol_ts_covering_idx
    ON time_series.candles_1m (symbol, ts DESC)
    INCLUDE (open_price, high_price, low_price, close_price, volume);

CREATE INDEX IF NOT EXISTS candles_1m_ts_brin_idx
    ON time_series.candles_1m
    USING brin (ts);
