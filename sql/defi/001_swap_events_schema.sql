CREATE SCHEMA IF NOT EXISTS defi;

CREATE TABLE IF NOT EXISTS defi.swap_events (
    chain_id integer NOT NULL,
    dex text NOT NULL,
    pair_address text NOT NULL,
    block_number bigint NOT NULL,
    block_hash text NOT NULL,
    transaction_hash text NOT NULL,
    transaction_index integer NOT NULL,
    log_index integer NOT NULL,
    sender text NOT NULL,
    recipient text NOT NULL,
    amount0_in numeric(78,0) NOT NULL,
    amount1_in numeric(78,0) NOT NULL,
    amount0_out numeric(78,0) NOT NULL,
    amount1_out numeric(78,0) NOT NULL,
    raw_log jsonb NOT NULL,
    projected_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (chain_id, transaction_hash, log_index),
    CHECK (chain_id > 0),
    CHECK (dex <> ''),
    CHECK (pair_address ~ '^0x[0-9a-f]{40}$'),
    CHECK (block_number >= 0),
    CHECK (block_hash <> ''),
    CHECK (transaction_hash <> ''),
    CHECK (transaction_index >= 0),
    CHECK (log_index >= 0),
    CHECK (sender ~ '^0x[0-9a-f]{40}$'),
    CHECK (recipient ~ '^0x[0-9a-f]{40}$'),
    CHECK (amount0_in >= 0),
    CHECK (amount1_in >= 0),
    CHECK (amount0_out >= 0),
    CHECK (amount1_out >= 0),
    CHECK (jsonb_typeof(raw_log) = 'object')
);

CREATE INDEX IF NOT EXISTS swap_events_pair_block_idx
    ON defi.swap_events (chain_id, dex, pair_address, block_number DESC, log_index DESC);

CREATE INDEX IF NOT EXISTS swap_events_transaction_idx
    ON defi.swap_events (chain_id, transaction_hash);
