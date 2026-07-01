# QueueDB Ingestion Jobs Experiment

This experiment uses PostgreSQL as a durable ingestion job queue.

## Study Question

How can PostgreSQL model ingestion jobs, retries, dead-letter records, and
worker claims with `FOR UPDATE SKIP LOCKED`?

## Schema

SQL file:

- `sql/queue/001_ingestion_jobs_schema.sql`

Table:

- `queue.ingestion_jobs`

Important columns:

- `job_kind`: ingestion type such as Binance klines or BNB raw logs
- `idempotency_key`: prevents duplicate enqueue for the same target
- `payload`: JSONB job arguments
- `status`: `available`, `running`, `completed`, `failed`, `dead_letter`
- `attempts`, `max_attempts`: retry state
- `available_at`, `locked_at`, `locked_by`: scheduling and worker claim state
- `last_error`: latest failure reason

## Claim Pattern

Workers claim work with:

```sql
SELECT job_id
FROM queue.ingestion_jobs
WHERE status IN ('available', 'failed')
  AND available_at <= now()
  AND attempts < max_attempts
ORDER BY priority DESC, available_at, job_id
FOR UPDATE SKIP LOCKED
LIMIT 1
```

The claim happens inside an `UPDATE ... FROM next_job ... RETURNING` statement
so the selected row immediately moves to `running`.

## Worker Execution

`queue-smoke` verifies queue state transitions. `queue-worker-smoke` goes one
step further and executes real ingestion payloads after claiming jobs.

The worker smoke uses an idempotency prefix:

- `worker:ingestion:{run_key}:`

This keeps the worker from claiming benchmark jobs, manual fixtures, or other
available queue rows. The `run_key` accepts only letters, numbers, `.`, `_`,
and `-` so the SQL `LIKE` prefix claim cannot be widened by wildcard
characters. The current worker dispatch table is intentionally small:

- `binance_klines`: fetches Binance public klines and stores them in
  `time_series.candles_1m`
- `bnb_block_timestamp`: projects PancakeSwap swap logs, reuses cached
  `onchain.blocks` rows, fetches missing block timestamps, and enriches
  `defi.swap_events`
- `bnb_swap_corpus`: runs the wider windowed BNB Swap corpus ingestion path,
  stores raw logs, projects swaps, enriches timestamps, and writes the
  generated on-chain report paths into the worker execution summary

Successful jobs are marked `completed`. Failed jobs go through the existing
`failed` or `dead_letter` status transition based on `attempts` and
`max_attempts`.

## Heartbeat and Stale Lock Recovery

Workers refresh ownership by updating `locked_at` while a row is still
`running` and `locked_by` matches the worker id. This uses the existing lock
columns instead of adding a separate heartbeat table.

If a worker dies after claiming a job, the row can remain `running`. Stale
recovery treats `locked_at` as the freshness timestamp:

- only `status='running'` rows with old `locked_at` values are recovered
- `attempts >= max_attempts` moves the job to `dead_letter`
- jobs with retry room move to `failed` and become immediately claimable
- `locked_at` and `locked_by` are cleared so the next worker owns the retry
- `last_error` records the stale-lock recovery reason

This intentionally consumes the attempt that was already incremented at claim
time. A worker that claimed a row and then disappeared has started an execution
attempt from the queue's point of view.

## Verification

```powershell
uv run quantgres queue-smoke
```

Expected behavior:

- Seeds one Binance kline ingestion job and one BNB raw log ingestion job.
- Claims the first job and completes it.
- Claims the second job, fails it once, retries it, and moves it to
  `dead_letter` after the second failure.
- Prints final queue state from PostgreSQL.

This smoke uses real PostgreSQL row state transitions. It does not use an
external queue service.

Run the worker execution smoke:

```powershell
uv run quantgres queue-worker-smoke --run-key default
```

Expected behavior:

- Seeds one Binance kline job, one BNB block timestamp job, and one BNB swap
  corpus job under the worker prefix.
- Claims each job with `FOR UPDATE SKIP LOCKED`.
- Executes the real ingestion payload.
- Marks all jobs `completed`.
- Prints execution summaries and final queue statuses.

Run stale-lock recovery smoke:

```powershell
uv run quantgres queue-stale-lock-smoke --run-key default
```

Expected behavior:

- Seeds real worker ingestion jobs under the worker prefix.
- Claims one job as a stale worker.
- Updates heartbeat on the running row.
- Ages that dedicated row to simulate a worker crash without sleeping.
- Recovers the stale lock into `failed`.
- Lets a recovery worker reclaim the same job and execute the real ingestion
  payload.
- Prints recovered rows, reclaimed execution summary, and final statuses.
