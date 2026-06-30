from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from quantgres.db import connect, query_text
from quantgres.experiments.binance_candles import BINANCE_SOURCE, fetch_and_store_binance_klines

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RDB_SQL_DIR = PROJECT_ROOT / "sql" / "rdb"
RDB_SCHEMA_SQL = RDB_SQL_DIR / "001_trading_ledger_schema.sql"

PAPER_ACCOUNT_CODE = "PAPER1"
PAPER_STRATEGY_CODE = "binance_kline_momentum_v1"
PAPER_INITIAL_CASH = Decimal("10000.0000000000")
DEFAULT_NOTIONAL = Decimal("100.0000000000")
FEE_RATE = Decimal("0.0010000000")
QTY_QUANTUM = Decimal("0.0000000001")
MONEY_QUANTUM = Decimal("0.0000000001")

LATEST_TWO_CANDLES_SQL = """
SELECT
    symbol,
    ts,
    close_price,
    volume
FROM time_series.candles_1m
WHERE symbol = %s
  AND source = %s
ORDER BY ts DESC
LIMIT 2
"""

UPSERT_PAPER_ACCOUNT_SQL = """
INSERT INTO rdb.accounts (account_code, base_currency, account_name, created_at)
VALUES (%(account_code)s, 'USDT', 'Paper Trading Account', %(created_at)s)
ON CONFLICT (account_code) DO UPDATE
SET base_currency = EXCLUDED.base_currency,
    account_name = EXCLUDED.account_name
"""

UPSERT_PAPER_STRATEGY_SQL = """
INSERT INTO rdb.strategies (strategy_code, strategy_name, description, created_at)
VALUES (
    %(strategy_code)s,
    'Binance Kline Momentum V1',
    'Paper-only strategy that records a one-candle momentum decision from Binance public klines.',
    %(created_at)s
)
ON CONFLICT (strategy_code) DO UPDATE
SET strategy_name = EXCLUDED.strategy_name,
    description = EXCLUDED.description
"""

UPSERT_PAPER_INSTRUMENT_SQL = """
INSERT INTO rdb.instruments (symbol, base_asset, quote_asset, tick_size, lot_size, is_active)
VALUES (%(symbol)s, %(base_asset)s, %(quote_asset)s, 0.0100000000, 0.0000000100, true)
ON CONFLICT (symbol) DO UPDATE
SET base_asset = EXCLUDED.base_asset,
    quote_asset = EXCLUDED.quote_asset,
    tick_size = EXCLUDED.tick_size,
    lot_size = EXCLUDED.lot_size,
    is_active = EXCLUDED.is_active
"""

UPSERT_PAPER_DEPOSIT_SQL = """
INSERT INTO rdb.cash_ledger_entries (
    entry_id,
    account_code,
    currency,
    amount,
    reason,
    reference_type,
    reference_id,
    occurred_at
)
VALUES (
    %(deposit_entry_id)s,
    %(account_code)s,
    'USDT',
    %(initial_cash)s,
    'deposit',
    'paper_seed',
    %(account_code)s,
    %(created_at)s
)
ON CONFLICT (entry_id) DO UPDATE
SET account_code = EXCLUDED.account_code,
    currency = EXCLUDED.currency,
    amount = EXCLUDED.amount,
    reason = EXCLUDED.reason,
    reference_type = EXCLUDED.reference_type,
    reference_id = EXCLUDED.reference_id,
    occurred_at = EXCLUDED.occurred_at
"""

UPSERT_PAPER_ORDER_SQL = """
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
    %(client_order_id)s,
    %(account_code)s,
    %(strategy_code)s,
    %(symbol)s,
    %(side)s,
    'market',
    %(quantity)s,
    NULL,
    'filled',
    %(decision_at)s,
    %(decision_at)s
)
ON CONFLICT (client_order_id) DO UPDATE
SET account_code = EXCLUDED.account_code,
    strategy_code = EXCLUDED.strategy_code,
    symbol = EXCLUDED.symbol,
    side = EXCLUDED.side,
    order_type = EXCLUDED.order_type,
    quantity = EXCLUDED.quantity,
    limit_price = EXCLUDED.limit_price,
    status = EXCLUDED.status,
    created_at = EXCLUDED.created_at,
    updated_at = EXCLUDED.updated_at
"""

