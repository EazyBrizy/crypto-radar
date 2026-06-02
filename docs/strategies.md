# MVP Strategies

Этот документ является обязательной спецификацией для работы со стратегиями Crypto Radar.

Итоговый MVP-набор:

1. `Trend Pullback Continuation` - базовый сигнал по тренду.
2. `Volatility Squeeze Breakout` - поиск сильных движений до или в момент старта.
3. `Liquidity Sweep Reversal` - простая Smart Money логика против ложных пробоев.

Эти стратегии покрывают разные рыночные режимы:

- `Trend Pullback` - рынок уже в тренде.
- `Squeeze Breakout` - рынок выходит из сжатия.
- `Liquidity Sweep` - рынок сделал ложный пробой.

## Signal Model

Сигнал не должен появляться только из-за одного индикатора. Каждая стратегия должна формировать оценку:

```text
Signal Score =
Trend Score
+ Momentum Score
+ Volume Score
+ Volatility Score
+ Liquidity Score
+ Derivatives Score
- Risk Penalty
```

Правила:

- `70+` - high-confidence discovery candidate.
- `60-69` - watchlist setup.
- `<60` - ignore.

Discovery score is not the same as production actionability. A strategy may
return a setup without a complete production trade plan. Such a signal must
remain visible for research/watchlist purposes, but it must not become
production-actionable until TradePlan completeness, Risk/RR Eligibility, and
Execution Eligibility pass for that scope.

Strategies should return market-based stop, invalidation, and target theses
whenever structure is available. If a strategy cannot produce a structural stop
or structural targets, it may still return the setup for `research_mode`, but
fallback ATR stops or fallback R-multiple targets must be marked in TradePlan
metadata and must not be silently treated as production-complete.

Strategy runtime may request production semantics with
`production_mode = true` or `signal_mode = "production"`. The default remains
research-compatible for discovery, backtests, and Strategy Test Lab. In
production mode, `trade_plan_completeness` blocks actionability when fallback
stop/targets are used or when structural stop, invalidation thesis, or
structural target thesis is missing. The setup remains visible as a watchlist
candidate with the blocker reason.

Каждый сигнал должен объяснять:

- что за сигнал;
- почему он появился;
- где вход;
- где invalidation / stop loss;
- где take profit;
- какой risk/reward;
- что может отменить идею.

## Data Layer

Для MVP достаточно:

```text
Market:
- price stream
- volume
- OHLCV candles by `exchange/symbol/timeframe`
- timeframes: `1m`, `5m`, `15m`, `1h`, `4h`, `1d`

Derived:
- EMA 20/50/200
- SMA 20
- RSI 14
- ATR 14
- Wilder ADX 14 with `adx_rising_bars` and `adx_slope_5`
- Bollinger Band Width
- Bollinger Band Width Percentile
- Donchian Channel 20
- Swing high / swing low
- Wick ratio proxy
- Volume MA 20
- Volume spike

Derivatives:
- funding rate
- open interest
- liquidations
```

Funding rate is supplied by the production derivative snapshot path:
`DerivativeSnapshotSyncRunner` refreshes Bybit ticker snapshots into PostgreSQL
and Redis every 30-60 seconds, while scanner-time strategy evaluation only reads
the Redis hot snapshot. If the snapshot is absent or stale, `funding_rate`
remains `None` and funding filters become non-blocking.

AUD-06 adds optional `AlphaMarketContext` for strategy-readable orderflow and
smart-money context. `MarketScanner` builds it from recent normalized trades,
hot L2 orderbook snapshots, derivative snapshots, and deterministic
`Features` level/VWAP fields before strategy evaluation. Strategies may read
`alpha_context` from `StrategyEvaluationContext` or runtime params, but they
must not call exchange, API, Redis, or DB sources directly. Missing trade side,
historical L2, derivative history, or liquidation data must remain explicit in
`alpha_context.data_quality.missing_sources`; strategies must not infer missing
buy/sell volume or CVD from price movement.

Derivatives поля пока могут быть `None`, но стратегия должна быть готова использовать их позже.

Сигналы MVP должны строиться от свечной серии, а не от одиночного тика. Тик обновляет OHLCV-свечу в `CandleService`, затем `FeatureEngine` считает derived-поля по серии свечей, после чего `StrategyEngine` запускает три MVP-стратегии.

## Strategy 1: Trend Pullback Continuation

Назначение: найти вход по тренду после отката, а не догонять импульс.

Индикаторы:

- EMA 20.
- EMA 50.
- EMA 200.
- RSI 14.
- ATR 14.
- Wilder ADX 14.
- Volume MA 20.
- Funding rate from hot derivative snapshot.
- EMA200 chop metrics.

