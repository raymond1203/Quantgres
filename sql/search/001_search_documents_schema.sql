CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE SCHEMA IF NOT EXISTS search;

CREATE TABLE IF NOT EXISTS search.search_documents (
    source text NOT NULL,
    external_id text NOT NULL,
    observed_at timestamptz NOT NULL,
    title text NOT NULL,
    document_text text NOT NULL,
    fuzzy_key text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    search_vector tsvector GENERATED ALWAYS AS (
        to_tsvector('english', document_text)
    ) STORED,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source, external_id),
    CHECK (source <> ''),
    CHECK (external_id <> ''),
    CHECK (title <> ''),
    CHECK (document_text <> ''),
    CHECK (fuzzy_key <> ''),
    CHECK (jsonb_typeof(metadata) = 'object')
);

CREATE INDEX IF NOT EXISTS search_documents_observed_at_idx
    ON search.search_documents (observed_at DESC);

CREATE INDEX IF NOT EXISTS search_documents_vector_idx
    ON search.search_documents
    USING gin (search_vector);

CREATE INDEX IF NOT EXISTS search_documents_fuzzy_key_trgm_idx
    ON search.search_documents
    USING gin (fuzzy_key gin_trgm_ops);
