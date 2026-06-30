from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import psycopg

from quantgres.db import connect, query_text

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SQL_DIR = PROJECT_ROOT / "sql" / "rdb"

SCHEMA_SQL = SQL_DIR / "001_trading_ledger_schema.sql"
FIXTURE_SQL = SQL_DIR / "002_trading_ledger_fixture.sql"


@dataclass(frozen=True)
class PositionRow:
    account_code: str
    strategy_code: str
    symbol: str
    quantity: Decimal
    average_entry_price: Decimal
    market_price: Decimal
    unrealized_pnl: Decimal


@dataclass(frozen=True)
class CashBalanceRow:
    account_code: str
    currency: str
    cash_balance: Decimal


@dataclass(frozen=True)
class ConstraintCheck:
    name: str
    passed: bool
    error_type: str


@dataclass(frozen=True)
class TradingLedgerSmokeResult:
    positions: tuple[PositionRow, ...]
    cash_balances: tuple[CashBalanceRow, ...]
    constraint_checks: tuple[ConstraintCheck, ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.constraint_checks)


def read_sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def apply_schema_and_fixture(database_url: str | None = None) -> None:
    with connect(database_url) as connection:
        connection.execute(query_text(read_sql(SCHEMA_SQL)))
        connection.execute(query_text(read_sql(FIXTURE_SQL)))


def load_positions(database_url: str | None = None) -> tuple[PositionRow, ...]:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                account_code,
                strategy_code,
                symbol,
                quantity,
                average_entry_price,
                market_price,
                (market_price - average_entry_price) * quantity AS unrealized_pnl
            FROM rdb.position_snapshots
            WHERE (account_code, strategy_code, symbol, snapshot_at) IN (
                SELECT
                    account_code,
                    strategy_code,
                    symbol,
                    max(snapshot_at)
                FROM rdb.position_snapshots
                WHERE account_code IN ('A1', 'A2')
                GROUP BY account_code, strategy_code, symbol
            )
            ORDER BY account_code, symbol
            """
        )
        rows = cursor.fetchall()

    return tuple(
        PositionRow(
            account_code=str(row[0]),
            strategy_code=str(row[1]),
            symbol=str(row[2]),
            quantity=row[3],
            average_entry_price=row[4],
            market_price=row[5],
            unrealized_pnl=row[6],
        )
        for row in rows
    )


def load_cash_balances(database_url: str | None = None) -> tuple[CashBalanceRow, ...]:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                account_code,
                currency,
                sum(amount) AS cash_balance
            FROM rdb.cash_ledger_entries
            WHERE account_code IN ('A1', 'A2')
            GROUP BY account_code, currency
            ORDER BY account_code, currency
            """
        )
        rows = cursor.fetchall()

    return tuple(
        CashBalanceRow(
            account_code=str(row[0]),
            currency=str(row[1]),
            cash_balance=row[2],
        )
        for row in rows
    )


def statement_is_rejected(sql: str, database_url: str | None = None) -> tuple[bool, str]:
    with connect(database_url) as connection:
        try:
            connection.execute(query_text(sql))
        except psycopg.Error as error:
            connection.rollback()
            return True, error.__class__.__name__

        connection.rollback()
        return False, ""


def run_constraint_checks(database_url: str | None = None) -> tuple[ConstraintCheck, ...]:
    checks = {
        "negative order quantity": """
            INSERT INTO rdb.orders (
                client_order_id,
                account_code,
                strategy_code,
                symbol,
                side,
                order_type,
                quantity,
                limit_price,
                status,
                created_at,
                updated_at
            )
            VALUES (
                concat('INVALID-NEGATIVE-QUANTITY-', extract(epoch from clock_timestamp())::text),
                'A1',
                'mean_reversion_v1',
                'BTCUSDT',
                'buy',
                'limit',
                -1,
                60000,
                'new',
                now(),
                now()
            )
        """,
        "limit order requires positive limit price": """
            INSERT INTO rdb.orders (
                client_order_id,
                account_code,
                strategy_code,
                symbol,
                side,
                order_type,
                quantity,
                limit_price,
                status,
                created_at,
                updated_at
            )
            VALUES (
                concat('INVALID-LIMIT-PRICE-', extract(epoch from clock_timestamp())::text),
                'A1',
                'mean_reversion_v1',
                'BTCUSDT',
                'buy',
                'limit',
                1,
                NULL,
                'new',
                now(),
                now()
            )
        """,
        "duplicate client order id": """
            INSERT INTO rdb.orders (
                client_order_id,
                account_code,
                strategy_code,
                symbol,
                side,
                order_type,
                quantity,
                limit_price,
                status,
                created_at,
                updated_at
            )
            VALUES (
                'A1-MR-BTC-0001',
                'A1',
                'mean_reversion_v1',
                'BTCUSDT',
                'buy',
                'limit',
                1,
                60000,
                'new',
                now(),
                now()
            )
        """,
    }

    results: list[ConstraintCheck] = []
    for name, sql in checks.items():
        passed, error_type = statement_is_rejected(sql, database_url)
        results.append(ConstraintCheck(name=name, passed=passed, error_type=error_type))

    return tuple(results)


def run_smoke(database_url: str | None = None) -> TradingLedgerSmokeResult:
    apply_schema_and_fixture(database_url)
    return TradingLedgerSmokeResult(
        positions=load_positions(database_url),
        cash_balances=load_cash_balances(database_url),
        constraint_checks=run_constraint_checks(database_url),
    )