UPSERT_PAPER_FILL_SQL = """
INSERT INTO rdb.fills (
    fill_id,
    client_order_id,
    fill_sequence,
    fill_quantity,
    fill_price,
    fee_currency,
    fee_amount,
    liquidity,
    filled_at
)
VALUES (
    %(fill_id)s,
    %(client_order_id)s,
    1,
    %(quantity)s,
    %(fill_price)s,
    'USDT',
    %(fee_amount)s,
    'taker',
    %(decision_at)s
)
ON CONFLICT (fill_id) DO UPDATE
SET client_order_id = EXCLUDED.client_order_id,
    fill_sequence = EXCLUDED.fill_sequence,
    fill_quantity = EXCLUDED.fill_quantity,
    fill_price = EXCLUDED.fill_price,
    fee_currency = EXCLUDED.fee_currency,
    fee_amount = EXCLUDED.fee_amount,
    liquidity = EXCLUDED.liquidity,
    filled_at = EXCLUDED.filled_at
"""

UPSERT_PAPER_CASH_LEDGER_SQL = """
INSERT INTO rdb.cash_ledger_entries (
    entry_id,
    account_code,
    currency,
    amount,
    reason,
    reference_type,
    reference_id,
    occurred_at
)
VALUES
    (
        %(trade_entry_id)s,
        %(account_code)s,
        'USDT',
        %(cash_delta)s,
        'trade',
        'order',
        %(client_order_id)s,
        %(decision_at)s
    ),
    (
        %(fee_entry_id)s,
        %(account_code)s,
        'USDT',
        %(fee_cash_delta)s,
        'fee',
        'order',
        %(client_order_id)s,
        %(decision_at)s
    )
ON CONFLICT (entry_id) DO UPDATE
SET account_code = EXCLUDED.account_code,
    currency = EXCLUDED.currency,
    amount = EXCLUDED.amount,
    reason = EXCLUDED.reason,
    reference_type = EXCLUDED.reference_type,
    reference_id = EXCLUDED.reference_id,
    occurred_at = EXCLUDED.occurred_at
"""

UPSERT_PAPER_POSITION_SQL = """
INSERT INTO rdb.position_snapshots (
    account_code,
    strategy_code,
    symbol,
    quantity,
    average_entry_price,
    market_price,
    snapshot_at
)
VALUES (
    %(account_code)s,
    %(strategy_code)s,
    %(symbol)s,
    %(position_quantity)s,
    %(fill_price)s,
    %(fill_price)s,
    %(decision_at)s
)
ON CONFLICT (account_code, strategy_code, symbol, snapshot_at) DO UPDATE
SET quantity = EXCLUDED.quantity,
    average_entry_price = EXCLUDED.average_entry_price,
    market_price = EXCLUDED.market_price
"""


@dataclass(frozen=True)
class DecisionCandle:
    symbol: str
    ts: datetime
    close_price: Decimal
    volume: Decimal


@dataclass(frozen=True)
class PaperDecisionTrace:
    client_order_id: str
    symbol: str
    side: str
    decision_at: datetime
    previous_close: Decimal
    latest_close: Decimal
    return_bps: Decimal
    quantity: Decimal
    trade_notional: Decimal
    cash_delta: Decimal
    fee_amount: Decimal


@dataclass(frozen=True)
class BinancePaperTraceSmokeResult:
    rows_fetched: int
    rows_upserted: int
    trace: PaperDecisionTrace


def read_sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def apply_rdb_schema(database_url: str | None = None) -> None:
    with connect(database_url) as connection:
        connection.execute(query_text(read_sql(RDB_SCHEMA_SQL)))


def split_symbol(symbol: str) -> tuple[str, str]:
    upper_symbol = symbol.upper()
    for quote_asset in ("USDT", "USDC", "BTC", "ETH", "BNB"):
        if upper_symbol.endswith(quote_asset) and len(upper_symbol) > len(quote_asset):
            return upper_symbol[: -len(quote_asset)], quote_asset

    return upper_symbol, "UNKNOWN"


def seed_paper_reference_data(
    *,
    symbol: str,
    created_at: datetime,
    database_url: str | None = None,
) -> None:
    base_asset, quote_asset = split_symbol(symbol)
    with connect(database_url) as connection:
        params = {
            "account_code": PAPER_ACCOUNT_CODE,
            "strategy_code": PAPER_STRATEGY_CODE,
            "symbol": symbol.upper(),
            "base_asset": base_asset,
            "quote_asset": quote_asset,
            "deposit_entry_id": f"CASH-{PAPER_ACCOUNT_CODE}-DEPOSIT-0001",
            "initial_cash": PAPER_INITIAL_CASH,
            "created_at": created_at,
        }
        connection.execute(query_text(UPSERT_PAPER_ACCOUNT_SQL), params)
        connection.execute(query_text(UPSERT_PAPER_STRATEGY_SQL), params)
        connection.execute(query_text(UPSERT_PAPER_INSTRUMENT_SQL), params)
        connection.execute(query_text(UPSERT_PAPER_DEPOSIT_SQL), params)


