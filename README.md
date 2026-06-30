# Quantgres

Quantgres is a PostgreSQL deep-dive project for learning production database
patterns through quantitative research and AI-agent workloads.

The project uses PostgreSQL as a practical lab for DB types that are often
separate systems in production:

1. RDB / Trading Ledger
2. Time-Series DB / Quant Market Data
3. Document DB / JSONB Event and Document Store
4. Vector DB / pgvector Agent Memory
5. Search DB / Full-Text, Trigram, and Hybrid Search
6. Queue DB / Jobs, Workers, and Notifications
7. Cache DB / Materialized Views, Summary Tables, and TTL Cache
8. OLAP / Analytics DB
9. Event Store / Audit Log
10. Feature Store

The goal is not to hide PostgreSQL behind abstractions. Experiments should keep
schemas, SQL, query plans, indexes, and benchmark results visible.

## Toolchain

- Python 3.14
- uv
- ruff
- ty
- pytest
- psycopg 3
- PostgreSQL 18 with pgvector 0.8.3

## Local Setup

Install dependencies:

```powershell
uv sync
```

Run the local gate:

```powershell
.\scripts\check.ps1
```

If PowerShell execution policy blocks local scripts:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
```

Start local PostgreSQL:

```powershell
docker compose up -d db
```

The local database image is pinned to `pgvector/pgvector:0.8.3-pg18-trixie`.
Benchmark writeups should record the exact server output from `SELECT version()`
because PostgreSQL minor versions can affect query plans and performance.
The container listens on PostgreSQL port `5432` internally and maps to host port
`55432` to avoid conflicts with locally installed PostgreSQL.

Run the CLI smoke check:

```powershell
uv run quantgres doctor
uv run quantgres doctor --check-db
uv run quantgres db-info
uv run quantgres rdb-ledger-smoke
```

## Project Layout

- `docs/`: experiment roadmap and writeups
- `sql/`: plain SQL schema and experiment files
- `scripts/`: local commands and benchmark entrypoints
- `src/quantgres/`: reusable Python helpers
- `tests/`: focused tests for core behavior

## Experiment Contract

Each major DB experiment should include:

- schema or migration SQL
- sample data generator or ingestion script
- benchmark query
- `EXPLAIN ANALYZE` output or summary
- dataset size
- index or schema variant used
- before/after latency
- interpretation
