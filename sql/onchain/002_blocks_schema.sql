CREATE SCHEMA IF NOT EXISTS onchain;

CREATE TABLE IF NOT EXISTS onchain.blocks (
    chain_id integer NOT NULL,
    block_number bigint NOT NULL,
    block_hash text NOT NULL,
    parent_hash text NOT NULL,
    block_timestamp timestamptz NOT NULL,
    raw_block jsonb NOT NULL,
    fetched_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (chain_id, block_number),
    UNIQUE (chain_id, block_hash),
    CHECK (chain_id > 0),
    CHECK (block_number >= 0),
    CHECK (block_hash <> ''),
    CHECK (parent_hash <> ''),
    CHECK (jsonb_typeof(raw_block) = 'object')
);

CREATE INDEX IF NOT EXISTS blocks_timestamp_idx
    ON onchain.blocks (chain_id, block_timestamp DESC);
