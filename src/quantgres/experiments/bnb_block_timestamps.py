from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import sleep
from typing import Any, Protocol

from psycopg.types.json import Jsonb

from quantgres.db import connect, query_text
from quantgres.experiments.bnb_swap_projection import (
    PANCAKESWAP_SAMPLE_BLOCK,
    PANCAKESWAP_V2,
    PANCAKESWAP_V2_SWAP_TOPIC0,
    PANCAKESWAP_V2_WBNB_USDT_PAIR,
    BnbSwapProjectionSmokeResult,
    run_bnb_swap_projection_smoke,
)
from quantgres.onchain.bnb_rpc import (
    BNB_CHAIN_ID,
    DEFAULT_BNB_RPC_URL,
    BnbBlock,
    get_block_by_number,
    load_bnb_rpc_info,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ONCHAIN_SQL_DIR = PROJECT_ROOT / "sql" / "onchain"
DEFI_SQL_DIR = PROJECT_ROOT / "sql" / "defi"
BLOCKS_SCHEMA_SQL = ONCHAIN_SQL_DIR / "002_blocks_schema.sql"
SWAP_EVENTS_SCHEMA_SQL = DEFI_SQL_DIR / "001_swap_events_schema.sql"

UPSERT_BLOCK_SQL = """
INSERT INTO onchain.blocks (
    chain_id,
    block_number,
    block_hash,
    parent_hash,
    block_timestamp,
    raw_block
)
VALUES (
    %(chain_id)s,
    %(block_number)s,
    %(block_hash)s,
    %(parent_hash)s,
    %(block_timestamp)s,
    %(raw_block)s
)
ON CONFLICT (chain_id, block_number) DO UPDATE
SET block_hash = EXCLUDED.block_hash,
    parent_hash = EXCLUDED.parent_hash,
    block_timestamp = EXCLUDED.block_timestamp,
    raw_block = EXCLUDED.raw_block,
    fetched_at = now()
"""

ENRICH_SWAP_EVENTS_SQL = """
UPDATE defi.swap_events AS swap
SET block_timestamp = block.block_timestamp,
    projected_at = now()
FROM onchain.blocks AS block
WHERE swap.chain_id = block.chain_id
  AND swap.block_number = block.block_number
  AND swap.chain_id = %(chain_id)s
  AND swap.dex = %(dex)s
  AND swap.pair_address = %(pair_address)s
  AND swap.block_number BETWEEN %(from_block)s AND %(to_block)s
  AND swap.block_timestamp IS DISTINCT FROM block.block_timestamp
"""

COUNT_BLOCKS_SQL = """
SELECT count(*)::integer
FROM onchain.blocks
WHERE chain_id = %(chain_id)s
  AND block_number BETWEEN %(from_block)s AND %(to_block)s
"""

COUNT_ENRICHED_SWAPS_SQL = """
SELECT count(*)::integer
FROM defi.swap_events
WHERE chain_id = %(chain_id)s
  AND dex = %(dex)s
  AND pair_address = %(pair_address)s
  AND block_number BETWEEN %(from_block)s AND %(to_block)s
  AND block_timestamp IS NOT NULL
"""

SELECT_ENRICHED_SWAPS_SQL = """
SELECT
    chain_id,
    dex,
    pair_address,
    block_number,
    block_timestamp,
    transaction_hash,
    log_index
FROM defi.swap_events
WHERE chain_id = %(chain_id)s
  AND dex = %(dex)s
  AND pair_address = %(pair_address)s
  AND block_number BETWEEN %(from_block)s AND %(to_block)s
ORDER BY block_timestamp, log_index
LIMIT %(limit)s
"""

SELECT_SWAP_BLOCK_NUMBERS_SQL = """
SELECT DISTINCT block_number
FROM defi.swap_events
WHERE chain_id = %(chain_id)s
  AND dex = %(dex)s
  AND pair_address = %(pair_address)s
  AND block_number BETWEEN %(from_block)s AND %(to_block)s
ORDER BY block_number
"""

SELECT_CACHED_BLOCK_NUMBERS_SQL = """
SELECT block_number
FROM onchain.blocks
WHERE chain_id = %(chain_id)s
  AND block_number BETWEEN %(from_block)s AND %(to_block)s
ORDER BY block_number
"""


class BlockFetcher(Protocol):
    def __call__(
        self,
        *,
        rpc_url: str,
        chain_id: int,
        block_number: int,
        include_transactions: bool = False,
    ) -> BnbBlock: ...


@dataclass(frozen=True)
class BlockFetchPolicy:
    max_attempts: int = 3
    retry_sleep_seconds: float = 0.25


@dataclass(frozen=True)
class BlockFetchFailure:
    block_number: int
    attempts: int
    error_type: str
    message: str


class BlockFetchRetryError(RuntimeError):
    def __init__(self, failures: tuple[BlockFetchFailure, ...]) -> None:
        self.failures = failures
        failed_blocks = ", ".join(str(failure.block_number) for failure in failures)
        super().__init__(f"Failed to fetch BNB blocks after retries: {failed_blocks}")


@dataclass(frozen=True)
class EnrichedSwapEventRow:
    chain_id: int
    dex: str
    pair_address: str
    block_number: int
    block_timestamp: object
    transaction_hash: str
    log_index: int


@dataclass(frozen=True)
class BnbBlockTimestampSmokeResult:
    swap_projection: BnbSwapProjectionSmokeResult
    requested_block_numbers: tuple[int, ...]
    cached_block_numbers: tuple[int, ...]
    missing_block_numbers: tuple[int, ...]
    fetched_blocks: tuple[BnbBlock, ...]
    upserted_blocks: int
    updated_swaps: int
    stored_blocks: int
    enriched_swaps: int
    sample_events: tuple[EnrichedSwapEventRow, ...]


def read_sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def ensure_block_timestamp_schema(database_url: str | None = None) -> None:
    with connect(database_url) as connection:
        connection.execute(query_text(read_sql(BLOCKS_SCHEMA_SQL)))
        connection.execute(query_text(read_sql(SWAP_EVENTS_SCHEMA_SQL)))


def block_to_params(block: BnbBlock) -> dict[str, object]:
    return {
        "chain_id": block.chain_id,
        "block_number": block.block_number,
        "block_hash": block.block_hash,
        "parent_hash": block.parent_hash,
        "block_timestamp": block.block_timestamp,
        "raw_block": Jsonb(block.raw_block),
    }


def upsert_blocks(
    blocks: tuple[BnbBlock, ...],
    database_url: str | None = None,
) -> int:
    ensure_block_timestamp_schema(database_url)
    if not blocks:
        return 0

    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.executemany(
            query_text(UPSERT_BLOCK_SQL), [block_to_params(block) for block in blocks]
        )

    return len(blocks)


def enrichment_params(
    *,
    from_block: int,
    to_block: int,
    chain_id: int = BNB_CHAIN_ID,
    dex: str = PANCAKESWAP_V2,
    pair_address: str = PANCAKESWAP_V2_WBNB_USDT_PAIR,
) -> dict[str, object]:
    return {
        "chain_id": chain_id,
        "dex": dex,
        "pair_address": pair_address.lower(),
        "from_block": from_block,
        "to_block": to_block,
    }


def enrich_swap_event_timestamps(
    *,
    from_block: int,
    to_block: int,
    chain_id: int = BNB_CHAIN_ID,
    dex: str = PANCAKESWAP_V2,
    pair_address: str = PANCAKESWAP_V2_WBNB_USDT_PAIR,
    database_url: str | None = None,
) -> int:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            query_text(ENRICH_SWAP_EVENTS_SQL),
            enrichment_params(
                from_block=from_block,
                to_block=to_block,
                chain_id=chain_id,
                dex=dex,
                pair_address=pair_address,
            ),
        )
        return cursor.rowcount


