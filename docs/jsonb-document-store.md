# JSONB Document Store Experiment

This experiment uses PostgreSQL JSONB as a document store for raw API and RPC
payloads.

## Study Question

How should raw market-data and on-chain payloads be stored so PostgreSQL can
preserve the full document while still supporting indexed source, time, symbol,
chain, and containment queries?

## Source Data

The smoke does not use mock payloads. It refreshes real upstream data first:

- Binance public `GET /api/v3/klines`
- BNB Chain JSON-RPC `eth_getLogs`

It then copies those stored rows into `documents.raw_payloads`.

## Schema

SQL file:

- `sql/documents/001_raw_payloads_schema.sql`

Table:

- `documents.raw_payloads`

Important columns:

- `source`, `external_id`: document identity
- `observed_at`: source event time or ingestion time
- `symbol`, `chain_id`: structured filters for common lookups
- `payload`: full JSONB document

Indexes:

- source/time B-tree index
- symbol/time B-tree index
- chain/time B-tree index
- GIN index on `payload`
- expression index on `payload ->> 'address'`

## Verification

```powershell
uv run quantgres jsonb-document-smoke --symbol BTCUSDT --document-limit 10
```

Expected behavior:

- Fetches real Binance klines.
- Fetches real BNB Chain PancakeSwap V2 Swap logs.
- Stores both as JSONB documents.
- Runs a JSONB containment query on the BNB log address.
- Prints document counts and a plan summary.

This is the first JSONB document-store layer. Later loops can compare
`jsonb_ops` and `jsonb_path_ops`, add jsonpath queries, and project documents
into normalized event tables.

The `jsonb_ops` vs `jsonb_path_ops` comparison is documented in
`docs/jsonb-index-benchmark.md`.
