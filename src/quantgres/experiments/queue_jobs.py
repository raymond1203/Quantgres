import re
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from psycopg.types.json import Jsonb

from quantgres.db import connect, query_text
from quantgres.experiments.binance_candles import fetch_and_store_binance_klines
from quantgres.experiments.bnb_block_timestamps import run_bnb_block_timestamp_smoke
from quantgres.experiments.bnb_swap_projection import (
    PANCAKESWAP_SAMPLE_BLOCK,
    PANCAKESWAP_V2_SWAP_TOPIC0,
    PANCAKESWAP_V2_WBNB_USDT_PAIR,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
QUEUE_SQL_DIR = PROJECT_ROOT / "sql" / "queue"
QUEUE_SCHEMA_SQL = QUEUE_SQL_DIR / "001_ingestion_jobs_schema.sql"
RUN_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")

SEED_JOB_SQL = """
INSERT INTO queue.ingestion_jobs (
    job_kind,
    idempotency_key,
    payload,
    status,
    priority,
    attempts,
    max_attempts,
    available_at,
    locked_at,
    locked_by,
    last_error,
    completed_at,
    updated_at
)
VALUES (
    %(job_kind)s,
    %(idempotency_key)s,
    %(payload)s,
    'available',
    %(priority)s,
    0,
    %(max_attempts)s,
    now(),
    NULL,
    NULL,
    NULL,
    NULL,
    now()
)
ON CONFLICT (idempotency_key) DO UPDATE
SET job_kind = EXCLUDED.job_kind,
    payload = EXCLUDED.payload,
    status = 'available',
    priority = EXCLUDED.priority,
    attempts = 0,
    max_attempts = EXCLUDED.max_attempts,
    available_at = now(),
    locked_at = NULL,
    locked_by = NULL,
    last_error = NULL,
    completed_at = NULL,
    updated_at = now()
"""

CLAIM_JOB_SQL = """
WITH next_job AS (
    SELECT job_id
    FROM queue.ingestion_jobs
    WHERE status IN ('available', 'failed')
      AND available_at <= now()
      AND attempts < max_attempts
    ORDER BY priority DESC, available_at, job_id
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
UPDATE queue.ingestion_jobs AS job
SET status = 'running',
    attempts = job.attempts + 1,
    locked_by = %(worker_id)s,
    locked_at = now(),
    updated_at = now()
FROM next_job
WHERE job.job_id = next_job.job_id
RETURNING
    job.job_id,
    job.job_kind,
    job.idempotency_key,
    job.payload,
    job.status,
    job.priority,
    job.attempts,
    job.max_attempts,
    job.locked_by
"""

CLAIM_BENCHMARK_JOB_SQL = """
WITH next_job AS (
    SELECT job_id
    FROM queue.ingestion_jobs
    WHERE idempotency_key LIKE %(prefix)s
      AND status IN ('available', 'failed')
      AND available_at <= now()
      AND attempts < max_attempts
    ORDER BY priority DESC, available_at, job_id
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
UPDATE queue.ingestion_jobs AS job
SET status = 'running',
    attempts = job.attempts + 1,
    locked_by = %(worker_id)s,
    locked_at = now(),
    updated_at = now()
FROM next_job
WHERE job.job_id = next_job.job_id
RETURNING
    job.job_id,
    job.job_kind,
    job.idempotency_key,
    job.payload,
    job.status,
    job.priority,
    job.attempts,
    job.max_attempts,
    job.locked_by
"""

CLAIM_PREFIX_JOB_SQL = """
WITH next_job AS (
    SELECT job_id
    FROM queue.ingestion_jobs
    WHERE idempotency_key LIKE %(prefix)s
      AND status IN ('available', 'failed')
      AND available_at <= now()
      AND attempts < max_attempts
    ORDER BY priority DESC, available_at, job_id
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
UPDATE queue.ingestion_jobs AS job
SET status = 'running',
    attempts = job.attempts + 1,
    locked_by = %(worker_id)s,
    locked_at = now(),
    updated_at = now()
FROM next_job
WHERE job.job_id = next_job.job_id
RETURNING
    job.job_id,
    job.job_kind,
    job.idempotency_key,
    job.payload,
    job.status,
    job.priority,
    job.attempts,
    job.max_attempts,
    job.locked_by
"""

COMPLETE_JOB_SQL = """
UPDATE queue.ingestion_jobs
SET status = 'completed',
    completed_at = now(),
    locked_at = NULL,
    locked_by = NULL,
    last_error = NULL,
    updated_at = now()
WHERE job_id = %(job_id)s
  AND status = 'running'
RETURNING job_id
"""

FAIL_JOB_SQL = """
UPDATE queue.ingestion_jobs
SET status = CASE
        WHEN attempts >= max_attempts THEN 'dead_letter'
        ELSE 'failed'
    END,
    available_at = CASE
        WHEN attempts >= max_attempts THEN available_at
        ELSE now() + (%(retry_delay_seconds)s::text || ' seconds')::interval
    END,
    locked_at = NULL,
    locked_by = NULL,
    last_error = %(error)s,
    updated_at = now()
WHERE job_id = %(job_id)s
  AND status = 'running'
RETURNING job_id, status
"""

JOB_STATUS_SQL = """
SELECT
    job_kind,
    idempotency_key,
    status,
    attempts,
    max_attempts,
    locked_by,
    last_error
FROM queue.ingestion_jobs
WHERE idempotency_key IN (
    'binance:BTCUSDT:1m:60',
    'bnb:pancakeswap-v2-wbnb-usdt:swap:107270817'
)
ORDER BY idempotency_key
"""

BENCHMARK_STATUS_COUNT_SQL = """
SELECT count(*)::integer
FROM queue.ingestion_jobs
WHERE idempotency_key LIKE %(prefix)s
  AND status = %(status)s
"""

JOB_STATUS_BY_PREFIX_SQL = """
SELECT
    job_kind,
    idempotency_key,
    status,
    attempts,
    max_attempts,
    locked_by,
    last_error
FROM queue.ingestion_jobs
WHERE idempotency_key LIKE %(prefix)s
ORDER BY idempotency_key
"""


@dataclass(frozen=True)
class QueueJob:
    job_id: int
    job_kind: str
    idempotency_key: str
    payload: dict[str, Any]
    status: str
    priority: int
    attempts: int
    max_attempts: int
    locked_by: str


@dataclass(frozen=True)
class QueueJobStatus:
    job_kind: str
    idempotency_key: str
    status: str
    attempts: int
    max_attempts: int
    locked_by: str | None
    last_error: str | None


@dataclass(frozen=True)
class QueueSmokeResult:
    first_claim: QueueJob
    second_claim: QueueJob
    retry_claim: QueueJob
    statuses: tuple[QueueJobStatus, ...]


@dataclass(frozen=True)
class QueueBenchmarkClaim:
    worker_id: str
    job_id: int
    idempotency_key: str
    priority: int


@dataclass(frozen=True)
class QueueBenchmarkResult:
    job_count: int
    worker_count: int
    claimed_count: int
    unique_claimed_count: int
    duplicate_claim_count: int
    completed_count: int
    elapsed_ms: float
    claims: tuple[QueueBenchmarkClaim, ...]


@dataclass(frozen=True)
class QueueWorkerExecution:
    worker_id: str
    job_kind: str
    idempotency_key: str
    final_status: str
    attempts: int
    summary: dict[str, object]


@dataclass(frozen=True)
class QueueWorkerSmokeResult:
    run_key: str
    worker_id: str
    seeded_jobs: int
    executions: tuple[QueueWorkerExecution, ...]
    statuses: tuple[QueueJobStatus, ...]


def read_sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def ensure_queue_schema(database_url: str | None = None) -> None:
    with connect(database_url) as connection:
        connection.execute(query_text(read_sql(QUEUE_SCHEMA_SQL)))


def seed_queue_fixture(database_url: str | None = None) -> None:
    jobs = (
        {
            "job_kind": "binance_klines",
            "idempotency_key": "binance:BTCUSDT:1m:60",
            "payload": Jsonb({"symbol": "BTCUSDT", "interval": "1m", "limit": 60}),
            "priority": 10,
            "max_attempts": 3,
        },
        {
            "job_kind": "bnb_raw_logs",
            "idempotency_key": "bnb:pancakeswap-v2-wbnb-usdt:swap:107270817",
            "payload": Jsonb(
                {
                    "from_block": 107270817,
                    "to_block": 107270817,
                    "address": "0x16b9a82891338f9ba80e2d6970fdda79d1eb0dae",
                    "topic0": "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822",
                }
            ),
            "priority": 5,
            "max_attempts": 2,
        },
    )
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.executemany(query_text(SEED_JOB_SQL), jobs)


def benchmark_prefix(run_key: str) -> str:
    validate_run_key(run_key)
    return f"benchmark:queue-skip-locked:{run_key}:"


def worker_prefix(run_key: str) -> str:
    validate_run_key(run_key)
    return f"worker:ingestion:{run_key}:"


def validate_run_key(run_key: str) -> None:
    if not RUN_KEY_PATTERN.fullmatch(run_key):
        raise ValueError("run_key must contain only letters, numbers, '.', '_' or '-'.")


def build_worker_jobs(
    *,
    run_key: str,
    binance_limit: int = 5,
) -> tuple[dict[str, object], ...]:
    if binance_limit <= 0:
        raise ValueError("binance_limit must be positive.")

    prefix = worker_prefix(run_key)
    return (
        {
            "job_kind": "binance_klines",
            "idempotency_key": f"{prefix}binance:BTCUSDT:1m:{binance_limit}",
            "payload": Jsonb({"symbol": "BTCUSDT", "interval": "1m", "limit": binance_limit}),
            "priority": 20,
            "max_attempts": 2,
        },
        {
            "job_kind": "bnb_block_timestamp",
            "idempotency_key": f"{prefix}bnb:block-timestamp:{PANCAKESWAP_SAMPLE_BLOCK}",
            "payload": Jsonb(
                {
                    "from_block": PANCAKESWAP_SAMPLE_BLOCK,
                    "to_block": PANCAKESWAP_SAMPLE_BLOCK,
                    "address": PANCAKESWAP_V2_WBNB_USDT_PAIR,
                    "topic0": PANCAKESWAP_V2_SWAP_TOPIC0,
                }
            ),
            "priority": 10,
            "max_attempts": 2,
        },
    )


def seed_queue_worker_jobs(
    *,
    run_key: str,
    binance_limit: int = 5,
    database_url: str | None = None,
) -> int:
    ensure_queue_schema(database_url)
    jobs = build_worker_jobs(run_key=run_key, binance_limit=binance_limit)
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.executemany(query_text(SEED_JOB_SQL), jobs)

    return len(jobs)


def build_benchmark_jobs(
    *,
    job_count: int,
    run_key: str,
) -> tuple[dict[str, object], ...]:
    if job_count <= 0:
        raise ValueError("job_count must be positive.")

    prefix = benchmark_prefix(run_key)
    jobs: list[dict[str, object]] = []
    for index in range(job_count):
        if index % 2 == 0:
            job_kind = "binance_klines"
            payload = {"symbol": "BTCUSDT", "interval": "1m", "limit": 60}
        else:
            job_kind = "bnb_block_timestamp"
            payload = {"from_block": 107270817, "to_block": 107270817}

        jobs.append(
            {
                "job_kind": job_kind,
                "idempotency_key": f"{prefix}{index:03d}",
                "payload": Jsonb(payload),
                "priority": job_count - index,
                "max_attempts": 3,
            }
        )

    return tuple(jobs)


def seed_queue_benchmark_jobs(
    *,
    job_count: int,
    run_key: str,
    database_url: str | None = None,
) -> None:
    ensure_queue_schema(database_url)
    jobs = build_benchmark_jobs(job_count=job_count, run_key=run_key)
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.executemany(query_text(SEED_JOB_SQL), jobs)


def row_to_job(row: tuple[Any, ...]) -> QueueJob:
    return QueueJob(
        job_id=int(row[0]),
        job_kind=str(row[1]),
        idempotency_key=str(row[2]),
        payload=dict(row[3]),
        status=str(row[4]),
        priority=int(row[5]),
        attempts=int(row[6]),
        max_attempts=int(row[7]),
        locked_by=str(row[8]),
    )


def job_to_benchmark_claim(job: QueueJob) -> QueueBenchmarkClaim:
    return QueueBenchmarkClaim(
        worker_id=job.locked_by,
        job_id=job.job_id,
        idempotency_key=job.idempotency_key,
        priority=job.priority,
    )


def claim_job(*, worker_id: str, database_url: str | None = None) -> QueueJob | None:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(query_text(CLAIM_JOB_SQL), {"worker_id": worker_id})
        row = cursor.fetchone()

    if row is None:
        return None

    return row_to_job(row)


def claim_job_by_prefix(
    *,
    worker_id: str,
    prefix: str,
    database_url: str | None = None,
) -> QueueJob | None:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            query_text(CLAIM_PREFIX_JOB_SQL),
            {
                "prefix": prefix + "%",
                "worker_id": worker_id,
            },
        )
        row = cursor.fetchone()

    if row is None:
        return None

    return row_to_job(row)


