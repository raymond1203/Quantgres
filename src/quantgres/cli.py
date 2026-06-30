from argparse import ArgumentParser, Namespace
from collections.abc import Sequence

from quantgres import __version__
from quantgres.config import load_settings, mask_database_url
from quantgres.db import ping
from quantgres.experiments.rdb_ledger_benchmark import run_rdb_ledger_cash_balance_benchmark
from quantgres.experiments.rdb_trading_ledger import TradingLedgerSmokeResult, run_smoke
from quantgres.experiments.time_series_candles import CandleSmokeResult
from quantgres.experiments.time_series_candles import run_smoke as run_candle_smoke
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

    parser.print_help()
    return 0
