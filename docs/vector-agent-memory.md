# VectorDB Agent Memory Experiment

This experiment uses PostgreSQL plus pgvector as a small agent-memory vector
store for real Quantgres payloads and search documents.

## Study Question

How should PostgreSQL store and retrieve agent memory chunks with vector
similarity search while preserving source metadata and replayability?

## Source Data

The smoke refreshes the existing real-data pipeline first:

- Binance public klines
- BNB Chain RPC logs
- JSONB documents
- SearchDB text projection

It then projects `search.search_documents` rows into:

- `memory.agent_memory_chunks`
- `memory.agent_memory_model_chunks`

## Embedding Strategy

The baseline loop does not call an external embedding API and does not require
an API key. Instead, it uses a deterministic local feature vector over the real
document text. Common Quantgres domain tokens such as `pancakeswap`, `swap`,
`bnb`, `chain`, `binance`, and `kline` use stable buckets; all other tokens use
a hash fallback.

This is intentional:

- It makes tests and smoke runs reproducible.
- It exercises pgvector schema, vector storage, cosine search, and HNSW index
  mechanics.
- It keeps a stable retrieval baseline for comparing real embedding models.

It is not a semantic-quality claim.

The real embedding comparison loop adds a separate 384-dimensional projection
using `fastembed==0.8.0` and `BAAI/bge-small-en-v1.5`. This runs locally on CPU
through ONNX Runtime, downloads the model on first use, and still does not
require an embedding API key. The real embedding table is separate so the
deterministic pgvector baseline remains available for before/after retrieval
comparison.

## Schema

SQL file:

- `sql/memory/001_agent_memory_schema.sql`
- `sql/memory/002_agent_memory_model_chunks.sql`

Table:

- `memory.agent_memory_chunks`

Important columns:

- `source`, `external_id`: source identity from the projected document
- `title`, `chunk_text`: retrievable memory text
- `metadata`: source lineage and embedding metadata
- `embedding vector(16)`: deterministic local vector

Index:

- `agent_memory_chunks_embedding_hnsw_idx` using `hnsw (embedding vector_cosine_ops)`

Real embedding comparison table:

- `memory.agent_memory_model_chunks`

Important columns:

- `embedding_model`: model identity, currently `BAAI/bge-small-en-v1.5`
- `source`, `external_id`: source identity from the projected document
- `title`, `chunk_text`: retrievable memory text
- `metadata`: source lineage and embedding metadata
- `embedding vector(384)`: local fastembed vector

Index:

- `agent_memory_model_chunks_embedding_hnsw_idx` using
  `hnsw (embedding vector_cosine_ops)`

## Verification

Run:

```powershell
uv run quantgres vector-memory-smoke --query "pancakeswap swap bnb chain"
```

Expected behavior:

- Refreshes real JSONB/SearchDB source data.
- Upserts memory chunks into `memory.agent_memory_chunks`.
- Runs cosine similarity search with pgvector `<=>`.
- Prints top results and a plan summary.

This experiment does not require wallet keys, exchange keys, embedding API keys,
or live trading.

Run the real embedding comparison:

```powershell
uv run quantgres embedding-comparison-smoke --query "pancakeswap swap bnb chain" --source-limit 20 --limit 5
```

Expected behavior:

- Refreshes the same real JSONB/SearchDB source data.
- Upserts deterministic hash chunks and real fastembed chunks.
- Prints the top deterministic results, top real embedding results, overlap
  count, and real embedding pgvector plan summary.
- Uses `agent_memory_model_chunks_embedding_hnsw_idx` for the 384-dimensional
  similarity search.

The first real embedding run may need network access to download the public
model files.

## Benchmark Report

The retrieval benchmark wraps the same real-data path and writes local JSON and
Markdown evidence under `reports/generated/vector/`:

```powershell
uv run quantgres vector-retrieval-benchmark --query "pancakeswap swap bnb chain" --source-limit 20 --limit 5
```

The report records:

- deterministic hash top-k results
- real fastembed top-k results
- top-k overlap count
- projected and total chunk counts
- embedding model and dimensions
- PostgreSQL runtime metadata
- deterministic and real embedding pgvector plan summaries

Use this report as retrieval evidence, not as a universal latency claim. Small
local datasets can make absolute timings noisy; the stable evidence is the query
shape, index usage, result set, overlap, runtime version, and exact parameters.
