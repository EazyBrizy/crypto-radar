# Strategy MVP Infrastructure Hints

## Responsibility Boundary Update

- Strategy block searches setups, classifies them, stores layer snapshots, and renders the classification in Radar.
- Strategy status is not the final permission to enter a position.
- Position entry validation belongs to the risk-management / risk-reward module: risk preview, risk gate, execution quality, spread, slippage, orderbook depth, account limits, and user risk settings.
- Strategy pipeline may expose RR, invalidation, overextension, and exit-plan context, but it must not replace the risk/reward gate.

## Current Point 1.1 Rule

- If a strategy has `pair_scope = []`, it means "scan all configured scanner pairs". In this mode `Market Quality Filter` is a hard pre-strategy exclusion layer: bad volume, bad spread, low-liquidity tier, rough chart, or illiquid pump can block the setup before it is shown.
- If a strategy has explicit pairs in `pair_scope`, that list is treated as a manual strategy watchlist. The scanner must subscribe to those symbols, the strategy must evaluate only those pairs, and market-quality problems are warnings/classification context only. Explicit strategy pairs are not filtered out by quality.
- Candle history and latest-candle volume still remain required, because strategies cannot classify a setup reliably without enough feature data.
- The strategy module must stop at setup classification/status. Final entry permission stays in risk-management / risk-reward.

Документ фиксирует рабочие подсказки для большого блока стратегий. Цель MVP:
не ловить каждое движение, а отсеивать плохие сделки и оставлять только идеи,
где есть сценарий, риск, причина входа и понятная отмена идеи.

## Целевая Логика

Каждый сигнал должен проходить шесть слоев:

1. `Market Quality Filter`
2. `Market Regime Filter`
3. `Strategy Setup`
4. `Confirmation Layer`
5. `Risk / Invalidation Layer`
6. `Exit Management`

Сигнал не должен становиться входом только потому, что совпали EMA или цена
пробила уровень. Базовый путь:

```text
market data -> features -> quality -> regime -> strategy setup
  -> confirmation -> RR/invalidation/exit plan -> signal status
  -> PostgreSQL signal -> ClickHouse event -> Redis/WebSocket -> frontend
```

## Что Уже Реализовано

### Backend

- Есть три MVP-стратегии:
  - `trend_pullback_continuation`
  - `volatility_squeeze_breakout`
  - `liquidity_sweep_reversal`
- `FeatureEngine` строит свечные признаки: EMA 20/50/200, RSI 14, ATR 14,
  ADX proxy, Bollinger width percentile, Donchian 20, swing high/low, wick
  ratios, volume spike.
- `CandleService` агрегирует тики в `1m`, `5m`, `15m`, `1h`, `4h`, `1d`.
- `MarketScanner` прогревает Bybit OHLCV, обновляет свечи, строит признаки,
  запускает `StrategyEngine` и возвращает сигналы.
- `StrategySignalPipeline` now wraps every candidate with the six MVP layers:
  market quality, market regime, setup, confirmation, invalidation/risk status,
  and exit management.
- `MarketQualityService` builds a reusable ticker snapshot before strategy
  evaluation: 24h quote volume, spread bps, best bid/ask, source and warnings.
- `StrategyConfigService` reads/writes `user_strategy_configs`, creates default
  configs for active strategy versions, and exposes runtime configs to scanner.
- Strategy config updates validate `exchange_scope` against `market_exchanges`
  and explicit `pair_scope` against active `market_pairs`, so the scanner cannot
  be configured with missing or disabled instruments.
- Strategy config API reconfigures a running scanner after scope changes and
  publishes refreshed radar status with subscription/config hashes.
- `SupportResistanceService` builds higher-timeframe S/R levels from candle
  local extrema, clusters retests, and scores freshness, retest count and
  volume at the level.
- `MarketScanner` now passes higher-timeframe context features, market quality,
  S/R snapshots, and matching strategy configs into `StrategyEngine`.
- `SignalService` пишет сигнал в PostgreSQL, событие в ClickHouse
  `analytics.signal_events`, hot-cache/ranking в Redis и realtime событие.
- `RiskGateService` уже умеет проверять R:R, spread, slippage, price drift,
  orderbook depth, open/correlated risk, futures guard и user risk settings.
- `RiskMarketDataService` для risk preview получает Bybit ticker/orderbook
  через REST. Это работает на этапе входа/preview, но пока не является общим
  market-quality слоем перед генерацией сигнала.
- A separate scanner-time market-quality path now exists, but orderbook depth
  and slippage still belong to risk-management for final entry validation.

### PostgreSQL

- Есть `strategy_templates`, `strategy_versions`, `user_strategy_configs`.
- `user_strategy_configs` уже содержит нужные контейнеры для будущих настроек:
  `exchange_scope`, `pair_scope`, `timeframes`, `params`, `risk_settings`.
- `pair_scope = []` is the default all-pairs mode; non-empty `pair_scope`
  stores explicit exchange+symbol pairs for a strategy watchlist.
- Есть `trading_signals` и `trading_signal_events`.
- Есть `market_exchanges`, `market_assets`, `market_pairs`.
- Есть user watchlists и alert rules, но это отдельная пользовательская
  сущность, не настройки работы конкретной стратегии.
- Bootstrap сидит три стратегии, Bybit, демо-пары, демо-пользователя,
  default watchlist и risk settings.

### ClickHouse

- Есть `market.raw_exchange_events`, `market.trades`, `market.ohlcv_1m`,
  `market.ohlcv_5m`, `market.ohlcv_15m`, `market.ohlcv_1h`, `market.ohlcv_1d`,
  `market.indicator_values`.
- Есть `market.orderbook_l2_deltas`, `market.orderbook_snapshots`,
  `market.liquidity_snapshots`, но L2/orderbook/liquidity writer пока не
  подключен.
- Есть `analytics.signal_events` и `analytics.strategy_performance_daily`.

### Redis / Realtime

