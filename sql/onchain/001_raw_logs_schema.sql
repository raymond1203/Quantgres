CREATE SCHEMA IF NOT EXISTS onchain;

CREATE TABLE IF NOT EXISTS onchain.raw_logs (
    chain_id integer NOT NULL,
    rpc_url text NOT NULL,
    address text NOT NULL,
    block_number bigint NOT NULL,
    block_hash text NOT NULL,
    transaction_hash text NOT NULL,
    transaction_index integer NOT NULL,
    log_index integer NOT NULL,
    data text NOT NULL,
    topics jsonb NOT NULL,
    raw_log jsonb NOT NULL,
    from_block bigint NOT NULL,
    to_block bigint NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (chain_id, transaction_hash, log_index),
    CHECK (chain_id > 0),
    CHECK (rpc_url <> ''),
    CHECK (address <> ''),
    CHECK (block_number >= 0),
    CHECK (transaction_hash <> ''),
    CHECK (transaction_index >= 0),
    CHECK (log_index >= 0),
    CHECK (jsonb_typeof(topics) = 'array'),
    CHECK (jsonb_typeof(raw_log) = 'object'),
    CHECK (from_block >= 0),
    CHECK (to_block >= from_block)
);

CREATE INDEX IF NOT EXISTS raw_logs_address_block_idx
    ON onchain.raw_logs (chain_id, address, block_number DESC);

CREATE INDEX IF NOT EXISTS raw_logs_topic0_idx
    ON onchain.raw_logs (chain_id, (topics ->> 0), block_number DESC);
