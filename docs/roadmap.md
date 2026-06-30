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

The first normalized DeFi projection decodes PancakeSwap V2 Swap logs:
`onchain.raw_logs` -> `defi.swap_events` typed sender, recipient, and amount
columns.

The first BNB event-time enrichment stores block timestamps:
`eth_getBlockByNumber` -> `onchain.blocks` -> `defi.swap_events.block_timestamp`
for market/on-chain time alignment.

The Document DB / JSONB track uses those real Binance and BNB payloads:
`time_series.candles_1m` plus `onchain.raw_logs` -> `documents.raw_payloads`
JSONB documents -> containment and expression-index queries.

The JSONB index benchmark compares default `jsonb_ops` and `jsonb_path_ops`
GIN indexes on the same real payload snapshot and records index size plus
`EXPLAIN ANALYZE` summaries.

The SearchDB track projects those JSONB documents into searchable text:
`documents.raw_payloads` -> `search.search_documents` -> full-text GIN search
and trigram fuzzy lookup.

The first VectorDB track projects search documents into deterministic pgvector
memory chunks:
`search.search_documents` -> `memory.agent_memory_chunks` -> cosine similarity
search with an HNSW index. This proves pgvector mechanics before introducing a
real embedding model.

The first hybrid retrieval track combines SearchDB and VectorDB candidates:
`search.search_documents` plus `memory.agent_memory_chunks` -> weighted
full-text, trigram, and vector scores in one retrieval result.

The QueueDB track models ingestion orchestration:
job payloads -> `queue.ingestion_jobs` -> `FOR UPDATE SKIP LOCKED` worker claim
-> retry and dead-letter state transitions.

The first CacheDB track uses a materialized view for repeated summary lookup:
`time_series.candles_1m` plus `defi.swap_events` ->
`cache.market_onchain_summary` -> indexed summary read compared with a base
aggregate query.

The first OLAP track builds an analytics panel with window functions:
`time_series.candles_1m` plus `defi.swap_events` ->
`analytics.market_return_panel` -> return bps, rolling return, and swap
aggregate metrics.

The first Event Store track records real workflow observations:
`analytics.market_return_panel` plus `memory.agent_memory_chunks` ->
`event_store.agent_events` append-oriented audit records.

The first Feature Store track stores point-in-time quant inputs:
`analytics.market_return_panel` plus `time_series.candles_1m` ->
`feature_store.quant_feature_snapshots` typed feature rows with as-of lookup.

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
