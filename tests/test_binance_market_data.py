from datetime import UTC, datetime
from decimal import Decimal

from quantgres.market_data.binance import build_klines_url, parse_kline_row


def test_build_klines_url_uses_public_market_data_endpoint():
    url = build_klines_url(
        symbol="btcusdt",
        interval="1m",
        limit=10,
        start_time_ms=1700000000000,
        end_time_ms=1700000060000,
    )

    assert url.startswith("https://data-api.binance.vision/api/v3/klines?")
    assert "symbol=BTCUSDT" in url
    assert "interval=1m" in url
    assert "limit=10" in url
    assert "startTime=1700000000000" in url
    assert "endTime=1700000060000" in url


def test_parse_kline_row_maps_binance_response_fields():
    row = [
        1700000000000,
        "60000.00000000",
        "60100.00000000",
        "59900.00000000",
        "60050.00000000",
        "12.34500000",
        1700000059999,
        "740000.00000000",
        1234,
        "6.00000000",
        "360300.00000000",
        "0",
    ]

    kline = parse_kline_row(row, symbol="btcusdt", interval="1m")

    assert kline.symbol == "BTCUSDT"
    assert kline.interval == "1m"
    assert kline.open_time == datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
    assert kline.open_price == Decimal("60000.00000000")
    assert kline.high_price == Decimal("60100.00000000")
    assert kline.low_price == Decimal("59900.00000000")
    assert kline.close_price == Decimal("60050.00000000")
    assert kline.volume == Decimal("12.34500000")
    assert kline.close_time == datetime(2023, 11, 14, 22, 14, 19, 999000, tzinfo=UTC)
    assert kline.quote_volume == Decimal("740000.00000000")
    assert kline.trade_count == 1234
    assert kline.taker_buy_base_volume == Decimal("6.00000000")
    assert kline.taker_buy_quote_volume == Decimal("360300.00000000")