Long:

- `close > EMA200`
- `EMA50 > EMA200`
- `EMA20 > EMA50`
- `ADX >= 18` or `ADX >= 15` with at least 3 rising ADX bars
- цена в зоне отката к `EMA20` или `EMA50`
- `RSI` between `40` and `55`
- текущий close bullish
- `volume >= volume_ma * 1.1`
- actual trigger uses `close > previous_high`, `close > open`,
  `volume >= volume_ma * 1.1`
- extreme positive funding blocks long continuation

Short:

- `close < EMA200`
- `EMA50 < EMA200`
- `EMA20 < EMA50`
- `ADX >= 18` or `ADX >= 15` with at least 3 rising ADX bars
- цена в зоне отката к `EMA20` или `EMA50`
- `RSI` between `45` and `60`
- текущий close bearish
- `volume >= volume_ma * 1.1`
- actual trigger uses `close < previous_low`, `close < open`,
  `volume >= volume_ma * 1.1`
- extreme negative funding blocks short continuation

Regime filters:

- severe EMA200 chop hides Trend Pullback ideas;
- borderline EMA200 chop downgrades Trend Pullback to watchlist and applies a
  score penalty;
- funding is checked again on lifecycle confirmation, so an armed auto-entry
  will not become production-actionable if funding turns extreme before the
  trigger candle.

Risk:

- Long stop = recent swing low - `0.5 ATR`
- Short stop = recent swing high + `0.5 ATR`
- TP1 = `1R`
- TP2 = `2R`

## Strategy 2: Volatility Squeeze Breakout

Назначение: найти выход из сжатия до или в момент сильного движения.

Индикаторы:

- Bollinger Bands 20.
- Bollinger Band Width.
- Donchian Channel 20.
- ATR 14.
- Volume MA 20.
- RSI 14.

Long:

- `BB_width_percentile < 20`
- close выше `Donchian high`
- `volume > volume_ma * 1.5`
- ATR increasing
- `RSI` между `55` и `70`

Short:

- `BB_width_percentile < 20`
- close ниже `Donchian low`
- `volume > volume_ma * 1.5`
- ATR increasing
- `RSI` между `30` и `45`

Filters:

- не входить, если candle body больше `2.5 ATR`;
- не входить при слишком широком spread;
- не входить при слишком низком 24h volume;
- учитывать funding против сделки, когда данные появятся.

Risk:

- Long stop = breakout level - `1 ATR`
- Short stop = breakout level + `1 ATR`
- TP1 = `1.5R`
- TP2 = `2.5R`
- TP3 = measured move of the Donchian range

Runtime implementation notes:

- The strategy now requires full compression before a setup is visible:
  `bb_width_percentile < threshold`, `ATR14 < ATR_SMA50`,
  `range_20 < range_50_average`, and `range_20_atr <= max_squeeze_range_atr`.
- Long/short breakout confirmation is based on candle close outside the
  Donchian range, not wick penetration.
- Strong candle close is configurable with `min_close_position`: long expects
  close in the upper part of the candle, short in the lower part.
- False-breakout filters include wick-only break, rejection wick ratio, weak
  close, overlarge body, nearby higher-timeframe S/R from the shared regime
  layer, and RR quality annotation from the shared eligibility layer.
- Signal metadata exposes both entries:
  aggressive entry at breakout close, and conservative retest zone around the
  Donchian breakout/breakdown level.
- User-tunable params live in `user_strategy_configs.params`; no extra DB
  columns are required for this MVP.

## Strategy 3: Liquidity Sweep Reversal

Назначение: ловить ложный пробой swing high / swing low и возврат внутрь диапазона.

Данные:

- Swing high / swing low.
- Wick size.
- Close location.
- Volume.
- ATR.
- Optional: liquidation data.

Long:

- price takes previous swing low
- close returns above previous swing low
- lower wick is large
- `volume > volume_ma * 1.3`
- RSI не проваливается ниже `25`

Short:

- price takes previous swing high
- close returns below previous swing high
- upper wick is large
- `volume > volume_ma * 1.3`
- RSI не пробивает выше `75` с силой

Risk:

- Long stop = sweep low - `0.3 ATR`
- Short stop = sweep high + `0.3 ATR`
- TP1 = середина диапазона
- TP2 = противоположная граница диапазона

Runtime implementation notes:

- `FeatureEngine` uses 20-50 candle fractal swing levels and records level
  touch count, age and volume score for sweep scoring.
- Equal high/low fallback is allowed only when the level has at least two
  recent touches; random one-off highs/lows are not promoted into sweep levels.