def validate_block_fetch_policy(policy: BlockFetchPolicy) -> None:
    if policy.max_attempts <= 0:
        raise ValueError("max_attempts must be positive.")
    if policy.retry_sleep_seconds < 0:
        raise ValueError("retry_sleep_seconds must be non-negative.")


def block_fetch_failure(
    *,
    block_number: int,
    attempts: int,
    error: Exception,
) -> BlockFetchFailure:
    return BlockFetchFailure(
        block_number=block_number,
        attempts=attempts,
        error_type=type(error).__name__,
        message=str(error),
    )


def fetch_block_with_retries(
    *,
    block_number: int,
    rpc_url: str,
    chain_id: int,
    policy: BlockFetchPolicy | None = None,
    fetcher: BlockFetcher = get_block_by_number,
    sleeper: Callable[[float], None] = sleep,
) -> BnbBlock:
    policy = policy or BlockFetchPolicy()
    validate_block_fetch_policy(policy)
    last_error: Exception | None = None

    for attempt in range(1, policy.max_attempts + 1):
        try:
            return fetcher(
                rpc_url=rpc_url,
                chain_id=chain_id,
                block_number=block_number,
                include_transactions=False,
            )
        except Exception as error:
            last_error = error
            if attempt < policy.max_attempts and policy.retry_sleep_seconds > 0:
                sleeper(policy.retry_sleep_seconds * attempt)

    if last_error is None:
        raise RuntimeError("Block fetch retry loop ended without an error.")

    raise BlockFetchRetryError(
        (
            block_fetch_failure(
                block_number=block_number,
                attempts=policy.max_attempts,
                error=last_error,
            ),
        )
    )


