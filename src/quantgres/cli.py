from argparse import ArgumentParser, Namespace
from collections.abc import Sequence

from quantgres import __version__
from quantgres.config import load_settings, mask_database_url
from quantgres.db import ping
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "doctor":
        return run_doctor(args)

    if args.command == "db-info":
        return run_db_info()

    parser.print_help()
    return 0
