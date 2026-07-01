# Feature Store Immutable Batches

This experiment adds immutable feature batches for research reproducibility.

## Study Question

How should Quantgres preserve the exact feature rows used by a research run
while still keeping a latest-value Feature Store table for serving-style as-of
queries?

## Tables

- `feature_store.quant_feature_batches`: one row per snapshot batch
- `feature_store.quant_feature_batch_items`: typed feature rows captured in
  that batch

The batch item table is append-oriented. Re-running the same batch id uses
`ON CONFLICT DO NOTHING`; it does not update prior feature rows.

Feature batch smoke uses the Feature Store source row ordering, so rows with
event-time aligned `swap_count > 0` are captured first. The smoke fails closed
if the selected as-of batch item has zero swap count; this keeps immutable batch
evidence tied to the real BNB swap corpus instead of only current market rows
with no observed on-chain event.

## Reproducibility Metadata

Batch ids include more than the typed feature rows. The batch material also
includes:

- `config_hash`: SHA-256 over canonical JSON execution config
- `code_hash`: SHA-256 over the canonical list of related code and SQL file
  hashes
- `dependency_hash`: SHA-256 over dependency and Python-version input file
  hashes
- `runtime_hash`: SHA-256 over PostgreSQL server version number and required
  extension versions

The batch metadata stores the human-readable material behind those hashes:

- `config`: symbol, feature set, run key, Binance source limit, and feature
  source limit
- `config_hash`
- `code_hash`
- `code_paths`: relative path and SHA-256 for each Python or SQL file used by
  the feature batch pipeline
- `dependency_hash`
- `dependency_paths`: relative path and SHA-256 for `pyproject.toml`,
  `uv.lock`, and `.python-version`
- `runtime_hash`
- `runtime`: PostgreSQL version, database/user identity, and installed
  required extension versions

This means a run with identical feature rows but different generation code or
execution settings, dependency lockfile, Python version, PostgreSQL version, or
extension versions produces a different batch id instead of silently reusing a
previous immutable batch.

## Verification

Run:

```powershell
uv run quantgres feature-batch-smoke
```

Expected behavior:

- Refreshes the real OLAP source workflow.
- Inserts or reuses an immutable feature batch.
- Inserts typed batch items.
- Records config, code, dependency, and runtime fingerprints in batch metadata.
- Reads the latest item as of a timestamp within the batch.
- Verifies the as-of item includes a nonzero event-time aligned swap count.
- Prints the as-of query plan and index names.
