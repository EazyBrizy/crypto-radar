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

- `70+` - actionable signal.
- `60-69` - watchlist setup.
- `<60` - ignore.

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

Derived:
- EMA 20/50/200
- SMA 20
- RSI 14
- ATR 14
- ADX proxy
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

Derivatives поля пока могут быть `None`, но стратегия должна быть готова использовать их позже.

## Strategy 1: Trend Pullback Continuation

Назначение: найти вход по тренду после отката, а не догонять импульс.

Индикаторы:

- EMA 20.
- EMA 50.
- EMA 200.
- RSI 14.
- ATR 14.
- Volume MA 20.

Long:

- `close > EMA200`
- `EMA50 > EMA200`
- цена в зоне отката к `EMA20` или `EMA50`
- `RSI` между `45` и `60`
- текущий close bullish
- `volume >= volume_ma * 1.1`

Short:

- `close < EMA200`
- `EMA50 < EMA200`
- цена в зоне отката к `EMA20` или `EMA50`
- `RSI` между `40` и `55`
- текущий close bearish
- `volume >= volume_ma * 1.1`

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