- Пишутся hot price keys `price:{exchange}:{symbol}`.
- Пишутся placeholder orderbook keys `orderbook:{exchange}:{symbol}`.
- Последние сигналы пишутся в `signals:latest`,
  `signals:latest:{strategy}` и `signals:latest:{exchange}:{symbol}`.
- Realtime события уже доходят до frontend через gateway/store/query-cache.

### Frontend

- Radar показывает ленту сигналов, детали, score breakdown, entry/SL/TP,
  risk-card и backend risk preview.
- Settings уже содержит большой блок risk management, exchange connections,
  alerts, watchlist и отображение timeframes.
- Settings now has a strategy configuration block: enable/disable strategy,
  select strategy exchanges, explicit pairs and timeframes, return to all-pairs
  mode, edit context-timeframe mapping, and edit basic market-quality/regime
  thresholds.
- Типы frontend уже знают `watchlist`, но текущая лента считает открытыми
  только `new`, `active`, `entry_touched`.

## Стыки Backend + DB + Frontend

### Где Что Хранить

PostgreSQL:

- шаблоны и версии стратегий;
- пользовательские конфиги стратегий;
- выбранные пары/биржи/таймфреймы для стратегии;
- сигналы как бизнес-сущности;
- статус сигнала и lifecycle events;
- snapshot плана сделки: entry, stop, targets, invalidation, exit plan;
- пользовательские risk settings.

ClickHouse:

- тики, сделки, свечи, индикаторы;
- quality/regime snapshots как market/time-series данные;
- signal events и runtime strategy analytics;
- будущие backtest/performance агрегаты.

Redis:

- горячие цены, bid/ask, orderbook cache;
- последние сигналы и realtime fanout;
- краткоживущие market-quality snapshots, если нужно быстро читать их в UI.

Frontend:

- читает конфиги стратегий через API;
- отображает стратегии и их пары в Settings;
- фильтрует Radar по status/strategy/exchange/symbol/timeframe/direction;
- показывает причину статуса, invalidation, RR, quality/regime checks и exit
  management в деталях сигнала.

### Минимальный Контракт Сигнала

Для MVP лучше расширять `features_snapshot`, не плодя сразу много колонок.
Но `status` должен быть отдельной колонкой, потому что по нему нужны фильтры.

```json
{
  "status": "watchlist | ready | actionable | wait_for_pullback | invalidated | expired | confirmed | closed",
  "status_reason": "why this is not actionable yet",
  "quality": {
    "passed": true,
    "tier": "major | mid_alt | low_liquidity",
    "volume_24h_quote": 100000000,
    "spread_bps": 4.5,
    "history_ok": true,
    "rough_chart_score": 12,
    "warnings": []
  },
  "regime": {
    "signal_timeframe": "15m",
    "context_timeframe": "1h",
    "direction": "bullish | bearish | range | volatile",
    "strength": "weak | normal | strong",
    "alignment": "aligned | mixed | against"
  },
  "setup": {
    "name": "volatility_squeeze_breakout",
    "stage": "forming | ready | confirmed"
  },
  "confirmation": {
    "passed": true,
    "checks": []
  },
  "invalidation": {
    "price": 0,
    "conditions": []
  },
  "exit_plan": {
    "tp": [],
    "breakeven": {},
    "trailing": {}
  }
}
```

## Статусы Сигналов

Целевые статусы:

- `watchlist`: условия формируются, входа нет.
- `ready`: сетап есть, ждем подтверждения.
- `actionable`: вход подтвержден и risk/RR проходят.
- `wait_for_pullback`: идея есть, но текущая свеча слишком большая.
- `invalidated`: идея сломана.
- `expired`: идея устарела по TTL.
- `confirmed`: пользователь подтвердил/открыл сделку.
- `closed`: сделка/идея закрыта.

Текущий разрыв:

- DB check constraint сейчас разрешает только
  `new`, `active`, `confirmed`, `expired`, `invalidated`, `closed`.
- API/frontend частично знают `watchlist`, но repository мапит `watchlist` в
  `new`, а actionable сейчас фактически выражается через `active`.
- Frontend feed скрывает `watchlist`, потому что открытыми считает только
  `new`, `active`, `entry_touched`.

Рекомендация:

- миграцией расширить DB statuses;
- временно поддержать старые `new`/`active` как aliases;
- в UI показывать человекочитаемые статусы:
  `WATCHLIST`, `READY`, `ACTIONABLE`, `WAIT FOR PULLBACK`, `INVALIDATED`;
- добавить фильтр Radar по статусу, стратегии, паре, бирже и таймфрейму.

Note: the legacy gap/recommendation notes immediately above are superseded by
the implementation status below.

Implementation status for point 1.3:

- DB/API/frontend schemas support `watchlist`, `ready`, `actionable`,
  `wait_for_pullback`, `invalidated`, `expired`, `confirmed`, and legacy
  `new/active`.
- Repository stores strategy status directly instead of collapsing staged
  statuses to `new/active`.
- Radar feed includes open staged statuses and has status filter chips.
- Strategy pipeline respects strategy-emitted stages:
  `watchlist` stays watchlist, `ready` stays ready unless a stronger downgrade
  applies, and actionable candidates can become actionable after shared layers.
- The three MVP strategies now emit forming candidates:
  Squeeze pre-breakout watchlist, Trend Pullback approaching EMA zone watchlist,
  Liquidity Sweep level test watchlist, and ready states while confirmation is
  incomplete.
- Frontend disables entry actions unless signal status is
  `actionable`/`active`/`entry_touched`; Paper Trade is blocked for
  `watchlist`, `ready`, `wait_for_pullback`, and `invalidated`.
- `SignalLifecycleWorker` advances stored open ideas on closed candles:
  `watchlist -> ready`, `ready -> actionable`, `wait_for_pullback -> ready/actionable`,
  and open ideas -> `invalidated` when their logical invalidation plan breaks.
