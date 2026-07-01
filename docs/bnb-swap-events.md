# BNB Swap Event Projection

This experiment turns raw BNB Chain EVM logs into an analysis-friendly DeFi
event table.

## Study Question

How should PostgreSQL keep raw on-chain evidence while also exposing typed,
queryable DeFi event columns for quant research and paper-agent workflows?

## Data Source

The projection starts from real BNB Chain `eth_getLogs` data stored in
`onchain.raw_logs`.

The default sample uses the PancakeSwap V2 WBNB/USDT pair:

- pair: `0x16b9a82891338f9ba80e2d6970fdda79d1eb0dae`
- block: `107270817`
- topic0: `0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822`

PancakeSwap V2 Pair follows the Uniswap V2-style Swap event layout:

```solidity
Swap(
    address indexed sender,
    uint amount0In,
    uint amount1In,
    uint amount0Out,
    uint amount1Out,
    address indexed to
)
```

Primary references:

- https://github.com/pancakeswap/pancake-swap-core/blob/master/contracts/interfaces/IPancakePair.sol
- https://github.com/pancakeswap/pancake-swap-core/blob/master/contracts/PancakePair.sol
- https://github.com/Uniswap/v2-core/blob/master/contracts/UniswapV2Pair.sol

## Schema

SQL file:

- `sql/defi/001_swap_events_schema.sql`

Table:

- `defi.swap_events`

Important columns:

- `sender`, `recipient`: decoded indexed address topics
- `amount0_in`, `amount1_in`, `amount0_out`, `amount1_out`: decoded raw token
  integer amounts stored as `numeric(78,0)`
- `raw_log`: original JSONB RPC log for evidence and replay
- `(chain_id, transaction_hash, log_index)`: idempotency key

## Verification

Run the projection smoke:

```powershell
uv run quantgres bnb-swap-projection-smoke
```

Expected behavior:

- Calls real BNB Chain JSON-RPC through the raw log ingestion path.
- Upserts raw logs into `onchain.raw_logs`.
- Decodes Swap topics/data into `defi.swap_events`.
- Prints sample sender, recipient, and amount columns.

Run the wider corpus smoke:

```powershell
uv run quantgres bnb-swap-corpus-smoke
```

Expected behavior:

- Calls real BNB Chain JSON-RPC through windowed raw log ingestion.
- Projects every fetched PancakeSwap Swap log into `defi.swap_events`.
- Fetches missing block headers and enriches swaps with block timestamps.
- Writes `reports/generated/onchain/bnb-swap-corpus.json` and `.md` with
  ingestion, projection, and enrichment counts.

This experiment does not require wallet keys, Binance keys, signed endpoints, or
live trading.