- The strategy emits staged ideas: `watchlist` near visible liquidity, `ready`
  after an unreclaimed or weak reclaim, and `confirmed_candidate` after an
  aggressive sweep or conservative confirmation candle. Production actionability
  still belongs to the shared eligibility layers.
- Aggressive sweep requires reclaim/rejection, wick ratio, volume and close
  strength. Conservative sweep requires the next candle to break micro
  structure in the reversal direction with at least `1.1x` volume.
- The scoring budget follows the 100-point Liquidity Sweep model in
  `docs/scoring.md`; HTF level confluence, RR, spread/liquidity and strong
  regime conflict stay in shared pipeline layers.
- Invalidation metadata stores the swept level, sweep extreme, wick ratio,
  level touch count, aggressive entry and conservative confirmation zone.
- Exit management uses TP1 at range midpoint, TP2 at the opposite range
  boundary, and a TP3 runner after micro-BOS/ATR trailing.

## Pipeline

```text
1. Market filter
2. Regime detection
3. Strategy matching
4. Signal scoring
5. Risk engine
```

Минимальные формулы для MVP:

```text
R = abs(entry - stop)
TP1_long = entry + R
TP2_long = entry + 2R
TP1_short = entry - R
TP2_short = entry - 2R
volume_spike = current_volume / SMA(volume, 20)
```

## Radar UI Contract

Главный экран Radar:

```text
Pair | Strategy | Direction | Score | Entry | Stop | TP | Risk | Timeframe
```

Карточка сигнала:

```text
BTCUSDT
Strategy: Squeeze Breakout
Direction: Long
Score: 82/100

Why:
- volatility compression
- break above 20-candle high
- volume above average
- ATR expanding

Entry
Stop
TP1
TP2
Invalidation
```

## Strategy Operating Playbook v3.4

All strategies remain pure trading logic. They read `Features`, return
`StrategySignal` plus optional `TradePlan` metadata, and do not call DB, API,
execution adapters, or risk services.

Strategies should emit market-based stop, invalidation, and target theses when
the setup structure supports them. They may emit a discovery setup without a
complete production trade plan, but that signal is research/watchlist-only until
the shared TradePlan Completeness, Risk/RR Eligibility, and Execution
Eligibility layers mark it actionable for the requested scope.

RR is measured outside the strategy as a shared quality/eligibility layer. A
weak RR annotation can block virtual or real execution in hard guard mode, but
it must not make the strategy hide the setup by itself.

Strategies receive `Features.candle_state` and copy it to
`StrategySignal.candle_state`. An open candle setup is a forming preview by
default: it remains visible for watchlist/research UI, but the shared pipeline
must not mark it actionable or arm auto-entry unless
`allow_open_candle_actionable=true` explicitly allows that source. Lower
timeframe trigger actionability is likewise disabled unless
`allow_lower_timeframe_trigger_actionable=true`.

Strategies may also receive `AlphaMarketContext` as optional alpha evidence:
recent trade delta/CVD, orderbook imbalance/depth-wall data, derivative
funding/OI deltas, liquidity pools, and VWAP/PDH/PDL reactions. These fields
are alpha/context inputs only; risk freshness, spread, depth, and execution
eligibility remain owned by the market-quality and risk layers.

Shared lifecycle:

```text
MarketData -> Features -> StrategySignal -> TradePlan -> Pipeline checks
-> RiskGate -> Virtual/Real Execution -> Outcome Labeling
-> Strategy Performance -> EV Gate
```

### trend_pullback_continuation

Idea:

- Join an established trend after a controlled pullback instead of chasing the
  impulse candle.

Entry model:

- Long setup expects trend alignment above EMA200 with EMA20 above EMA50 and a
  pullback into the EMA20/EMA50 zone.
- Short setup mirrors that structure below EMA200 with EMA20 below EMA50.
- Preferred executable entry is a confirmation/retest entry from the pullback
  zone; aggressive entry metadata may exist but must be explicit.

Invalidation:

- Long invalidates when price loses the pullback structure or breaks below the
  recent swing low/structure stop.
- Short invalidates when price reclaims above the recent swing high/structure
  stop.
- Time stop may be supplied through `TradePlan.risk_rules.metadata` when the
  pullback does not continue within the configured holding window.

Targets:

- TP1: first structure-aware target, usually around `1R` or nearby liquidity.
- TP2: continuation target around `2R` or the next structure level.
- Optional runner/trailing metadata can be used after continuation is confirmed.

Good regime:

- Directional trend, EMA stack aligned, ADX stable or rising, healthy volume,
  and no extreme funding against the trade.

