# Runtime Verification

Quantgres uses PostgreSQL 18 with pgvector 0.8.3 as the local database baseline.
Before running benchmark experiments, verify the actual local runtime.

PostgreSQL 18 Docker images store data under a major-version-specific directory
such as `/var/lib/postgresql/18/docker`. Mount the named volume at
`/var/lib/postgresql`, not `/var/lib/postgresql/data`.

The Compose service maps host port `55432` to container port `5432` to avoid
conflicts with local PostgreSQL installations that commonly bind host port
`5432`.

## Start PostgreSQL

```powershell
docker compose up -d db
```

## Check Compose Configuration

```powershell
docker compose config --quiet
```

## Check Database Runtime

```powershell
uv run quantgres db-info
```

The command prints:

- `SELECT version()` output
- `server_version_num`
- current database and user
- installed `vector` and `pg_trgm` extension versions

The command exits with status code `1` if required extensions are missing.

## Raw SQL

The equivalent SQL lives in:

```text
sql/001_runtime_checks.sql
```

Benchmark reports should copy the exact `SELECT version()` output because minor
PostgreSQL versions can affect query plans and performance.
