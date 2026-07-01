import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from quantgres.experiments.bnb_block_timestamps import (
    BlockFetchPolicy,
    EnrichedSwapEventRow,
    count_enriched_swaps,
    enrich_swap_event_timestamps,
    fetch_blocks,
    load_cached_block_numbers,
    load_enriched_swaps,
    load_swap_block_numbers,
    select_missing_block_numbers,
    upsert_blocks,
)
from quantgres.experiments.bnb_raw_logs import (
    BnbWindowedLogIngestionResult,
    fetch_and_store_bnb_logs_windowed,
)
from quantgres.experiments.bnb_swap_projection import (
    PANCAKESWAP_SAMPLE_BLOCK,
    PANCAKESWAP_V2,
    PANCAKESWAP_V2_SWAP_TOPIC0,
    PANCAKESWAP_V2_WBNB_USDT_PAIR,
    load_raw_swap_logs,
    upsert_swap_events,
)
from quantgres.onchain.bnb_rpc import DEFAULT_BNB_RPC_URL, BnbBlock
from quantgres.reports import WrittenReport, default_generated_reports_dir
from quantgres.runtime import DatabaseRuntimeInfo, load_runtime_info

DEFAULT_CORPUS_FROM_BLOCK = PANCAKESWAP_SAMPLE_BLOCK - 100
DEFAULT_CORPUS_TO_BLOCK = PANCAKESWAP_SAMPLE_BLOCK
DEFAULT_CORPUS_WINDOW_SIZE = 10


@dataclass(frozen=True)
class BnbSwapCorpusSmokeResult:
    windowed_ingestion: BnbWindowedLogIngestionResult
    projected_events: int
    requested_block_numbers: tuple[int, ...]
    cached_block_numbers: tuple[int, ...]
    missing_block_numbers: tuple[int, ...]
    fetched_blocks: tuple[BnbBlock, ...]
    upserted_blocks: int
    updated_swaps: int
    enriched_swaps: int
    sample_events: tuple[EnrichedSwapEventRow, ...]
    report: WrittenReport


def window_result_to_dict(result: BnbWindowedLogIngestionResult) -> dict[str, object]:
    return {
        "rpc_url": result.rpc_url,
        "chain_id": result.chain_id,
        "from_block": result.from_block,
        "to_block": result.to_block,
        "address": result.address,
        "topic0": result.topic0,
        "window_size": result.window_size,
        "window_count": len(result.windows),
        "rows_fetched": result.rows_fetched,
        "rows_upserted": result.rows_upserted,
        "windows": [
            {
                "from_block": window.from_block,
                "to_block": window.to_block,
                "rows_fetched": window.rows_fetched,
                "rows_upserted": window.rows_upserted,
            }
            for window in result.windows
        ],
    }


def block_to_dict(block: BnbBlock) -> dict[str, object]:
    return {
        "chain_id": block.chain_id,
        "block_number": block.block_number,
        "block_hash": block.block_hash,
        "parent_hash": block.parent_hash,
        "block_timestamp": block.block_timestamp,
    }


