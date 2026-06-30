CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS memory;

CREATE TABLE IF NOT EXISTS memory.agent_memory_chunks (
    source text NOT NULL,
    external_id text NOT NULL,
    observed_at timestamptz NOT NULL,
    title text NOT NULL,
    chunk_text text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    embedding vector(16) NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source, external_id),
    CHECK (source <> ''),
    CHECK (external_id <> ''),
    CHECK (title <> ''),
    CHECK (chunk_text <> ''),
    CHECK (jsonb_typeof(metadata) = 'object')
);

CREATE INDEX IF NOT EXISTS agent_memory_chunks_observed_at_idx
    ON memory.agent_memory_chunks (observed_at DESC);

CREATE INDEX IF NOT EXISTS agent_memory_chunks_embedding_hnsw_idx
    ON memory.agent_memory_chunks
    USING hnsw (embedding vector_cosine_ops);
