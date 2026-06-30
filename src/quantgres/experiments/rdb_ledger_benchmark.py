import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from quantgres.db import connect, query_text
from quantgres.experiments.rdb_trading_ledger import apply_schema_and_fixture
from quantgres.reports import WrittenReport, default_generated_reports_dir
from quantgres.runtime import load_runtime_info

CASH_BALANCE_QUERY = """
SELECT
    account_code,
    currency,
    sum(amount) AS cash_balance
FROM rdb.cash_ledger_entries
WHERE account_code = %s
GROUP BY account_code, currency
ORDER BY account_code, currency
"""

EXPLAIN_CASH_BALANCE_QUERY = f"""
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
{CASH_BALANCE_QUERY}
"""


@dataclass(frozen=True)
class BenchmarkPaths:
    output_dir: Path
    slug: str

    @property
    def json_path(self) -> Path:
        return self.output_dir / f"{self.slug}.json"

    @property
    def markdown_path(self) -> Path:
        return self.output_dir / f"{self.slug}.md"


def decimal_to_string(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    return value


def json_default(value: object) -> str:
    if isinstance(value, Decimal | datetime | Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def load_dataset_sizes(database_url: str | None = None) -> dict[str, int]:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT 'accounts' AS table_name, count(*)::integer FROM rdb.accounts
            UNION ALL
            SELECT 'strategies', count(*)::integer FROM rdb.strategies
            UNION ALL
            SELECT 'instruments', count(*)::integer FROM rdb.instruments
            UNION ALL
            SELECT 'orders', count(*)::integer FROM rdb.orders
            UNION ALL
            SELECT 'fills', count(*)::integer FROM rdb.fills
            UNION ALL
            SELECT 'cash_ledger_entries', count(*)::integer FROM rdb.cash_ledger_entries
            UNION ALL
            SELECT 'position_snapshots', count(*)::integer FROM rdb.position_snapshots
            ORDER BY table_name
            """
        )
        rows = cursor.fetchall()

    return {str(row[0]): int(row[1]) for row in rows}


def run_cash_balance_query(
    account_code: str, database_url: str | None = None
) -> list[dict[str, object]]:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(query_text(CASH_BALANCE_QUERY), (account_code,))
        rows = cursor.fetchall()

    return [
        {
            "account_code": str(row[0]),
            "currency": str(row[1]),
            "cash_balance": decimal_to_string(row[2]),
        }
        for row in rows
    ]


def run_cash_balance_explain(
    account_code: str, database_url: str | None = None
) -> list[dict[str, Any]]:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(query_text(EXPLAIN_CASH_BALANCE_QUERY), (account_code,))
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("EXPLAIN did not return a plan.")

    plan = row[0]
    if not isinstance(plan, list):
        raise TypeError("Expected EXPLAIN FORMAT JSON to return a list.")

    return plan


def extract_plan_summary(plan: list[dict[str, Any]]) -> dict[str, Any]:
    if not plan:
        raise ValueError("EXPLAIN plan is empty.")

    root = plan[0]
    plan_node = root.get("Plan", {})

    return {
        "planning_time_ms": root.get("Planning Time"),
        "execution_time_ms": root.get("Execution Time"),
        "root_node_type": plan_node.get("Node Type"),
        "shared_hit_blocks": plan_node.get("Shared Hit Blocks"),
    }


def build_markdown_report(report: dict[str, Any]) -> str:
    summary = report["plan_summary"]
    dataset_sizes = report["dataset_sizes"]
    result_rows = report["result_rows"]

    lines = [
        f"# {report['title']}",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Track: `{report['track']}`",
        f"- Query name: `{report['query_name']}`",
        f"- Account filter: `{report['parameters']['account_code']}`",
        f"- PostgreSQL: `{report['postgresql']['server_version']}`",
        "",
        "## Dataset Size",
        "",
    ]

    for table_name, row_count in dataset_sizes.items():
        lines.append(f"- `{table_name}`: {row_count} rows")

    lines.extend(
        [
            "",
            "## Query",
            "",
            "```sql",
            report["query"].strip(),
            "```",
            "",
            "## Result Rows",
            "",
        ]
    )

    for row in result_rows:
        lines.append(
            f"- `{row['account_code']}` `{row['currency']}` cash_balance=`{row['cash_balance']}`"
        )

    lines.extend(
        [
            "",
            "## Plan Summary",
            "",
            f"- Root node: `{summary['root_node_type']}`",
            f"- Planning time: `{summary['planning_time_ms']}` ms",
            f"- Execution time: `{summary['execution_time_ms']}` ms",
            f"- Shared hit blocks: `{summary['shared_hit_blocks']}`",
            "",
            "## Interpretation",
            "",
            report["interpretation"],
            "",
        ]
    )

    return "\n".join(lines)


def write_report(report: dict[str, Any], paths: BenchmarkPaths) -> WrittenReport:
    paths.output_dir.mkdir(parents=True, exist_ok=True)

    paths.json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, default=json_default),
        encoding="utf-8",
    )
    paths.markdown_path.write_text(build_markdown_report(report), encoding="utf-8")

    return WrittenReport(json_path=paths.json_path, markdown_path=paths.markdown_path)


def run_rdb_ledger_cash_balance_benchmark(
    account_code: str = "A1",
    output_dir: Path | None = None,
    database_url: str | None = None,
) -> WrittenReport:
    apply_schema_and_fixture(database_url)

    runtime = load_runtime_info(database_url)
    dataset_sizes = load_dataset_sizes(database_url)
    result_rows = run_cash_balance_query(account_code, database_url)
    plan = run_cash_balance_explain(account_code, database_url)
    plan_summary = extract_plan_summary(plan)

    slug = "rdb-trading-ledger-cash-balance"
    report = {
        "title": "RDB Trading Ledger Cash Balance Benchmark",
        "slug": slug,
        "generated_at": datetime.now(UTC).isoformat(),
        "track": "RDB / Trading Ledger",
        "query_name": "cash balance by account",
        "parameters": {"account_code": account_code},
        "schema_files": [
            "sql/rdb/001_trading_ledger_schema.sql",
            "sql/rdb/002_trading_ledger_fixture.sql",
        ],
        "query": CASH_BALANCE_QUERY,
        "dataset_sizes": dataset_sizes,
        "result_rows": result_rows,
        "plan": plan,
        "plan_summary": plan_summary,
        "postgresql": {
            "server_version": runtime.server_version,
            "server_version_num": runtime.server_version_num,
        },
        "interpretation": (
            "This fixture-sized benchmark is a reproducibility baseline, not a "
            "speed claim. It records the exact query, dataset size, PostgreSQL "
            "version, plan shape, and timing so later larger datasets can be "
            "compared against the same report structure."
        ),
    }

    report_dir = output_dir or (default_generated_reports_dir() / "rdb")
    return write_report(report, BenchmarkPaths(output_dir=report_dir, slug=slug))
