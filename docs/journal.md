# Trade Journal

Backtest note: `GET /api/v1/trades` also surfaces Strategy Test Lab trades as
journal projections with `source="backtest"`, `tags` including `backtest`, and
`run_id`. These projections read `analytics.strategy_test_trades` through
`StrategyTestJournalAdapter` and must not write to `orders`, `positions`,
portfolio balances, or `risk_state`.

Для MVP журнал сделок делится на:

- `Virtual Trades` - виртуальные сделки, открытые через Manual Confirm.
- `Real Trades` - будущие реальные сделки через биржевые адаптеры.

Текущая реализация:

- `POST /api/v1/signals/{signal_id}/confirm` с `mode=virtual` открывает виртуальную сделку.
- `POST /api/v1/signals/{signal_id}/reject` отклоняет сигнал и сохраняет причину решения.
- `GET /api/v1/trades` возвращает единый journal по virtual и real trades.
- `GET /api/v1/trades/virtual` читает виртуальные сделки из PostgreSQL `orders`, `order_fills`, `positions`, `portfolio_balances`, `portfolio_balance_ledger`.
- `GET /api/v1/trades/real` читает нормализованные реальные сделки из PostgreSQL `external_exchange_trades`; импорт пока ждет connector.
- `POST /api/v1/trades/virtual/{trade_id}/close` закрывает виртуальную сделку вручную.

Открытые virtual trades обновляются по realtime market price. Если цена достигает `stop_loss` или финального `take_profit`, сделка закрывается автоматически.

DB boundary:

- единый DTO: `TradeJournalEntry`;
- repository boundary: `TradeRepository`;
- production source of truth: `PostgresVirtualTradeRepository`;
- virtual trading analytics: ClickHouse `analytics.virtual_trade_events`;
- realtime fanout: Redis `pubsub:portfolio:{user_id}` и `pubsub:realtime`.

Metrics:

- PnL
- MFE (max favorable excursion)
- MAE (max adverse excursion)
- fees
- slippage
- risk percent
- close reason

Mistakes detection:

- early exit
- bad stop
- overtrading

Trade score: 0-100 based on execution quality.
