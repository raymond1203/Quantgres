# Quantgres Roadmap

Quantgres starts as a DB study project. DeFi, market-data, quant, and
paper-agent workflows provide the domain context for realistic PostgreSQL
experiments.

Synthetic fixtures are allowed for deterministic schema and constraint checks,
but each core track should be hardened with real public data before moving on.
The primary data sources are Binance public market-data endpoints and BNB Chain
JSON-RPC logs. Dune is optional and should only be used later for external
metric comparison, not as the primary ingestion path.

## Phase 0: Foundation

- uv, ruff, ty, pytest
- psycopg 3 and raw SQL first
- Docker Compose PostgreSQL 18 with pgvector 0.8.3
- SQL directory conventions
- benchmark/reporting conventions

## Phase 1: Core PostgreSQL Roles

1. RDB / Trading Ledger
2. Time-Series DB / Quant Market Data
3. Document DB / JSONB
4. Vector DB / pgvector

RDB and Time-Series are connected by a real-data vertical slice: Binance public
klines -> `time_series.candles_1m` -> paper-only RDB order/fill/cash/position
trace.

The on-chain foundation starts with BNB Chain RPC raw logs:
`eth_getLogs` -> `onchain.raw_logs` JSONB -> later normalized DeFi event
projections.

The Document DB / JSONB track uses those real Binance and BNB payloads:
`time_series.candles_1m` plus `onchain.raw_logs` -> `documents.raw_payloads`
JSONB documents -> containment and expression-index queries.

The SearchDB track projects those JSONB documents into searchable text:
`documents.raw_payloads` -> `search.search_documents` -> full-text GIN search
and trigram fuzzy lookup.

## Phase 2: Backend System Patterns

5. Search DB / Full-Text, Trigram, Hybrid Search
6. Queue DB / Jobs, Workers, Notifications
7. Cache DB / Materialized Views, Summary Tables, TTL Cache

## Phase 3: Research and ML Data Systems

8. OLAP / Analytics DB
9. Event Store / Audit Log
10. Feature Store

## Standard Experiment Shape

Each track should produce small, reproducible experiments:

- schema
- deterministic sample data for schema smoke checks
- real public API or RPC data for portfolio evidence when available
- benchmark query
- index or schema variant
- `EXPLAIN ANALYZE`
- benchmark summary
- interpretation
