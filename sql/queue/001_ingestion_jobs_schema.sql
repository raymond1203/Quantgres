CREATE SCHEMA IF NOT EXISTS queue;

CREATE TABLE IF NOT EXISTS queue.ingestion_jobs (
    job_id bigserial PRIMARY KEY,
    job_kind text NOT NULL,
    idempotency_key text NOT NULL UNIQUE,
    payload jsonb NOT NULL,
    status text NOT NULL DEFAULT 'available',
    priority integer NOT NULL DEFAULT 0,
    attempts integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 3,
    available_at timestamptz NOT NULL DEFAULT now(),
    locked_at timestamptz,
    locked_by text,
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    CHECK (job_kind <> ''),
    CHECK (idempotency_key <> ''),
    CHECK (jsonb_typeof(payload) = 'object'),
    CHECK (status IN ('available', 'running', 'completed', 'failed', 'dead_letter')),
    CHECK (attempts >= 0),
    CHECK (max_attempts > 0),
    CHECK (locked_by IS NULL OR locked_by <> ''),
    CHECK (completed_at IS NULL OR status = 'completed')
);

CREATE INDEX IF NOT EXISTS ingestion_jobs_claim_idx
    ON queue.ingestion_jobs (priority DESC, available_at, job_id)
    WHERE status IN ('available', 'failed');

CREATE INDEX IF NOT EXISTS ingestion_jobs_status_updated_at_idx
    ON queue.ingestion_jobs (status, updated_at DESC);

CREATE INDEX IF NOT EXISTS ingestion_jobs_running_locked_at_idx
    ON queue.ingestion_jobs (locked_at, job_id)
    WHERE status = 'running';
