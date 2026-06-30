CREATE SCHEMA IF NOT EXISTS event_store;

CREATE TABLE IF NOT EXISTS event_store.agent_events (
    event_id text PRIMARY KEY,
    event_type text NOT NULL,
    subject_type text NOT NULL,
    subject_id text NOT NULL,
    occurred_at timestamptz NOT NULL,
    source text NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (event_id <> ''),
    CHECK (event_type <> ''),
    CHECK (subject_type <> ''),
    CHECK (subject_id <> ''),
    CHECK (source <> ''),
    CHECK (jsonb_typeof(payload) = 'object')
);

CREATE INDEX IF NOT EXISTS agent_events_type_occurred_idx
    ON event_store.agent_events (event_type, occurred_at DESC);

CREATE INDEX IF NOT EXISTS agent_events_subject_idx
    ON event_store.agent_events (subject_type, subject_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS agent_events_payload_gin_idx
    ON event_store.agent_events
    USING gin (payload);
