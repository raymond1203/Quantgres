import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from quantgres.db import connect, query_text
from quantgres.experiments.binance_candles import (
    BinanceCandleIngestionResult,
    fetch_and_store_binance_klines,
)
from quantgres.experiments.bnb_raw_logs import fetch_and_store_bnb_logs
from quantgres.experiments.jsonb_documents import (
    PANCAKESWAP_SAMPLE_BLOCK,
    PANCAKESWAP_V2_SWAP_TOPIC0,
    PANCAKESWAP_V2_WBNB_USDT_PAIR,
    ensure_document_schema,
    run_jsonb_document_smoke,
    upsert_binance_documents,
    upsert_bnb_log_documents,
)
from quantgres.reports import WrittenReport, default_generated_reports_dir
from quantgres.runtime import DatabaseRuntimeInfo, load_runtime_info

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SEARCH_SQL_DIR = PROJECT_ROOT / "sql" / "search"
SEARCH_DOCUMENTS_SCHEMA_SQL = SEARCH_SQL_DIR / "001_search_documents_schema.sql"
FULL_TEXT_INDEX_NAME = "search_documents_vector_idx"
TRIGRAM_INDEX_NAME = "search_documents_fuzzy_key_trgm_idx"
DEFAULT_BENCHMARK_SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT")

UPSERT_SEARCH_DOCUMENTS_SQL = """
WITH source_documents AS (
    SELECT *
    FROM documents.raw_payloads
    WHERE source IN ('binance_kline', 'bnb_rpc_log')
),
projected AS (
    SELECT
        source,
        external_id,
        observed_at,
        CASE
            WHEN source = 'binance_kline'
                THEN concat(payload ->> 'symbol', ' Binance 1m kline')
            WHEN source = 'bnb_rpc_log'
                THEN concat('BNB Chain PancakeSwap swap log ', payload ->> 'transactionHash')
            ELSE concat(source, ' ', external_id)
        END AS title,
        CASE
            WHEN source = 'binance_kline' THEN concat_ws(
                ' ',
                'binance kline market candle',
                payload ->> 'symbol',
                payload ->> 'source',
                'open', payload ->> 'open_price',
                'close', payload ->> 'close_price',
                'volume', payload ->> 'volume'
            )
            WHEN source = 'bnb_rpc_log' THEN concat_ws(
                ' ',
                'bnb chain pancakeswap swap rpc log',
                payload ->> 'address',
                payload ->> 'transactionHash',
                payload -> 'topics' ->> 0
            )
            ELSE payload::text
        END AS document_text,
        CASE
            WHEN source = 'binance_kline' THEN coalesce(payload ->> 'symbol', external_id)
            WHEN source = 'bnb_rpc_log' THEN coalesce(payload ->> 'address', external_id)
            ELSE external_id
        END AS fuzzy_key,
        jsonb_build_object(
            'source', source,
            'external_id', external_id
        ) AS metadata
    FROM source_documents
)
INSERT INTO search.search_documents (
    source,
    external_id,
    observed_at,
    title,
    document_text,
    fuzzy_key,
    metadata
)
SELECT
    source,
    external_id,
    observed_at,
    title,
    document_text,
    fuzzy_key,
    metadata
FROM projected
ON CONFLICT (source, external_id) DO UPDATE
SET observed_at = EXCLUDED.observed_at,
    title = EXCLUDED.title,
    document_text = EXCLUDED.document_text,
    fuzzy_key = EXCLUDED.fuzzy_key,
    metadata = EXCLUDED.metadata,
    ingested_at = now()
"""

FULL_TEXT_SEARCH_SQL = """
SELECT
    source,
    external_id,
    title,
    ts_rank(search_vector, websearch_to_tsquery('english', %s)) AS rank
FROM search.search_documents
WHERE search_vector @@ websearch_to_tsquery('english', %s)
ORDER BY rank DESC, observed_at DESC
LIMIT %s
"""

EXPLAIN_FULL_TEXT_SEARCH_SQL = f"""
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
{FULL_TEXT_SEARCH_SQL}
"""

TRIGRAM_SEARCH_SQL = """
SELECT
    source,
    external_id,
    fuzzy_key,
    similarity(fuzzy_key, %s) AS similarity_score
FROM search.search_documents
WHERE fuzzy_key %% %s
ORDER BY similarity_score DESC, observed_at DESC
LIMIT %s
"""

COUNT_SEARCH_DOCUMENTS_BY_SOURCE_SQL = """
SELECT source, count(*)::integer
FROM search.search_documents
GROUP BY source
ORDER BY source
"""

