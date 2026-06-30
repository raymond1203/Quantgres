# JSONB GIN Operator Class Benchmark

This experiment compares PostgreSQL JSONB GIN operator classes on the same real
payload snapshot.

## Study Question

How do `jsonb_ops` and `jsonb_path_ops` differ for containment queries on
financial JSONB payloads?

## Source Data

The benchmark refreshes real upstream data first:

- Binance public klines copied into `documents.raw_payloads`
- BNB Chain RPC Swap logs copied into `documents.raw_payloads`

The benchmark then copies that same payload snapshot into two comparison tables:

- `documents.jsonb_ops_benchmark_payloads`
- `documents.jsonb_path_ops_benchmark_payloads`

## Indexes

SQL file:

- `sql/documents/002_jsonb_index_benchmark_schema.sql`

Indexes:

- `jsonb_ops_benchmark_payload_gin_idx`: default `jsonb_ops`
- `jsonb_path_ops_benchmark_payload_gin_idx`: `jsonb_path_ops`

Tradeoff:

- `jsonb_ops` supports more operators, including key-exists operators.
- `jsonb_path_ops` focuses on containment and jsonpath match operators and can
  produce a smaller, more specific index.

## Verification

Run:

```powershell
uv run quantgres benchmark-jsonb-indexes
```

The command prints:

- table row counts
- matched containment rows
- index sizes
- plan root node and index names
- execution time summary
- JSON and Markdown report paths

The `EXPLAIN` step uses `SET LOCAL enable_seqscan = off` so tiny local datasets
still show an index-probe comparison. Normal planner choices can prefer
sequential scans when the benchmark tables are small.
