# Database Schema

## trades

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
