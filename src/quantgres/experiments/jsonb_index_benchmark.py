import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

from quantgres.db import connect, query_text
from quantgres.experiments.binance_candles import fetch_and_store_binance_klines
from quantgres.experiments.bnb_raw_logs import fetch_and_store_bnb_logs
from quantgres.experiments.jsonb_documents import (
    PANCAKESWAP_SAMPLE_BLOCK,
    PANCAKESWAP_V2_SWAP_TOPIC0,
    PANCAKESWAP_V2_WBNB_USDT_PAIR,
    ensure_document_schema,
    upsert_binance_documents,
    upsert_bnb_log_documents,
)
from quantgres.reports import WrittenReport, default_generated_reports_dir
from quantgres.runtime import load_runtime_info

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DOCUMENT_SQL_DIR = PROJECT_ROOT / "sql" / "documents"
JSONB_INDEX_BENCHMARK_SCHEMA_SQL = DOCUMENT_SQL_DIR / "002_jsonb_index_benchmark_schema.sql"

JSONB_OPS_TABLE = "documents.jsonb_ops_benchmark_payloads"
JSONB_PATH_OPS_TABLE = "documents.jsonb_path_ops_benchmark_payloads"
JSONB_OPS_INDEX = "documents.jsonb_ops_benchmark_payload_gin_idx"
JSONB_PATH_OPS_INDEX = "documents.jsonb_path_ops_benchmark_payload_gin_idx"

UPSERT_BENCHMARK_TABLE_SQL = """
INSERT INTO {table_name} (
    source,
    external_id,
    observed_at,
    symbol,
    chain_id,
    payload
)
SELECT
    source,
    external_id,
    observed_at,
    symbol,
    chain_id,
    payload
FROM documents.raw_payloads
WHERE source IN ('binance_kline', 'bnb_rpc_log')
ON CONFLICT (source, external_id) DO UPDATE
SET observed_at = EXCLUDED.observed_at,
    symbol = EXCLUDED.symbol,
    chain_id = EXCLUDED.chain_id,
    payload = EXCLUDED.payload,
    benchmarked_at = now()
"""

COUNT_TABLE_SQL = "SELECT count(*)::integer FROM {table_name}"

COUNT_CONTAINMENT_SQL = """
SELECT count(*)::integer
FROM {table_name}
WHERE payload @> %s::jsonb
"""

EXPLAIN_CONTAINMENT_SQL = """
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
SELECT count(*)::integer
FROM {table_name}
WHERE payload @> %s::jsonb
"""

INDEX_SIZE_SQL = """
SELECT
    pg_relation_size(%s::regclass)::bigint,
    pg_size_pretty(pg_relation_size(%s::regclass))
"""

ANALYZE_TABLE_SQL = "ANALYZE {table_name}"


@dataclass(frozen=True)
class JsonbIndexPlanSummary:
    root_node_type: str
    index_names: tuple[str, ...]
    planning_time_ms: float
    execution_time_ms: float
    shared_hit_blocks: int
    shared_read_blocks: int


@dataclass(frozen=True)
class JsonbIndexComparison:
    opclass: str
    table_name: str
    index_name: str
    table_rows: int
    matched_rows: int
    index_size_bytes: int
    index_size_pretty: str
    plan: JsonbIndexPlanSummary


@dataclass(frozen=True)
class JsonbIndexBenchmarkResult:
    query_name: str
    containment_filter: dict[str, object]
    comparisons: tuple[JsonbIndexComparison, ...]
    report: WrittenReport


def read_sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def ensure_jsonb_index_benchmark_schema(database_url: str | None = None) -> None:
    with connect(database_url) as connection:
        connection.execute(query_text(read_sql(JSONB_INDEX_BENCHMARK_SCHEMA_SQL)))


def refresh_real_jsonb_documents(
    *,
    symbol: str,
    binance_limit: int,
    database_url: str | None = None,
) -> None:
    ensure_document_schema(database_url)
    fetch_and_store_binance_klines(
        symbol=symbol,
        interval="1m",
        limit=binance_limit,
        database_url=database_url,
    )
    fetch_and_store_bnb_logs(
        from_block=PANCAKESWAP_SAMPLE_BLOCK,
        to_block=PANCAKESWAP_SAMPLE_BLOCK,
        address=PANCAKESWAP_V2_WBNB_USDT_PAIR,
        topic0=PANCAKESWAP_V2_SWAP_TOPIC0,
        database_url=database_url,
    )
    upsert_binance_documents(
        symbol=symbol,
        limit=binance_limit,
        database_url=database_url,
    )
    upsert_bnb_log_documents(
        limit=10,
        database_url=database_url,
    )


def upsert_benchmark_table(table_name: str, database_url: str | None = None) -> int:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(query_text(UPSERT_BENCHMARK_TABLE_SQL.format(table_name=table_name)))
        return cursor.rowcount


