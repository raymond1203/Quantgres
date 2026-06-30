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

## Embedding Strategy

This first loop does not call an external embedding API and does not require an
API key. Instead, it uses a deterministic local feature vector over the real
document text. Common Quantgres domain tokens such as `pancakeswap`, `swap`,
`bnb`, `chain`, `binance`, and `kline` use stable buckets; all other tokens use
a hash fallback.

This is intentional:

- It makes tests and smoke runs reproducible.
- It exercises pgvector schema, vector storage, cosine search, and HNSW index
  mechanics.
- It avoids introducing paid services or model downloads before the database
  shape is clear.

It is not a semantic-quality claim. A later loop can replace this with a real
embedding model after a separate technology-adoption review.

## Schema

SQL file:

- `sql/memory/001_agent_memory_schema.sql`

Table:

- `memory.agent_memory_chunks`

Important columns:

- `source`, `external_id`: source identity from the projected document
- `title`, `chunk_text`: retrievable memory text
- `metadata`: source lineage and embedding metadata
- `embedding vector(16)`: deterministic local vector

Index:

- `agent_memory_chunks_embedding_hnsw_idx` using `hnsw (embedding vector_cosine_ops)`

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
