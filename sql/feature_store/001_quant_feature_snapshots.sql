CREATE SCHEMA IF NOT EXISTS feature_store;

CREATE TABLE IF NOT EXISTS feature_store.quant_feature_snapshots (
    feature_set text NOT NULL,
    symbol text NOT NULL,
    event_ts timestamptz NOT NULL,
    feature_ts timestamptz NOT NULL,
    close_price numeric(28, 10) NOT NULL,
    previous_close_price numeric(28, 10),
    return_bps numeric(28, 10),
    rolling_5_return_bps numeric(28, 10),
    volume numeric(28, 10) NOT NULL,
    quote_volume numeric(28, 10) NOT NULL,
    swap_count integer NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    computed_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (feature_set, symbol, event_ts),
    CHECK (feature_set <> ''),
    CHECK (symbol <> ''),
    CHECK (feature_ts >= event_ts),
    CHECK (close_price > 0),
    CHECK (volume >= 0),
    CHECK (quote_volume >= 0),
    CHECK (swap_count >= 0),
    CHECK (jsonb_typeof(metadata) = 'object')
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'quant_feature_snapshots_pkey'
          AND conrelid = 'feature_store.quant_feature_snapshots'::regclass
          AND pg_get_constraintdef(oid) <> 'PRIMARY KEY (feature_set, symbol, event_ts)'
    ) THEN
        ALTER TABLE feature_store.quant_feature_snapshots
            DROP CONSTRAINT quant_feature_snapshots_pkey;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'quant_feature_snapshots_pkey'
          AND conrelid = 'feature_store.quant_feature_snapshots'::regclass
    ) THEN
        ALTER TABLE feature_store.quant_feature_snapshots
            ADD CONSTRAINT quant_feature_snapshots_pkey
            PRIMARY KEY (feature_set, symbol, event_ts);
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_class AS index_class
        JOIN pg_namespace AS namespace
          ON namespace.oid = index_class.relnamespace
        JOIN pg_index AS index_meta
          ON index_meta.indexrelid = index_class.oid
        WHERE namespace.nspname = 'feature_store'
          AND index_class.relname = 'quant_feature_snapshots_symbol_asof_idx'
          AND NOT index_meta.indisunique
    ) THEN
        DROP INDEX feature_store.quant_feature_snapshots_symbol_asof_idx;
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS quant_feature_snapshots_symbol_asof_idx
    ON feature_store.quant_feature_snapshots (feature_set, symbol, feature_ts DESC)
    INCLUDE (
        event_ts,
        close_price,
        return_bps,
        rolling_5_return_bps,
        volume,
        quote_volume,
        swap_count
    );

CREATE INDEX IF NOT EXISTS quant_feature_snapshots_metadata_gin_idx
    ON feature_store.quant_feature_snapshots
    USING gin (metadata);
