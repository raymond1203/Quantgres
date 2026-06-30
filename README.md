# Quantgres

Quantgres is a PostgreSQL deep-dive project for learning production database
patterns through realistic DeFi, market-data, quantitative research, and
paper-trading agent workloads.

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

The project should not stop at synthetic smoke tests. Deterministic fixtures are
used to prove schemas and constraints, but portfolio evidence should come from
real public data where possible:

- Binance public market-data endpoints for candles, prices, trades, and order
  book snapshots. These do not require Binance API keys.
- BNB Chain JSON-RPC logs for raw on-chain event ingestion. This does not
  require wallet keys.
- Dune only as an optional external reconciliation source after Quantgres has
  its own raw RPC ingestion.

Live trading and signed private exchange endpoints are out of scope. Trading
agent examples write paper-only decisions and execution traces into PostgreSQL.

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
uv run quantgres benchmark-rdb-ledger
uv run quantgres time-series-candles-smoke
uv run quantgres ingest-binance-klines --symbol BTCUSDT --interval 1m --limit 60
uv run quantgres binance-paper-trace-smoke --symbol BTCUSDT --interval 1m --limit 60
uv run quantgres bnb-rpc-info
uv run quantgres ingest-bnb-logs --from-block 107270817 --to-block 107270817 --address 0x16b9a82891338f9ba80e2d6970fdda79d1eb0dae --topic0 0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822
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
