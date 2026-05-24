# Database Schema

## trade_journal

- id
- user_id
- signal_id
- mode
- exchange
- symbol
- strategy
- timeframe
- side
- entry_price
- current_price
- exit_price
- size_usd
- quantity
- leverage
- risk_percent
- stop_loss
- take_profit
- fees
- slippage_bps
- status
- result
- close_reason
- pnl
- pnl_percent
- mfe
- mae
- created_at
- updated_at
- closed_at
- screenshots
- ai_review

`mode` разделяет два журнала:

- `virtual` - виртуальные сделки внутри приложения.
- `real` - будущие реальные сделки, синхронизированные через биржевые адаптеры.

В коде подготовлены SQLAlchemy-модель `TradeJournalRecord` и `SqlAlchemyTradeRepository`. Текущий MVP использует `InMemoryTradeRepository`, но `TradeService` уже работает через repository boundary, поэтому PostgreSQL-реализация сможет заменить in-memory слой без изменения API.

## signals

- id
- symbol
- strategy
- direction
- score
- timestamp
- status
- confirmed_trade_id
- decision_mode
- decision_note

## features

- symbol
- timestamp
- volume_spike
- oi_change
- funding_rate
