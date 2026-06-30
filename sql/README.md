# SQL

This directory stores plain SQL files for PostgreSQL experiments.

Use raw SQL first so schema design, indexes, query plans, and PostgreSQL-specific
operators remain easy to inspect.

Initial conventions:

- `000_extensions.sql`: local extension setup
- `rdb/`: relational ledger experiments
- `time_series/`: tick, candle, and partitioning experiments
- `document/`: JSONB document store experiments
- `vector/`: pgvector experiments
- `search/`: full-text and trigram search experiments
- `queue/`: `SKIP LOCKED` and notification experiments
- `cache/`: materialized view, summary table, and TTL cache experiments
- `olap/`: analytics and rollup experiments
- `event_store/`: append-only audit log experiments
- `feature_store/`: point-in-time feature experiments