def load_latest_two_binance_candles(
    *,
    symbol: str,
    database_url: str | None = None,
) -> tuple[DecisionCandle, DecisionCandle]:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(query_text(LATEST_TWO_CANDLES_SQL), (symbol.upper(), BINANCE_SOURCE))
        rows = cursor.fetchall()

    if len(rows) < 2:
        raise RuntimeError(
            f"Need at least two Binance candle rows for {symbol.upper()} to build a paper trace."
        )

    latest = DecisionCandle(
        symbol=str(rows[0][0]),
        ts=rows[0][1],
        close_price=rows[0][2],
        volume=rows[0][3],
    )
    previous = DecisionCandle(
        symbol=str(rows[1][0]),
        ts=rows[1][1],
        close_price=rows[1][2],
        volume=rows[1][3],
    )
    return previous, latest


def build_paper_decision(
    *,
    previous: DecisionCandle,
    latest: DecisionCandle,
    notional: Decimal = DEFAULT_NOTIONAL,
) -> PaperDecisionTrace:
    if latest.close_price <= 0:
        raise ValueError("Latest close price must be positive.")
    if previous.close_price <= 0:
        raise ValueError("Previous close price must be positive.")

    side = "buy" if latest.close_price >= previous.close_price else "sell"
    quantity = (notional / latest.close_price).quantize(QTY_QUANTUM)
    trade_notional = (quantity * latest.close_price).quantize(MONEY_QUANTUM)
    fee_amount = (trade_notional * FEE_RATE).quantize(MONEY_QUANTUM)
    cash_delta = -trade_notional if side == "buy" else trade_notional
    return_bps = (
        ((latest.close_price - previous.close_price) / previous.close_price) * Decimal("10000")
    ).quantize(MONEY_QUANTUM)
    timestamp_slug = latest.ts.strftime("%Y%m%dT%H%M%SZ")
    client_order_id = f"PAPER-{latest.symbol}-{timestamp_slug}"

    return PaperDecisionTrace(
        client_order_id=client_order_id,
        symbol=latest.symbol,
        side=side,
        decision_at=latest.ts,
        previous_close=previous.close_price,
        latest_close=latest.close_price,
        return_bps=return_bps,
        quantity=quantity,
        trade_notional=trade_notional,
        cash_delta=cash_delta,
        fee_amount=fee_amount,
    )


def write_paper_trace(
    trace: PaperDecisionTrace,
    database_url: str | None = None,
) -> None:
    position_quantity = trace.quantity if trace.side == "buy" else -trace.quantity
    with connect(database_url) as connection:
        params = {
            "client_order_id": trace.client_order_id,
            "fill_id": f"{trace.client_order_id}-FILL-1",
            "trade_entry_id": f"{trace.client_order_id}-CASH-TRADE",
            "fee_entry_id": f"{trace.client_order_id}-CASH-FEE",
            "account_code": PAPER_ACCOUNT_CODE,
            "strategy_code": PAPER_STRATEGY_CODE,
            "symbol": trace.symbol,
            "side": trace.side,
            "quantity": trace.quantity,
            "fill_price": trace.latest_close,
            "fee_amount": trace.fee_amount,
            "cash_delta": trace.cash_delta,
            "fee_cash_delta": -trace.fee_amount,
            "position_quantity": position_quantity,
            "decision_at": trace.decision_at,
        }
        connection.execute(query_text(UPSERT_PAPER_ORDER_SQL), params)
        connection.execute(query_text(UPSERT_PAPER_FILL_SQL), params)
        connection.execute(query_text(UPSERT_PAPER_CASH_LEDGER_SQL), params)
        connection.execute(query_text(UPSERT_PAPER_POSITION_SQL), params)


def record_latest_binance_paper_trace(
    *,
    symbol: str,
    database_url: str | None = None,
) -> PaperDecisionTrace:
    previous, latest = load_latest_two_binance_candles(symbol=symbol, database_url=database_url)
    apply_rdb_schema(database_url)
    seed_paper_reference_data(symbol=symbol, created_at=latest.ts, database_url=database_url)
    trace = build_paper_decision(previous=previous, latest=latest)
    write_paper_trace(trace, database_url)
    return trace


def run_binance_paper_trace_smoke(
    *,
    symbol: str = "BTCUSDT",
    interval: str = "1m",
    limit: int = 60,
    database_url: str | None = None,
) -> BinancePaperTraceSmokeResult:
    ingestion = fetch_and_store_binance_klines(
        symbol=symbol,
        interval=interval,
        limit=limit,
        database_url=database_url,
    )
    trace = record_latest_binance_paper_trace(symbol=symbol, database_url=database_url)
    return BinancePaperTraceSmokeResult(
        rows_fetched=ingestion.rows_fetched,
        rows_upserted=ingestion.rows_upserted,
        trace=trace,
    )