def analyze_benchmark_table(table_name: str, database_url: str | None = None) -> None:
    with connect(database_url) as connection:
        connection.execute(query_text(ANALYZE_TABLE_SQL.format(table_name=table_name)))


def refresh_benchmark_tables(database_url: str | None = None) -> dict[str, int]:
    ensure_jsonb_index_benchmark_schema(database_url)
    upserted = {
        JSONB_OPS_TABLE: upsert_benchmark_table(JSONB_OPS_TABLE, database_url),
        JSONB_PATH_OPS_TABLE: upsert_benchmark_table(JSONB_PATH_OPS_TABLE, database_url),
    }
    analyze_benchmark_table(JSONB_OPS_TABLE, database_url)
    analyze_benchmark_table(JSONB_PATH_OPS_TABLE, database_url)
    return upserted


def load_table_count(table_name: str, database_url: str | None = None) -> int:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(query_text(COUNT_TABLE_SQL.format(table_name=table_name)))
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError(f"Count query returned no row for {table_name}.")

    return int(row[0])


def load_index_size(index_name: str, database_url: str | None = None) -> tuple[int, str]:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(query_text(INDEX_SIZE_SQL), (index_name, index_name))
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError(f"Index size query returned no row for {index_name}.")

    return int(row[0]), str(row[1])


def count_containment_matches(
    *,
    table_name: str,
    containment_filter: dict[str, object],
    database_url: str | None = None,
) -> int:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            query_text(COUNT_CONTAINMENT_SQL.format(table_name=table_name)),
            (Jsonb(containment_filter),),
        )
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError(f"Containment count returned no row for {table_name}.")

    return int(row[0])


def run_containment_explain(
    *,
    table_name: str,
    containment_filter: dict[str, object],
    database_url: str | None = None,
) -> list[dict[str, Any]]:
    with (
        connect(database_url) as connection,
        connection.transaction(),
        connection.cursor() as cursor,
    ):
        cursor.execute(query_text("SET LOCAL enable_seqscan = off"))
        cursor.execute(
            query_text(EXPLAIN_CONTAINMENT_SQL.format(table_name=table_name)),
            (Jsonb(containment_filter),),
        )
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError(f"EXPLAIN returned no row for {table_name}.")

    plan = row[0]
    if not isinstance(plan, list):
        raise TypeError("Expected EXPLAIN FORMAT JSON to return a list.")

    return plan


def iter_plan_nodes(plan_node: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    children = plan_node.get("Plans", [])
    if not isinstance(children, list):
        children = []

    nodes = [plan_node]
    for child in children:
        if isinstance(child, dict):
            nodes.extend(iter_plan_nodes(child))

    return tuple(nodes)


def summarize_plan(plan: list[dict[str, Any]]) -> JsonbIndexPlanSummary:
    if not plan:
        raise ValueError("EXPLAIN plan is empty.")

    root = plan[0]
    plan_node = root["Plan"]
    if not isinstance(plan_node, dict):
        raise TypeError("Expected EXPLAIN root Plan to be an object.")

    nodes = iter_plan_nodes(plan_node)
    index_names = tuple(
        str(node["Index Name"]) for node in nodes if isinstance(node.get("Index Name"), str)
    )

    return JsonbIndexPlanSummary(
        root_node_type=str(plan_node["Node Type"]),
        index_names=index_names,
        planning_time_ms=float(root["Planning Time"]),
        execution_time_ms=float(root["Execution Time"]),
        shared_hit_blocks=sum(int(node.get("Shared Hit Blocks", 0)) for node in nodes),
        shared_read_blocks=sum(int(node.get("Shared Read Blocks", 0)) for node in nodes),
    )


def compare_opclass(
    *,
    opclass: str,
    table_name: str,
    index_name: str,
    containment_filter: dict[str, object],
    database_url: str | None = None,
) -> JsonbIndexComparison:
    index_size_bytes, index_size_pretty = load_index_size(index_name, database_url)
    plan = run_containment_explain(
        table_name=table_name,
        containment_filter=containment_filter,
        database_url=database_url,
    )
    return JsonbIndexComparison(
        opclass=opclass,
        table_name=table_name,
        index_name=index_name,
        table_rows=load_table_count(table_name, database_url),
        matched_rows=count_containment_matches(
            table_name=table_name,
            containment_filter=containment_filter,
            database_url=database_url,
        ),
        index_size_bytes=index_size_bytes,
        index_size_pretty=index_size_pretty,
        plan=summarize_plan(plan),
    )


def json_default(value: object) -> str:
    if isinstance(value, Decimal | datetime | Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def comparison_to_dict(comparison: JsonbIndexComparison) -> dict[str, object]:
    return {
        "opclass": comparison.opclass,
        "table_name": comparison.table_name,
        "index_name": comparison.index_name,
        "table_rows": comparison.table_rows,
        "matched_rows": comparison.matched_rows,
        "index_size_bytes": comparison.index_size_bytes,
        "index_size_pretty": comparison.index_size_pretty,
        "plan": {
            "root_node_type": comparison.plan.root_node_type,
            "index_names": list(comparison.plan.index_names),
            "planning_time_ms": comparison.plan.planning_time_ms,
            "execution_time_ms": comparison.plan.execution_time_ms,
            "shared_hit_blocks": comparison.plan.shared_hit_blocks,
            "shared_read_blocks": comparison.plan.shared_read_blocks,
        },
    }


def build_markdown_report(report: dict[str, Any]) -> str:
    lines = [
        f"# {report['title']}",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Track: `{report['track']}`",
        f"- Query name: `{report['query_name']}`",
        f"- Containment filter: `{json.dumps(report['parameters']['containment_filter'])}`",
        f"- PostgreSQL: `{report['postgresql']['server_version']}`",
        "",
        "## Dataset",
        "",
    ]

    for table_name, row_count in report["dataset_sizes"].items():
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
            "## Operator Class Comparison",
            "",
            "| Opclass | Index size | Matched rows | Root node | Index names | "
            "Execution ms | Shared hits | Shared reads |",
            "|---|---:|---:|---|---|---:|---:|---:|",
        ]
    )

    for comparison in report["comparisons"]:
        plan = comparison["plan"]
        lines.append(
            "| "
            f"`{comparison['opclass']}` | "
            f"`{comparison['index_size_pretty']}` | "
            f"{comparison['matched_rows']} | "
            f"`{plan['root_node_type']}` | "
            f"`{', '.join(plan['index_names'])}` | "
            f"{plan['execution_time_ms']} | "
            f"{plan['shared_hit_blocks']} | "
            f"{plan['shared_read_blocks']} |"
        )

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            report["interpretation"],
            "",
        ]
    )
    return "\n".join(lines)