def fetch_blocks(
    *,
    block_numbers: tuple[int, ...],
    rpc_url: str,
    chain_id: int,
    policy: BlockFetchPolicy | None = None,
    fetcher: BlockFetcher = get_block_by_number,
    sleeper: Callable[[float], None] = sleep,
) -> tuple[BnbBlock, ...]:
    policy = policy or BlockFetchPolicy()
    validate_block_fetch_policy(policy)
    blocks: list[BnbBlock] = []
    failures: list[BlockFetchFailure] = []

    for block_number in block_numbers:
        try:
            blocks.append(
                fetch_block_with_retries(
                    block_number=block_number,
                    rpc_url=rpc_url,
                    chain_id=chain_id,
                    policy=policy,
                    fetcher=fetcher,
                    sleeper=sleeper,
                )
            )
        except BlockFetchRetryError as error:
            failures.extend(error.failures)

    if failures:
        raise BlockFetchRetryError(tuple(failures))

    return tuple(blocks)


def select_missing_block_numbers(
    *,
    requested_block_numbers: tuple[int, ...],
    cached_block_numbers: tuple[int, ...],
) -> tuple[int, ...]:
    cached = set(cached_block_numbers)
    return tuple(
        block_number for block_number in requested_block_numbers if block_number not in cached
    )


def load_cached_block_numbers(
    *,
    from_block: int,
    to_block: int,
    chain_id: int = BNB_CHAIN_ID,
    database_url: str | None = None,
) -> tuple[int, ...]:
    ensure_block_timestamp_schema(database_url)
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            query_text(SELECT_CACHED_BLOCK_NUMBERS_SQL),
            {
                "chain_id": chain_id,
                "from_block": from_block,
                "to_block": to_block,
            },
        )
        rows = cursor.fetchall()

    return tuple(int(row[0]) for row in rows)


def count_blocks(
    *,
    from_block: int,
    to_block: int,
    chain_id: int = BNB_CHAIN_ID,
    database_url: str | None = None,
) -> int:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            query_text(COUNT_BLOCKS_SQL),
            {
                "chain_id": chain_id,
                "from_block": from_block,
                "to_block": to_block,
            },
        )
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("Block count returned no row.")

    return int(row[0])


def count_enriched_swaps(
    *,
    from_block: int,
    to_block: int,
    chain_id: int = BNB_CHAIN_ID,
    dex: str = PANCAKESWAP_V2,
    pair_address: str = PANCAKESWAP_V2_WBNB_USDT_PAIR,
    database_url: str | None = None,
) -> int:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            query_text(COUNT_ENRICHED_SWAPS_SQL),
            enrichment_params(
                from_block=from_block,
                to_block=to_block,
                chain_id=chain_id,
                dex=dex,
                pair_address=pair_address,
            ),
        )
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("Enriched swap count returned no row.")

    return int(row[0])


def coerce_event_timestamp(value: object) -> object:
    if value is None:
        raise TypeError("Expected enriched swap event timestamp.")
    return value


def row_to_enriched_swap(row: tuple[Any, ...]) -> EnrichedSwapEventRow:
    return EnrichedSwapEventRow(
        chain_id=int(row[0]),
        dex=str(row[1]),
        pair_address=str(row[2]),
        block_number=int(row[3]),
        block_timestamp=coerce_event_timestamp(row[4]),
        transaction_hash=str(row[5]),
        log_index=int(row[6]),
    )