def count_duplicate_claims(claims: tuple[QueueBenchmarkClaim, ...]) -> int:
    job_ids = [claim.job_id for claim in claims]
    return len(job_ids) - len(set(job_ids))


def claim_benchmark_jobs_with_open_transactions(
    *,
    worker_count: int,
    run_key: str,
    database_url: str | None = None,
) -> tuple[QueueBenchmarkClaim, ...]:
    if worker_count <= 0:
        raise ValueError("worker_count must be positive.")

    claims: list[QueueBenchmarkClaim] = []
    with ExitStack() as stack:
        connections = [stack.enter_context(connect(database_url)) for _ in range(worker_count)]
        cursors = [stack.enter_context(connection.cursor()) for connection in connections]

        for index, cursor in enumerate(cursors):
            worker_id = f"benchmark-worker-{index + 1}"
            cursor.execute(
                query_text(CLAIM_BENCHMARK_JOB_SQL),
                {
                    "prefix": benchmark_prefix(run_key) + "%",
                    "worker_id": worker_id,
                },
            )
            row = cursor.fetchone()
            if row is not None:
                claims.append(job_to_benchmark_claim(row_to_job(row)))

        for claim, cursor in zip(claims, cursors, strict=False):
            cursor.execute(query_text(COMPLETE_JOB_SQL), {"job_id": claim.job_id})
            if cursor.fetchone() is None:
                raise RuntimeError(f"Could not complete benchmark job {claim.job_id}.")

    return tuple(claims)


