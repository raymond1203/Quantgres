from pathlib import Path

from quantgres.experiments.rdb_ledger_benchmark import (
    BenchmarkPaths,
    build_markdown_report,
    write_report,
)


def test_write_report_creates_json_and_markdown(tmp_path: Path):
    report = {
        "title": "Example Benchmark",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "track": "RDB / Trading Ledger",
        "query_name": "cash balance by account",
        "parameters": {"account_code": "A1"},
        "postgresql": {"server_version": "PostgreSQL 18.4"},
        "dataset_sizes": {"cash_ledger_entries": 8},
        "query": "SELECT 1",
        "result_rows": [
            {
                "account_code": "A1",
                "currency": "USDT",
                "cash_balance": "76183.8100000000",
            }
        ],
        "plan_summary": {
            "root_node_type": "Aggregate",
            "planning_time_ms": 0.1,
            "execution_time_ms": 0.2,
            "shared_hit_blocks": 5,
        },
        "interpretation": "Fixture baseline.",
    }

    written = write_report(report, BenchmarkPaths(output_dir=tmp_path, slug="example"))

    assert written.json_path.exists()
    assert written.markdown_path.exists()
    assert "Example Benchmark" in written.markdown_path.read_text(encoding="utf-8")


def test_build_markdown_report_includes_required_sections():
    report = {
        "title": "Example Benchmark",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "track": "RDB / Trading Ledger",
        "query_name": "cash balance by account",
        "parameters": {"account_code": "A1"},
        "postgresql": {"server_version": "PostgreSQL 18.4"},
        "dataset_sizes": {"cash_ledger_entries": 8},
        "query": "SELECT 1",
        "result_rows": [
            {
                "account_code": "A1",
                "currency": "USDT",
                "cash_balance": "76183.8100000000",
            }
        ],
        "plan_summary": {
            "root_node_type": "Aggregate",
            "planning_time_ms": 0.1,
            "execution_time_ms": 0.2,
            "shared_hit_blocks": 5,
        },
        "interpretation": "Fixture baseline.",
    }

    markdown = build_markdown_report(report)

    assert "## Dataset Size" in markdown
    assert "## Query" in markdown
    assert "## Plan Summary" in markdown
    assert "Fixture baseline." in markdown
