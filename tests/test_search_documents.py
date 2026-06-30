from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from quantgres.experiments.binance_candles import BinanceCandleIngestionResult
from quantgres.experiments.search_documents import (
    FULL_TEXT_INDEX_NAME,
    TRIGRAM_INDEX_NAME,
    SearchPlanSummary,
    SearchResultRow,
    TrigramResultRow,
    build_search_benchmark_markdown,
    build_search_benchmark_report,
    normalize_symbols,
    summarize_search_plan,
    write_search_benchmark_report,
)
from quantgres.runtime import DatabaseRuntimeInfo, ExtensionStatus


def test_normalize_symbols_deduplicates_and_uppercases():
    assert normalize_symbols(("btcusdt", " ETHUSDT ", "BTCUSDT")) == (
        "BTCUSDT",
        "ETHUSDT",
    )


def test_normalize_symbols_rejects_empty_input():
    with pytest.raises(ValueError, match="At least one symbol"):
        normalize_symbols((" ", ""))


def test_summarize_search_plan_extracts_index_names_and_buffers():
    plan = [
        {
            "Plan": {
                "Node Type": "Limit",
                "Plans": [
                    {
                        "Node Type": "Bitmap Index Scan",
                        "Index Name": FULL_TEXT_INDEX_NAME,
                        "Shared Hit Blocks": 3,
                        "Shared Read Blocks": 1,
                    }
                ],
            },
            "Planning Time": 0.1,
            "Execution Time": 0.2,
        }
    ]

    summary = summarize_search_plan(plan)

    assert summary.index_names == (FULL_TEXT_INDEX_NAME,)
    assert summary.shared_hit_blocks == 3
    assert summary.shared_read_blocks == 1


def build_runtime_info() -> DatabaseRuntimeInfo:
    return DatabaseRuntimeInfo(
        server_version="PostgreSQL 18.4 on test",
        server_version_num=180004,
        database_name="quantgres",
        user_name="quantgres",
        extensions=(
            ExtensionStatus(name="pg_trgm", version="1.6"),
            ExtensionStatus(name="vector", version="0.8.3"),
        ),
    )


def build_report() -> dict[str, Any]:
    ingestion = BinanceCandleIngestionResult(
        symbol="BTCUSDT",
        interval="1m",
        source="binance_spot_klines",
        rows_fetched=200,
        rows_upserted=200,
        first_ts=datetime(2026, 1, 1, tzinfo=UTC),
        last_ts=datetime(2026, 1, 1, 3, 19, tzinfo=UTC),
    )
    return build_search_benchmark_report(
        symbols=("BTCUSDT",),
        binance_limit=200,
        bnb_log_limit=25,
        binance_ingestions=(ingestion,),
        binance_documents_upserted=200,
        bnb_documents_upserted=2,
        projected_documents=202,
        source_counts=(("binance_kline", 200), ("bnb_rpc_log", 2)),
        full_text_query="binance kline market candle",
        fuzzy_query="0x16b9a82891338f9b",
        result_limit=5,
        full_text_results=(
            SearchResultRow(
                "binance_kline", "BTCUSDT:1", "BTCUSDT Binance 1m kline", Decimal("0.1")
            ),
        ),
        trigram_results=(TrigramResultRow("bnb_rpc_log", "56:tx:1", "0x16b9a82891338f9b", 0.9),),
        full_text_plan=SearchPlanSummary(
            root_node_type="Limit",
            planning_time_ms=0.1,
            execution_time_ms=0.2,
            index_names=(FULL_TEXT_INDEX_NAME,),
        ),
        trigram_plan=SearchPlanSummary(
            root_node_type="Limit",
            planning_time_ms=0.1,
            execution_time_ms=0.2,
            index_names=(TRIGRAM_INDEX_NAME,),
        ),
        runtime=build_runtime_info(),
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_build_search_benchmark_report_includes_dataset_and_plan():
    report = build_report()

    assert report["title"] == "SearchDB Larger Corpus Benchmark"
    assert report["ingestion"]["binance_rows_fetched"] == 200
    assert report["dataset_sizes"]["binance_kline"] == 200
    assert report["plan_summary"]["full_text"]["index_names"] == [FULL_TEXT_INDEX_NAME]
    assert report["plan_summary"]["trigram"]["index_names"] == [TRIGRAM_INDEX_NAME]


def test_build_search_benchmark_markdown_includes_required_sections():
    markdown = build_search_benchmark_markdown(build_report())

    assert "## Dataset" in markdown
    assert "## Full-Text Results" in markdown
    assert "## Trigram Results" in markdown
    assert FULL_TEXT_INDEX_NAME in markdown
    assert TRIGRAM_INDEX_NAME in markdown


def test_write_search_benchmark_report_creates_json_and_markdown(tmp_path: Path):
    written = write_search_benchmark_report(build_report(), tmp_path)

    assert written.json_path.exists()
    assert written.markdown_path.exists()
    assert "SearchDB Larger Corpus Benchmark" in written.markdown_path.read_text(encoding="utf-8")
