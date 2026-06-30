from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from quantgres.db import connect, query_text
from quantgres.market_data.binance import BinanceKline, fetch_klines

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TIME_SERIES_SQL_DIR = PROJECT_ROOT / "sql" / "time_series"
TIME_SERIES_SCHEMA_SQL = TIME_SERIES_SQL_DIR / "001_candles_schema.sql"

BINANCE_SOURCE = "binance_spot_klines"

UPSERT_BINANCE_KLINE_SQL = """
INSERT INTO time_series.candles_1m (
    symbol,
    ts,
    close_ts,
    open_price,
    high_price,
    low_price,
    close_price,
    volume,
    quote_volume,
    trade_count,
    taker_buy_base_volume,
    taker_buy_quote_volume,
    source
)
VALUES (
    %(symbol)s,
    %(ts)s,
    %(close_ts)s,
    %(open_price)s,
    %(high_price)s,
    %(low_price)s,
    %(close_price)s,
    %(volume)s,
    %(quote_volume)s,
    %(trade_count)s,
    %(taker_buy_base_volume)s,
    %(taker_buy_quote_volume)s,
    %(source)s
)
ON CONFLICT (symbol, ts) DO UPDATE
SET close_ts = EXCLUDED.close_ts,
    open_price = EXCLUDED.open_price,
    high_price = EXCLUDED.high_price,
    low_price = EXCLUDED.low_price,
    close_price = EXCLUDED.close_price,
    volume = EXCLUDED.volume,
    quote_volume = EXCLUDED.quote_volume,
    trade_count = EXCLUDED.trade_count,
    taker_buy_base_volume = EXCLUDED.taker_buy_base_volume,
    taker_buy_quote_volume = EXCLUDED.taker_buy_quote_volume,
    source = EXCLUDED.source,
    ingested_at = now()
"""


@dataclass(frozen=True)
class BinanceCandleIngestionResult:
    symbol: str
    interval: str
    source: str
    rows_fetched: int
    rows_upserted: int
    first_ts: datetime | None
    last_ts: datetime | None


def read_sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def ensure_time_series_schema(database_url: str | None = None) -> None:
    with connect(database_url) as connection:
        connection.execute(query_text(read_sql(TIME_SERIES_SCHEMA_SQL)))


def kline_to_params(kline: BinanceKline) -> dict[str, object]:
    return {
        "symbol": kline.symbol,
        "ts": kline.open_time,
        "close_ts": kline.close_time,
        "open_price": kline.open_price,
        "high_price": kline.high_price,
        "low_price": kline.low_price,
        "close_price": kline.close_price,
        "volume": kline.volume,
        "quote_volume": kline.quote_volume,
        "trade_count": kline.trade_count,
        "taker_buy_base_volume": kline.taker_buy_base_volume,
        "taker_buy_quote_volume": kline.taker_buy_quote_volume,
        "source": BINANCE_SOURCE,
    }


def upsert_klines(
    klines: tuple[BinanceKline, ...],
    database_url: str | None = None,
) -> int:
    if not klines:
        return 0

    ensure_time_series_schema(database_url)
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.executemany(
            query_text(UPSERT_BINANCE_KLINE_SQL),
            [kline_to_params(kline) for kline in klines],
        )

    return len(klines)


def fetch_and_store_binance_klines(
    *,
    symbol: str,
    interval: str = "1m",
    limit: int = 60,
    base_url: str | None = None,
    start_time_ms: int | None = None,
    end_time_ms: int | None = None,
    database_url: str | None = None,
) -> BinanceCandleIngestionResult:
    if base_url is None:
        klines = fetch_klines(
            symbol=symbol,
            interval=interval,
            limit=limit,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
        )
    else:
        klines = fetch_klines(
            symbol=symbol,
            interval=interval,
            limit=limit,
            base_url=base_url,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
        )
    rows_upserted = upsert_klines(klines, database_url)

    return BinanceCandleIngestionResult(
        symbol=symbol.upper(),
        interval=interval,
        source=BINANCE_SOURCE,
        rows_fetched=len(klines),
        rows_upserted=rows_upserted,
        first_ts=klines[0].open_time if klines else None,
        last_ts=klines[-1].open_time if klines else None,
    )
