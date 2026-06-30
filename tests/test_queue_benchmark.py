import pytest

from quantgres.experiments.queue_jobs import (
    QueueBenchmarkClaim,
    QueueJob,
    build_benchmark_jobs,
    build_worker_jobs,
    count_duplicate_claims,
    execute_queue_job,
    payload_int,
    worker_prefix,
)


def test_build_benchmark_jobs_uses_unique_idempotency_keys():
    jobs = build_benchmark_jobs(job_count=4, run_key="test")

    keys = [job["idempotency_key"] for job in jobs]

    assert keys == [
        "benchmark:queue-skip-locked:test:000",
        "benchmark:queue-skip-locked:test:001",
        "benchmark:queue-skip-locked:test:002",
        "benchmark:queue-skip-locked:test:003",
    ]
    assert len(set(keys)) == 4


def test_count_duplicate_claims_counts_repeated_job_ids():
    claims = (
        QueueBenchmarkClaim("worker-a", 1, "job-1", 10),
        QueueBenchmarkClaim("worker-b", 2, "job-2", 9),
        QueueBenchmarkClaim("worker-c", 1, "job-1", 10),
    )

    assert count_duplicate_claims(claims) == 1


def test_build_worker_jobs_uses_isolated_prefix_and_real_payloads():
    jobs = build_worker_jobs(run_key="test", binance_limit=7)

    keys = [job["idempotency_key"] for job in jobs]

    assert keys == [
        "worker:ingestion:test:binance:BTCUSDT:1m:7",
        "worker:ingestion:test:bnb:block-timestamp:107270817",
    ]
    assert jobs[0]["job_kind"] == "binance_klines"
    assert jobs[1]["job_kind"] == "bnb_block_timestamp"
    assert worker_prefix("test") == "worker:ingestion:test:"


def test_payload_int_rejects_bool_values():
    with pytest.raises(ValueError, match="integer payload field"):
        payload_int({"limit": True}, "limit")


def test_execute_queue_job_rejects_unsupported_job_kind():
    job = QueueJob(
        job_id=1,
        job_kind="unknown",
        idempotency_key="worker:ingestion:test:unknown",
        payload={},
        status="running",
        priority=1,
        attempts=1,
        max_attempts=2,
        locked_by="worker",
    )

    with pytest.raises(ValueError, match="Unsupported queue job kind"):
        execute_queue_job(job)
