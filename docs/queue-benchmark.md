# QueueDB Multi-Worker Benchmark

This experiment uses PostgreSQL row locks to show how queue workers can claim
different jobs without an external queue service.

## Study Question

Can Quantgres use `FOR UPDATE SKIP LOCKED` to let multiple ingestion workers
claim jobs without duplicate processing?

## Method

The smoke seeds benchmark-only jobs with realistic ingestion payload shapes:

- Binance kline ingestion
- BNB block timestamp ingestion

It then opens multiple database transactions, lets each worker claim a job, and
keeps the transactions open until all claims have happened. This makes row locks
observable without adding thread scheduling noise.

## Verification

Run:

```powershell
uv run quantgres queue-benchmark-smoke
```

Expected behavior:

- The number of claimed jobs equals the worker count when enough jobs exist.
- Claimed job ids are unique.
- Duplicate claim count is zero.
- Claimed jobs are completed after the benchmark transactions commit.
