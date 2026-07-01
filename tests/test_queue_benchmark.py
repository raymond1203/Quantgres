import pytest
from psycopg.types.json import Jsonb

from quantgres.experiments.bnb_raw_logs import BnbLogWindowResult, BnbWindowedLogIngestionResult
from quantgres.experiments.bnb_swap_corpus import BnbSwapCorpusSmokeResult
from quantgres.experiments.queue_jobs import (
    QueueBenchmarkClaim,
    QueueJob,
    age_running_job_lock,
    build_benchmark_jobs,
    build_worker_jobs,
    count_duplicate_claims,
    execute_queue_job,
    payload_int,
    recover_stale_jobs,
    worker_prefix,
)
from quantgres.reports import WrittenReport


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
        "worker:ingestion:test:bnb:swap-corpus:107270717-107270817:w10",
    ]
    assert jobs[0]["job_kind"] == "binance_klines"
    assert jobs[1]["job_kind"] == "bnb_block_timestamp"
    assert jobs[2]["job_kind"] == "bnb_swap_corpus"
    payload = jobs[2]["payload"]
    assert isinstance(payload, Jsonb)
    corpus_payload = payload.obj
    assert corpus_payload["from_block"] == 107270717
    assert corpus_payload["to_block"] == 107270817
    assert corpus_payload["window_size"] == 10
    assert corpus_payload["limit"] == 5
    assert worker_prefix("test") == "worker:ingestion:test:"


def test_worker_prefix_rejects_like_wildcards():
    with pytest.raises(ValueError, match="run_key"):
        worker_prefix("bad%key")


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


def test_execute_queue_job_dispatches_bnb_swap_corpus(monkeypatch, tmp_path):
    result = BnbSwapCorpusSmokeResult(
        windowed_ingestion=BnbWindowedLogIngestionResult(
            rpc_url="https://example.invalid",
            chain_id=56,
            from_block=100,
            to_block=109,
            address="0xpair",
            topic0="0xtopic",
            window_size=10,
            windows=(
                BnbLogWindowResult(
                    from_block=100,
                    to_block=109,
                    rows_fetched=2,
                    rows_upserted=2,
                ),
            ),
        ),
        projected_events=2,
        requested_block_numbers=(100, 101),
        cached_block_numbers=(),
        missing_block_numbers=(100, 101),
        fetched_blocks=(),
        upserted_blocks=2,
        updated_swaps=2,
        enriched_swaps=2,
        sample_events=(),
        report=WrittenReport(
            json_path=tmp_path / "bnb-swap-corpus.json",
            markdown_path=tmp_path / "bnb-swap-corpus.md",
        ),
    )
    calls: dict[str, object] = {}

    def fake_corpus_smoke(**kwargs):
        calls.update(kwargs)
        return result

    monkeypatch.setattr(
        "quantgres.experiments.queue_jobs.run_bnb_swap_corpus_smoke",
        fake_corpus_smoke,
    )
    job = QueueJob(
        job_id=1,
        job_kind="bnb_swap_corpus",
        idempotency_key="worker:ingestion:test:bnb:swap-corpus",
        payload={
            "from_block": 100,
            "to_block": 109,
            "window_size": 10,
            "address": "0xpair",
            "topic0": "0xtopic",
            "limit": 5,
        },
        status="running",
        priority=1,
        attempts=1,
        max_attempts=2,
        locked_by="worker",
    )

    summary = execute_queue_job(job, database_url="postgresql://example")

    assert calls == {
        "from_block": 100,
        "to_block": 109,
        "window_size": 10,
        "pair_address": "0xpair",
        "topic0": "0xtopic",
        "result_limit": 5,
        "database_url": "postgresql://example",
    }
    assert summary == {
        "windows": 1,
        "rows_fetched": 2,
        "rows_upserted": 2,
        "projected_swaps": 2,
        "requested_blocks": 2,
        "fetched_blocks": 0,
        "enriched_swaps": 2,
        "report_json": str(tmp_path / "bnb-swap-corpus.json"),
        "report_markdown": str(tmp_path / "bnb-swap-corpus.md"),
    }


def test_age_running_job_lock_rejects_non_positive_age():
    with pytest.raises(ValueError, match="age_seconds"):
        age_running_job_lock(job_id=1, age_seconds=0)


def test_recover_stale_jobs_rejects_non_positive_limits():
    with pytest.raises(ValueError, match="timeout_seconds"):
        recover_stale_jobs(timeout_seconds=0)

    with pytest.raises(ValueError, match="limit"):
        recover_stale_jobs(timeout_seconds=60, limit=0)
