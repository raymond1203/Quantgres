CREATE SCHEMA IF NOT EXISTS feature_store;

CREATE TABLE IF NOT EXISTS feature_store.quant_feature_batches (
    batch_id text PRIMARY KEY,
    feature_set text NOT NULL,
    source text NOT NULL,
    source_row_count integer NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (batch_id <> ''),
    CHECK (feature_set <> ''),
    CHECK (source <> ''),
    CHECK (source_row_count >= 0),
    CHECK (jsonb_typeof(metadata) = 'object')
);

CREATE TABLE IF NOT EXISTS feature_store.quant_feature_batch_items (
    batch_id text NOT NULL REFERENCES feature_store.quant_feature_batches (batch_id),
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
    inserted_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (batch_id, symbol, event_ts),
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
        WHERE conname = 'quant_feature_batch_items_pkey'
          AND conrelid = 'feature_store.quant_feature_batch_items'::regclass
          AND pg_get_constraintdef(oid) <> 'PRIMARY KEY (batch_id, symbol, event_ts)'
    ) THEN
        ALTER TABLE feature_store.quant_feature_batch_items
            DROP CONSTRAINT quant_feature_batch_items_pkey;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'quant_feature_batch_items_pkey'
          AND conrelid = 'feature_store.quant_feature_batch_items'::regclass
    ) THEN
        ALTER TABLE feature_store.quant_feature_batch_items
            ADD CONSTRAINT quant_feature_batch_items_pkey
            PRIMARY KEY (batch_id, symbol, event_ts);
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
          AND index_class.relname = 'quant_feature_batch_items_symbol_asof_idx'
          AND NOT index_meta.indisunique
    ) THEN
        DROP INDEX feature_store.quant_feature_batch_items_symbol_asof_idx;
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS quant_feature_batch_items_symbol_asof_idx
    ON feature_store.quant_feature_batch_items (batch_id, symbol, feature_ts DESC);