def complete_job(*, job_id: int, database_url: str | None = None) -> None:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(query_text(COMPLETE_JOB_SQL), {"job_id": job_id})
        if cursor.fetchone() is None:
            raise RuntimeError(f"Could not complete running job {job_id}.")


def fail_job(
    *,
    job_id: int,
    error: str,
    retry_delay_seconds: int = 0,
    database_url: str | None = None,
) -> str:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            query_text(FAIL_JOB_SQL),
            {
                "job_id": job_id,
                "error": error,
                "retry_delay_seconds": retry_delay_seconds,
            },
        )
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError(f"Could not fail running job {job_id}.")

    return str(row[1])


def load_job_statuses(database_url: str | None = None) -> tuple[QueueJobStatus, ...]:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(query_text(JOB_STATUS_SQL))
        rows = cursor.fetchall()

    return tuple(
        QueueJobStatus(
            job_kind=str(row[0]),
            idempotency_key=str(row[1]),
            status=str(row[2]),
            attempts=int(row[3]),
            max_attempts=int(row[4]),
            locked_by=None if row[5] is None else str(row[5]),
            last_error=None if row[6] is None else str(row[6]),
        )
        for row in rows
    )


def load_job_statuses_by_prefix(
    *,
    prefix: str,
    database_url: str | None = None,
) -> tuple[QueueJobStatus, ...]:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(query_text(JOB_STATUS_BY_PREFIX_SQL), {"prefix": prefix + "%"})
        rows = cursor.fetchall()

    return tuple(
        QueueJobStatus(
            job_kind=str(row[0]),
            idempotency_key=str(row[1]),
            status=str(row[2]),
            attempts=int(row[3]),
            max_attempts=int(row[4]),
            locked_by=None if row[5] is None else str(row[5]),
            last_error=None if row[6] is None else str(row[6]),
        )
        for row in rows
    )


