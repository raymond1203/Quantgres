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

## Verification

Run:

```powershell
uv run quantgres feature-batch-smoke
```

Expected behavior:

- Refreshes the real OLAP source workflow.
- Inserts or reuses an immutable feature batch.
- Inserts typed batch items.
- Reads the latest item as of a timestamp within the batch.
- Prints the as-of query plan and index names.
