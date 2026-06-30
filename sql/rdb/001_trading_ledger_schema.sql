CREATE SCHEMA IF NOT EXISTS rdb;

CREATE TABLE IF NOT EXISTS rdb.accounts (
    account_code text PRIMARY KEY,
    base_currency text NOT NULL,
    account_name text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (account_code <> ''),
    CHECK (base_currency <> '')
);

CREATE TABLE IF NOT EXISTS rdb.strategies (
    strategy_code text PRIMARY KEY,
    strategy_name text NOT NULL,
    description text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (strategy_code <> '')
);

CREATE TABLE IF NOT EXISTS rdb.instruments (
    symbol text PRIMARY KEY,
    base_asset text NOT NULL,
    quote_asset text NOT NULL,
    tick_size numeric(28, 10) NOT NULL,
    lot_size numeric(28, 10) NOT NULL,
    is_active boolean NOT NULL DEFAULT true,
    CHECK (symbol <> ''),
    CHECK (base_asset <> ''),
    CHECK (quote_asset <> ''),
    CHECK (tick_size > 0),
    CHECK (lot_size > 0)
);

CREATE TABLE IF NOT EXISTS rdb.orders (
    client_order_id text PRIMARY KEY,
    account_code text NOT NULL REFERENCES rdb.accounts (account_code),
    strategy_code text NOT NULL REFERENCES rdb.strategies (strategy_code),
    symbol text NOT NULL REFERENCES rdb.instruments (symbol),
    side text NOT NULL CHECK (side IN ('buy', 'sell')),
    order_type text NOT NULL CHECK (order_type IN ('market', 'limit')),
    quantity numeric(28, 10) NOT NULL CHECK (quantity > 0),
    limit_price numeric(28, 10),
    status text NOT NULL CHECK (status IN ('new', 'partially_filled', 'filled', 'cancelled', 'rejected')),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    CONSTRAINT orders_limit_price_required_check CHECK (
        (order_type = 'market' AND limit_price IS NULL)
        OR (order_type = 'limit' AND limit_price IS NOT NULL AND limit_price > 0)
    ),
    CHECK (updated_at >= created_at)
);

ALTER TABLE rdb.orders
    DROP CONSTRAINT IF EXISTS orders_limit_price_required_check;

ALTER TABLE rdb.orders
    ADD CONSTRAINT orders_limit_price_required_check
    CHECK (
        (order_type = 'market' AND limit_price IS NULL)
        OR (order_type = 'limit' AND limit_price IS NOT NULL AND limit_price > 0)
    ) NOT VALID;

CREATE INDEX IF NOT EXISTS orders_account_created_at_idx
    ON rdb.orders (account_code, created_at DESC);

CREATE INDEX IF NOT EXISTS orders_strategy_symbol_created_at_idx
    ON rdb.orders (strategy_code, symbol, created_at DESC);

CREATE TABLE IF NOT EXISTS rdb.fills (
    fill_id text PRIMARY KEY,
    client_order_id text NOT NULL REFERENCES rdb.orders (client_order_id),
    fill_sequence integer NOT NULL,
    fill_quantity numeric(28, 10) NOT NULL CHECK (fill_quantity > 0),
    fill_price numeric(28, 10) NOT NULL CHECK (fill_price > 0),
    fee_currency text NOT NULL,
    fee_amount numeric(28, 10) NOT NULL CHECK (fee_amount >= 0),
    liquidity text NOT NULL CHECK (liquidity IN ('maker', 'taker')),
    filled_at timestamptz NOT NULL,
    UNIQUE (client_order_id, fill_sequence),
    CHECK (fill_sequence > 0),
    CHECK (fee_currency <> '')
);

CREATE INDEX IF NOT EXISTS fills_order_filled_at_idx
    ON rdb.fills (client_order_id, filled_at);

CREATE TABLE IF NOT EXISTS rdb.cash_ledger_entries (
    entry_id text PRIMARY KEY,
    account_code text NOT NULL REFERENCES rdb.accounts (account_code),
    currency text NOT NULL,
    amount numeric(28, 10) NOT NULL CHECK (amount <> 0),
    reason text NOT NULL CHECK (reason IN ('deposit', 'trade', 'fee', 'withdrawal', 'adjustment')),
    reference_type text NOT NULL,
    reference_id text NOT NULL,
    occurred_at timestamptz NOT NULL,
    CHECK (currency <> ''),
    CHECK (reference_type <> ''),
    CHECK (reference_id <> '')
);

CREATE INDEX IF NOT EXISTS cash_ledger_account_currency_occurred_at_idx
    ON rdb.cash_ledger_entries (account_code, currency, occurred_at DESC);

CREATE TABLE IF NOT EXISTS rdb.position_snapshots (
    account_code text NOT NULL REFERENCES rdb.accounts (account_code),
    strategy_code text NOT NULL REFERENCES rdb.strategies (strategy_code),
    symbol text NOT NULL REFERENCES rdb.instruments (symbol),
    quantity numeric(28, 10) NOT NULL,
    average_entry_price numeric(28, 10),
    market_price numeric(28, 10),
    snapshot_at timestamptz NOT NULL,
    PRIMARY KEY (account_code, strategy_code, symbol, snapshot_at),
    CHECK (
        (quantity = 0 AND average_entry_price IS NULL)
        OR (quantity <> 0 AND average_entry_price > 0)
    ),
    CHECK (market_price IS NULL OR market_price > 0)
);

CREATE INDEX IF NOT EXISTS position_snapshots_account_symbol_snapshot_at_idx
    ON rdb.position_snapshots (account_code, symbol, snapshot_at DESC);
