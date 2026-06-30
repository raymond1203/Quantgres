CREATE SCHEMA IF NOT EXISTS documents;

CREATE TABLE IF NOT EXISTS documents.jsonb_ops_benchmark_payloads (
    source text NOT NULL,
    external_id text NOT NULL,
    observed_at timestamptz NOT NULL,
    symbol text,
    chain_id integer,
    payload jsonb NOT NULL,
    benchmarked_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source, external_id),
    CHECK (source <> ''),
    CHECK (external_id <> ''),
    CHECK (symbol IS NULL OR symbol <> ''),
    CHECK (chain_id IS NULL OR chain_id > 0),
    CHECK (jsonb_typeof(payload) = 'object')
);

CREATE TABLE IF NOT EXISTS documents.jsonb_path_ops_benchmark_payloads (
    source text NOT NULL,
    external_id text NOT NULL,
    observed_at timestamptz NOT NULL,
    symbol text,
    chain_id integer,
    payload jsonb NOT NULL,
    benchmarked_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source, external_id),
    CHECK (source <> ''),
    CHECK (external_id <> ''),
    CHECK (symbol IS NULL OR symbol <> ''),
    CHECK (chain_id IS NULL OR chain_id > 0),
    CHECK (jsonb_typeof(payload) = 'object')
);

CREATE INDEX IF NOT EXISTS jsonb_ops_benchmark_source_observed_idx
    ON documents.jsonb_ops_benchmark_payloads (source, observed_at DESC);

CREATE INDEX IF NOT EXISTS jsonb_path_ops_benchmark_source_observed_idx
    ON documents.jsonb_path_ops_benchmark_payloads (source, observed_at DESC);

CREATE INDEX IF NOT EXISTS jsonb_ops_benchmark_payload_gin_idx
    ON documents.jsonb_ops_benchmark_payloads
    USING gin (payload);

CREATE INDEX IF NOT EXISTS jsonb_path_ops_benchmark_payload_gin_idx
    ON documents.jsonb_path_ops_benchmark_payloads
    USING gin (payload jsonb_path_ops);
