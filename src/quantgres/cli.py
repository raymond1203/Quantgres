from argparse import ArgumentParser, Namespace
from collections.abc import Sequence

from quantgres import __version__
from quantgres.config import load_settings, mask_database_url
from quantgres.db import ping
from quantgres.experiments.binance_candles import (
    BinanceCandleIngestionResult,
    fetch_and_store_binance_klines,
)
from quantgres.experiments.bnb_block_timestamps import (
    BlockFetchPolicy,
    BnbBlockTimestampSmokeResult,
    run_bnb_block_timestamp_smoke,
)
from quantgres.experiments.bnb_raw_logs import BnbLogIngestionResult, fetch_and_store_bnb_logs
from quantgres.experiments.bnb_swap_projection import (
    PANCAKESWAP_SAMPLE_BLOCK,
    PANCAKESWAP_V2_SWAP_TOPIC0,
    PANCAKESWAP_V2_WBNB_USDT_PAIR,
    BnbSwapProjectionSmokeResult,
    run_bnb_swap_projection_smoke,
)
from quantgres.experiments.cache_summary import (
    DEFAULT_ONCHAIN_SUMMARY_KEY,
    CacheSummarySmokeResult,
    run_cache_summary_smoke,
)
from quantgres.experiments.embedding_comparison import (
    DEFAULT_FASTEMBED_MODEL,
    MODEL_VECTOR_INDEX_NAME,
    EmbeddingComparisonSmokeResult,
    run_embedding_comparison_smoke,
)
from quantgres.experiments.embedding_comparison import (
    run_vector_retrieval_benchmark as run_vector_retrieval_benchmark_report,
)
from quantgres.experiments.event_store import EventStoreSmokeResult, run_event_store_smoke
from quantgres.experiments.feature_batches import (
    BATCH_ASOF_INDEX_NAME,
    FeatureBatchSmokeResult,
    run_feature_batch_smoke,
)
from quantgres.experiments.feature_store import (
    ASOF_INDEX_NAME,
    FeatureStoreSmokeResult,
    run_feature_store_smoke,
)
from quantgres.experiments.hybrid_retrieval import (
    SEARCH_VECTOR_INDEX_NAME,
    TRIGRAM_INDEX_NAME,
    VECTOR_INDEX_NAME,
    HybridRetrievalSmokeResult,
    run_hybrid_retrieval_smoke,
)
from quantgres.experiments.jsonb_documents import (
    JsonbDocumentSmokeResult,
    run_jsonb_document_smoke,
)
from quantgres.experiments.jsonb_index_benchmark import (
    JsonbIndexBenchmarkResult,
    run_jsonb_index_benchmark,
)
from quantgres.experiments.olap_return_panel import (
    OlapReturnPanelSmokeResult,
    run_olap_return_panel_smoke,
)
from quantgres.experiments.queue_jobs import (
    QueueBenchmarkResult,
    QueueSmokeResult,
    QueueStaleLockSmokeResult,
    QueueWorkerSmokeResult,
    run_queue_benchmark_smoke,
    run_queue_smoke,
    run_queue_stale_lock_smoke,
    run_queue_worker_smoke,
)
from quantgres.experiments.rdb_ledger_benchmark import run_rdb_ledger_cash_balance_benchmark
from quantgres.experiments.rdb_paper_trace import (
    BinancePaperTraceSmokeResult,
    run_binance_paper_trace_smoke,
)
from quantgres.experiments.rdb_trading_ledger import TradingLedgerSmokeResult, run_smoke
from quantgres.experiments.search_documents import (
    FULL_TEXT_INDEX_NAME,
    SearchDocumentBenchmarkResult,
    SearchDocumentSmokeResult,
    run_search_document_benchmark,
    run_search_document_smoke,
)
from quantgres.experiments.search_documents import (
    TRIGRAM_INDEX_NAME as SEARCH_TRIGRAM_INDEX_NAME,
)
from quantgres.experiments.time_series_candles import CandleSmokeResult
from quantgres.experiments.time_series_candles import run_smoke as run_candle_smoke
from quantgres.experiments.vector_memory import (
    VectorMemorySmokeResult,
    run_vector_memory_smoke,
)
from quantgres.onchain.bnb_rpc import DEFAULT_BNB_RPC_URL, BnbRpcInfo, load_bnb_rpc_info
from quantgres.onchain.bnb_rpc import parse_block_arg as parse_bnb_block_arg
from quantgres.runtime import DatabaseRuntimeInfo, load_runtime_info


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(prog="quantgres")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command")

    doctor = subparsers.add_parser("doctor", help="Show local Quantgres configuration.")
    doctor.add_argument(
        "--check-db",
        action="store_true",
        help="Connect to PostgreSQL and print the server version.",
    )

    subparsers.add_parser(
        "db-info",
        help="Connect to PostgreSQL and print runtime and extension metadata.",
    )

    subparsers.add_parser(
        "rdb-ledger-smoke",
        help="Apply the RDB trading ledger fixture and verify core constraints.",
    )

    subparsers.add_parser(
        "benchmark-rdb-ledger",
        help="Generate the RDB trading ledger cash balance benchmark report.",
    )

    subparsers.add_parser(
        "time-series-candles-smoke",
        help="Apply the candle fixture and verify a symbol/time range query.",
    )

    ingest_binance = subparsers.add_parser(
        "ingest-binance-klines",
        help="Fetch public Binance Spot klines and upsert them into time_series.candles_1m.",
    )
    ingest_binance.add_argument("--symbol", default="BTCUSDT")
    ingest_binance.add_argument("--interval", default="1m")
    ingest_binance.add_argument("--limit", type=int, default=60)

    paper_trace = subparsers.add_parser(
        "binance-paper-trace-smoke",
        help="Fetch Binance klines and record a paper-only RDB decision trace.",
    )
    paper_trace.add_argument("--symbol", default="BTCUSDT")
    paper_trace.add_argument("--interval", default="1m")
    paper_trace.add_argument("--limit", type=int, default=60)

    bnb_info = subparsers.add_parser(
        "bnb-rpc-info",
        help="Call BNB Chain JSON-RPC and print chain id and latest block.",
    )
    bnb_info.add_argument("--rpc-url", default=DEFAULT_BNB_RPC_URL)

    ingest_bnb_logs = subparsers.add_parser(
        "ingest-bnb-logs",
        help="Fetch BNB Chain raw logs with eth_getLogs and store them as JSONB.",
    )
    ingest_bnb_logs.add_argument("--rpc-url", default=DEFAULT_BNB_RPC_URL)
    ingest_bnb_logs.add_argument("--from-block", required=True)
    ingest_bnb_logs.add_argument("--to-block", required=True)
    ingest_bnb_logs.add_argument("--address")
    ingest_bnb_logs.add_argument("--topic0")

    bnb_swap_projection = subparsers.add_parser(
        "bnb-swap-projection-smoke",
        help="Fetch BNB Chain Swap logs and project them into defi.swap_events.",
    )
    bnb_swap_projection.add_argument("--rpc-url", default=DEFAULT_BNB_RPC_URL)
    bnb_swap_projection.add_argument("--from-block", default=str(PANCAKESWAP_SAMPLE_BLOCK))
    bnb_swap_projection.add_argument("--to-block", default=str(PANCAKESWAP_SAMPLE_BLOCK))
    bnb_swap_projection.add_argument("--address", default=PANCAKESWAP_V2_WBNB_USDT_PAIR)
    bnb_swap_projection.add_argument("--topic0", default=PANCAKESWAP_V2_SWAP_TOPIC0)

    bnb_block_timestamp = subparsers.add_parser(
        "bnb-block-timestamp-smoke",
        help="Fetch BNB block timestamps and enrich projected swap events.",
    )
    bnb_block_timestamp.add_argument("--rpc-url", default=DEFAULT_BNB_RPC_URL)
    bnb_block_timestamp.add_argument("--from-block", default=str(PANCAKESWAP_SAMPLE_BLOCK))
    bnb_block_timestamp.add_argument("--to-block", default=str(PANCAKESWAP_SAMPLE_BLOCK))
    bnb_block_timestamp.add_argument("--address", default=PANCAKESWAP_V2_WBNB_USDT_PAIR)
    bnb_block_timestamp.add_argument("--topic0", default=PANCAKESWAP_V2_SWAP_TOPIC0)
    bnb_block_timestamp.add_argument("--block-fetch-attempts", type=int, default=3)
    bnb_block_timestamp.add_argument("--block-fetch-retry-sleep", type=float, default=0.25)

    jsonb_smoke = subparsers.add_parser(
        "jsonb-document-smoke",
        help="Store real Binance and BNB RPC payloads as JSONB documents and query them.",
    )
    jsonb_smoke.add_argument("--symbol", default="BTCUSDT")
    jsonb_smoke.add_argument("--document-limit", type=int, default=10)

    jsonb_index_benchmark = subparsers.add_parser(
        "benchmark-jsonb-indexes",
        help="Compare jsonb_ops and jsonb_path_ops GIN indexes on real JSONB payloads.",
    )
    jsonb_index_benchmark.add_argument("--symbol", default="BTCUSDT")
    jsonb_index_benchmark.add_argument("--binance-limit", type=int, default=500)

    search_smoke = subparsers.add_parser(
        "search-document-smoke",
        help="Project JSONB documents into a full-text/trigram search table and query them.",
    )
    search_smoke.add_argument("--query", default="pancakeswap swap")
    search_smoke.add_argument("--fuzzy", default="0x16b9a82891338f9b")
    search_smoke.add_argument("--limit", type=int, default=5)

    search_benchmark = subparsers.add_parser(
        "search-document-benchmark",
        help="Generate a larger-corpus SearchDB full-text/trigram benchmark report.",
    )
    search_benchmark.add_argument("--symbols", default="BTCUSDT,ETHUSDT,BNBUSDT")
    search_benchmark.add_argument("--binance-limit", type=int, default=500)
    search_benchmark.add_argument("--bnb-log-limit", type=int, default=25)
    search_benchmark.add_argument("--query", default="binance kline market candle")
    search_benchmark.add_argument("--fuzzy", default="0x16b9a82891338f9b")
    search_benchmark.add_argument("--limit", type=int, default=5)

    vector_memory = subparsers.add_parser(
        "vector-memory-smoke",
        help="Project real search documents into pgvector memory and run similarity search.",
    )
    vector_memory.add_argument("--query", default="pancakeswap swap bnb chain")
    vector_memory.add_argument("--source-limit", type=int, default=1000)
    vector_memory.add_argument("--limit", type=int, default=5)

    embedding_comparison = subparsers.add_parser(
        "embedding-comparison-smoke",
        help="Compare deterministic pgvector memory with real fastembed model retrieval.",
    )
    embedding_comparison.add_argument("--query", default="pancakeswap swap bnb chain")
    embedding_comparison.add_argument("--model-name", default=DEFAULT_FASTEMBED_MODEL)
    embedding_comparison.add_argument("--source-limit", type=int, default=100)
    embedding_comparison.add_argument("--limit", type=int, default=5)

    vector_retrieval_benchmark = subparsers.add_parser(
        "vector-retrieval-benchmark",
        help="Generate a VectorDB retrieval comparison benchmark report.",
    )
    vector_retrieval_benchmark.add_argument("--query", default="pancakeswap swap bnb chain")
    vector_retrieval_benchmark.add_argument("--model-name", default=DEFAULT_FASTEMBED_MODEL)
    vector_retrieval_benchmark.add_argument("--source-limit", type=int, default=100)
    vector_retrieval_benchmark.add_argument("--limit", type=int, default=5)

    cache_summary = subparsers.add_parser(
        "cache-summary-smoke",
        help="Refresh a materialized market/on-chain summary and compare cache lookup plans.",
    )
    cache_summary.add_argument("--symbol", default="BTCUSDT")
    cache_summary.add_argument("--binance-limit", type=int, default=500)
    cache_summary.add_argument("--summary-key", default=DEFAULT_ONCHAIN_SUMMARY_KEY)

    olap_panel = subparsers.add_parser(
        "olap-return-panel-smoke",
        help="Refresh an OLAP market return panel with on-chain aggregate metrics.",
    )
    olap_panel.add_argument("--symbol", default="BTCUSDT")
    olap_panel.add_argument("--binance-limit", type=int, default=500)
    olap_panel.add_argument("--limit", type=int, default=5)

    event_store = subparsers.add_parser(
        "event-store-smoke",
        help="Append real OLAP and vector retrieval results into an audit event store.",
    )
    event_store.add_argument("--query", default="pancakeswap swap bnb chain")

    feature_store = subparsers.add_parser(
        "feature-store-smoke",
        help="Build point-in-time quant feature snapshots and run an as-of lookup.",
    )
    feature_store.add_argument("--symbol", default="BTCUSDT")
    feature_store.add_argument("--feature-set", default="market_return_v1")
    feature_store.add_argument("--binance-limit", type=int, default=500)
    feature_store.add_argument("--source-limit", type=int, default=100)
    feature_store.add_argument("--as-of")

    feature_batch = subparsers.add_parser(
        "feature-batch-smoke",
        help="Write immutable point-in-time feature batch rows and run an as-of lookup.",
    )
    feature_batch.add_argument("--symbol", default="BTCUSDT")
    feature_batch.add_argument("--feature-set", default="market_return_v1")
    feature_batch.add_argument("--run-key", default="default")
    feature_batch.add_argument("--binance-limit", type=int, default=500)
    feature_batch.add_argument("--source-limit", type=int, default=50)

    hybrid_retrieval = subparsers.add_parser(
        "hybrid-retrieval-smoke",
        help="Combine SearchDB and VectorDB candidates into a hybrid ranked result.",
    )
    hybrid_retrieval.add_argument("--query", default="pancakeswap swap bnb chain")
    hybrid_retrieval.add_argument("--fuzzy", default="0x16b9a82891338f9b")
    hybrid_retrieval.add_argument("--source-limit", type=int, default=1000)
    hybrid_retrieval.add_argument("--candidate-limit", type=int, default=100)
    hybrid_retrieval.add_argument("--limit", type=int, default=5)

    subparsers.add_parser(
        "queue-smoke",
        help="Run a PostgreSQL SKIP LOCKED ingestion queue smoke test.",
    )

    queue_benchmark = subparsers.add_parser(
        "queue-benchmark-smoke",
        help="Benchmark multi-worker SKIP LOCKED queue claims.",
    )
    queue_benchmark.add_argument("--jobs", type=int, default=12)
    queue_benchmark.add_argument("--workers", type=int, default=4)
    queue_benchmark.add_argument("--run-key", default="default")

    queue_worker = subparsers.add_parser(
        "queue-worker-smoke",
        help="Claim QueueDB jobs and execute real ingestion payloads.",
    )
    queue_worker.add_argument("--run-key", default="default")
    queue_worker.add_argument("--worker-id", default="worker-exec-1")
    queue_worker.add_argument("--binance-limit", type=int, default=5)

    queue_stale_lock = subparsers.add_parser(
        "queue-stale-lock-smoke",
        help="Recover a stale running QueueDB job and let another worker reclaim it.",
    )
    queue_stale_lock.add_argument("--run-key", default="default")
    queue_stale_lock.add_argument("--stale-worker-id", default="worker-stale-1")
    queue_stale_lock.add_argument("--recovery-worker-id", default="worker-recovery-1")
    queue_stale_lock.add_argument("--stale-timeout-seconds", type=int, default=60)
    queue_stale_lock.add_argument("--stale-age-seconds", type=int, default=120)
    queue_stale_lock.add_argument("--binance-limit", type=int, default=5)

    return parser


