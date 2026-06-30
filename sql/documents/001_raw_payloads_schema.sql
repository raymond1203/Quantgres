CREATE SCHEMA IF NOT EXISTS documents;

CREATE TABLE IF NOT EXISTS documents.raw_payloads (
    source text NOT NULL,
    external_id text NOT NULL,
    observed_at timestamptz NOT NULL,
    symbol text,
    chain_id integer,
    payload jsonb NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source, external_id),
    CHECK (source <> ''),
    CHECK (external_id <> ''),
    CHECK (symbol IS NULL OR symbol <> ''),
    CHECK (chain_id IS NULL OR chain_id > 0),
    CHECK (jsonb_typeof(payload) = 'object')
);

CREATE INDEX IF NOT EXISTS raw_payloads_source_observed_at_idx
    ON documents.raw_payloads (source, observed_at DESC);

CREATE INDEX IF NOT EXISTS raw_payloads_symbol_observed_at_idx
    ON documents.raw_payloads (symbol, observed_at DESC)
    WHERE symbol IS NOT NULL;

CREATE INDEX IF NOT EXISTS raw_payloads_chain_observed_at_idx
    ON documents.raw_payloads (chain_id, observed_at DESC)
    WHERE chain_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS raw_payloads_payload_gin_idx
    ON documents.raw_payloads
    USING gin (payload);

CREATE INDEX IF NOT EXISTS raw_payloads_payload_address_idx
    ON documents.raw_payloads ((payload ->> 'address'))
    WHERE payload ? 'address';