- Lifecycle transitions write `trading_signal_events`, enqueue outbox events,
  fan out through the signal service, and publish realtime `signal.updated` or
  `signal.invalidated`.
- Radar now has `open ideas` and `history` views; history shows
  `invalidated`/`expired` signals outside the normal open feed.

Remaining for point 1.3:

- Tune lifecycle thresholds per strategy after backtests, especially the
  confirmation candle and pullback retest rules.
- Add a richer archive/analytics screen later if the compact Radar history tab
  is not enough for reviewing invalidated/expired ideas.

## Strategy Settings / Watchlist Per Strategy

Требование: у каждой стратегии должен быть свой набор торговых пар разных бирж
и собственные настройки.

Уже подходящая база:

- `user_strategy_configs.exchange_scope`
- `user_strategy_configs.pair_scope`
- `user_strategy_configs.timeframes`
- `user_strategy_configs.params`
- `user_strategy_configs.risk_settings`

MVP-представление `pair_scope`:

```json
[
  {
    "exchange": "bybit",
    "symbol": "BTCUSDT",
    "pair_id": "uuid-if-known",
    "enabled": true,
    "timeframes": ["15m", "1h"]
  }
]
```

Что нужно сделать:

- backend CRUD для strategy configs;
- endpoint списка templates/versions;
- загрузку enabled configs в scanner;
- генерацию сигналов только по парам и таймфреймам из strategy config;
- Settings UI: выбрать стратегию, включить/выключить, выбрать биржи/пары,
  выбрать timeframes, настроить thresholds;
- валидировать пары через `market_pairs`, а не хранить произвольные строки без
  проверки.

Implementation status for this section:

- MVP config API/UI exists for user strategy configs.
- Runtime scanner matching uses enabled strategy configs, timeframes and
  explicit pair scope.
- Pair, exchange, timeframe and basic quality-threshold selection exist in
  Settings.
- Explicit pairs are strictly validated through `market_pairs`; missing pairs,
  disabled pairs, and disabled exchanges return API validation errors instead
  of being persisted.
- Scanner subscriptions have a config-version/hash path and are reconfigured
  after strategy scope changes without a manual backend restart.
- Templates/versions management screen is still pending.
- Empty `pair_scope` means all-pairs scanning and hard market-quality
  exclusion.
- Non-empty `pair_scope` means manual strategy watchlist and no quality-based
  exclusion for selected pairs.
- Explicit strategy pairs are added to scanner subscriptions even when they are
  not in the global Radar symbol list.

## Layer 1: Market Quality Filter

Назначение: не давать стратегиям работать на плохом инструменте.

Минимальные проверки:

- `24h quote volume >= min_volume_by_tier`;
- `spread_bps <= max_spread_by_tier`;
- хватает истории свечей для signal и context timeframe;
- нет экстремально рваного графика;
- нет аномального гэпа/пампа без ликвидности.

Предлагаемые tiers:

- `major`: BTC, ETH, SOL, BNB, XRP. Разрешены более частые сигналы.
- `mid_alt`: средние альты. Строже volume/spread и выше min score.
- `low_liquidity`: низколиквидные альты. Для текущих трех стратегий лучше
  снижать статус до `watchlist` или блокировать. Поиск неэффективностей делаем
  позже отдельным модулем.

MVP-алгоритм:

```text
pair_tier = from market_pairs.metadata or base symbol fallback
volume_ok = ticker.quote_volume_24h >= thresholds[pair_tier].min_volume_24h
spread_ok = current_spread_bps <= thresholds[pair_tier].max_spread_bps
history_ok = signal_history >= strategy_min and context_history >= context_min
roughness = sum(abs(close-open)/ATR + wick_penalties over N candles)
gap_or_pump = abs(close - prev_close) > 3 ATR or N-candle move > threshold
liquidity_ok = orderbook_depth/spread available or tier is trusted major

if not volume_ok or not spread_ok or not history_ok:
  BLOCK
if roughness high or gap_or_pump without liquidity:
  WATCHLIST_ONLY or BLOCK
else:
  PASS
```

With strategy pair scope:

```text
if pair_scope is empty:
  apply quality failures as hard pre-strategy filter
else:
  evaluate only explicit pairs
  convert volume/spread/roughness/liquidity failures to warnings
  do not exclude the signal by market quality
```

Где брать данные:

- 24h volume/spread: Bybit ticker сейчас есть в `RiskMarketDataService`, но его
  нужно вынести/переиспользовать до генерации сигнала.
- Свечная история: `CandleService` и ClickHouse `market.ohlcv_*`.
- Ликвидность: сначала REST ticker/orderbook, позже Redis hot orderbook и
  ClickHouse `market.liquidity_snapshots`.

## Layer 2: Market Regime Filter

Нужно минимум два таймфрейма:

| Signal timeframe | Context timeframe |
| --- | --- |
| `1m` | `15m` или `5m` |
| `5m` | `1h` |
| `15m` | `1h` |
| `1h` | `4h` |
| `4h` | `1d` |

Implementation status for point 1.2:

- Scanner now requests all context timeframes returned by
  `context_timeframes_for(signal_timeframe)`.
- Primary context mapping is `5m -> 1h`, `15m -> 1h`, `1h -> 4h`,
  `4h -> 1d`.
- Macro context mapping is `5m -> 4h`, `15m -> 4h`, `1h -> 1d`,
  `4h -> 1d`.
- `MarketRegimeFilter` writes checks for context timeframe, context history,
  primary alignment, trend strength, macro alignment, and context
  support/resistance distance.
- Context support/resistance now uses `SupportResistanceService` snapshots when
  available; swing/Donchian remains only a fallback proxy.
- S/R levels are built from local extrema, clustered retests, level freshness
  and volume at the level. The nearest relevant obstacle is measured in ATR.
- Strategy params support `context_timeframe_map`, `context_obstacle_min_atr`
  and `context_level_min_strength`; Settings exposes context TF, min S/R ATR
  and S/R strength controls per strategy.