def run_doctor(args: Namespace) -> int:
    settings = load_settings()
    print(f"Quantgres {__version__}")
    print(f"Environment: {settings.app_env}")
    print(f"Database URL: {mask_database_url(settings.database_url)}")

    if args.check_db:
        version = ping(settings.database_url)
        print(f"PostgreSQL: {version}")

    return 0


def format_runtime_info(info: DatabaseRuntimeInfo) -> list[str]:
    lines = [
        f"PostgreSQL: {info.server_version}",
        f"server_version_num: {info.server_version_num}",
        f"Database: {info.database_name}",
        f"User: {info.user_name}",
        "Extensions:",
    ]

    if info.extensions:
        lines.extend(f"- {extension.name}: {extension.version}" for extension in info.extensions)
    else:
        lines.append("- none")

    missing_extensions = info.missing_extensions()
    if missing_extensions:
        lines.append(f"Missing required extensions: {', '.join(missing_extensions)}")

    return lines


def run_db_info() -> int:
    info = load_runtime_info()
    for line in format_runtime_info(info):
        print(line)

    if info.missing_extensions():
        return 1

    return 0


def format_trading_ledger_smoke(result: TradingLedgerSmokeResult) -> list[str]:
    lines = ["RDB Trading Ledger Smoke"]

    lines.append("Positions:")
    for position in result.positions:
        lines.append(
            "- "
            f"{position.account_code} {position.strategy_code} {position.symbol} "
            f"quantity={position.quantity} "
            f"average_entry_price={position.average_entry_price} "
            f"market_price={position.market_price} "
            f"unrealized_pnl={position.unrealized_pnl}"
        )

    lines.append("Cash balances:")
    for balance in result.cash_balances:
        lines.append(
            f"- {balance.account_code} {balance.currency} cash_balance={balance.cash_balance}"
        )

    lines.append("Constraint checks:")
    for check in result.constraint_checks:
        status = "passed" if check.passed else "failed"
        lines.append(f"- {check.name}: {status} {check.error_type}".rstrip())

    return lines


