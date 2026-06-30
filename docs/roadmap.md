# Quantgres Roadmap

Quantgres starts as a DB study project. Quant and AI-agent workflows provide the
domain context for realistic PostgreSQL experiments.

## Phase 0: Foundation

- uv, ruff, ty, pytest
- psycopg 3 and raw SQL first
- Docker Compose PostgreSQL with pgvector
- SQL directory conventions
- benchmark/reporting conventions

## Phase 1: Core PostgreSQL Roles

1. RDB / Trading Ledger
2. Time-Series DB / Quant Market Data
3. Document DB / JSONB
4. Vector DB / pgvector

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
- sample data
- benchmark query
- index or schema variant
- `EXPLAIN ANALYZE`
- benchmark summary
- interpretation
