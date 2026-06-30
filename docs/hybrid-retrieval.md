# Hybrid Retrieval

This experiment combines PostgreSQL SearchDB and VectorDB results into one
ranked retrieval surface.

## Study Question

How should Quantgres combine exact keyword evidence with semantic memory search
without adding an external search service?

## Source Data

The smoke uses real upstream workflow outputs:

- JSONB documents projected into `search.search_documents`
- deterministic pgvector memory chunks in `memory.agent_memory_chunks`

It then runs a CTE query that merges:

- full-text candidates using `ts_rank_cd(..., 32)`
- trigram candidates using `similarity(...)`
- vector candidates using cosine similarity from pgvector

## Scoring

The first scorer uses a simple weighted sum:

- text rank: 0.45
- trigram similarity: 0.15
- vector similarity: 0.40

This keeps the component scores visible in the result row. A later loop can
compare this against reciprocal rank fusion or learned reranking.

## Verification

Run:

```powershell
uv run quantgres hybrid-retrieval-smoke
```

Expected behavior:

- Refreshes the real SearchDB and VectorDB source workflows.
- Returns ranked rows with text, trigram, vector, and hybrid scores.
- Prints an `EXPLAIN ANALYZE` plan summary with index names.

The `EXPLAIN` step uses `SET LOCAL enable_seqscan = off` so a tiny local dataset
still proves the index paths for search and vector lookup.