def run_rdb_ledger_smoke() -> int:
    result = run_smoke()
    for line in format_trading_ledger_smoke(result):
        print(line)

    if not result.passed:
        return 1

    return 0


def run_benchmark_rdb_ledger() -> int:
    report = run_rdb_ledger_cash_balance_benchmark()
    print(f"JSON report: {report.json_path}")
    print(f"Markdown report: {report.markdown_path}")
    return 0


def format_candle_smoke(result: CandleSmokeResult) -> list[str]:
    summary = result.summary
    plan = result.plan
    return [
        "Time-Series Candles Smoke",
        (
            f"Summary: symbol={summary.symbol} "
            f"candle_count={summary.candle_count} "
            f"first_ts={summary.first_ts} "
            f"last_ts={summary.last_ts} "
            f"vwap={summary.vwap}"
        ),
        (
            f"Plan: root_node={plan.root_node_type} "
            f"planning_time_ms={plan.planning_time_ms} "
            f"execution_time_ms={plan.execution_time_ms}"
        ),
    ]


def run_time_series_candles_smoke() -> int:
    result = run_candle_smoke()
    for line in format_candle_smoke(result):
        print(line)

    if result.summary.candle_count != 60:
        return 1

    return 0


def format_binance_ingestion(result: BinanceCandleIngestionResult) -> list[str]:
    return [
        "Binance Kline Ingestion",
        f"Source: {result.source}",
        f"Symbol: {result.symbol}",
        f"Interval: {result.interval}",
        f"Rows fetched: {result.rows_fetched}",
        f"Rows upserted: {result.rows_upserted}",
        f"First timestamp: {result.first_ts}",
        f"Last timestamp: {result.last_ts}",
    ]


def run_ingest_binance_klines(args: Namespace) -> int:
    result = fetch_and_store_binance_klines(
        symbol=args.symbol,
        interval=args.interval,
        limit=args.limit,
    )
    for line in format_binance_ingestion(result):
        print(line)

    if result.rows_fetched == 0:
        return 1

    return 0