- Strong higher-timeframe conflict reduces score and forces `watchlist`.
- Nearby higher-timeframe support/resistance reduces score and keeps the setup
  at `ready` instead of `actionable`.
- Frontend signal details show non-passed regime checks so the user can see why
  a signal was downgraded.

MVP-алгоритм:

```text
context = features(exchange, symbol, context_timeframe)

trend_direction:
  bullish if close > EMA200 and EMA50 > EMA200
  bearish if close < EMA200 and EMA50 < EMA200
  range otherwise

trend_strength:
  strong if ADX proxy rising and EMA distance > 1 ATR
  weak if range/chop

alignment:
  aligned if signal direction matches context trend
  mixed if context is range
  against if opposite strong trend

macro_context:
  for 15m liquidity sweep also check 4h
  strong macro trend against the signal forces watchlist

context_obstacle:
  long checks nearest context S/R resistance above entry
  short checks nearest context S/R support below entry
  fallback is context swing/donchian when no S/R snapshot exists
  if distance <= strategy min S/R ATR, keep signal ready instead of actionable
```

Применение:

- Если signal long и context bullish: повышаем score/status.
- Если signal против сильного context trend: снижаем score или оставляем
  `watchlist`.
- Breakout вверх слабее, если context рядом с сопротивлением или уже
  overextended.
- Liquidity Sweep против сильного тренда требует более жесткого подтверждения:
  wick, volume, reclaim и follow-through.

Инфраструктурно нужен объект `StrategyEvaluationContext`:

```text
signal_features
context_features
context_features_by_timeframe
quality_result
regime_result
strategy_config
```

## Layer 3-6 По Стратегиям

### Trend Pullback Continuation

Что уже есть:

- min history 200;
- EMA20/50/200, RSI, ATR, volume spike;
- long/short по EMA50 vs EMA200 и close относительно EMA200;
- зона отката к EMA20/EMA50 в пределах ATR;
- bullish/bearish candle;
- volume >= 1.1x добавляет score;
- stop от swing low/high +/- `0.5 ATR`;
- TP по умолчанию 1R/2R.

Что нужно добавить:

- market-quality до стратегии;
- context timeframe: `15m -> 1h`, `1h -> 4h`, `4h -> 1d`;
- статусы `watchlist/ready/actionable`;
- общий overextension guard;
- hard/downgrade rule по RR;
- invalidation plan;
- параметры из `user_strategy_configs`, а не константы в коде.

Предлагаемый workflow:

```text
WATCHLIST:
  context not bearish for long / not bullish for short
  EMA trend exists
  price is approaching EMA20/EMA50 pullback zone

READY:
  price is in pullback zone
  RSI is in allowed reset band
  no quality blockers

ACTIONABLE:
  candle closes back in trend direction
  volume >= 1.1x volume_ma
  context is aligned or not strongly against
  body <= 2.0 ATR
  RR >= min_rr

WAIT_FOR_PULLBACK:
  confirmation candle body > 2.0-2.5 ATR
```

Invalidation:

- Long invalidated if close below EMA50;
- or close below last swing low;
- or RSI loses 45 zone;
- or context timeframe flips bearish.
- Short зеркально: close above EMA50/swing high, RSI above 55, context flips
  bullish.

Exit:

- stop: swing +/- `0.5 ATR`;
- TP1: `1R`;
- TP2: `2R` or nearest context resistance/support if it is closer and still
  satisfies min RR;
- after TP1: breakeven;
- trailing: EMA20 or last minor swing.

### Volatility Squeeze Breakout

Что уже есть:

- min history 60;
- breakout over/under Donchian 20;
- BB width percentile < 20 adds volatility score;
- volume > 1.5x adds score;
- ATR increasing adds score;
- RSI overheat adds penalty;
- candle body > 2.5 ATR adds penalty;
- stop = breakout level +/- `1 ATR`;
- TP по умолчанию 1R/2R.

Что нужно добавить:

- pre-breakout `watchlist` и `ready`;
- WAIT_FOR_PULLBACK вместо обычной penalty после огромной свечи;
- context resistance/support check;
- explicit range metadata: range high/low/mid, compression duration;
- RR до ближайшей цели;
- invalidation plan.

Предлагаемый workflow:

```text
WATCHLIST:
  BB width percentile < 20
  range is mature enough
  price is still inside Donchian range

READY:
  price is in upper 20% of range for long or lower 20% for short
  volume is starting to expand
  context does not block direction

ACTIONABLE:
  candle closes outside Donchian range
  volume > 1.5x volume_ma
  ATR is expanding
  RSI in allowed impulse band
  body <= 2.0-2.5 ATR
  no nearby context resistance/support blocking target
  RR >= min_rr

WAIT_FOR_PULLBACK:
  breakout is real but candle body > 2.0-2.5 ATR
  entry changes to retest of Donchian level, VWAP, or EMA20
```

Invalidation:

- Long invalidated if close returns inside previous range;
- or breakout candle is fully retraced;
- or volume drops below average on next candles;
- or price cannot hold retest level.
- Short зеркально.

Exit:

- stop: breakout level +/- `1 ATR`;
- TP1: `1.5R`;
- TP2: `2.5R` or next context level;
- optional trailing after TP1 while ATR expands.

Implementation status after Strategy 2 hardening:

- `FeatureEngine` now exposes squeeze-specific candle metrics:
  `atr_sma_50`, `range_20`, `range_50_average`, and `range_20_atr`.
- `VolatilitySqueezeBreakoutStrategy` requires measurable compression before
  it emits a setup: BB width percentile below threshold, ATR below ATR SMA 50,
  current 20-candle range below recent average, and Donchian range not wider
  than the configured ATR limit.
- Breakouts are candle-close based. Wick-only breaks remain `ready`, not
  `actionable`.
- Confirmation checks include configurable volume impulse, close location in
  the breakout candle, ATR expansion, and rejection-wick limit.
