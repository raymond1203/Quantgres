import json
from datetime import UTC, datetime

from quantgres.experiments.bnb_block_timestamps import EnrichedSwapEventRow
from quantgres.experiments.bnb_raw_logs import BnbLogWindowResult, BnbWindowedLogIngestionResult
from quantgres.experiments.bnb_swap_corpus import (
    BnbSwapCorpusSmokeResult,
    build_bnb_swap_corpus_markdown,
    build_bnb_swap_corpus_report,
    write_bnb_swap_corpus_report,
)
from quantgres.onchain.bnb_rpc import BnbBlock
from quantgres.reports import WrittenReport
from quantgres.runtime import DatabaseRuntimeInfo, ExtensionStatus


def make_corpus_result(tmp_path) -> BnbSwapCorpusSmokeResult:
    windowed_ingestion = BnbWindowedLogIngestionResult(
        rpc_url="https://example.invalid",
        chain_id=56,
        from_block=100,
        to_block=120,
        address="0x16b9a82891338f9ba80e2d6970fdda79d1eb0dae",
        topic0="0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822",
        window_size=10,
        windows=(
            BnbLogWindowResult(
                from_block=100,
                to_block=109,
                rows_fetched=2,
                rows_upserted=2,
            ),
            BnbLogWindowResult(
                from_block=110,
                to_block=119,
                rows_fetched=3,
                rows_upserted=3,
            ),
            BnbLogWindowResult(
                from_block=120,
                to_block=120,
                rows_fetched=1,
                rows_upserted=1,
            ),
        ),
    )
    return BnbSwapCorpusSmokeResult(
        windowed_ingestion=windowed_ingestion,
        projected_events=6,
        requested_block_numbers=(100, 110, 120),
        cached_block_numbers=(100,),
        missing_block_numbers=(110, 120),
        fetched_blocks=(
            BnbBlock(
                chain_id=56,
                rpc_url="https://example.invalid",
                block_number=110,
                block_hash="0xblock",
                parent_hash="0xparent",
                block_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                raw_block={"number": "0x6e"},
            ),
        ),
        upserted_blocks=2,
        updated_swaps=6,
        enriched_swaps=6,
        sample_events=(
            EnrichedSwapEventRow(
                chain_id=56,
                dex="pancakeswap_v2",
                pair_address="0x16b9a82891338f9ba80e2d6970fdda79d1eb0dae",
                block_number=110,
                block_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                transaction_hash="0xtx",
                log_index=1,
            ),
        ),
        report=WrittenReport(
            json_path=tmp_path / "pending.json",
            markdown_path=tmp_path / "pending.md",
        ),
    )


def test_build_bnb_swap_corpus_report_records_windowed_counts(tmp_path):
    result = make_corpus_result(tmp_path)
    runtime = DatabaseRuntimeInfo(
        server_version="PostgreSQL 18.4 on test",
        server_version_num=180004,
        database_name="quantgres",
        user_name="quantgres",
        extensions=(ExtensionStatus(name="vector", version="0.8.3"),),
    )

    report = build_bnb_swap_corpus_report(
        result=result,
        runtime=runtime,
        generated_at=datetime(2026, 1, 2, tzinfo=UTC),
    )

    assert report["ingestion"]["window_count"] == 3
    assert report["ingestion"]["rows_fetched"] == 6
    assert report["projection"]["projected_events"] == 6
    assert report["projection"]["enriched_swaps"] == 6
    assert report["postgresql"]["server_version_num"] == 180004


def test_write_bnb_swap_corpus_report_creates_json_and_markdown(tmp_path):
    result = make_corpus_result(tmp_path)
    runtime = DatabaseRuntimeInfo(
        server_version="PostgreSQL 18.4 on test",
        server_version_num=180004,
        database_name="quantgres",
        user_name="quantgres",
        extensions=(),
    )
    report = build_bnb_swap_corpus_report(result=result, runtime=runtime)

    written = write_bnb_swap_corpus_report(report, tmp_path)

    persisted = json.loads(written.json_path.read_text(encoding="utf-8"))
    markdown = written.markdown_path.read_text(encoding="utf-8")
    assert persisted["slug"] == "bnb-swap-corpus"
    assert persisted["ingestion"]["rows_upserted"] == 6
    assert "# BNB Swap Corpus Windowed Ingestion" in markdown
    assert "## Projection" in markdown
    assert build_bnb_swap_corpus_markdown(report) == markdown
