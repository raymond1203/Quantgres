from quantgres.experiments.queue_jobs import (
    QueueBenchmarkClaim,
    build_benchmark_jobs,
    count_duplicate_claims,
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
