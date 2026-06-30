# RDB Trading Ledger Experiment

This experiment models a minimal trading ledger using PostgreSQL relational
features only. It starts with a deterministic ledger fixture and is hardened by
recording paper-only order/fill/cash/position traces from real Binance public
candle data.

## Study Question

How should orders, fills, cash ledger entries, and position snapshots be modeled
so PostgreSQL rejects obviously invalid trading data before application logic
sees it?

## Schema

SQL files:

- `sql/rdb/001_trading_ledger_schema.sql`
- `sql/rdb/002_trading_ledger_fixture.sql`
- `sql/rdb/003_trading_ledger_queries.sql`

Tables:

- `rdb.accounts`
- `rdb.strategies`
- `rdb.instruments`
- `rdb.orders`
- `rdb.fills`
- `rdb.cash_ledger_entries`
- `rdb.position_snapshots`

## Modeling Choices

- `client_order_id`, `fill_id`, and `entry_id` are natural fixture keys so the
  fixture can be rerun with `ON CONFLICT`.
- `orders` stores order intent and lifecycle status.
- `fills` stores execution facts and enforces unique fill sequence per order.
- `cash_ledger_entries` is append-only in shape and records deposits, trades,
  fees, withdrawals, and adjustments.
- `position_snapshots` stores current-state snapshots separately from the cash
  and fill history.

## Constraints

The schema uses PostgreSQL `PRIMARY KEY`, `FOREIGN KEY`, `UNIQUE`, and `CHECK`
constraints to reject:

- unknown account, strategy, or symbol references
- negative or zero order quantities
- limit orders without positive limit prices
- duplicate client order IDs
- duplicate fill sequence per order
- zero cash ledger entries
- nonsensical position prices

## Verification

Run the local database:

```powershell
docker compose up -d db
```

Run the smoke check:

```powershell
uv run quantgres rdb-ledger-smoke
```

The smoke check applies the schema and fixture, prints current positions, prints
cash balances, and confirms that representative invalid writes are rejected.

Expected fixture facts:

- Account `A1` holds `0.4 BTCUSDT`.
- Account `A1` has `76183.8100000000 USDT`.
- Account `A2` holds `3 ETHUSDT`.
- Account `A2` has `15690.7000000000 USDT`.

## Real-Data Paper Trace

The RDB ledger should not remain a synthetic-only example. Use real Binance
public candles as the market input, then record a paper-only decision trace into
the ledger:

```powershell
uv run quantgres binance-paper-trace-smoke --symbol BTCUSDT --interval 1m --limit 60
```

Expected behavior:

- Fetches real public Binance klines without an API key.
- Stores the candles in `time_series.candles_1m`.
- Reads the latest two stored Binance candles.
- Creates or updates the `PAPER1` account and
  `binance_kline_momentum_v1` strategy.
- Records a paper-only market order, fill, cash ledger trade/fee entries, and
  position snapshot in RDB tables.

This is not live trading and does not call any signed/private Binance endpoint.
It is a database trace that connects real market data to relational ledger
state.

## Benchmark Query

The first benchmark query is intentionally small:

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT
    account_code,
    currency,
    sum(amount) AS cash_balance
FROM rdb.cash_ledger_entries
WHERE account_code = 'A1'
GROUP BY account_code, currency;
```

It should use the `cash_ledger_account_currency_occurred_at_idx` index once the
table grows beyond fixture size. With the tiny fixture, PostgreSQL may prefer a
sequential scan because the table is too small for the index to matter.

Fixture result on PostgreSQL 18.4:

- Dataset: 8 cash ledger rows
- Query filter: `account_code = 'A1'`
- Plan: `Bitmap Index Scan` on `cash_ledger_account_currency_occurred_at_idx`
  followed by `Bitmap Heap Scan`, `Sort`, and `GroupAggregate`
- Buffers: 5 shared hits
- Execution time: 0.070 ms

Interpretation: even on the tiny fixture, PostgreSQL used the account/currency
ledger index for the account filter. This is not a meaningful speed benchmark
yet, but it confirms the first lookup path and gives a baseline query shape for
larger ledger datasets.