def write_report(report: dict[str, Any], output_dir: Path) -> WrittenReport:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "jsonb-operator-class-benchmark.json"
    markdown_path = output_dir / "jsonb-operator-class-benchmark.md"

    json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, default=json_default),
        encoding="utf-8",
    )
    markdown_path.write_text(build_markdown_report(report), encoding="utf-8")

    return WrittenReport(json_path=json_path, markdown_path=markdown_path)


def run_jsonb_index_benchmark(
    *,
    symbol: str = "BTCUSDT",
    binance_limit: int = 500,
    containment_filter: dict[str, object] | None = None,
    output_dir: Path | None = None,
    database_url: str | None = None,
) -> JsonbIndexBenchmarkResult:
    filter_value = containment_filter or {"address": PANCAKESWAP_V2_WBNB_USDT_PAIR}

    refresh_real_jsonb_documents(
        symbol=symbol,
        binance_limit=binance_limit,
        database_url=database_url,
    )
    refresh_benchmark_tables(database_url)

    comparisons = (
        compare_opclass(
            opclass="jsonb_ops",
            table_name=JSONB_OPS_TABLE,
            index_name=JSONB_OPS_INDEX,
            containment_filter=filter_value,
            database_url=database_url,
        ),
        compare_opclass(
            opclass="jsonb_path_ops",
            table_name=JSONB_PATH_OPS_TABLE,
            index_name=JSONB_PATH_OPS_INDEX,
            containment_filter=filter_value,
            database_url=database_url,
        ),
    )

    runtime = load_runtime_info(database_url)
    report = {
        "title": "JSONB GIN Operator Class Benchmark",
        "slug": "jsonb-operator-class-benchmark",
        "generated_at": datetime.now(UTC).isoformat(),
        "track": "Document DB / JSONB",
        "query_name": "payload containment",
        "parameters": {
            "symbol": symbol.upper(),
            "binance_limit": binance_limit,
            "containment_filter": filter_value,
            "enable_seqscan": False,
        },
        "schema_files": [
            "sql/documents/001_raw_payloads_schema.sql",
            "sql/documents/002_jsonb_index_benchmark_schema.sql",
        ],
        "query": COUNT_CONTAINMENT_SQL.format(table_name="<benchmark_table>"),
        "dataset_sizes": {
            comparison.table_name: comparison.table_rows for comparison in comparisons
        },
        "comparisons": [comparison_to_dict(comparison) for comparison in comparisons],
        "postgresql": {
            "server_version": runtime.server_version,
            "server_version_num": runtime.server_version_num,
        },
        "interpretation": (
            "This benchmark compares two JSONB GIN operator classes against the "
            "same real Binance and BNB RPC payload snapshot. The EXPLAIN runs set "
            "enable_seqscan=off so the report captures an index-probe comparison; "
            "normal planner choices can still prefer sequential scans on very "
            "small local datasets."
        ),
    }

    report_dir = output_dir or (default_generated_reports_dir() / "documents")
    written = write_report(report, report_dir)
    return JsonbIndexBenchmarkResult(
        query_name="payload containment",
        containment_filter=filter_value,
        comparisons=comparisons,
        report=written,
    )
