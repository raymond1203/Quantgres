# SearchDB Documents Experiment

This experiment uses PostgreSQL as a search engine over real JSONB documents.

## Study Question

How should raw Binance and BNB Chain payloads be projected into searchable text
so PostgreSQL can support ranked full-text search and fuzzy trigram lookup?

## Source Data

The smoke refreshes real upstream data through:

- Binance public klines
- BNB Chain JSON-RPC logs
- `documents.raw_payloads`

It then projects those documents into `search.search_documents`.

## Schema

SQL file:

- `sql/search/001_search_documents_schema.sql`

Table:

- `search.search_documents`

Important columns:

- `document_text`: normalized text assembled from source payload fields
- `fuzzy_key`: symbol or address field for trigram lookup
- `search_vector`: stored generated `tsvector`
- `metadata`: lineage back to the raw document

Indexes:

- GIN index on `search_vector`
- GIN trigram index on `fuzzy_key`
- observed time B-tree index

## Verification

```powershell
uv run quantgres search-document-smoke --query "pancakeswap swap" --fuzzy 0x16b9a82891338f9b --limit 5
```

Expected behavior:

- Refreshes real JSONB documents from Binance and BNB Chain data.
- Projects documents into the search table.
- Returns full-text results for the PancakeSwap swap query.
- Returns trigram results for the partial pair address.
- Prints full-text and trigram plan summaries.

Later loops can add hybrid keyword/vector retrieval and larger benchmark
datasets.

## Larger Corpus Benchmark

Run:

```powershell
uv run quantgres search-document-benchmark --symbols BTCUSDT,ETHUSDT,BNBUSDT --binance-limit 200 --limit 5
```

Expected behavior:

- Fetches Binance public klines for each requested symbol.
- Projects those klines plus the PancakeSwap BNB log document into
  `search.search_documents`.
- Runs full-text search and trigram search.
- Writes JSON and Markdown reports under `reports/generated/search/`.
- Records source-level document counts, top results, PostgreSQL runtime, and
  plan summaries with index names.

The benchmark plan uses `enable_seqscan=off` to capture index-probe evidence for
the GIN full-text and trigram indexes. Treat the report as reproducibility and
index evidence, not as a production latency claim.
