# Charts

The MVP chart layer uses TradingView Lightweight Charts.

Use it for:

- candles and volume
- entry zone lines
- SL and TP lines
- EMA overlays
- signal and trade markers
- realtime price/candle updates

`ChartPanel` is the low-level Lightweight Charts wrapper.
`PositionChartPanel` is the domain wrapper for signal/trade overlays. It accepts
both virtual and real trades because both share the same chart concepts:
entry, stop loss, take profit, side, status, and marker time.

Do not introduce TradingView Charting Library unless the product needs a full
terminal experience. Lightweight Charts is the default for Radar and position
views.