EXPLAIN_TRIGRAM_SEARCH_SQL = f"""
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
{TRIGRAM_SEARCH_SQL}
"""


@dataclass(frozen=True)
class SearchResultRow:
    source: str
    external_id: str
    title: str
    score: Decimal


@dataclass(frozen=True)
class TrigramResultRow:
    source: str
    external_id: str
    fuzzy_key: str
    score: float


@dataclass(frozen=True)
class SearchPlanSummary:
    root_node_type: str
    execution_time_ms: float
    planning_time_ms: float
    index_names: tuple[str, ...] = ()
    shared_hit_blocks: int = 0
    shared_read_blocks: int = 0


@dataclass(frozen=True)
class SearchDocumentSmokeResult:
    projected_documents: int
    full_text_results: tuple[SearchResultRow, ...]
    trigram_results: tuple[TrigramResultRow, ...]
    full_text_plan: SearchPlanSummary
    trigram_plan: SearchPlanSummary


@dataclass(frozen=True)
class SearchDocumentBenchmarkResult:
    symbols: tuple[str, ...]
    binance_limit: int
    bnb_log_limit: int
    binance_ingestions: tuple[BinanceCandleIngestionResult, ...]
    binance_documents_upserted: int
    bnb_documents_upserted: int
    projected_documents: int
    source_counts: tuple[tuple[str, int], ...]
    full_text_query: str
    fuzzy_query: str
    full_text_results: tuple[SearchResultRow, ...]
    trigram_results: tuple[TrigramResultRow, ...]
    full_text_plan: SearchPlanSummary
    trigram_plan: SearchPlanSummary
    report: WrittenReport


def read_sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def ensure_search_schema(database_url: str | None = None) -> None:
    with connect(database_url) as connection:
        connection.execute(query_text(read_sql(SEARCH_DOCUMENTS_SCHEMA_SQL)))


def refresh_search_documents(database_url: str | None = None) -> int:
    ensure_search_schema(database_url)
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(query_text(UPSERT_SEARCH_DOCUMENTS_SQL))
        return cursor.rowcount


def normalize_symbols(symbols: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(
        dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol.strip())
    )
    if not normalized:
        raise ValueError("At least one symbol is required.")
    return normalized


def load_search_document_source_counts(
    database_url: str | None = None,
) -> tuple[tuple[str, int], ...]:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(query_text(COUNT_SEARCH_DOCUMENTS_BY_SOURCE_SQL))
        rows = cursor.fetchall()

    return tuple((str(row[0]), int(row[1])) for row in rows)


def load_full_text_results(
    *,
    query: str,
    limit: int,
    database_url: str | None = None,
) -> tuple[SearchResultRow, ...]:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(query_text(FULL_TEXT_SEARCH_SQL), (query, query, limit))
        rows = cursor.fetchall()

    return tuple(
        SearchResultRow(
            source=str(row[0]),
            external_id=str(row[1]),
            title=str(row[2]),
            score=row[3],
        )
        for row in rows
    )


def load_trigram_results(
    *,
    query: str,
    limit: int,
    database_url: str | None = None,
) -> tuple[TrigramResultRow, ...]:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(query_text(TRIGRAM_SEARCH_SQL), (query, query, limit))
        rows = cursor.fetchall()

    return tuple(
        TrigramResultRow(
            source=str(row[0]),
            external_id=str(row[1]),
            fuzzy_key=str(row[2]),
            score=float(row[3]),
        )
        for row in rows
    )


def load_plan(
    *,
    sql: str,
    params: tuple[object, ...],
    force_index: bool = False,
    database_url: str | None = None,
) -> SearchPlanSummary:
    if force_index:
        with (
            connect(database_url) as connection,
            connection.transaction(),
            connection.cursor() as cursor,
        ):
            cursor.execute(query_text("SET LOCAL enable_seqscan = off"))
            cursor.execute(query_text(sql), params)
            row = cursor.fetchone()
    else:
        with connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(query_text(sql), params)
            row = cursor.fetchone()

    if row is None:
        raise RuntimeError("EXPLAIN did not return a plan.")

    plan = row[0]
    if not isinstance(plan, list) or not plan:
        raise TypeError("Expected EXPLAIN FORMAT JSON to return a non-empty list.")

    return summarize_search_plan(plan)