def count_benchmark_jobs_by_status(
    *,
    run_key: str,
    status: str,
    database_url: str | None = None,
) -> int:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            query_text(BENCHMARK_STATUS_COUNT_SQL),
            {
                "prefix": benchmark_prefix(run_key) + "%",
                "status": status,
            },
        )
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("Benchmark status count returned no row.")

    return int(row[0])


def payload_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Expected non-empty string payload field {key!r}.")
    return value


def payload_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Expected integer payload field {key!r}.")
    return value


def execute_queue_job(job: QueueJob, database_url: str | None = None) -> dict[str, object]:
    if job.job_kind == "binance_klines":
        result = fetch_and_store_binance_klines(
            symbol=payload_string(job.payload, "symbol"),
            interval=payload_string(job.payload, "interval"),
            limit=payload_int(job.payload, "limit"),
            database_url=database_url,
        )
        return {
            "rows_fetched": result.rows_fetched,
            "rows_upserted": result.rows_upserted,
            "symbol": result.symbol,
            "interval": result.interval,
        }

    if job.job_kind == "bnb_block_timestamp":
        result = run_bnb_block_timestamp_smoke(
            from_block=payload_int(job.payload, "from_block"),
            to_block=payload_int(job.payload, "to_block"),
            pair_address=payload_string(job.payload, "address"),
            topic0=payload_string(job.payload, "topic0"),
            database_url=database_url,
        )
        return {
            "requested_blocks": len(result.requested_block_numbers),
            "cached_blocks": len(result.cached_block_numbers),
            "missing_blocks": len(result.missing_block_numbers),
            "fetched_blocks": len(result.fetched_blocks),
            "projected_swaps": result.swap_projection.projected_events,
            "enriched_swaps": result.enriched_swaps,
        }

    raise ValueError(f"Unsupported queue job kind: {job.job_kind}")