Bad regime:

- EMA200 chop, flat/mean-reverting range, exhausted extension far from EMA20/50,
  crowded funding/open-interest conditions, or major HTF obstacle directly in
  front of entry.

Required confirmations:

- Trend alignment.
- Pullback zone touched or reclaimed.
- Directional candle confirmation.
- Volume confirmation.
- RR measured and annotated; failed RR affects execution eligibility only in
  the active guard mode.
- HTF alignment when configured.

No-trade filters:

- overextended entry;
- near higher-timeframe obstacle;
- extreme funding in the trade direction;
- crowded open-interest warning/block when configured;
- low liquidity, high spread, or high slippage;
- negative/insufficient edge for real entry.

Expected holding period:

- Multi-candle continuation; usually longer than squeeze breakouts and shorter
  than broad position-trend systems. Use configured time-stop metadata instead
  of hardcoded bars.

### volatility_squeeze_breakout

Idea:

- Trade expansion after volatility compression, only when the breakout has
  enough close quality, volume, and measurable RR context to evaluate random
  wick-break risk.

Entry model:

- Aggressive entry: breakout candle closes beyond the Donchian/compression
  boundary with required volume and close-position quality.
- Conservative entry: wait for retest of the broken level after a large candle
  or when strategy params require retest.
- Entry metadata must identify whether the executable plan is
  `aggressive_breakout` or `conservative_retest`.

Invalidation:

- Breakout closes back inside the compression range.
- Retest fails and accepts price back inside the old range.
- Follow-through candle reverses through the breakout level.
- Overlarge candle requires retest or blocks the setup, depending on params.

Targets:

- TP1: around `1.5R` or first post-breakout liquidity.
- TP2: around `2.5R`.
- TP3: measured move from the Donchian/compression range when enabled and valid.

Good regime:

- Clear compression, low BB width percentile, range contraction, ATR ready to
  expand, volume expansion, and no immediate HTF obstacle.

Bad regime:

- News-like oversized candle, wick-only breakout, low-liquidity symbols, wide
  spread, choppy fakeout environment, or breakout directly into major
  resistance/support.

Required confirmations:

- Compression passed.
- Directional close outside range.
- Volume spike.
- Close in directional candle area.
- ATR expansion or configured volatility confirmation.
- RR measured and annotated; failed RR affects execution eligibility only in
  the active guard mode.

No-trade filters:

- candle body above configured ATR threshold;
- wick-only or weak-close breakout;
- nearby HTF obstacle;
- high spread/slippage or insufficient depth;
- no open-interest expansion when configured as required;
- negative/insufficient edge for real entry.

Expected holding period:

- Short to medium momentum burst. Conservative retest entries can hold longer
  than aggressive breakout entries; exact limits should come from params.

### liquidity_sweep_reversal

Idea:

- Trade a failed break of visible liquidity when price sweeps a swing/equal
  high or low and then reclaims back into the range.

Entry model:

- Aggressive entry: sweep plus reclaim/rejection on the same candle with wick,
  volume, and close-quality confirmation.
- Conservative entry: next candle breaks micro-structure in the reversal
  direction after the sweep.
- The plan should expose swept level, sweep extreme, reclaim state, and
  confirmation zone in metadata.

Invalidation:

- Price accepts beyond the swept level instead of reclaiming.
- Next candle continues the breakout.
- Reversal fails before reaching midpoint target.
- Opposing trend pressure or HTF structure invalidates the reversal thesis.

Targets:

- TP1: range midpoint.
- TP2: opposite range boundary.
- TP3/runner: optional micro-BOS/ATR trailing target when continuation develops.

Good regime:

- Range or late-trend liquidity event, visible swing/equal highs/lows, strong
  rejection wick, absorption/flush evidence, and room back to range midpoint.

Bad regime:

- Clean trend breakout, weak wick/reclaim, no visible liquidity level, thin
  orderbook, high spread, or strong HTF trend directly against the reversal.

Required confirmations:

- Valid visible liquidity level.
- Sweep of that level.
- Reclaim or configured absorption confirmation.
- Directional wick and close quality.
- Volume confirmation.
- RR measured and annotated; failed RR affects execution eligibility only in
  the active guard mode.

No-trade filters:

- no reclaim when reclaim is required;
- no absorption when absorption is required;
- obstacle too close relative to R;
- strong trend continuation against the reversal;
- low liquidity, high spread, or high slippage;
- negative/insufficient edge for real entry.

Expected holding period:

- Usually mean-reversion back into the range. TP1 can be fast; runners should be
  controlled by configured trailing/time-stop metadata.