- Strategy params for Squeeze Breakout are persisted in
  `user_strategy_configs.params`: `bb_width_percentile_threshold`,
  `volume_spike_multiplier`, `min_close_position`,
  `max_breakout_wick_ratio`, `max_squeeze_range_atr`,
  `watchlist_distance_atr`, `breakout_stop_atr`, and
  `narrow_range_stop_atr`.
- Signal snapshots now include aggressive entry, conservative retest entry
  zone, Donchian range metadata, close/wick quality, and measured-move target.
- Exit management adds measured-move TP3 for Squeeze Breakout, while TP1/TP2
  use 1.5R/2.5R.
- Settings UI exposes the most useful Squeeze Breakout knobs without adding
  new DB columns.

Remaining tails:

- Backtest and tune squeeze thresholds per timeframe and symbol tier.
- Add BTC/macro shock filter before promoting opposite-side alt breakouts.
- Persist/aggregate S/R snapshots only if runtime S/R recomputation becomes a
  scanner bottleneck.
- Add production analytics for false-breakout rate after the daily strategy
  performance aggregator exists.

### Liquidity Sweep Reversal

Что уже есть:

- min history 30;
- long when low sweeps swing low and close reclaims it;
- short when high sweeps swing high and close returns below it;
- wick ratio check;
- volume > 1.3x adds score;
- RSI extremes add penalty;
- stop = sweep low/high +/- `0.3 ATR`;
- TP1 = середина диапазона;
- TP2 = противоположная граница диапазона.

Что нужно добавить:

- staged status: `watchlist -> ready -> actionable`;
- follow-through confirmation on next 1-3 candles;
- context trend penalty;
- stricter market-quality for low-liquidity pairs;
- invalidation monitoring.

Предлагаемый workflow:

```text
WATCHLIST:
  price is close to prior swing high/low liquidity
  range boundaries are valid
  market quality is acceptable

READY:
  sweep happened
  candle reclaimed the swept level
  wick ratio is large enough

ACTIONABLE:
  volume > 1.3x volume_ma
  next candle or current close confirms reclaim
  price holds above swept low for long / below swept high for short
  context is not strongly against, or confirmation is stronger
  RR to mid/range target >= min_rr
```

Invalidation:

- Long invalidated if price closes back below swept low;
- or next candles fail to reclaim/hold level;
- or sweep candle low is broken again;
- or volume disappears after reclaim.
- Short зеркально: close back above swept high, high broken again, failed
  rejection.

Exit:

- stop: sweep extreme +/- `0.3 ATR`;
- TP1: range midpoint;
- TP2: opposite range boundary;
- if TP1 is too close and RR < min, do not make actionable.

Implementation status for Strategy 3 pass:

- Backend feature layer now derives 20-50 candle fractal swing levels and
  keeps level touch count, age and local volume score in `Features`.
- Liquidity Sweep scoring was upgraded to the 100-point budget: level quality,
  sweep/reclaim, wick ratio, volume, confirmation candle, micro BOS and
  ADX/trend context, with penalties for settled breaks, follow-through
  breakouts and strong local trend conflict.
- The strategy now supports aggressive and conservative entry modes through
  staged statuses: `watchlist`, `ready`, `actionable`.
- Higher-timeframe level confluence is evaluated in the shared regime layer via
  S/R snapshots or context swing/Donchian fallback.
- Structured invalidation metadata now includes swept level, sweep extreme,
  wick ratio, touch count, aggressive entry and conservative confirmation zone.
- Exit management adds a Liquidity Sweep TP3 runner after micro-BOS/ATR
  trailing.
- Strategy config defaults and Settings UI expose the main Liquidity Sweep
  knobs without adding PostgreSQL columns: wick threshold, sweep volume,
  confirmation volume, close strength, stop ATR, retests and HTF confluence.
- Signal Details now has a Liquidity Sweep block showing swept level, wick,
  touches, aggressive entry and confirmation zone.

Remaining tails for Strategy 3:

- Previous session/day high/low levels are not yet first-class inputs; MVP uses
  fractal/equal swing levels plus higher-timeframe S/R snapshots.
- Orderbook/liquidity-depth writer is still missing, so bad liquidity/spread is
  handled by scanner quality and execution-time risk preview, not by live L2
  sweep absorption.
- News impulse filtering is not implemented; strong breakout/news regimes must
  be handled later by a macro/news guard or analytics rule.
- Micro BOS is based on previous candle high/low for MVP. A richer internal
  market-structure model can replace it after backtests.
- Thresholds need calibration per symbol tier and timeframe after backtests and
  paper-trade samples.

## Overextension Guard

Правило должно быть общим для всех стратегий:

```text
body_atr = abs(close - open) / ATR
range_atr = (high - low) / ATR

if body_atr > strategy.max_body_atr:
  status = wait_for_pullback
  entry_plan = retest of trigger level / EMA / VWAP
  market order disabled
```

MVP thresholds:

- Trend Pullback: `2.0 ATR`;
- Squeeze Breakout: `2.5 ATR`;
- Liquidity Sweep: `2.0 ATR`, дополнительно проверять wick/body.

Важно: это не просто штраф к score. Если свеча слишком большая, идея может быть
хорошей, но вход сейчас плохой.

Implementation status for point 1.4:

- Overextension is a shared strategy-pipeline classifier, not a risk/reward
  gate.
- If the current signal candle is too late to chase, the pipeline keeps the
  setup but changes status to `wait_for_pullback`.
- The guard now evaluates:
  - candle body in ATR;
  - full candle range in ATR;
  - body-to-range ratio;
  - whether the candle body goes in the signal direction;
  - whether close is near the directional extreme;
  - rejection wick against the signal direction;
  - ATR expansion and volume impulse;
  - liquidity-sweep absorption wick allowance.
- Dynamic body threshold starts from per-strategy defaults:
  `trend_pullback_continuation=2.0`, `volatility_squeeze_breakout=2.5`,
  `liquidity_sweep_reversal=2.0`.
