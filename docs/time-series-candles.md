# Time-Series Candles Experiment

This experiment models 1-minute candles in PostgreSQL before adding
partitioning. It starts with a deterministic fixture and is hardened with real
Binance public kline ingestion.

## Study Question

How should candle data be modeled for symbol/time range queries, how should raw
exchange kline fields be preserved, and what plan does PostgreSQL choose for
small deterministic and real public-data samples with B-tree and BRIN indexes
present?

## Schema

SQL files:

- `sql/time_series/001_candles_schema.sql`
- `sql/time_series/002_candles_fixture.sql`
- `sql/time_series/003_candles_queries.sql`

Table:

- `time_series.candles_1m`

Important columns:

- `symbol`, `ts`: primary key; Binance klines are uniquely identified by open
  time.
- `close_ts`: exchange-reported close time.
- `open_price`, `high_price`, `low_price`, `close_price`, `volume`: OHLCV.
- `quote_volume`, `trade_count`, `taker_buy_base_volume`,
  `taker_buy_quote_volume`: Binance kline payload fields retained for later
  feature and liquidity work.
- `source`: distinguishes deterministic fixtures from real public API data.

Indexes:

- Primary key: `(symbol, ts)`
- Covering B-tree index: `(symbol, ts DESC) INCLUDE (open_price, high_price, low_price, close_price, volume)`
- BRIN index: `ts`

## Fixture

The fixture uses PostgreSQL `generate_series` to create deterministic 1-minute
candles:

- Symbols: `BTCUSDT`, `ETHUSDT`
- Time range: `2026-01-01T00:00:00Z` through `2026-01-02T23:59:00Z`
- Rows: 5,760 total candles

## Verification

```powershell
docker compose up -d db
uv run quantgres time-series-candles-smoke
```

The smoke check applies the schema and fixture, then queries `BTCUSDT` candles
from `2026-01-01T00:00:00Z` to `2026-01-01T01:00:00Z`.

Expected facts:

- Candle count: 60
- First timestamp: `2026-01-01 00:00:00+00:00`
- Last timestamp: `2026-01-01 00:59:00+00:00`

## Real Binance Public Ingestion

Binance public Spot market-data endpoints do not require an API key for kline
reads. The project uses this path for real market-data evidence before adding
more database tracks:

```powershell
uv run quantgres ingest-binance-klines --symbol BTCUSDT --interval 1m --limit 60
```

Expected behavior:

- Fetches real Binance public `GET /api/v3/klines` rows.
- Upserts them into `time_series.candles_1m`.
- Marks `source = 'binance_spot_klines'`.
- Prints fetched/upserted row counts and first/last timestamps.

No Binance API key or private account endpoint is used.

## Benchmark Query

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT
    symbol,
    count(*) AS candle_count,
    sum(close_price * volume) / sum(volume) AS vwap
FROM time_series.candles_1m
WHERE symbol = 'BTCUSDT'
  AND ts >= '2026-01-01T00:00:00Z'::timestamptz
  AND ts < '2026-01-01T01:00:00Z'::timestamptz
GROUP BY symbol;
```

Interpretation should focus on plan shape, not speed. The fixture is still small
enough that timings are only a reproducibility baseline.

Fixture result on PostgreSQL 18.4:

- Dataset: 5,760 candle rows
- Query filter: `symbol = 'BTCUSDT'`, 1-hour range
- Plan: `Index Only Scan` using `candles_1m_symbol_ts_covering_idx`, followed
  by `GroupAggregate`
- Rows scanned: 60
- Heap fetches: 60
- Buffers: 4 shared hits
- Execution time: 0.077 ms

Interpretation: PostgreSQL used the covering B-tree index for the symbol/time
range query. The plan is shaped correctly for point symbol range lookup. The
heap fetches show that an index-only plan can still touch the heap when pages
are not all-visible yet. The BRIN index is present for later append-heavy and
wide time-range experiments, but this narrow symbol/time lookup naturally uses
the B-tree path.