def run_claimed_job(
    *,
    job: QueueJob,
    worker_id: str,
    database_url: str | None = None,
) -> QueueWorkerExecution:
    try:
        summary = execute_queue_job(job, database_url=database_url)
        complete_job(job_id=job.job_id, database_url=database_url)
        final_status = "completed"
    except Exception as error:
        final_status = fail_job(
            job_id=job.job_id,
            error=f"{type(error).__name__}: {error}",
            database_url=database_url,
        )
        summary = {
            "error_type": type(error).__name__,
            "error": str(error),
        }

    return QueueWorkerExecution(
        worker_id=worker_id,
        job_kind=job.job_kind,
        idempotency_key=job.idempotency_key,
        final_status=final_status,
        attempts=job.attempts,
        summary=summary,
    )


def run_queue_worker_smoke(
    *,
    run_key: str = "default",
    worker_id: str = "worker-exec-1",
    binance_limit: int = 5,
    database_url: str | None = None,
) -> QueueWorkerSmokeResult:
    seeded_jobs = seed_queue_worker_jobs(
        run_key=run_key,
        binance_limit=binance_limit,
        database_url=database_url,
    )
    prefix = worker_prefix(run_key)
    executions: list[QueueWorkerExecution] = []

    while len(executions) < seeded_jobs * 2:
        job = claim_job_by_prefix(
            worker_id=worker_id,
            prefix=prefix,
            database_url=database_url,
        )
        if job is None:
            break
        executions.append(
            run_claimed_job(
                job=job,
                worker_id=worker_id,
                database_url=database_url,
            )
        )

    return QueueWorkerSmokeResult(
        run_key=run_key,
        worker_id=worker_id,
        seeded_jobs=seeded_jobs,
        executions=tuple(executions),
        statuses=load_job_statuses_by_prefix(prefix=prefix, database_url=database_url),
    )


def run_queue_smoke(database_url: str | None = None) -> QueueSmokeResult:
    ensure_queue_schema(database_url)
    seed_queue_fixture(database_url)

    first_claim = claim_job(worker_id="worker-a", database_url=database_url)
    if first_claim is None:
        raise RuntimeError("Expected first queue claim to return a job.")
    complete_job(job_id=first_claim.job_id, database_url=database_url)

    second_claim = claim_job(worker_id="worker-b", database_url=database_url)
    if second_claim is None:
        raise RuntimeError("Expected second queue claim to return a job.")
    fail_job(job_id=second_claim.job_id, error="temporary RPC limit", database_url=database_url)

    retry_claim = claim_job(worker_id="worker-c", database_url=database_url)
    if retry_claim is None:
        raise RuntimeError("Expected retry queue claim to return a job.")
    fail_job(job_id=retry_claim.job_id, error="permanent RPC limit", database_url=database_url)

    return QueueSmokeResult(
        first_claim=first_claim,
        second_claim=second_claim,
        retry_claim=retry_claim,
        statuses=load_job_statuses(database_url),
    )


def run_queue_benchmark_smoke(
    *,
    job_count: int = 12,
    worker_count: int = 4,
    run_key: str = "default",
    database_url: str | None = None,
) -> QueueBenchmarkResult:
    seed_queue_benchmark_jobs(
        job_count=job_count,
        run_key=run_key,
        database_url=database_url,
    )
    started_at = perf_counter()
    claims = claim_benchmark_jobs_with_open_transactions(
        worker_count=worker_count,
        run_key=run_key,
        database_url=database_url,
    )
    elapsed_ms = (perf_counter() - started_at) * 1000
    duplicate_claim_count = count_duplicate_claims(claims)

    return QueueBenchmarkResult(
        job_count=job_count,
        worker_count=worker_count,
        claimed_count=len(claims),
        unique_claimed_count=len({claim.job_id for claim in claims}),
        duplicate_claim_count=duplicate_claim_count,
        completed_count=count_benchmark_jobs_by_status(
            run_key=run_key,
            status="completed",
            database_url=database_url,
        ),
        elapsed_ms=elapsed_ms,
        claims=claims,
    )