- Threshold is tightened in high ATR%, ATR expansion, high-volume impulse and
  marubozu-style candles, and slightly relaxed for valid liquidity absorption
  sweeps.
- Pullback target is now structured and numeric where data exists:
  breakout/breakdown level, EMA/VWAP pullback zone, swept liquidity level, or
  VWAP fallback.
- For `wait_for_pullback`, the strategy card entry zone is moved to the planned
  retest zone and the original reason remains in `status_reason`.
- `FeatureEngine` calculates session VWAP for intraday candle features.
- Settings UI exposes per-strategy `max_body_atr` and `max_range_atr`.
- Signal Details shows why the user should not enter now and where to wait for
  the pullback.
- Frontend blocks entry actions for `wait_for_pullback`.

Remaining for point 1.4:

- Tune thresholds after backtests and live paper-trade review.

## Risk / Reward Guard

Сейчас RR считается в `build_signal`, а risk-gate проверяет RR при preview или
confirm. Для точности стратегий нужен guard еще до статуса `actionable`.

Алгоритм:

```text
risk = abs(entry - stop)
reward = abs(primary_target - entry)
rr = reward / risk

if rr < 1.5:
  status = watchlist or invalidated_by_rr
if 1.5 <= rr < 2.0:
  status can be actionable only for high-quality major/context-aligned setups
if rr >= 2.0:
  status can be actionable
```

Для UI:

- показывать `RR blocked` как причину;
- показывать ближайшую цель, из-за которой RR не проходит;
- не давать кнопку входа, если backend status не `actionable` или risk preview
  failed.

Implementation status for point 1.5:

- RR is checked in the shared strategy pipeline before a signal can become
  `actionable`.
- The check uses strategy `risk_settings.min_rr_ratio`; when it is not set, the
  runtime inherits `min_rr_ratio` from the current risk-management profile, with
  `2.0` as fallback.
- Strategy settings support `rr_target`:
  - `final` uses the planned final target, matching the execution-time
    risk-management gate;
  - `nearest` can enforce the nearest/TP1 target when we want stricter
    strategy classification.
- If RR fails and cards are not hidden, the signal remains visible with status
  `ready`, status reason `Risk/reward blocked...`, and the reason is added to
  signal risks.
- Strategy settings support `hide_failed_rr_signals`; when enabled, failed RR
  ideas are not returned to Radar.
- Settings UI exposes per-strategy `Min RR`, `RR target`, and
  `Hide low-RR cards`.
- Backend signal response exposes `first_target_rr`, `final_target_rr`,
  `selected_rr`, `selected_rr_target`, and `min_rr_ratio`.
- Default RR target is strategy-specific: Trend Pullback and Squeeze Breakout
  use `final`; Liquidity Sweep uses `nearest`.
- Signal Details shows nearest/final/selected RR and the target used by the
  strategy guard.
- Paper Trade remains blocked because frontend entry actions require
  `actionable`/`active`/`entry_touched`.

Remaining for point 1.5:

- Backtest the strategy-specific RR defaults and tune them per timeframe.

## Invalidation Layer

Invalidation - это не просто stop-loss. Это логическая отмена идеи.

MVP-структура:

```json
{
  "price": 98000,
  "type": "structure_close",
  "conditions": [
    "15m close below EMA50",
    "15m close below last swing low",
    "RSI below 45"
  ],
  "hard_stop": 97800,
  "expires_at": "..."
}
```

Backend lifecycle:

- при создании сигнала сохранять invalidation в `features_snapshot`;
- на каждой новой свече по открытым сигналам запускать `SignalLifecycleWorker`;
- если условие отмены выполнено, переводить сигнал в `invalidated` и писать
  `trading_signal_events`;
- frontend получает `signal.invalidated` realtime event и убирает/помечает
  карточку.

Implementation status for point 1.6:

- Strategy pipeline now stores actionable invalidation metadata, not just text:
  EMA50, swing high/low, Donchian range, breakout level, signal candle values,
  swept liquidity level and RSI thresholds.
- `TradeInvalidationService` can re-evaluate an open trade against the stored
  signal invalidation plan and fresh candle-derived features.
- `GET /api/v1/trades/{trade_id}/invalidation` returns a structured
  `TradeInvalidationAlert`: `valid`, `invalidated`, or `unavailable`, with
  triggered conditions and `suggested_action=close_market_or_wait_stop`.
- Virtual/market close requests support `reason=invalidation`, so journal
  records distinguish logical idea failure from manual close or stop-loss.
- `TradeInvalidationMonitor` runs on closed-candle lifecycle and publishes
  `trade.invalidation` realtime events for open trades when the stored strategy
  idea breaks.
- `trade_invalidation_actions` persists user decisions by trade/fingerprint:
  `close_market`, `keep_stop_loss`, or `dismissed`.
- Active Trades UI shows an invalidation warning card only when the open
  position is logically invalidated, with two actions:
  `Close market` or `Keep stop loss`.
- `Keep stop loss` is saved through
  `POST /api/v1/trades/{trade_id}/invalidation/actions`, so the same alert stays
  dismissed after refresh.
- Frontend no longer polls invalidation every 10 seconds; the selected trade is
  checked once for reconciliation and then updated by `trade.invalidation`.

Remaining for point 1.6:

- Extend real-trade close integration when exchange market-close orders are
  implemented.

## Что Необходимо Реализовать

1. Strategy config CRUD:
   - схемы request/response;
   - service/repository;
   - endpoints `/api/v1/strategies/templates`, `/versions`, `/configs`;
   - frontend Settings tab.

2. Strategy-scoped pair selection:
   - done: использовать `user_strategy_configs.pair_scope`;
   - done: валидировать exchange+symbol через `market_pairs`;
   - done: scanner читает enabled configs and explicit pair scope in addition
     to global Radar symbols;
   - tail: implement non-Bybit exchange adapters before enabling real
     subscriptions for other exchanges.

3. Общий evaluation context:
   - `signal_features`;
   - `context_features`;
   - `quality_result`;
   - `regime_result`;
   - `strategy_config`.