def enriched_event_to_dict(event: EnrichedSwapEventRow) -> dict[str, object]:
    return {
        "chain_id": event.chain_id,
        "dex": event.dex,
        "pair_address": event.pair_address,
        "block_number": event.block_number,
        "block_timestamp": event.block_timestamp,
        "transaction_hash": event.transaction_hash,
        "log_index": event.log_index,
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


def build_bnb_swap_corpus_report(
    *,
    result: BnbSwapCorpusSmokeResult,
    runtime: DatabaseRuntimeInfo,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated = generated_at or datetime.now(UTC)
    ingestion = result.windowed_ingestion
    return {
        "title": "BNB Swap Corpus Windowed Ingestion",
        "slug": "bnb-swap-corpus",
        "generated_at": generated.isoformat(),
        "track": "On-chain / BNB Chain Raw Logs",
        "parameters": {
            "from_block": ingestion.from_block,
            "to_block": ingestion.to_block,
            "window_size": ingestion.window_size,
            "address": ingestion.address,
            "topic0": ingestion.topic0,
        },
        "schema_files": [
            "sql/onchain/001_raw_logs_schema.sql",
            "sql/defi/001_swap_events_schema.sql",
            "sql/onchain/002_blocks_schema.sql",
        ],
        "ingestion": window_result_to_dict(ingestion),
        "projection": {
            "projected_events": result.projected_events,
            "requested_block_count": len(result.requested_block_numbers),
            "cached_block_count": len(result.cached_block_numbers),
            "missing_block_count": len(result.missing_block_numbers),
            "fetched_block_count": len(result.fetched_blocks),
            "upserted_blocks": result.upserted_blocks,
            "updated_swaps": result.updated_swaps,
            "enriched_swaps": result.enriched_swaps,
        },
        "requested_block_numbers": list(result.requested_block_numbers),
        "cached_block_numbers": list(result.cached_block_numbers),
        "missing_block_numbers": list(result.missing_block_numbers),
        "fetched_blocks": [block_to_dict(block) for block in result.fetched_blocks],
        "sample_events": [enriched_event_to_dict(event) for event in result.sample_events],
        "postgresql": runtime_to_dict(runtime),
        "interpretation": (
            "This smoke expands the BNB Chain PancakeSwap swap corpus by calling "
            "eth_getLogs in small block windows. The windowing is intentional: the "
            "default public RPC accepts narrow log ranges but rejects larger single "
            "range calls. The report records raw log ingestion, typed swap projection, "
            "and block timestamp enrichment so downstream SearchDB, VectorDB, OLAP, "
            "Event Store, and Feature Store experiments can use a larger on-chain "
            "corpus without relying on Dune or an external indexer."
        ),
    }


def build_bnb_swap_corpus_markdown(report: dict[str, Any]) -> str:
    parameters = report["parameters"]
    ingestion = report["ingestion"]
    projection = report["projection"]
    lines = [
        f"# {report['title']}",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Track: `{report['track']}`",
        f"- Block range: `{parameters['from_block']}..{parameters['to_block']}`",
        f"- Window size: `{parameters['window_size']}`",
        f"- Address: `{parameters['address']}`",
        f"- Topic0: `{parameters['topic0']}`",
        f"- PostgreSQL: `{report['postgresql']['server_version']}`",
        "",
        "## Ingestion",
        "",
        f"- Window count: `{ingestion['window_count']}`",
        f"- Rows fetched: `{ingestion['rows_fetched']}`",
        f"- Rows upserted: `{ingestion['rows_upserted']}`",
        "",
        "| From block | To block | Rows fetched | Rows upserted |",
        "|---:|---:|---:|---:|",
    ]
    for window in ingestion["windows"]:
        lines.append(
            "| "
            f"{window['from_block']} | "
            f"{window['to_block']} | "
            f"{window['rows_fetched']} | "
            f"{window['rows_upserted']} |"
        )

    lines.extend(
        [
            "",
            "## Projection",
            "",
            f"- Projected swap events: `{projection['projected_events']}`",
            f"- Requested block count: `{projection['requested_block_count']}`",
            f"- Cached block count: `{projection['cached_block_count']}`",
            f"- Missing block count: `{projection['missing_block_count']}`",
            f"- Fetched block count: `{projection['fetched_block_count']}`",
            f"- Upserted blocks: `{projection['upserted_blocks']}`",
            f"- Updated swaps: `{projection['updated_swaps']}`",
            f"- Enriched swaps: `{projection['enriched_swaps']}`",
            "",
            "## Sample Events",
            "",
            "| Block | Timestamp | Transaction | Log index |",
            "|---:|---|---|---:|",
        ]
    )
    for event in report["sample_events"]:
        lines.append(
            "| "
            f"{event['block_number']} | "
            f"`{event['block_timestamp']}` | "
            f"`{event['transaction_hash']}` | "
            f"{event['log_index']} |"
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


def json_default(value: object) -> str:
    if isinstance(value, Decimal | datetime | Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def write_bnb_swap_corpus_report(report: dict[str, Any], output_dir: Path) -> WrittenReport:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "bnb-swap-corpus.json"
    markdown_path = output_dir / "bnb-swap-corpus.md"
    json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, default=json_default),
        encoding="utf-8",
    )
    markdown_path.write_text(build_bnb_swap_corpus_markdown(report), encoding="utf-8")
    return WrittenReport(json_path=json_path, markdown_path=markdown_path)


def run_bnb_swap_corpus_smoke(
    *,
    from_block: int = DEFAULT_CORPUS_FROM_BLOCK,
    to_block: int = DEFAULT_CORPUS_TO_BLOCK,
    window_size: int = DEFAULT_CORPUS_WINDOW_SIZE,
    pair_address: str = PANCAKESWAP_V2_WBNB_USDT_PAIR,
    topic0: str = PANCAKESWAP_V2_SWAP_TOPIC0,
    rpc_url: str = DEFAULT_BNB_RPC_URL,
    block_fetch_policy: BlockFetchPolicy | None = None,
    result_limit: int = 5,
    output_dir: Path | None = None,
    database_url: str | None = None,
) -> BnbSwapCorpusSmokeResult:
    windowed_ingestion = fetch_and_store_bnb_logs_windowed(
        from_block=from_block,
        to_block=to_block,
        window_size=window_size,
        address=pair_address,
        topic0=topic0,
        rpc_url=rpc_url,
        database_url=database_url,
    )
    raw_logs = load_raw_swap_logs(
        from_block=from_block,
        to_block=to_block,
        pair_address=pair_address,
        topic0=topic0,
        chain_id=windowed_ingestion.chain_id,
        database_url=database_url,
    )
    projected_events = upsert_swap_events(
        raw_logs,
        dex=PANCAKESWAP_V2,
        topic0=topic0,
        database_url=database_url,
    )
    block_numbers = load_swap_block_numbers(
        from_block=from_block,
        to_block=to_block,
        chain_id=windowed_ingestion.chain_id,
        pair_address=pair_address,
        database_url=database_url,
    )
    requested_block_set = set(block_numbers)
    cached_block_numbers = tuple(
        block_number
        for block_number in load_cached_block_numbers(
            from_block=from_block,
            to_block=to_block,
            chain_id=windowed_ingestion.chain_id,
            database_url=database_url,
        )
        if block_number in requested_block_set
    )
    missing_block_numbers = select_missing_block_numbers(
        requested_block_numbers=block_numbers,
        cached_block_numbers=cached_block_numbers,
    )
    fetched_blocks = fetch_blocks(
        block_numbers=missing_block_numbers,
        rpc_url=rpc_url,
        chain_id=windowed_ingestion.chain_id,
        policy=block_fetch_policy,
    )
    upserted_blocks = upsert_blocks(fetched_blocks, database_url)
    updated_swaps = enrich_swap_event_timestamps(
        from_block=from_block,
        to_block=to_block,
        chain_id=windowed_ingestion.chain_id,
        pair_address=pair_address,
        database_url=database_url,
    )
    enriched_swaps = count_enriched_swaps(
        from_block=from_block,
        to_block=to_block,
        chain_id=windowed_ingestion.chain_id,
        pair_address=pair_address,
        database_url=database_url,
    )
    sample_events = load_enriched_swaps(
        from_block=from_block,
        to_block=to_block,
        chain_id=windowed_ingestion.chain_id,
        pair_address=pair_address,
        limit=result_limit,
        database_url=database_url,
    )

    report_dir = output_dir or (default_generated_reports_dir() / "onchain")
    result_without_report = BnbSwapCorpusSmokeResult(
        windowed_ingestion=windowed_ingestion,
        projected_events=projected_events,
        requested_block_numbers=block_numbers,
        cached_block_numbers=cached_block_numbers,
        missing_block_numbers=missing_block_numbers,
        fetched_blocks=fetched_blocks,
        upserted_blocks=upserted_blocks,
        updated_swaps=updated_swaps,
        enriched_swaps=enriched_swaps,
        sample_events=sample_events,
        report=WrittenReport(
            json_path=report_dir / "pending.json",
            markdown_path=report_dir / "pending.md",
        ),
    )
    report = build_bnb_swap_corpus_report(
        result=result_without_report,
        runtime=load_runtime_info(database_url),
    )
    written = write_bnb_swap_corpus_report(report, report_dir)

    return BnbSwapCorpusSmokeResult(
        windowed_ingestion=windowed_ingestion,
        projected_events=projected_events,
        requested_block_numbers=block_numbers,
        cached_block_numbers=cached_block_numbers,
        missing_block_numbers=missing_block_numbers,
        fetched_blocks=fetched_blocks,
        upserted_blocks=upserted_blocks,
        updated_swaps=updated_swaps,
        enriched_swaps=enriched_swaps,
        sample_events=sample_events,
        report=written,
    )
