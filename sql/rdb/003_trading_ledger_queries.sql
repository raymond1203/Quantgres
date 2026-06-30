SELECT
    account_code,
    strategy_code,
    symbol,
    quantity,
    average_entry_price,
    market_price,
    (market_price - average_entry_price) * quantity AS unrealized_pnl
FROM rdb.position_snapshots
WHERE snapshot_at = (
    SELECT max(snapshot_at)
    FROM rdb.position_snapshots
)
ORDER BY account_code, symbol;

SELECT
    account_code,
    currency,
    sum(amount) AS cash_balance
FROM rdb.cash_ledger_entries
GROUP BY account_code, currency
ORDER BY account_code, currency;

SELECT
    orders.client_order_id,
    orders.account_code,
    orders.strategy_code,
    orders.symbol,
    orders.side,
    orders.status,
    sum(fills.fill_quantity) AS filled_quantity,
    sum(fills.fill_quantity * fills.fill_price) / sum(fills.fill_quantity) AS average_fill_price,
    sum(fills.fee_amount) AS total_fee
FROM rdb.orders
JOIN rdb.fills USING (client_order_id)
GROUP BY
    orders.client_order_id,
    orders.account_code,
    orders.strategy_code,
    orders.symbol,
    orders.side,
    orders.status
ORDER BY orders.client_order_id;

EXPLAIN (ANALYZE, BUFFERS)
SELECT
    account_code,
    currency,
    sum(amount) AS cash_balance
FROM rdb.cash_ledger_entries
WHERE account_code = 'A1'
GROUP BY account_code, currency;
