# BNB Chain Raw Logs Experiment

This experiment stores raw BNB Chain JSON-RPC logs in PostgreSQL before building
normalized DeFi event projections.

## Study Question

How should raw EVM logs be ingested, stored, and de-duplicated in PostgreSQL so
later DocumentDB, Time-Series, Event Store, and Feature Store tracks can reuse
the same source data?

## Data Source

The experiment uses BNB Chain JSON-RPC:

- `eth_chainId`
- `eth_blockNumber`
- `eth_getLogs`

The official BNB Chain public dataseed endpoint works for basic RPC calls, but
it can reject `eth_getLogs` with `limit exceeded` even for narrow filters. The
default CLI endpoint is therefore a keyless public BSC RPC endpoint that supports
small `eth_getLogs` ranges. Use `--rpc-url` to override it.

## Schema

SQL file:

- `sql/onchain/001_raw_logs_schema.sql`

Table:

- `onchain.raw_logs`

Important columns:

- `raw_log`: full JSONB payload from JSON-RPC
- `topics`: JSONB topic array
- `chain_id`, `rpc_url`, `from_block`, `to_block`: ingestion lineage
- `transaction_hash`, `log_index`: idempotency key
- `address`, `block_number`, `topic0`: query/index paths for later projections

## Verification

Check RPC connectivity:

```powershell
uv run quantgres bnb-rpc-info
```

Ingest a narrow PancakeSwap V2 WBNB/USDT Swap log range:

```powershell
uv run quantgres ingest-bnb-logs `
  --from-block 107270817 `
  --to-block 107270817 `
  --address 0x16b9a82891338f9ba80e2d6970fdda79d1eb0dae `
  --topic0 0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822
```

Expected behavior:

- Calls real BNB Chain JSON-RPC.
- Stores raw logs in `onchain.raw_logs`.
- Preserves the full JSON payload in JSONB.
- Upserts by `(chain_id, transaction_hash, log_index)`.

This experiment does not require wallet keys, exchange keys, or paid RPC
provider credentials.
