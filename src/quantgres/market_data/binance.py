import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_BINANCE_MARKET_DATA_BASE_URL = "https://data-api.binance.vision"
KLINES_PATH = "/api/v3/klines"


@dataclass(frozen=True)
class BinanceKline:
    symbol: str
    interval: str
    open_time: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Decimal
    close_time: datetime
    quote_volume: Decimal
    trade_count: int
    taker_buy_base_volume: Decimal
    taker_buy_quote_volume: Decimal


def milliseconds_to_datetime(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, UTC)


def parse_kline_row(row: Sequence[Any], *, symbol: str, interval: str) -> BinanceKline:
    if len(row) < 11:
        raise ValueError(f"Expected at least 11 Binance kline fields, got {len(row)}.")

    return BinanceKline(
        symbol=symbol.upper(),
        interval=interval,
        open_time=milliseconds_to_datetime(int(row[0])),
        open_price=Decimal(str(row[1])),
        high_price=Decimal(str(row[2])),
        low_price=Decimal(str(row[3])),
        close_price=Decimal(str(row[4])),
        volume=Decimal(str(row[5])),
        close_time=milliseconds_to_datetime(int(row[6])),
        quote_volume=Decimal(str(row[7])),
        trade_count=int(row[8]),
        taker_buy_base_volume=Decimal(str(row[9])),
        taker_buy_quote_volume=Decimal(str(row[10])),
    )


def build_klines_url(
    *,
    symbol: str,
    interval: str,
    limit: int,
    base_url: str = DEFAULT_BINANCE_MARKET_DATA_BASE_URL,
    start_time_ms: int | None = None,
    end_time_ms: int | None = None,
) -> str:
    if not 1 <= limit <= 1000:
        raise ValueError("Binance kline limit must be between 1 and 1000.")

    params: dict[str, str | int] = {
        "symbol": symbol.upper(),
        "interval": interval,
        "limit": limit,
    }
    if start_time_ms is not None:
        params["startTime"] = start_time_ms
    if end_time_ms is not None:
        params["endTime"] = end_time_ms

    return f"{base_url.rstrip('/')}{KLINES_PATH}?{urlencode(params)}"


def fetch_klines(
    *,
    symbol: str,
    interval: str = "1m",
    limit: int = 60,
    base_url: str = DEFAULT_BINANCE_MARKET_DATA_BASE_URL,
    start_time_ms: int | None = None,
    end_time_ms: int | None = None,
    timeout_seconds: float = 10,
) -> tuple[BinanceKline, ...]:
    url = build_klines_url(
        symbol=symbol,
        interval=interval,
        limit=limit,
        base_url=base_url,
        start_time_ms=start_time_ms,
        end_time_ms=end_time_ms,
    )
    request = Request(url, headers={"User-Agent": "Quantgres/0.1"})

    with urlopen(request, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if not isinstance(payload, list):
        raise TypeError("Expected Binance klines response to be a list.")

    klines: list[BinanceKline] = []
    for row in payload:
        if not isinstance(row, list):
            raise TypeError("Expected every Binance kline response row to be a list.")
        klines.append(parse_kline_row(row, symbol=symbol, interval=interval))

    return tuple(klines)
