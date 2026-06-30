from dataclasses import dataclass
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

from quantgres.db import connect, query_text

PROJECT_ROOT = Path(__file__).resolve().parents[3]
QUEUE_SQL_DIR = PROJECT_ROOT / "sql" / "queue"
QUEUE_SCHEMA_SQL = QUEUE_SQL_DIR / "001_ingestion_jobs_schema.sql"

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


def claim_job(*, worker_id: str, database_url: str | None = None) -> QueueJob | None:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(query_text(CLAIM_JOB_SQL), {"worker_id": worker_id})
        row = cursor.fetchone()

    if row is None:
        return None

    return row_to_job(row)


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