def iter_plan_nodes(plan_node: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    children = plan_node.get("Plans", [])
    if not isinstance(children, list):
        children = []

    nodes = [plan_node]
    for child in children:
        if isinstance(child, dict):
            nodes.extend(iter_plan_nodes(child))

    return tuple(nodes)


def summarize_search_plan(plan: list[dict[str, Any]]) -> SearchPlanSummary:
    if not plan:
        raise ValueError("EXPLAIN plan is empty.")

    root: dict[str, Any] = plan[0]
    plan_node = root["Plan"]
    if not isinstance(plan_node, dict):
        raise TypeError("Expected EXPLAIN root Plan to be an object.")

    nodes = iter_plan_nodes(plan_node)
    index_names = tuple(
        str(node["Index Name"]) for node in nodes if isinstance(node.get("Index Name"), str)
    )
    return SearchPlanSummary(
        root_node_type=str(plan_node["Node Type"]),
        planning_time_ms=float(root["Planning Time"]),
        execution_time_ms=float(root["Execution Time"]),
        index_names=index_names,
        shared_hit_blocks=sum(int(node.get("Shared Hit Blocks", 0)) for node in nodes),
        shared_read_blocks=sum(int(node.get("Shared Read Blocks", 0)) for node in nodes),
    )


def refresh_search_benchmark_corpus(
    *,
    symbols: Sequence[str] = DEFAULT_BENCHMARK_SYMBOLS,
    binance_limit: int = 500,
    bnb_log_limit: int = 25,
    database_url: str | None = None,
) -> tuple[tuple[BinanceCandleIngestionResult, ...], int, int, int]:
    normalized_symbols = normalize_symbols(symbols)
    if bnb_log_limit <= 0:
        raise ValueError("bnb_log_limit must be positive.")

    ensure_document_schema(database_url)
    binance_ingestions: list[BinanceCandleIngestionResult] = []
    binance_documents_upserted = 0
    for symbol in normalized_symbols:
        ingestion = fetch_and_store_binance_klines(
            symbol=symbol,
            interval="1m",
            limit=binance_limit,
            database_url=database_url,
        )
        binance_ingestions.append(ingestion)
        binance_documents_upserted += upsert_binance_documents(
            symbol=symbol,
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
    bnb_documents_upserted = upsert_bnb_log_documents(
        limit=bnb_log_limit,
        database_url=database_url,
    )
    projected_documents = refresh_search_documents(database_url)

    return (
        tuple(binance_ingestions),
        binance_documents_upserted,
        bnb_documents_upserted,
        projected_documents,
    )


def search_result_to_dict(result: SearchResultRow) -> dict[str, object]:
    return {
        "source": result.source,
        "external_id": result.external_id,
        "title": result.title,
        "score": str(result.score),
    }


def trigram_result_to_dict(result: TrigramResultRow) -> dict[str, object]:
    return {
        "source": result.source,
        "external_id": result.external_id,
        "fuzzy_key": result.fuzzy_key,
        "score": result.score,
    }


def search_plan_to_dict(plan: SearchPlanSummary) -> dict[str, object]:
    return {
        "root_node_type": plan.root_node_type,
        "planning_time_ms": plan.planning_time_ms,
        "execution_time_ms": plan.execution_time_ms,
        "index_names": list(plan.index_names),
        "shared_hit_blocks": plan.shared_hit_blocks,
        "shared_read_blocks": plan.shared_read_blocks,
    }


def runtime_to_dict(runtime: DatabaseRuntimeInfo) -> dict[str, object]:
    return {
        "server_version": runtime.server_version,
        "server_version_num": runtime.server_version_num,
        "extensions": [
            {"name": extension.name, "version": extension.version}
            for extension in runtime.extensions
        ],
    }


def build_search_benchmark_report(
    *,
    symbols: tuple[str, ...],
    binance_limit: int,
    bnb_log_limit: int,
    binance_ingestions: tuple[BinanceCandleIngestionResult, ...],
    binance_documents_upserted: int,
    bnb_documents_upserted: int,
    projected_documents: int,
    source_counts: tuple[tuple[str, int], ...],
    full_text_query: str,
    fuzzy_query: str,
    result_limit: int,
    full_text_results: tuple[SearchResultRow, ...],
    trigram_results: tuple[TrigramResultRow, ...],
    full_text_plan: SearchPlanSummary,
    trigram_plan: SearchPlanSummary,
    runtime: DatabaseRuntimeInfo,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated = generated_at or datetime.now(UTC)
    return {
        "title": "SearchDB Larger Corpus Benchmark",
        "slug": "search-document-benchmark",
        "generated_at": generated.isoformat(),
        "track": "Search DB / Full-Text and Trigram",
        "parameters": {
            "symbols": list(symbols),
            "binance_limit": binance_limit,
            "bnb_log_limit": bnb_log_limit,
            "full_text_query": full_text_query,
            "fuzzy_query": fuzzy_query,
            "result_limit": result_limit,
            "enable_seqscan": False,
        },
        "schema_files": ["sql/search/001_search_documents_schema.sql"],
        "ingestion": {
            "binance_rows_fetched": sum(item.rows_fetched for item in binance_ingestions),
            "binance_rows_upserted": sum(item.rows_upserted for item in binance_ingestions),
            "binance_documents_upserted": binance_documents_upserted,
            "bnb_documents_upserted": bnb_documents_upserted,
            "projected_documents": projected_documents,
        },
        "dataset_sizes": dict(source_counts),
        "queries": {
            "full_text": FULL_TEXT_SEARCH_SQL,
            "trigram": TRIGRAM_SEARCH_SQL,
        },
        "results": {
            "full_text": [search_result_to_dict(result) for result in full_text_results],
            "trigram": [trigram_result_to_dict(result) for result in trigram_results],
        },
        "plan_summary": {
            "full_text": search_plan_to_dict(full_text_plan),
            "trigram": search_plan_to_dict(trigram_plan),
        },
        "postgresql": runtime_to_dict(runtime),
        "interpretation": (
            "This benchmark grows the SearchDB corpus with real Binance public "
            "klines across multiple symbols and keeps the BNB PancakeSwap log "
            "projection in the same table. EXPLAIN runs set enable_seqscan=off "
            "to capture index-probe evidence for the GIN full-text and trigram "
            "indexes; absolute timings on a local corpus should not be treated "
            "as production latency claims."
        ),
    }


def markdown_cell(value: object) -> str:
    return str(value).replace("\n", " ").replace("|", "\\|")


def build_search_benchmark_markdown(report: dict[str, Any]) -> str:
    parameters = report["parameters"]
    ingestion = report["ingestion"]
    plan_summary = report["plan_summary"]
    lines = [
        f"# {report['title']}",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Track: `{report['track']}`",
        f"- Symbols: `{', '.join(parameters['symbols'])}`",
        f"- Binance limit: `{parameters['binance_limit']}`",
        f"- PostgreSQL: `{report['postgresql']['server_version']}`",
        "",
        "## Dataset",
        "",
    ]
    for name, value in ingestion.items():
        lines.append(f"- `{name}`: {value}")
    for source, row_count in report["dataset_sizes"].items():
        lines.append(f"- `search.search_documents[{source}]`: {row_count}")

    lines.extend(
        [
            "",
            "## Full-Text Results",
            "",
            f"- Query: `{parameters['full_text_query']}`",
            "",
            "| Source | Title | Rank | External ID |",
            "|---|---|---:|---|",
        ]
    )
    for result in report["results"]["full_text"]:
        lines.append(
            "| "
            f"`{markdown_cell(result['source'])}` | "
            f"{markdown_cell(result['title'])} | "
            f"`{markdown_cell(result['score'])}` | "
            f"`{markdown_cell(result['external_id'])}` |"
        )

    lines.extend(
        [
            "",
            "## Trigram Results",
            "",
            f"- Query: `{parameters['fuzzy_query']}`",
            "",
            "| Source | Fuzzy key | Similarity | External ID |",
            "|---|---|---:|---|",
        ]
    )
    for result in report["results"]["trigram"]:
        lines.append(
            "| "
            f"`{markdown_cell(result['source'])}` | "
            f"`{markdown_cell(result['fuzzy_key'])}` | "
            f"{float(result['score']):.6f} | "
            f"`{markdown_cell(result['external_id'])}` |"
        )

    lines.extend(
        [
            "",
            "## Plan Summary",
            "",
            "| Path | Root node | Index names | Planning ms | Execution ms | Shared hits |",
            "|---|---|---|---:|---:|---:|",
        ]
    )
    for path_name, plan in plan_summary.items():
        lines.append(
            "| "
            f"`{path_name}` | "
            f"`{plan['root_node_type']}` | "
            f"`{', '.join(plan['index_names'])}` | "
            f"{plan['planning_time_ms']} | "
            f"{plan['execution_time_ms']} | "
            f"{plan['shared_hit_blocks']} |"
        )

    lines.extend(
        [
            "",
            "## Query",
            "",
            "### Full-Text",
            "",
            "```sql",
            report["queries"]["full_text"].strip(),
            "```",
            "",
            "### Trigram",
            "",
            "```sql",
            report["queries"]["trigram"].strip(),
            "```",
            "",
            "## Interpretation",
            "",
            report["interpretation"],
            "",
        ]
    )
    return "\n".join(lines)


def json_default(value: object) -> str:
    if isinstance(value, Decimal | datetime | Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def write_search_benchmark_report(report: dict[str, Any], output_dir: Path) -> WrittenReport:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "search-document-benchmark.json"
    markdown_path = output_dir / "search-document-benchmark.md"

    json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, default=json_default),
        encoding="utf-8",
    )
    markdown_path.write_text(build_search_benchmark_markdown(report), encoding="utf-8")

    return WrittenReport(json_path=json_path, markdown_path=markdown_path)


def run_search_document_benchmark(
    *,
    symbols: Sequence[str] = DEFAULT_BENCHMARK_SYMBOLS,
    binance_limit: int = 500,
    bnb_log_limit: int = 25,
    full_text_query: str = "binance kline market candle",
    fuzzy_query: str = PANCAKESWAP_V2_WBNB_USDT_PAIR[:18],
    result_limit: int = 5,
    output_dir: Path | None = None,
    database_url: str | None = None,
) -> SearchDocumentBenchmarkResult:
    normalized_symbols = normalize_symbols(symbols)
    (
        binance_ingestions,
        binance_documents_upserted,
        bnb_documents_upserted,
        projected_documents,
    ) = refresh_search_benchmark_corpus(
        symbols=normalized_symbols,
        binance_limit=binance_limit,
        bnb_log_limit=bnb_log_limit,
        database_url=database_url,
    )
    source_counts = load_search_document_source_counts(database_url)
    full_text_results = load_full_text_results(
        query=full_text_query,
        limit=result_limit,
        database_url=database_url,
    )
    trigram_results = load_trigram_results(
        query=fuzzy_query,
        limit=result_limit,
        database_url=database_url,
    )
    full_text_plan = load_plan(
        sql=EXPLAIN_FULL_TEXT_SEARCH_SQL,
        params=(full_text_query, full_text_query, result_limit),
        force_index=True,
        database_url=database_url,
    )
    trigram_plan = load_plan(
        sql=EXPLAIN_TRIGRAM_SEARCH_SQL,
        params=(fuzzy_query, fuzzy_query, result_limit),
        force_index=True,
        database_url=database_url,
    )
    report = build_search_benchmark_report(
        symbols=normalized_symbols,
        binance_limit=binance_limit,
        bnb_log_limit=bnb_log_limit,
        binance_ingestions=binance_ingestions,
        binance_documents_upserted=binance_documents_upserted,
        bnb_documents_upserted=bnb_documents_upserted,
        projected_documents=projected_documents,
        source_counts=source_counts,
        full_text_query=full_text_query,
        fuzzy_query=fuzzy_query,
        result_limit=result_limit,
        full_text_results=full_text_results,
        trigram_results=trigram_results,
        full_text_plan=full_text_plan,
        trigram_plan=trigram_plan,
        runtime=load_runtime_info(database_url),
    )
    report_dir = output_dir or (default_generated_reports_dir() / "search")
    written = write_search_benchmark_report(report, report_dir)

    return SearchDocumentBenchmarkResult(
        symbols=normalized_symbols,
        binance_limit=binance_limit,
        bnb_log_limit=bnb_log_limit,
        binance_ingestions=binance_ingestions,
        binance_documents_upserted=binance_documents_upserted,
        bnb_documents_upserted=bnb_documents_upserted,
        projected_documents=projected_documents,
        source_counts=source_counts,
        full_text_query=full_text_query,
        fuzzy_query=fuzzy_query,
        full_text_results=full_text_results,
        trigram_results=trigram_results,
        full_text_plan=full_text_plan,
        trigram_plan=trigram_plan,
        report=written,
    )


def run_search_document_smoke(
    *,
    full_text_query: str = "pancakeswap swap",
    fuzzy_query: str = "0x16b9a82891338f9b",
    limit: int = 5,
    database_url: str | None = None,
) -> SearchDocumentSmokeResult:
    run_jsonb_document_smoke(database_url=database_url)
    projected_documents = refresh_search_documents(database_url)
    return SearchDocumentSmokeResult(
        projected_documents=projected_documents,
        full_text_results=load_full_text_results(
            query=full_text_query,
            limit=limit,
            database_url=database_url,
        ),
        trigram_results=load_trigram_results(
            query=fuzzy_query,
            limit=limit,
            database_url=database_url,
        ),
        full_text_plan=load_plan(
            sql=EXPLAIN_FULL_TEXT_SEARCH_SQL,
            params=(full_text_query, full_text_query, limit),
            database_url=database_url,
        ),
        trigram_plan=load_plan(
            sql=EXPLAIN_TRIGRAM_SEARCH_SQL,
            params=(fuzzy_query, fuzzy_query, limit),
            database_url=database_url,
        ),
    )