def format_binance_paper_trace(result: BinancePaperTraceSmokeResult) -> list[str]:
    trace = result.trace
    return [
        "Binance Paper Trace Smoke",
        f"Rows fetched: {result.rows_fetched}",
        f"Rows upserted: {result.rows_upserted}",
        (
            f"Decision: client_order_id={trace.client_order_id} "
            f"symbol={trace.symbol} "
            f"side={trace.side} "
            f"decision_at={trace.decision_at}"
        ),
        (
            f"Signal: previous_close={trace.previous_close} "
            f"latest_close={trace.latest_close} "
            f"return_bps={trace.return_bps}"
        ),
        (
            f"Paper execution: quantity={trace.quantity} "
            f"trade_notional={trace.trade_notional} "
            f"cash_delta={trace.cash_delta} "
            f"fee_amount={trace.fee_amount}"
        ),
    ]


def run_binance_paper_trace(args: Namespace) -> int:
    result = run_binance_paper_trace_smoke(
        symbol=args.symbol,
        interval=args.interval,
        limit=args.limit,
    )
    for line in format_binance_paper_trace(result):
        print(line)

    if result.rows_fetched < 2:
        return 1

    return 0


def format_bnb_rpc_info(info: BnbRpcInfo) -> list[str]:
    return [
        "BNB Chain RPC Info",
        f"RPC URL: {info.rpc_url}",
        f"Chain ID: {info.chain_id}",
        f"Latest block: {info.latest_block_number}",
    ]


def run_bnb_rpc_info(args: Namespace) -> int:
    info = load_bnb_rpc_info(rpc_url=args.rpc_url)
    for line in format_bnb_rpc_info(info):
        print(line)

    return 0


def format_bnb_log_ingestion(result: BnbLogIngestionResult) -> list[str]:
    return [
        "BNB Chain Raw Log Ingestion",
        f"RPC URL: {result.rpc_url}",
        f"Chain ID: {result.chain_id}",
        f"Range: {result.from_block}..{result.to_block}",
        f"Address: {result.address}",
        f"Topic0: {result.topic0}",
        f"Rows fetched: {result.rows_fetched}",
        f"Rows upserted: {result.rows_upserted}",
    ]


def run_ingest_bnb_logs(args: Namespace) -> int:
    result = fetch_and_store_bnb_logs(
        rpc_url=args.rpc_url,
        from_block=parse_bnb_block_arg(args.from_block),
        to_block=parse_bnb_block_arg(args.to_block),
        address=args.address,
        topic0=args.topic0,
    )
    for line in format_bnb_log_ingestion(result):
        print(line)

    return 0


def format_bnb_swap_projection(result: BnbSwapProjectionSmokeResult) -> list[str]:
    lines = [
        "BNB Swap Projection Smoke",
        f"RPC URL: {result.ingestion.rpc_url}",
        f"Raw logs fetched: {result.ingestion.rows_fetched}",
        f"Raw logs upserted: {result.ingestion.rows_upserted}",
        f"Projected events: {result.projected_events}",
        "Sample events:",
    ]
    lines.extend(
        (
            f"- block={event.block_number} "
            f"tx={event.transaction_hash} "
            f"log_index={event.log_index} "
            f"sender={event.sender} "
            f"recipient={event.recipient} "
            f"amount0_in={event.amount0_in} "
            f"amount1_in={event.amount1_in} "
            f"amount0_out={event.amount0_out} "
            f"amount1_out={event.amount1_out}"
        )
        for event in result.sample_events
    )
    return lines


def run_bnb_swap_projection(args: Namespace) -> int:
    result = run_bnb_swap_projection_smoke(
        rpc_url=args.rpc_url,
        from_block=parse_bnb_block_arg(args.from_block),
        to_block=parse_bnb_block_arg(args.to_block),
        pair_address=args.address,
        topic0=args.topic0,
    )
    for line in format_bnb_swap_projection(result):
        print(line)

    if result.projected_events == 0 or not result.sample_events:
        return 1

    return 0


def format_bnb_block_timestamp(result: BnbBlockTimestampSmokeResult) -> list[str]:
    lines = [
        "BNB Block Timestamp Smoke",
        f"Raw logs fetched: {result.swap_projection.ingestion.rows_fetched}",
        f"Projected swaps: {result.swap_projection.projected_events}",
        f"Requested blocks: {len(result.requested_block_numbers)}",
        f"Cached blocks: {len(result.cached_block_numbers)}",
        f"Missing blocks: {len(result.missing_block_numbers)}",
        f"Fetched missing blocks: {len(result.fetched_blocks)}",
        f"Upserted blocks: {result.upserted_blocks}",
        f"Updated swaps: {result.updated_swaps}",
        f"Stored blocks: {result.stored_blocks}",
        f"Enriched swaps: {result.enriched_swaps}",
        "Fetched blocks:",
    ]
    lines.extend(
        (f"- block={block.block_number} timestamp={block.block_timestamp} hash={block.block_hash}")
        for block in result.fetched_blocks
    )
    lines.append("Sample enriched swaps:")
    lines.extend(
        (
            f"- block={event.block_number} "
            f"timestamp={event.block_timestamp} "
            f"tx={event.transaction_hash} "
            f"log_index={event.log_index}"
        )
        for event in result.sample_events
    )
    return lines


def run_bnb_block_timestamp(args: Namespace) -> int:
    result = run_bnb_block_timestamp_smoke(
        rpc_url=args.rpc_url,
        from_block=parse_bnb_block_arg(args.from_block),
        to_block=parse_bnb_block_arg(args.to_block),
        pair_address=args.address,
        topic0=args.topic0,
        block_fetch_policy=BlockFetchPolicy(
            max_attempts=args.block_fetch_attempts,
            retry_sleep_seconds=args.block_fetch_retry_sleep,
        ),
    )
    for line in format_bnb_block_timestamp(result):
        print(line)

    if not result.requested_block_numbers or result.stored_blocks == 0:
        return 1
    if result.enriched_swaps == 0 or not result.sample_events:
        return 1

    return 0


def format_jsonb_document_smoke(result: JsonbDocumentSmokeResult) -> list[str]:
    lines = [
        "JSONB Document Store Smoke",
        f"Binance documents upserted: {result.binance_documents_upserted}",
        f"BNB documents upserted: {result.bnb_documents_upserted}",
        "Source counts:",
    ]
    lines.extend(f"- {source}: {count}" for source, count in result.source_counts)
    lines.extend(
        [
            f"BNB containment count: {result.bnb_containment_count}",
            (
                f"Plan: root_node={result.plan.root_node_type} "
                f"planning_time_ms={result.plan.planning_time_ms} "
                f"execution_time_ms={result.plan.execution_time_ms}"
            ),
        ]
    )
    return lines


def run_jsonb_documents(args: Namespace) -> int:
    result = run_jsonb_document_smoke(
        symbol=args.symbol,
        document_limit=args.document_limit,
    )
    for line in format_jsonb_document_smoke(result):
        print(line)

    if result.bnb_containment_count == 0:
        return 1

    return 0