def load_enriched_swaps(
    *,
    from_block: int,
    to_block: int,
    chain_id: int = BNB_CHAIN_ID,
    dex: str = PANCAKESWAP_V2,
    pair_address: str = PANCAKESWAP_V2_WBNB_USDT_PAIR,
    limit: int = 5,
    database_url: str | None = None,
) -> tuple[EnrichedSwapEventRow, ...]:
    with connect(database_url) as connection, connection.cursor() as cursor:
        params = {
            **enrichment_params(
                from_block=from_block,
                to_block=to_block,
                chain_id=chain_id,
                dex=dex,
                pair_address=pair_address,
            ),
            "limit": limit,
        }
        cursor.execute(query_text(SELECT_ENRICHED_SWAPS_SQL), params)
        rows = cursor.fetchall()

    return tuple(row_to_enriched_swap(row) for row in rows)


def load_swap_block_numbers(
    *,
    from_block: int,
    to_block: int,
    chain_id: int = BNB_CHAIN_ID,
    dex: str = PANCAKESWAP_V2,
    pair_address: str = PANCAKESWAP_V2_WBNB_USDT_PAIR,
    database_url: str | None = None,
) -> tuple[int, ...]:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            query_text(SELECT_SWAP_BLOCK_NUMBERS_SQL),
            enrichment_params(
                from_block=from_block,
                to_block=to_block,
                chain_id=chain_id,
                dex=dex,
                pair_address=pair_address,
            ),
        )
        rows = cursor.fetchall()

    return tuple(int(row[0]) for row in rows)


def run_bnb_block_timestamp_smoke(
    *,
    from_block: int = PANCAKESWAP_SAMPLE_BLOCK,
    to_block: int = PANCAKESWAP_SAMPLE_BLOCK,
    pair_address: str = PANCAKESWAP_V2_WBNB_USDT_PAIR,
    topic0: str = PANCAKESWAP_V2_SWAP_TOPIC0,
    rpc_url: str = DEFAULT_BNB_RPC_URL,
    block_fetch_policy: BlockFetchPolicy | None = None,
    database_url: str | None = None,
) -> BnbBlockTimestampSmokeResult:
    info = load_bnb_rpc_info(rpc_url=rpc_url)
    if info.chain_id != BNB_CHAIN_ID:
        raise RuntimeError(f"Expected BNB Chain id {BNB_CHAIN_ID}, got {info.chain_id}.")

    swap_projection = run_bnb_swap_projection_smoke(
        from_block=from_block,
        to_block=to_block,
        pair_address=pair_address,
        topic0=topic0,
        rpc_url=rpc_url,
        database_url=database_url,
    )
    block_numbers = load_swap_block_numbers(
        from_block=from_block,
        to_block=to_block,
        chain_id=info.chain_id,
        pair_address=pair_address,
        database_url=database_url,
    )
    requested_block_set = set(block_numbers)
    cached_block_numbers = tuple(
        block_number
        for block_number in load_cached_block_numbers(
            from_block=from_block,
            to_block=to_block,
            chain_id=info.chain_id,
            database_url=database_url,
        )
        if block_number in requested_block_set
    )
    missing_block_numbers = select_missing_block_numbers(
        requested_block_numbers=block_numbers,
        cached_block_numbers=cached_block_numbers,
    )
    blocks = fetch_blocks(
        block_numbers=missing_block_numbers,
        rpc_url=rpc_url,
        chain_id=info.chain_id,
        policy=block_fetch_policy,
    )
    upserted_blocks = upsert_blocks(blocks, database_url)
    updated_swaps = enrich_swap_event_timestamps(
        from_block=from_block,
        to_block=to_block,
        chain_id=info.chain_id,
        pair_address=pair_address,
        database_url=database_url,
    )

    return BnbBlockTimestampSmokeResult(
        swap_projection=swap_projection,
        requested_block_numbers=block_numbers,
        cached_block_numbers=cached_block_numbers,
        missing_block_numbers=missing_block_numbers,
        fetched_blocks=blocks,
        upserted_blocks=upserted_blocks,
        updated_swaps=updated_swaps,
        stored_blocks=count_blocks(
            from_block=from_block,
            to_block=to_block,
            chain_id=info.chain_id,
            database_url=database_url,
        ),
        enriched_swaps=count_enriched_swaps(
            from_block=from_block,
            to_block=to_block,
            chain_id=info.chain_id,
            pair_address=pair_address,
            database_url=database_url,
        ),
        sample_events=load_enriched_swaps(
            from_block=from_block,
            to_block=to_block,
            chain_id=info.chain_id,
            pair_address=pair_address,
            database_url=database_url,
        ),
    )
