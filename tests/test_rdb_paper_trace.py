from datetime import UTC, datetime
from decimal import Decimal

from quantgres.experiments.rdb_paper_trace import (
    DecisionCandle,
    build_paper_decision,
    split_symbol,
)


def test_split_symbol_extracts_common_quote_asset():
    assert split_symbol("btcusdt") == ("BTC", "USDT")
    assert split_symbol("ethbtc") == ("ETH", "BTC")
    assert split_symbol("UNKNOWN") == ("UNKNOWN", "UNKNOWN")


def test_build_paper_decision_records_buy_when_latest_close_is_higher():
    previous = DecisionCandle(
        symbol="BTCUSDT",
        ts=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
        close_price=Decimal("50000.0000000000"),
        volume=Decimal("10"),
    )
    latest = DecisionCandle(
        symbol="BTCUSDT",
        ts=datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
        close_price=Decimal("50500.0000000000"),
        volume=Decimal("12"),
    )

    trace = build_paper_decision(previous=previous, latest=latest)

    assert trace.client_order_id == "PAPER-BTCUSDT-20260101T000100Z"
    assert trace.side == "buy"
    assert trace.return_bps == Decimal("100.0000000000")
    assert trace.quantity == Decimal("0.0019801980")
    assert trace.trade_notional == Decimal("99.9999990000")
    assert trace.cash_delta == Decimal("-99.9999990000")
    assert trace.fee_amount == Decimal("0.0999999990")


def test_build_paper_decision_records_sell_when_latest_close_is_lower():
    previous = DecisionCandle(
        symbol="BTCUSDT",
        ts=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
        close_price=Decimal("50000.0000000000"),
        volume=Decimal("10"),
    )
    latest = DecisionCandle(
        symbol="BTCUSDT",
        ts=datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
        close_price=Decimal("49500.0000000000"),
        volume=Decimal("12"),
    )

    trace = build_paper_decision(previous=previous, latest=latest)

    assert trace.side == "sell"
    assert trace.return_bps == Decimal("-100.0000000000")
    assert trace.cash_delta == trace.trade_notional