4. Market Quality Filter:
   - 24h volume;
   - spread;
   - history sufficiency;
   - rough chart score;
   - anomalous gap/pump guard;
   - tier thresholds.

5. Market Regime Filter:
   - done: signal/context timeframe mapping with per-strategy overrides;
   - done: context features lookup;
   - alignment score/penalty;
   - done: key support/resistance proximity through S/R snapshots;
   - tail: store S/R snapshots/aggregates if runtime recomputation becomes too
     expensive.

6. Status lifecycle:
   - expand DB/API/frontend statuses;
   - map old `new/active` during transition;
   - add status filters in Radar.

7. Overextension guard:
   - shared helper;
   - status `wait_for_pullback`;
   - retest entry plan.

8. RR guard before actionable:
   - `min_rr` from strategy config or risk settings;
   - downgrade/block before writing `actionable`.

9. Invalidation plan:
   - build per strategy and store in signal snapshot;
   - expose open-trade invalidation check API;
   - lifecycle worker/realtime event to invalidate open ideas automatically.

10. Exit management:
    - store TP plan, breakeven, trailing source;
    - connect with existing risk-management helpers where possible.

11. Frontend Radar:
    - filters by status/strategy/exchange/symbol/timeframe;
    - status badges;
    - show quality/regime/invalidation/exit plan.

12. Tests:
    - strategy context unit tests;
    - DB status contract tests;
    - API filter tests;
    - frontend filter/store tests.

## Хвосты И Риски Стыков

- Current point 1.1 is implemented at MVP infrastructure level:
  scanner-time market-quality snapshot, hard all-pairs filter, manual pair
  scope bypass, strict `market_pairs` validation, strategy config API,
  exchange/pair/timeframe Settings UI, scanner subscription union, and hot
  reconfiguration after strategy scope changes.
- Remaining for point 1.1: add orderbook-depth quality data if we decide to
  show it before risk preview, add non-Bybit exchange adapters, and decide
  whether disabled market pairs should stay visible in Settings as disabled
  options or be hidden from the strategy scope picker.
- Current point 1.2 is implemented at MVP infrastructure level:
  primary and macro context timeframe lookup, regime score adjustment,
  `watchlist` downgrade on strong higher-timeframe conflict, `ready` downgrade
  near context support/resistance, `SupportResistanceService` snapshots,
  per-strategy context timeframe settings, persisted regime checks, and
  frontend detail output for non-passed regime checks.
- Remaining for point 1.2: persist or aggregate S/R snapshots in the
  ClickHouse/feature layer if runtime recomputation becomes too expensive, and
  tune `context_obstacle_min_atr` / `context_level_min_strength` per strategy
  after backtests.
- Current point 1.3 is implemented at MVP infrastructure level:
  DB/API/frontend status enum alignment, staged strategy output for the three
  MVP strategies, repository preservation of staged statuses, Radar filters,
  frontend status badges, and blocked Paper Trade actions for non-actionable
  strategy statuses, closed-candle lifecycle worker, transition events/outbox,
  realtime `signal.updated`/`signal.invalidated`, and the Radar history view for
  invalidated/expired ideas.
- Remaining for point 1.3: lifecycle threshold tuning after backtests and a
  richer archive/analytics screen if needed.
- Current point 1.4 is implemented at MVP infrastructure level:
  dynamic overextension guard, `wait_for_pullback` downgrade, body/range ATR
  checks, impulse close detection, rejection-wick detection, and
  liquidity-sweep absorption allowance, session VWAP feature, structured numeric
  pullback targets, Settings controls for `max_body_atr`/`max_range_atr`, and
  Signal Details pullback guidance.
- Remaining for point 1.4: tune thresholds after backtests.
- Current point 1.5 is implemented at MVP infrastructure level:
  RR guard before `actionable`, risk-management `min_rr_ratio` inheritance,
  per-strategy `min_rr_ratio`, `rr_target`, and `hide_failed_rr_signals`, plus
  Settings UI controls, strategy-specific final/nearest defaults, explicit
  first/final/selected RR response fields, and Signal Details RR comparison.
- Remaining for point 1.5: tune RR defaults per strategy/timeframe after
  backtests.
- Current point 1.6 is implemented at MVP infrastructure level:
  structured per-strategy invalidation metadata, open-trade invalidation API,
  closed-candle trade invalidation monitor, realtime `trade.invalidation`,
  persisted `Keep stop loss`/dismiss actions, `reason=invalidation` virtual
  market close, and Active Trades prompt with `Close market` /
  `Keep stop loss`.
- Remaining for point 1.6: real exchange market-close integration.
- `user_strategy_configs` now has MVP list/update API and Settings UI, but no
  separate templates/versions management screen yet.
- `RadarConfigService` is in-memory and global; strategy configs must be
  persistent and user-scoped in PostgreSQL.
- DB/API/frontend signal statuses are aligned for staged strategy signals.
- Radar feed and filter chips include staged open statuses
  (`watchlist`, `ready`, `actionable`, `wait_for_pullback`); `invalidated`
  remains a lifecycle/historical status outside the normal open feed.
- `StrategySignal` now carries `status`, `status_reason`, `quality`, `regime`,
  `setup`, `confirmation`, `invalidation`, and `exit_plan` snapshots.
- `build_signal` calculates RR, and the strategy pipeline now blocks
  `actionable` classification when configured RR is too low.
- Overextension has a shared dynamic pipeline downgrade to
  `wait_for_pullback`.
- Market-quality filter is centralized for 24h volume/spread/history/roughness;
  orderbook liquidity remains in risk preview.
- Multi-timeframe context is wired for scanner-time strategy evaluation, and
  4h ClickHouse table/routing support exists.
- Strategy config updates now expose scanner subscription/config hashes in
  radar status and trigger subscription reconfiguration when the hash changes.
- `market.liquidity_snapshots` exists but is not written.
- `market.orderbook_l2_deltas` and `market.orderbook_snapshots` exist but L2
  writer is missing.