def format_jsonb_index_benchmark(result: JsonbIndexBenchmarkResult) -> list[str]:
    lines = [
        "JSONB GIN Operator Class Benchmark",
        f"Query: {result.query_name}",
        f"Containment filter: {result.containment_filter}",
        "Comparisons:",
    ]
    lines.extend(
        (
            f"- {comparison.opclass}: "
            f"rows={comparison.table_rows} "
            f"matches={comparison.matched_rows} "
            f"index_size={comparison.index_size_pretty} "
            f"root_node={comparison.plan.root_node_type} "
            f"indexes={','.join(comparison.plan.index_names)} "
            f"execution_time_ms={comparison.plan.execution_time_ms}"
        )
        for comparison in result.comparisons
    )
    lines.extend(
        [
            f"JSON report: {result.report.json_path}",
            f"Markdown report: {result.report.markdown_path}",
        ]
    )
    return lines


def run_benchmark_jsonb_indexes(args: Namespace) -> int:
    result = run_jsonb_index_benchmark(
        symbol=args.symbol,
        binance_limit=args.binance_limit,
    )
    for line in format_jsonb_index_benchmark(result):
        print(line)

    if any(comparison.matched_rows == 0 for comparison in result.comparisons):
        return 1

    return 0


def format_search_document_smoke(result: SearchDocumentSmokeResult) -> list[str]:
    lines = [
        "Search Document Smoke",
        f"Projected documents: {result.projected_documents}",
        "Full-text results:",
    ]
    lines.extend(f"- {row.source} {row.title} rank={row.score}" for row in result.full_text_results)
    lines.append("Trigram results:")
    lines.extend(
        f"- {row.source} {row.fuzzy_key} similarity={row.score}" for row in result.trigram_results
    )
    lines.extend(
        [
            (
                f"Full-text plan: root_node={result.full_text_plan.root_node_type} "
                f"planning_time_ms={result.full_text_plan.planning_time_ms} "
                f"execution_time_ms={result.full_text_plan.execution_time_ms}"
            ),
            (
                f"Trigram plan: root_node={result.trigram_plan.root_node_type} "
                f"planning_time_ms={result.trigram_plan.planning_time_ms} "
                f"execution_time_ms={result.trigram_plan.execution_time_ms}"
            ),
        ]
    )
    return lines


def run_search_documents(args: Namespace) -> int:
    result = run_search_document_smoke(
        full_text_query=args.query,
        fuzzy_query=args.fuzzy,
        limit=args.limit,
    )
    for line in format_search_document_smoke(result):
        print(line)

    if not result.full_text_results or not result.trigram_results:
        return 1

    return 0


def parse_symbol_list(value: str) -> tuple[str, ...]:
    symbols = tuple(symbol.strip().upper() for symbol in value.split(",") if symbol.strip())
    if not symbols:
        raise ValueError("At least one symbol is required.")
    return symbols


def format_search_document_benchmark(result: SearchDocumentBenchmarkResult) -> list[str]:
    return [
        "SearchDB Larger Corpus Benchmark",
        f"Symbols: {','.join(result.symbols)}",
        f"Binance limit: {result.binance_limit}",
        f"Binance rows fetched: {sum(item.rows_fetched for item in result.binance_ingestions)}",
        f"Binance documents upserted: {result.binance_documents_upserted}",
        f"BNB documents upserted: {result.bnb_documents_upserted}",
        f"Projected documents: {result.projected_documents}",
        f"Source counts: {dict(result.source_counts)}",
        f"Full-text results: {len(result.full_text_results)}",
        f"Trigram results: {len(result.trigram_results)}",
        f"Full-text indexes: {','.join(result.full_text_plan.index_names)}",
        f"Trigram indexes: {','.join(result.trigram_plan.index_names)}",
        f"JSON report: {result.report.json_path}",
        f"Markdown report: {result.report.markdown_path}",
    ]


def run_search_benchmark(args: Namespace) -> int:
    result = run_search_document_benchmark(
        symbols=parse_symbol_list(args.symbols),
        binance_limit=args.binance_limit,
        bnb_log_limit=args.bnb_log_limit,
        full_text_query=args.query,
        fuzzy_query=args.fuzzy,
        result_limit=args.limit,
    )
    for line in format_search_document_benchmark(result):
        print(line)

    if not result.full_text_results:
        return 1
    if not result.trigram_results:
        return 1
    if FULL_TEXT_INDEX_NAME not in result.full_text_plan.index_names:
        return 1
    if SEARCH_TRIGRAM_INDEX_NAME not in result.trigram_plan.index_names:
        return 1

    return 0


def format_vector_memory_smoke(result: VectorMemorySmokeResult) -> list[str]:
    lines = [
        "Vector Memory Smoke",
        f"Projected chunks: {result.projected_chunks}",
        f"Total chunks: {result.total_chunks}",
        f"Query: {result.query_text}",
        "Similarity results:",
    ]
    lines.extend(
        (
            f"- {row.source} {row.title} "
            f"similarity={row.cosine_similarity:.6f} "
            f"external_id={row.external_id}"
        )
        for row in result.results
    )
    lines.extend(
        [
            (
                f"Plan: root_node={result.plan.root_node_type} "
                f"indexes={','.join(result.plan.index_names)} "
                f"planning_time_ms={result.plan.planning_time_ms} "
                f"execution_time_ms={result.plan.execution_time_ms}"
            )
        ]
    )
    return lines


def run_vector_memory(args: Namespace) -> int:
    result = run_vector_memory_smoke(
        query=args.query,
        source_limit=args.source_limit,
        result_limit=args.limit,
    )
    for line in format_vector_memory_smoke(result):
        print(line)

    if not result.results:
        return 1

    return 0


def format_embedding_comparison_smoke(result: EmbeddingComparisonSmokeResult) -> list[str]:
    lines = [
        "Embedding Comparison Smoke",
        f"Model: {result.embedding_model}",
        f"Embedding dimensions: {result.embedding_dimensions}",
        f"Projected model chunks: {result.projected_model_chunks}",
        f"Total model chunks: {result.total_model_chunks}",
        f"Query: {result.query_text}",
        (
            f"Top overlap: {result.top_overlap_count}/"
            f"{len(result.deterministic_results)} deterministic results"
        ),
        "Deterministic hash results:",
    ]
    lines.extend(
        (
            f"- {row.source} {row.title} "
            f"similarity={row.cosine_similarity:.6f} "
            f"external_id={row.external_id}"
        )
        for row in result.deterministic_results
    )
    lines.append("Real embedding results:")
    lines.extend(
        (
            f"- {row.source} {row.title} "
            f"similarity={row.cosine_similarity:.6f} "
            f"external_id={row.external_id}"
        )
        for row in result.model_results
    )
    lines.append(
        f"Plan: root_node={result.plan.root_node_type} "
        f"indexes={','.join(result.plan.index_names)} "
        f"planning_time_ms={result.plan.planning_time_ms} "
        f"execution_time_ms={result.plan.execution_time_ms}"
    )
    return lines


