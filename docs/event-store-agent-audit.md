# Event Store Agent Audit Log

This experiment uses PostgreSQL as an append-oriented audit log for research
and agent workflow events.

## Study Question

How should Quantgres preserve enough event history to replay or explain an
analysis or agent context decision?

## Source Data

The smoke uses real upstream workflow outputs:

- latest rows from `analytics.market_return_panel`
- top retrieval results from `memory.agent_memory_chunks`

It then appends events to:

- `event_store.agent_events`

## Event Types

The first vertical slice records:

- `olap_return_panel_observed`
- `vector_memory_retrieval_observed`

Each event stores:

- deterministic `event_id`
- `event_type`
- `subject_type`
- `subject_id`
- `occurred_at`
- `source`
- JSONB `payload`

## Idempotency

The event id is a SHA-256 hash of the event type, subject, occurred time, and a
canonical JSON payload. Re-running the same smoke can skip existing events with
`ON CONFLICT DO NOTHING` instead of mutating prior audit records.

This first loop keeps append-only behavior in the application path. Trigger
based hard prevention of updates/deletes is left for a later operations-focused
loop.

The smoke uses `SET LOCAL enable_seqscan = off` for the payload containment
`EXPLAIN` step so the tiny local event table still proves the JSONB GIN lookup
path. Normal planner behavior can prefer a sequential scan when there are only a
few audit rows.

## Verification

Run:

```powershell
uv run quantgres event-store-smoke
```

Expected behavior:

- Refreshes the real OLAP and VectorDB source workflows.
- Appends or skips deterministic audit events.
- Queries events by subject.
- Runs a JSONB payload containment query.
- Prints plan summaries for both lookup paths.

This experiment does not require wallet keys, exchange keys, live trading, or
external event infrastructure.