- Scanner accepts exchanges list, but only Bybit adapter is implemented.
- Bootstrap seeds Bybit BTC/ETH/SOL/DOGE/1000PEPE only; requested major set
  mentions BNB/XRP, but those pairs are not seeded for Bybit.
- Strategy default params still need tuning after staged status backtests.
- `docs/scoring.md` still describes old 0-1 scoring, while runtime uses 0-100.
- Signal lifecycle now supports manual confirm/reject, TTL expiry, and automatic
  closed-candle transitions for stored strategy ideas; open trade logical
  invalidation prompts have persisted user actions through
  `trade_invalidation_actions`.
- `analytics.strategy_performance_daily` table exists but no aggregator worker.
- Risk card frontend uses backend preview, but scanner-time strategy quality is
  not the same as execution-time risk quality yet.

## Current Remaining Tails Audit

This audit supersedes the older implementation checklist above. As of the
current MVP infrastructure pass, points 1.1-1.6 are wired across backend, DB,
realtime, and frontend. Remaining work is calibration, production exchange
coverage, and analytics depth rather than missing base plumbing.

1. Market Quality / strategy pairs:
   - implemented: strict `market_pairs` validation, manual pair-scope bypass of
     quality exclusion, Settings exchange/pair/timeframe controls, scanner
     subscription/config hashes, and hot reconfiguration;
   - remaining: non-Bybit exchange adapters, optional orderbook-depth quality
     before risk preview, and a product decision for disabled pair visibility.

2. Market Regime / higher timeframe:
   - implemented: per-strategy context timeframe overrides, higher-timeframe
     features, score/status downgrades on regime conflict, and
     `SupportResistanceService` snapshots;
   - remaining: persist/aggregate S/R snapshots if runtime recomputation becomes
     expensive, then tune obstacle thresholds after backtests.

3. Signal statuses / lifecycle:
   - implemented: staged statuses in DB/API/frontend, Radar status filters,
     closed-candle lifecycle transitions, `trading_signal_events`, realtime
     `signal.updated`/`signal.invalidated`, and invalidated/expired history;
   - remaining: backtest threshold tuning and richer lifecycle analytics if
     needed.

4. Overextension:
   - implemented: body/range ATR guard, impulse/rejection-wick handling,
     `wait_for_pullback`, session VWAP, numeric pullback targets, Settings
     thresholds, and Signal Details guidance;
   - remaining: strategy/timeframe threshold calibration after backtests.

5. Risk/Reward:
   - implemented: scanner-time RR classification guard, inherited risk-manager
     `min_rr_ratio`, strategy overrides, hide-failed-RR option, first/final/
     selected RR fields, and Signal Details comparison;
   - remaining: tune nearest-vs-final target defaults per strategy/timeframe.

6. Trade invalidation:
   - implemented: structured per-strategy invalidation metadata, open-trade API,
     closed-candle `TradeInvalidationMonitor`, realtime `trade.invalidation`,
     persisted `Keep stop loss`/dismiss/virtual close decisions, and Active
     Trades prompt;
   - remaining: real exchange market-close order integration.

7. Trend Pullback continuation hardening:
   - implemented: Bybit derivative snapshot background runner writes funding
     context to PostgreSQL and Redis hot cache; scanner and closed-candle
     lifecycle read the hot snapshot only, so strategy evaluation does not call
     REST;
   - implemented: funding sign semantics now block long continuation on
     extreme positive funding and short continuation on extreme negative
     funding; auto-entry confirmation checks funding again before becoming
     actionable;
   - implemented: candle `FeatureEngine` uses Wilder ADX 14 on OHLCV candles,
     exposes `adx_rising_bars`/`adx_slope_5`, and keeps tick-stream ADX as
     fallback only;
   - implemented: EMA200 chop metrics are computed from candle history and
     surfaced in `MarketRegimeFilter`; severe chop hides Trend Pullback, while
     borderline chop downgrades it to watchlist with a score penalty;
   - remaining: collect production samples to tune funding thresholds,
     EMA200-chop score cutoffs, and ADX rising-bar defaults per timeframe.

8. Volatility Squeeze Breakout hardening:
   - implemented: FeatureEngine squeeze metrics, strict compression
     requirement, Donchian range ATR cap, candle-close breakout confirmation,
     volume/close-position/ATR-expansion/wick filters, wick-only ready stage,
     retest-zone metadata, measured-move target, 1.5R/2.5R exits, and Settings
     knobs for the main squeeze thresholds;
   - remaining: backtest threshold calibration per timeframe/symbol tier,
     BTC/macro shock filter for opposite-side alt breakouts, and false-breakout
     analytics after the strategy performance aggregator is wired.

9. Cross-cutting production tails:
   - persist strategy configs per real user instead of relying on global/demo
     assumptions;
   - add analytics aggregation for `analytics.strategy_performance_daily`;
   - align `docs/scoring.md` with runtime 0-100 scoring;
   - seed/enable the requested major pairs such as BNB/XRP where exchange
     adapters and market-pair data support them.

## Recommended Implementation Order

1. Run backtests for strategy/timeframe calibration: regime obstacle thresholds,
   overextension ATR limits, lifecycle transitions, and RR target choice.
2. Add non-Bybit exchange adapters before exposing multi-exchange strategy
   scopes as real subscriptions.
3. Tune derivative/funding freshness, EMA200-chop thresholds, Squeeze Breakout
   compression/confirmation defaults, and Wilder ADX
   rising-bar defaults after live samples and backtests.
4. Decide whether scanner-time orderbook-depth quality is needed before risk
   preview; if yes, write/read `market.liquidity_snapshots`.
5. Persist/aggregate S/R snapshots if runtime recomputation becomes a scanner
   bottleneck.
6. Wire real exchange execution for invalidation `Close market`.
7. Add strategy performance aggregation and analytics once lifecycle outcomes
   are calibrated.