def run_embedding_comparison(args: Namespace) -> int:
    result = run_embedding_comparison_smoke(
        query=args.query,
        model_name=args.model_name,
        source_limit=args.source_limit,
        result_limit=args.limit,
    )
    for line in format_embedding_comparison_smoke(result):
        print(line)

    if not result.model_results:
        return 1
    if MODEL_VECTOR_INDEX_NAME not in result.plan.index_names:
        return 1

    return 0


def run_vector_retrieval_benchmark(args: Namespace) -> int:
    result = run_vector_retrieval_benchmark_report(
        query=args.query,
        model_name=args.model_name,
        source_limit=args.source_limit,
        result_limit=args.limit,
    )
    print(f"JSON report: {result.report.json_path}")
    print(f"Markdown report: {result.report.markdown_path}")

    if not result.comparison.model_results:
        return 1
    if MODEL_VECTOR_INDEX_NAME not in result.comparison.plan.index_names:
        return 1

    return 0


def format_cache_summary_smoke(result: CacheSummarySmokeResult) -> list[str]:
    summary = result.selected_summary
    metrics = summary.metrics
    return [
        "Cache Summary Smoke",
        f"Binance rows fetched: {result.binance_ingestion.rows_fetched}",
        f"Swap events projected: {result.swap_projection.projected_events}",
        f"Materialized rows: {result.refreshed_rows}",
        (
            f"Selected summary: key={summary.summary_key} "
            f"kind={summary.summary_kind} "
            f"latest_observed_at={summary.latest_observed_at}"
        ),
        f"Metrics: {metrics}",
        (
            f"Base plan: root_node={result.base_plan.root_node_type} "
            f"indexes={','.join(result.base_plan.index_names)} "
            f"planning_time_ms={result.base_plan.planning_time_ms} "
            f"execution_time_ms={result.base_plan.execution_time_ms}"
        ),
        (
            f"Cache plan: root_node={result.cache_plan.root_node_type} "
            f"indexes={','.join(result.cache_plan.index_names)} "
            f"planning_time_ms={result.cache_plan.planning_time_ms} "
            f"execution_time_ms={result.cache_plan.execution_time_ms}"
        ),
    ]


def run_cache_summary(args: Namespace) -> int:
    result = run_cache_summary_smoke(
        symbol=args.symbol,
        binance_limit=args.binance_limit,
        summary_key=args.summary_key,
    )
    for line in format_cache_summary_smoke(result):
        print(line)

    if result.refreshed_rows == 0:
        return 1

    return 0


def format_olap_return_panel_smoke(result: OlapReturnPanelSmokeResult) -> list[str]:
    lines = [
        "OLAP Return Panel Smoke",
        f"Binance rows fetched: {result.binance_ingestion.rows_fetched}",
        f"Swap events projected: {result.swap_projection.projected_events}",
        f"Panel rows: {result.panel_rows}",
        "Latest rows:",
    ]
    lines.extend(
        (
            f"- {row.symbol} ts={row.ts} "
            f"close={row.close_price} "
            f"return_bps={row.return_bps} "
            f"rolling_5_return_bps={row.rolling_5_return_bps} "
            f"swap_count={row.swap_count}"
        )
        for row in result.latest_rows
    )
    lines.append(
        f"Plan: root_node={result.plan.root_node_type} "
        f"indexes={','.join(result.plan.index_names)} "
        f"planning_time_ms={result.plan.planning_time_ms} "
        f"execution_time_ms={result.plan.execution_time_ms}"
    )
    return lines


def run_olap_return_panel(args: Namespace) -> int:
    result = run_olap_return_panel_smoke(
        symbol=args.symbol,
        binance_limit=args.binance_limit,
        result_limit=args.limit,
    )
    for line in format_olap_return_panel_smoke(result):
        print(line)

    if result.panel_rows == 0 or not result.latest_rows:
        return 1

    return 0


def format_event_store_smoke(result: EventStoreSmokeResult) -> list[str]:
    lines = [
        "Event Store Smoke",
        f"Inserted events: {result.inserted_events}",
        f"Skipped events: {result.skipped_events}",
        f"Payload match count: {result.payload_match_count}",
        "Subject events:",
    ]
    lines.extend(
        (
            f"- {row.event_type} subject={row.subject_type}:{row.subject_id} "
            f"occurred_at={row.occurred_at} event_id={row.event_id}"
        )
        for row in result.subject_events
    )
    lines.extend(
        [
            (
                f"Subject plan: root_node={result.subject_plan.root_node_type} "
                f"indexes={','.join(result.subject_plan.index_names)} "
                f"planning_time_ms={result.subject_plan.planning_time_ms} "
                f"execution_time_ms={result.subject_plan.execution_time_ms}"
            ),
            (
                f"Payload plan: root_node={result.payload_plan.root_node_type} "
                f"indexes={','.join(result.payload_plan.index_names)} "
                f"planning_time_ms={result.payload_plan.planning_time_ms} "
                f"execution_time_ms={result.payload_plan.execution_time_ms}"
            ),
        ]
    )
    return lines


def run_event_store(args: Namespace) -> int:
    result = run_event_store_smoke(query=args.query)
    for line in format_event_store_smoke(result):
        print(line)

    if result.inserted_events == 0 and result.skipped_events == 0:
        return 1
    if not result.subject_events or result.payload_match_count == 0:
        return 1

    return 0


def format_feature_store_smoke(result: FeatureStoreSmokeResult) -> list[str]:
    feature = result.as_of_feature
    return [
        "Feature Store Smoke",
        f"Binance rows fetched: {result.olap_result.binance_ingestion.rows_fetched}",
        f"OLAP panel rows: {result.olap_result.panel_rows}",
        f"Feature set: {result.feature_set}",
        f"Source rows: {result.source_rows}",
        f"Upserted snapshots: {result.upserted_snapshots}",
        f"Total snapshots: {result.total_snapshots}",
        f"As of: {result.as_of_ts}",
        (
            f"Feature: symbol={feature.symbol} "
            f"event_ts={feature.event_ts} "
            f"feature_ts={feature.feature_ts} "
            f"close={feature.close_price} "
            f"return_bps={feature.return_bps} "
            f"rolling_5_return_bps={feature.rolling_5_return_bps} "
            f"swap_count={feature.swap_count}"
        ),
        (
            f"Plan: root_node={result.plan.root_node_type} "
            f"indexes={','.join(result.plan.index_names)} "
            f"planning_time_ms={result.plan.planning_time_ms} "
            f"execution_time_ms={result.plan.execution_time_ms}"
        ),
    ]


