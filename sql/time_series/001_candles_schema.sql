CREATE SCHEMA IF NOT EXISTS time_series;

CREATE TABLE IF NOT EXISTS time_series.candles_1m (
    symbol text NOT NULL,
    ts timestamptz NOT NULL,
    close_ts timestamptz NOT NULL,
    open_price numeric(28, 10) NOT NULL,
    high_price numeric(28, 10) NOT NULL,
    low_price numeric(28, 10) NOT NULL,
    close_price numeric(28, 10) NOT NULL,
    volume numeric(28, 10) NOT NULL,
    quote_volume numeric(28, 10) NOT NULL DEFAULT 0,
    trade_count integer NOT NULL,
    taker_buy_base_volume numeric(28, 10) NOT NULL DEFAULT 0,
    taker_buy_quote_volume numeric(28, 10) NOT NULL DEFAULT 0,
    source text NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, ts),
    CHECK (symbol <> ''),
    CONSTRAINT candles_1m_close_ts_after_ts_check CHECK (close_ts > ts),
    CHECK (high_price >= open_price),
    CHECK (high_price >= close_price),
    CHECK (low_price <= open_price),
    CHECK (low_price <= close_price),
    CHECK (volume >= 0),
    CONSTRAINT candles_1m_quote_volume_nonnegative_check CHECK (quote_volume >= 0),
    CHECK (trade_count >= 0),
    CONSTRAINT candles_1m_taker_buy_base_volume_nonnegative_check
        CHECK (taker_buy_base_volume >= 0),
    CONSTRAINT candles_1m_taker_buy_quote_volume_nonnegative_check
        CHECK (taker_buy_quote_volume >= 0),
    CHECK (source <> '')
);

ALTER TABLE time_series.candles_1m
    ADD COLUMN IF NOT EXISTS close_ts timestamptz;

UPDATE time_series.candles_1m
SET close_ts = ts + interval '1 minute' - interval '1 millisecond'
WHERE close_ts IS NULL;

ALTER TABLE time_series.candles_1m
    ALTER COLUMN close_ts SET NOT NULL;

ALTER TABLE time_series.candles_1m
    ADD COLUMN IF NOT EXISTS quote_volume numeric(28, 10) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS taker_buy_base_volume numeric(28, 10) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS taker_buy_quote_volume numeric(28, 10) NOT NULL DEFAULT 0;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'candles_1m_close_ts_after_ts_check'
          AND conrelid = 'time_series.candles_1m'::regclass
    ) THEN
        ALTER TABLE time_series.candles_1m
            ADD CONSTRAINT candles_1m_close_ts_after_ts_check
            CHECK (close_ts > ts);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'candles_1m_quote_volume_nonnegative_check'
          AND conrelid = 'time_series.candles_1m'::regclass
    ) THEN
        ALTER TABLE time_series.candles_1m
            ADD CONSTRAINT candles_1m_quote_volume_nonnegative_check
            CHECK (quote_volume >= 0);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'candles_1m_taker_buy_base_volume_nonnegative_check'
          AND conrelid = 'time_series.candles_1m'::regclass
    ) THEN
        ALTER TABLE time_series.candles_1m
            ADD CONSTRAINT candles_1m_taker_buy_base_volume_nonnegative_check
            CHECK (taker_buy_base_volume >= 0);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'candles_1m_taker_buy_quote_volume_nonnegative_check'
          AND conrelid = 'time_series.candles_1m'::regclass
    ) THEN
        ALTER TABLE time_series.candles_1m
            ADD CONSTRAINT candles_1m_taker_buy_quote_volume_nonnegative_check
            CHECK (taker_buy_quote_volume >= 0);
    END IF;
END $$;

DROP INDEX IF EXISTS time_series.candles_1m_symbol_ts_covering_idx;

CREATE INDEX candles_1m_symbol_ts_covering_idx
    ON time_series.candles_1m (symbol, ts DESC)
    INCLUDE (open_price, high_price, low_price, close_price, volume, quote_volume);

CREATE INDEX IF NOT EXISTS candles_1m_ts_brin_idx
    ON time_series.candles_1m
    USING brin (ts);
