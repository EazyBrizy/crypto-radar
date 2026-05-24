# Trade Journal

Для MVP журнал делится на:

- `Virtual Trades` - виртуальные сделки, открытые через Manual Confirm.
- `Real Trades` - будущие реальные сделки через биржевые адаптеры.

Текущая реализация:

- `POST /api/v1/signals/{signal_id}/confirm` с `mode=virtual` открывает виртуальную сделку.
- `POST /api/v1/signals/{signal_id}/reject` отклоняет сигнал и сохраняет причину решения.
- `GET /api/v1/trades/virtual` возвращает журнал виртуальных сделок.
- `POST /api/v1/trades/virtual/{trade_id}/close` закрывает виртуальную сделку вручную.

Открытые virtual trades обновляются по realtime market price. Если цена достигает `stop_loss` или финального `take_profit`, сделка закрывается автоматически.

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

Trade score:
0–100 based on execution quality