def run_feature_store(args: Namespace) -> int:
    result = run_feature_store_smoke(
        symbol=args.symbol,
        feature_set=args.feature_set,
        binance_limit=args.binance_limit,
        source_limit=args.source_limit,
        as_of_ts=args.as_of,
    )
    for line in format_feature_store_smoke(result):
        print(line)

    if result.upserted_snapshots == 0 or result.total_snapshots == 0:
        return 1
    if ASOF_INDEX_NAME not in result.plan.index_names:
        return 1

    return 0


def format_feature_batch_smoke(result: FeatureBatchSmokeResult) -> list[str]:
    item = result.as_of_item
    return [
        "Feature Batch Smoke",
        f"Batch id: {result.batch_id}",
        f"Feature set: {result.feature_set}",
        f"Config hash: {result.config_hash}",
        f"Code hash: {result.code_hash}",
        f"Dependency hash: {result.dependency_hash}",
        f"Runtime hash: {result.runtime_hash}",
        f"Source rows: {result.source_rows}",
        f"Inserted batch: {result.inserted_batch}",
        f"Inserted items: {result.inserted_items}",
        f"Total batch items: {result.total_batch_items}",
        f"As of: {result.as_of_ts}",
        (
            f"Feature: symbol={item.symbol} "
            f"event_ts={item.event_ts} "
            f"feature_ts={item.feature_ts} "
            f"close={item.close_price} "
            f"return_bps={item.return_bps} "
            f"rolling_5_return_bps={item.rolling_5_return_bps} "
            f"swap_count={item.swap_count}"
        ),
        (
            f"Plan: root_node={result.plan.root_node_type} "
            f"indexes={','.join(result.plan.index_names)} "
            f"planning_time_ms={result.plan.planning_time_ms} "
            f"execution_time_ms={result.plan.execution_time_ms}"
        ),
    ]


def run_feature_batch(args: Namespace) -> int:
    result = run_feature_batch_smoke(
        symbol=args.symbol,
        feature_set=args.feature_set,
        run_key=args.run_key,
        binance_limit=args.binance_limit,
        source_limit=args.source_limit,
    )
    for line in format_feature_batch_smoke(result):
        print(line)

    if result.total_batch_items == 0:
        return 1
    if BATCH_ASOF_INDEX_NAME not in result.plan.index_names:
        return 1

    return 0


def format_hybrid_retrieval_smoke(result: HybridRetrievalSmokeResult) -> list[str]:
    lines = [
        "Hybrid Retrieval Smoke",
        f"Projected chunks: {result.vector_projection.projected_chunks}",
        f"Total chunks: {result.vector_projection.total_chunks}",
        f"Query: {result.query}",
        f"Fuzzy query: {result.fuzzy_query}",
        f"Candidate limit: {result.candidate_limit}",
        "Results:",
    ]
    lines.extend(
        (
            f"- {row.source} {row.title} "
            f"hybrid_score={row.hybrid_score:.6f} "
            f"text_rank={row.text_rank:.6f} "
            f"trigram_similarity={row.trigram_similarity:.6f} "
            f"vector_similarity={row.vector_similarity:.6f} "
            f"external_id={row.external_id}"
        )
        for row in result.results
    )
    lines.append(
        f"Plan: root_node={result.plan.root_node_type} "
        f"indexes={','.join(result.plan.index_names)} "
        f"planning_time_ms={result.plan.planning_time_ms} "
        f"execution_time_ms={result.plan.execution_time_ms}"
    )
    return lines


def run_hybrid_retrieval(args: Namespace) -> int:
    result = run_hybrid_retrieval_smoke(
        query=args.query,
        fuzzy_query=args.fuzzy,
        source_limit=args.source_limit,
        candidate_limit=args.candidate_limit,
        result_limit=args.limit,
    )
    for line in format_hybrid_retrieval_smoke(result):
        print(line)

    if not result.results:
        return 1

    search_indexes = {SEARCH_VECTOR_INDEX_NAME, TRIGRAM_INDEX_NAME}
    if VECTOR_INDEX_NAME not in result.plan.index_names:
        return 1
    if not search_indexes.intersection(result.plan.index_names):
        return 1

    return 0


def format_queue_smoke(result: QueueSmokeResult) -> list[str]:
    lines = [
        "QueueDB Smoke",
        (
            f"First claim: worker={result.first_claim.locked_by} "
            f"job={result.first_claim.idempotency_key} "
            f"attempts={result.first_claim.attempts}"
        ),
        (
            f"Second claim: worker={result.second_claim.locked_by} "
            f"job={result.second_claim.idempotency_key} "
            f"attempts={result.second_claim.attempts}"
        ),
        (
            f"Retry claim: worker={result.retry_claim.locked_by} "
            f"job={result.retry_claim.idempotency_key} "
            f"attempts={result.retry_claim.attempts}"
        ),
        "Final statuses:",
    ]
    lines.extend(
        (
            f"- {status.idempotency_key} status={status.status} "
            f"attempts={status.attempts}/{status.max_attempts} "
            f"last_error={status.last_error}"
        )
        for status in result.statuses
    )
    return lines


def run_queue_jobs() -> int:
    result = run_queue_smoke()
    for line in format_queue_smoke(result):
        print(line)

    statuses = {status.idempotency_key: status.status for status in result.statuses}
    if statuses.get("binance:BTCUSDT:1m:60") != "completed":
        return 1
    if statuses.get("bnb:pancakeswap-v2-wbnb-usdt:swap:107270817") != "dead_letter":
        return 1

    return 0


def format_queue_benchmark(result: QueueBenchmarkResult) -> list[str]:
    lines = [
        "QueueDB Multi-Worker Benchmark",
        f"Jobs seeded: {result.job_count}",
        f"Workers: {result.worker_count}",
        f"Claimed jobs: {result.claimed_count}",
        f"Unique claimed jobs: {result.unique_claimed_count}",
        f"Duplicate claims: {result.duplicate_claim_count}",
        f"Completed jobs: {result.completed_count}",
        f"Elapsed ms: {result.elapsed_ms:.3f}",
        "Claims:",
    ]
    lines.extend(
        (
            f"- worker={claim.worker_id} "
            f"job_id={claim.job_id} "
            f"priority={claim.priority} "
            f"idempotency_key={claim.idempotency_key}"
        )
        for claim in result.claims
    )
    return lines


