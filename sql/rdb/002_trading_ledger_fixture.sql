INSERT INTO rdb.accounts (account_code, base_currency, account_name, created_at)
VALUES
    ('A1', 'USD', 'Research Account 1', '2026-01-01T00:00:00Z'),
    ('A2', 'USD', 'Research Account 2', '2026-01-01T00:00:00Z')
ON CONFLICT (account_code) DO UPDATE
SET base_currency = EXCLUDED.base_currency,
    account_name = EXCLUDED.account_name;

INSERT INTO rdb.strategies (strategy_code, strategy_name, description, created_at)
VALUES
    ('mean_reversion_v1', 'Mean Reversion V1', 'Fixture strategy for RDB ledger experiments.', '2026-01-01T00:00:00Z'),
    ('momentum_v1', 'Momentum V1', 'Secondary fixture strategy.', '2026-01-01T00:00:00Z')
ON CONFLICT (strategy_code) DO UPDATE
SET strategy_name = EXCLUDED.strategy_name,
    description = EXCLUDED.description;

INSERT INTO rdb.instruments (symbol, base_asset, quote_asset, tick_size, lot_size, is_active)
VALUES
    ('BTCUSDT', 'BTC', 'USDT', 0.0100000000, 0.0001000000, true),
    ('ETHUSDT', 'ETH', 'USDT', 0.0100000000, 0.0010000000, true)
ON CONFLICT (symbol) DO UPDATE
SET base_asset = EXCLUDED.base_asset,
    quote_asset = EXCLUDED.quote_asset,
    tick_size = EXCLUDED.tick_size,
    lot_size = EXCLUDED.lot_size,
    is_active = EXCLUDED.is_active;

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
VALUES
    (
        'A1-MR-BTC-0001',
        'A1',
        'mean_reversion_v1',
        'BTCUSDT',
        'buy',
        'limit',
        0.5000000000,
        60000.0000000000,
        'filled',
        '2026-01-02T09:30:00Z',
        '2026-01-02T09:31:00Z'
    ),
    (
        'A1-MR-BTC-0002',
        'A1',
        'mean_reversion_v1',
        'BTCUSDT',
        'sell',
        'limit',
        0.1000000000,
        62000.0000000000,
        'filled',
        '2026-01-03T10:00:00Z',
        '2026-01-03T10:01:00Z'
    ),
    (
        'A2-MOM-ETH-0001',
        'A2',
        'momentum_v1',
        'ETHUSDT',
        'buy',
        'market',
        3.0000000000,
        NULL,
        'filled',
        '2026-01-02T11:00:00Z',
        '2026-01-02T11:00:05Z'
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
    updated_at = EXCLUDED.updated_at;

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
VALUES
    ('FILL-BTC-0001-1', 'A1-MR-BTC-0001', 1, 0.3000000000, 59950.0000000000, 'USDT', 17.9850000000, 'maker', '2026-01-02T09:30:30Z'),
    ('FILL-BTC-0001-2', 'A1-MR-BTC-0001', 2, 0.2000000000, 60000.0000000000, 'USDT', 12.0000000000, 'maker', '2026-01-02T09:31:00Z'),
    ('FILL-BTC-0002-1', 'A1-MR-BTC-0002', 1, 0.1000000000, 62050.0000000000, 'USDT', 6.2050000000, 'taker', '2026-01-03T10:01:00Z'),
    ('FILL-ETH-0001-1', 'A2-MOM-ETH-0001', 1, 3.0000000000, 3100.0000000000, 'USDT', 9.3000000000, 'taker', '2026-01-02T11:00:05Z')
ON CONFLICT (fill_id) DO UPDATE
SET client_order_id = EXCLUDED.client_order_id,
    fill_sequence = EXCLUDED.fill_sequence,
    fill_quantity = EXCLUDED.fill_quantity,
    fill_price = EXCLUDED.fill_price,
    fee_currency = EXCLUDED.fee_currency,
    fee_amount = EXCLUDED.fee_amount,
    liquidity = EXCLUDED.liquidity,
    filled_at = EXCLUDED.filled_at;

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
    ('CASH-A1-DEPOSIT-0001', 'A1', 'USDT', 100000.0000000000, 'deposit', 'deposit', 'WIRE-0001', '2026-01-01T00:00:00Z'),
    ('CASH-A1-BTC-0001-TRADE', 'A1', 'USDT', -29985.0000000000, 'trade', 'order', 'A1-MR-BTC-0001', '2026-01-02T09:31:00Z'),
    ('CASH-A1-BTC-0001-FEE', 'A1', 'USDT', -29.9850000000, 'fee', 'order', 'A1-MR-BTC-0001', '2026-01-02T09:31:00Z'),
    ('CASH-A1-BTC-0002-TRADE', 'A1', 'USDT', 6205.0000000000, 'trade', 'order', 'A1-MR-BTC-0002', '2026-01-03T10:01:00Z'),
    ('CASH-A1-BTC-0002-FEE', 'A1', 'USDT', -6.2050000000, 'fee', 'order', 'A1-MR-BTC-0002', '2026-01-03T10:01:00Z'),
    ('CASH-A2-DEPOSIT-0001', 'A2', 'USDT', 25000.0000000000, 'deposit', 'deposit', 'WIRE-0002', '2026-01-01T00:00:00Z'),
    ('CASH-A2-ETH-0001-TRADE', 'A2', 'USDT', -9300.0000000000, 'trade', 'order', 'A2-MOM-ETH-0001', '2026-01-02T11:00:05Z'),
    ('CASH-A2-ETH-0001-FEE', 'A2', 'USDT', -9.3000000000, 'fee', 'order', 'A2-MOM-ETH-0001', '2026-01-02T11:00:05Z')
ON CONFLICT (entry_id) DO UPDATE
SET account_code = EXCLUDED.account_code,
    currency = EXCLUDED.currency,
    amount = EXCLUDED.amount,
    reason = EXCLUDED.reason,
    reference_type = EXCLUDED.reference_type,
    reference_id = EXCLUDED.reference_id,
    occurred_at = EXCLUDED.occurred_at;

INSERT INTO rdb.position_snapshots (
    account_code,
    strategy_code,
    symbol,
    quantity,
    average_entry_price,
    market_price,
    snapshot_at
)
VALUES
    ('A1', 'mean_reversion_v1', 'BTCUSDT', 0.4000000000, 59970.0000000000, 62100.0000000000, '2026-01-03T23:59:00Z'),
    ('A2', 'momentum_v1', 'ETHUSDT', 3.0000000000, 3100.0000000000, 3150.0000000000, '2026-01-03T23:59:00Z')
ON CONFLICT (account_code, strategy_code, symbol, snapshot_at) DO UPDATE
SET quantity = EXCLUDED.quantity,
    average_entry_price = EXCLUDED.average_entry_price,
    market_price = EXCLUDED.market_price;