def run_queue_benchmark(args: Namespace) -> int:
    result = run_queue_benchmark_smoke(
        job_count=args.jobs,
        worker_count=args.workers,
        run_key=args.run_key,
    )
    for line in format_queue_benchmark(result):
        print(line)

    expected_claims = min(result.job_count, result.worker_count)
    if result.claimed_count != expected_claims:
        return 1
    if result.duplicate_claim_count != 0:
        return 1
    if result.completed_count < result.claimed_count:
        return 1

    return 0


def format_queue_worker_smoke(result: QueueWorkerSmokeResult) -> list[str]:
    lines = [
        "QueueDB Worker Smoke",
        f"Run key: {result.run_key}",
        f"Worker: {result.worker_id}",
        f"Seeded jobs: {result.seeded_jobs}",
        f"Executions: {len(result.executions)}",
        "Executed jobs:",
    ]
    lines.extend(
        (
            f"- {execution.job_kind} "
            f"status={execution.final_status} "
            f"attempts={execution.attempts} "
            f"idempotency_key={execution.idempotency_key} "
            f"summary={execution.summary}"
        )
        for execution in result.executions
    )
    lines.append("Final statuses:")
    lines.extend(
        (
            f"- {status.job_kind} "
            f"status={status.status} "
            f"attempts={status.attempts}/{status.max_attempts} "
            f"idempotency_key={status.idempotency_key} "
            f"last_error={status.last_error}"
        )
        for status in result.statuses
    )
    return lines


def run_queue_worker(args: Namespace) -> int:
    result = run_queue_worker_smoke(
        run_key=args.run_key,
        worker_id=args.worker_id,
        binance_limit=args.binance_limit,
    )
    for line in format_queue_worker_smoke(result):
        print(line)

    if len(result.executions) != result.seeded_jobs:
        return 1
    if any(status.status != "completed" for status in result.statuses):
        return 1

    return 0


def format_queue_stale_lock_smoke(result: QueueStaleLockSmokeResult) -> list[str]:
    lines = [
        "QueueDB Stale Lock Smoke",
        f"Run key: {result.run_key}",
        f"Stale worker: {result.stale_worker_id}",
        f"Recovery worker: {result.recovery_worker_id}",
        f"Stale timeout seconds: {result.stale_timeout_seconds}",
        (
            f"First claim: job={result.first_claim.idempotency_key} "
            f"attempts={result.first_claim.attempts}/{result.first_claim.max_attempts} "
            f"locked_by={result.first_claim.locked_by}"
        ),
        f"Heartbeat updated: {result.heartbeat_updated}",
        f"Recovered jobs: {len(result.recovered_jobs)}",
    ]
    lines.extend(
        (
            f"- {job.idempotency_key} "
            f"status={job.status} "
            f"attempts={job.attempts}/{job.max_attempts} "
            f"locked_by={job.locked_by} "
            f"last_error={job.last_error}"
        )
        for job in result.recovered_jobs
    )
    lines.extend(
        [
            (
                f"Reclaimed job: {result.reclaimed_job.idempotency_key} "
                f"attempts={result.reclaimed_job.attempts}/"
                f"{result.reclaimed_job.max_attempts} "
                f"locked_by={result.reclaimed_job.locked_by}"
            ),
            (
                f"Reclaimed execution: status={result.reclaimed_execution.final_status} "
                f"summary={result.reclaimed_execution.summary}"
            ),
            "Final statuses:",
        ]
    )
    lines.extend(
        (
            f"- {status.idempotency_key} "
            f"status={status.status} "
            f"attempts={status.attempts}/{status.max_attempts} "
            f"locked_by={status.locked_by} "
            f"last_error={status.last_error}"
        )
        for status in result.statuses
    )
    return lines


def run_queue_stale_lock(args: Namespace) -> int:
    result = run_queue_stale_lock_smoke(
        run_key=args.run_key,
        stale_worker_id=args.stale_worker_id,
        recovery_worker_id=args.recovery_worker_id,
        stale_timeout_seconds=args.stale_timeout_seconds,
        stale_age_seconds=args.stale_age_seconds,
        binance_limit=args.binance_limit,
    )
    for line in format_queue_stale_lock_smoke(result):
        print(line)

    if not result.heartbeat_updated:
        return 1
    if not result.recovered_jobs:
        return 1
    if result.reclaimed_job.job_id != result.first_claim.job_id:
        return 1
    if result.reclaimed_execution.final_status != "completed":
        return 1

    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "doctor":
        return run_doctor(args)

    if args.command == "db-info":
        return run_db_info()

    if args.command == "rdb-ledger-smoke":
        return run_rdb_ledger_smoke()

    if args.command == "benchmark-rdb-ledger":
        return run_benchmark_rdb_ledger()

    if args.command == "time-series-candles-smoke":
        return run_time_series_candles_smoke()

    if args.command == "ingest-binance-klines":
        return run_ingest_binance_klines(args)

    if args.command == "binance-paper-trace-smoke":
        return run_binance_paper_trace(args)

    if args.command == "bnb-rpc-info":
        return run_bnb_rpc_info(args)

    if args.command == "ingest-bnb-logs":
        return run_ingest_bnb_logs(args)

    if args.command == "bnb-swap-projection-smoke":
        return run_bnb_swap_projection(args)

    if args.command == "bnb-block-timestamp-smoke":
        return run_bnb_block_timestamp(args)

    if args.command == "jsonb-document-smoke":
        return run_jsonb_documents(args)

    if args.command == "benchmark-jsonb-indexes":
        return run_benchmark_jsonb_indexes(args)

    if args.command == "search-document-smoke":
        return run_search_documents(args)

    if args.command == "search-document-benchmark":
        return run_search_benchmark(args)

    if args.command == "vector-memory-smoke":
        return run_vector_memory(args)

    if args.command == "embedding-comparison-smoke":
        return run_embedding_comparison(args)

    if args.command == "vector-retrieval-benchmark":
        return run_vector_retrieval_benchmark(args)

    if args.command == "cache-summary-smoke":
        return run_cache_summary(args)

    if args.command == "olap-return-panel-smoke":
        return run_olap_return_panel(args)

    if args.command == "event-store-smoke":
        return run_event_store(args)

    if args.command == "feature-store-smoke":
        return run_feature_store(args)

    if args.command == "feature-batch-smoke":
        return run_feature_batch(args)

    if args.command == "hybrid-retrieval-smoke":
        return run_hybrid_retrieval(args)

    if args.command == "queue-smoke":
        return run_queue_jobs()

    if args.command == "queue-benchmark-smoke":
        return run_queue_benchmark(args)

    if args.command == "queue-worker-smoke":
        return run_queue_worker(args)

    if args.command == "queue-stale-lock-smoke":
        return run_queue_stale_lock(args)

    parser.print_help()
    return 0
