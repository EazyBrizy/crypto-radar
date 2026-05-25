Ниже — несколько вариантов интерфейса для **Crypto_radar**, с фокусом на простоту, скорость принятия решения и дружелюбность для трейдера.

Главная UX-цель:

> Пользователь должен за **20–30 секунд** понять:
> **есть ли сигнал → насколько он надежен → почему он появился → стоит ли входить в сделку.**

---

# 1. Общая концепция интерфейса

Crypto_radar не должен выглядеть как сложный терминал Bloomberg/TradingView. Он должен ощущаться как:

**“умный радар сделок”**, а не “еще одна аналитическая панель”.

Основной принцип:

> Сначала сигнал. Потом объяснение. Потом детали.

То есть мы не показываем пользователю сразу 50 графиков, индикаторов и таблиц. Мы даем ему понятную карточку:

**BTC/USDT — Long Signal — Confidence 82% — Risk: Medium — Entry Zone: 67,800–68,100**

А уже по клику раскрываем детали.

---

# 2. Основные экраны MVP

Для MVP я бы предложил 6 ключевых экранов:

1. **Radar / Главный экран сигналов**
2. **Signal Details / Детальный экран сигнала**
3. **Market Scanner / Сканер рынка**
4. **Watchlist / Избранные пары**
5. **Portfolio / Активные сделки**
6. **Settings / Настройки стратегии и бирж**

Дополнительно позже:

7. **AI Assistant**
8. **Backtesting**
9. **User Analytics**
10. **Subscription / Billing**

---

# 3. Вариант A — “Signal First”

Это самый подходящий вариант для MVP.

## Идея

Пользователь открывает приложение и сразу видит список торговых сигналов. Не графики. Не новости. Не таблицы. Именно сигналы.

Главный экран похож на “ленту возможностей”.

---

## Экран 1: Radar

### Что видит пользователь

Верхняя часть:

```text
Crypto Radar
Market Status: Neutral / Volatile / Bullish
Active Signals: 12
High Confidence: 3
```

Ниже — быстрые фильтры:

```text
[All] [Long] [Short] [Scalp] [Intraday] [Swing]
[BTC] [ETH] [Top 20] [High Volume] [Favorites]
```

Основная область — карточки сигналов.

Пример карточки:

```text
BTC/USDT
LONG

Confidence: 84%
Risk: Medium
Strategy: EMA Pullback + Volume Confirmation
Timeframe: 15m
Entry Zone: 67,850–68,100
Take Profit: 68,900
Stop Loss: 67,420

[View Analysis]
```

---

## Карточка сигнала должна быть очень понятной

Я бы использовал цветовую логику:

* **Зеленый** — Long
* **Красный** — Short
* **Желтый/оранжевый** — средний риск
* **Серый** — нейтральный или слабый сигнал
* **Фиолетовый/синий** — AI/Smart Money signal

Но важно не перегрузить экран цветами. Лучше использовать цвет только как акцент.

---

## Важные элементы карточки

На карточке обязательно должны быть:

```text
Pair
Direction
Confidence Score
Risk Level
Strategy
Timeframe
Entry Zone
SL / TP
Signal Age
```

Например:

```text
ETH/USDT
SHORT
78% Confidence
Risk: Low
RSI Divergence + Breakdown
Generated 4 min ago
```

---

# 4. Экран 2: Signal Details

После клика на карточку пользователь попадает на детальный экран.

## Структура экрана

Верхний блок:

```text
BTC/USDT — Long Signal
Confidence: 84%
Risk: Medium
Status: Active
```

Главный блок решения:

```text
Recommended Action:
Wait for entry inside 67,850–68,100

Entry Zone: 67,850–68,100
Stop Loss: 67,420
Take Profit 1: 68,900
Take Profit 2: 69,450
Risk/Reward: 1:2.4
```

Далее — объяснение простым языком:

```text
Why this signal appeared:

1. Price pulled back to EMA 50
2. Volume increased on bounce
3. RSI recovered from oversold zone
4. BTC dominance is stable
5. No strong resistance before TP1
```

---

## Главное: объяснение должно быть не техническим, а человеческим

Плохо:

```text
EMA50 confluence with RSI 42 and OBV divergence.
```

Лучше:

```text
Цена откатилась к средней зоне поддержки, покупатели начали возвращаться, а объем подтверждает интерес к движению вверх.
```

Можно добавить переключатель:

```text
[Simple Explanation] [Pro View]
```

В Simple View — человеческий язык.
В Pro View — индикаторы, значения, графики, свечные паттерны.

---

# 5. Экран 3: Market Scanner

Этот экран нужен для более продвинутых пользователей.

## Назначение

Показывать, что сейчас происходит на рынке:

```text
Top Movers
Volume Spikes
Breakouts
Oversold Assets
Smart Money Activity
Funding Rate Anomalies
Liquidation Clusters
```

Но в MVP его можно сделать простым.

---

## Интерфейс Scanner

Верх:

```text
Exchange: Binance / Bybit / OKX / All
Market: Spot / Futures
Timeframe: 5m / 15m / 1h / 4h
Strategy: All / Scalping / Trend / Reversal
```

Таблица:

```text
Pair      Signal      Confidence   Volume    Timeframe   Action
BTC/USDT  Long        84%          +28%      15m         View
SOL/USDT  Short       76%          +41%      5m          View
ETH/USDT  Watch       62%          +12%      1h          View
```

Чтобы не перегрузить, таблица должна быть компактной. Основной экран все равно должен оставаться Radar, а Scanner — инструмент для поиска.

---

# 6. Экран 4: Watchlist

Пользователь должен иметь возможность отслеживать только интересующие пары.

## Что показывать

```text
My Watchlist

BTC/USDT
ETH/USDT
SOL/USDT
BNB/USDT
TON/USDT
```

Для каждой пары:

```text
Price
24h Change
Current Signal
Trend Status
Volume Status
```

Пример:

```text
SOL/USDT
$172.40
+4.8%
Current Signal: Long Watch
Trend: Bullish
Volume: High
```

---

# 7. Экран 5: Portfolio / Active Trades

Даже если в MVP нет автотрейдинга, пользователю нужно видеть активные идеи.

## Назначение

Показывать сделки, которые пользователь “принял” или сохранил.

```text
Active Trades

BTC/USDT Long
Entry: 67,950
Current: 68,420
PnL: +0.69%
TP1: 68,900
SL: 67,420
Status: In Progress
```

Также нужны статусы:

```text
Waiting Entry
Active
TP1 Hit
TP2 Hit
Stopped Out
Expired
Invalidated
```

Это важно, потому что сигнал не должен просто появляться и исчезать. Пользователь должен видеть его жизненный цикл.

---

# 8. Экран 6: Settings

Настройки должны быть простыми, без ощущения “алготрейдинг-комбайна”.

## Основные настройки

```text
Exchanges:
[Binance] [Bybit] [OKX] [KuCoin]

Markets:
[Spot] [Futures]

Risk Profile:
[Conservative] [Balanced] [Aggressive]

Signal Types:
[Scalping] [Intraday] [Swing]

Minimum Confidence:
[60%] [70%] [80%]

Notifications:
[High Confidence Signals]
[Only Favorites]
[Risk Warnings]
```

Для MVP лучше не давать слишком много параметров. Чем больше настроек, тем сложнее пользователю начать.

---

# 9. Три варианта UX-концепции

## Вариант 1: “Signal Feed”

Самый простой и лучший для MVP.

### Суть

Главный экран — это лента сигналов.

Похоже на:

```text
Telegram signals + Bloomberg intelligence + TradingView confirmation
```

### Подходит для

* Новичков
* Быстрого принятия решений
* Мобильной версии
* MVP

### Минусы

Меньше ощущения “профессионального терминала”.

### Моя оценка

**Лучший вариант для старта.**

---

# 10. Рекомендованная структура MVP

Я бы начал с гибрида:

## Главный интерфейс MVP

```text
1. Radar
2. Signal Details
3. Watchlist
4. Active Trades
5. Settings
```

Scanner можно сделать не отдельным сложным экраном, а встроить в Radar через фильтры.

---

# 11. MVP Navigation

Лучший вариант нижнего меню:

```text
Radar
Watchlist
Trades
AI
Settings
```

Для desktop:

```text
Left Sidebar:
- Radar
- Watchlist
- Trades
- Scanner
- AI Assistant
- Settings
```

---

# 12. Главный экран MVP — рекомендуемый макет

```text
------------------------------------------------
Crypto Radar                         Profile
------------------------------------------------

Market Mood: Neutral        Active Signals: 12
BTC Trend: Bullish          Volatility: Medium

[All] [Long] [Short] [Scalp] [Intraday] [Swing]

------------------------------------------------
Top Signal
BTC/USDT                       LONG
Confidence 84%                 Risk Medium

Entry: 67,850–68,100
TP: 68,900
SL: 67,420

Strategy:
EMA Pullback + Volume Confirmation

[View Analysis]
------------------------------------------------

ETH/USDT                       SHORT
Confidence 78%                 Risk Low

Reason:
RSI divergence + support breakdown

[View Analysis]
------------------------------------------------

SOL/USDT                       WATCH
Confidence 64%                 Risk High

Reason:
Possible breakout, waiting volume confirmation

[View Analysis]
------------------------------------------------
```

---

# 13. Детальный экран сигнала — рекомендуемый макет

```text
BTC/USDT Long Signal
Confidence: 84%
Risk: Medium
Status: Active

--------------------------------
Trade Setup
--------------------------------

Entry Zone:
67,850–68,100

Stop Loss:
67,420

Take Profit:
TP1: 68,900
TP2: 69,450

Risk / Reward:
1 : 2.4

--------------------------------
Why this signal?
--------------------------------

Price returned to EMA 50 support.
Volume increased during the bounce.
RSI recovered from oversold area.
No major resistance before TP1.

--------------------------------
Confirmation Checklist
--------------------------------

[✓] Trend is bullish
[✓] Pullback completed
[✓] Volume confirms move
[✓] RSI supports entry
[ ] BTC dominance risk checked

--------------------------------
Chart
--------------------------------

Mini chart with:
- Entry zone
- Stop loss
- Take profit
- EMA 50 / EMA 200
- Volume
```

---

# 14. Очень важный элемент — Signal Confidence

Нужно не просто писать “84%”. Нужно объяснять, из чего состоит confidence.

Например:

```text
Confidence Score: 84%

Trend: 25/25
Volume: 18/20
Momentum: 16/20
Risk/Reward: 15/20
Market Context: 10/15
```

Это повышает доверие.

---

# 15. Риск-профиль сигнала

Каждая карточка должна иметь понятный risk label:

```text
Low Risk
Medium Risk
High Risk
Speculative
```

И короткое объяснение:

```text
Risk: Medium
Because price is close to resistance and BTC volatility is elevated.
```

---

# 16. Режимы отображения

Я бы добавил переключатель:

```text
Simple / Pro
```

## Simple Mode

Для новичков:

```text
BTC looks ready for a possible upward move.
Better entry: 67,850–68,100.
Risk is medium.
```

## Pro Mode

Для трейдеров:

```text
EMA50 retest on 15m.
RSI recovered from 38 to 51.
Volume +28% above average.
Price holding above VWAP.
R/R: 1:2.4.
```

Это даст продукту дружелюбность без потери профессиональности.

---

# 17. Визуальный стиль

Я бы предложил такой стиль:

## Общий стиль

```text
Dark mode first
Clean cards
Soft borders
Minimal gradients
High contrast text
Subtle neon accents
```

## Цвета

```text
Background: #0B0F19
Card: #111827
Border: #1F2937
Text Primary: #F9FAFB
Text Secondary: #9CA3AF

Green: Long / Profit
Red: Short / Loss
Yellow: Risk / Warning
Blue: AI / Info
Purple: Smart Money
```

## Шрифты

Подойдут:

```text
Inter
Manrope
Satoshi
IBM Plex Sans
```

Лучше использовать современный нейтральный шрифт, например **Inter** или **Manrope**.

---

# 18. Компоненты интерфейса

Для MVP нужны такие компоненты:

```text
Signal Card
Confidence Badge
Risk Badge
Market Mood Indicator
Strategy Tag
Entry Zone Block
SL/TP Block
Mini Chart
Confirmation Checklist
Signal Timeline
Exchange Filter
Timeframe Filter
Notification Toggle
```

---

# 19. Signal Timeline

Очень полезный элемент.

На детальном экране можно показывать жизнь сигнала:

```text
12:04 — Signal detected
12:06 — Volume confirmation
12:08 — Entry zone reached
12:14 — Trade active
12:27 — TP1 hit
```

Это делает систему прозрачной и повышает доверие.

---

# 20. Что не стоит делать в MVP

Я бы избегал:

```text
Слишком много графиков
Слишком много индикаторов на первом экране
Большие таблицы
Сложные настройки стратегий
Панель “для квантов”
100 фильтров
Автотрейдинг на старте
Перегруженные heatmap
```

Главная ошибка — попытаться сразу сделать Nansen + TradingView + Binance + AI-chat в одном экране.

---

# 21. Самый сильный MVP-вариант

Я рекомендую начать с варианта:

# **Signal Feed + AI Explanation**

То есть:

```text
Radar = лента лучших сигналов
Signal Details = объяснение и торговый план
Watchlist = избранные пары
Trades = сохраненные/активные идеи
Settings = биржи, риск, уведомления
```

Это даст простую и сильную структуру.

---

# 22. Базовый пользовательский сценарий

```text
1. Пользователь открывает Radar
2. Видит 3–5 лучших сигналов
3. Кликает на BTC/USDT Long
4. Видит понятный trade setup
5. Проверяет причины сигнала
6. Нажимает:
   - Save Trade
   - Set Alert
   - Open Exchange
7. Следит за статусом в Trades
```

---

# 23. Кнопки на экране сигнала

Я бы сделал такие действия:

```text
[Save Trade]
[Set Alert]
[Open Exchange]
[Ignore Signal]
```

Позже:

```text
[Auto Trade]
[Copy Strategy]
[Backtest Similar Signals]
```

---

# 24. Моя финальная рекомендация

Для MVP лучше всего сделать интерфейс вокруг **трех главных экранов**:

## 1. Radar

Главная лента сигналов.

## 2. Signal Details

Объяснение, торговый план, риск, SL/TP, confidence.

## 3. Trades

Отслеживание сохраненных и активных сигналов.

А уже вторым этапом добавить:

```text
Watchlist
Scanner
AI Assistant
Backtesting
Smart Money Dashboard
```

---

# Итоговая MVP-навигация

```text
Radar
Watchlist
Trades
Settings
```

AI можно встроить внутрь Signal Details как блок:

```text
AI Explanation
“Почему появился этот сигнал?”
```

А отдельный AI Assistant сделать позже.

Главный принцип интерфейса:

> **Не показывать пользователю весь рынок. Показывать лучшие возможности и объяснять, почему они важны.**

Лучшее место для журнала сделок — отдельный раздел **Trades**, но внутри него нужно разделить две сущности:

1. **Active Trades** — текущие активные сделки / идеи
2. **Trade Journal** — история, аналитика и разбор сделок

То есть в нижнем меню или sidebar оставляем пункт:

```text
Radar
Watchlist
Trades
Settings
```

А внутри **Trades** делаем вкладки:

```text
[Active] [Journal] [Analytics]
```

---

# Как это встроить в UX

## 1. Trades → Active

Это экран для текущих сделок.

Сюда попадают:

```text
Открытые сделки с бирж
Виртуальные сделки
Сохраненные сигналы
Сделки в ожидании входа
```

Пример:

```text
BTC/USDT Long
Source: Binance
Status: Active
Entry: 67,950
Current: 68,420
PnL: +0.69%
SL: 67,420
TP1: 68,900

[View Trade]
```

Или:

```text
SOL/USDT Short
Source: Paper Trade
Status: Waiting Entry
Signal: Breakdown Strategy
Confidence: 76%
```

---

## 2. Trades → Journal

Это уже полноценный журнал завершенных и частично завершенных сделок.

Сюда попадают:

```text
Закрытые сделки с бирж
Виртуальные сделки
Сделки, созданные из сигналов Crypto_radar
Ручные сделки пользователя
```

Пример строки журнала:

```text
ETH/USDT Short
Source: Bybit
Strategy: RSI Divergence
Result: +2.4%
Risk/Reward: 1:2.1
Duration: 3h 42m
Status: TP2 Hit
```

Главная задача журнала — не просто показать историю, а помочь пользователю понять:

> Какие стратегии реально работают для него.

---

# 3. Trades → Analytics

Это аналитика по журналу сделок.

Здесь показываем:

```text
Win Rate
Average Profit
Average Loss
Profit Factor
Best Strategy
Worst Strategy
Best Timeframe
Best Exchange
Manual vs Signal Trades
Real vs Virtual Trades
```

Пример:

```text
Last 30 Days

Total Trades: 42
Win Rate: 61%
Profit Factor: 1.84
Average R/R: 1:2.2

Best Strategy:
EMA Pullback
Win Rate: 68%

Weak Strategy:
Breakout Chase
Win Rate: 39%
```

---

# Важное разделение: реальные и виртуальные сделки

Нужно сразу в UX заложить понятное разделение по источнику.

## Источник сделки

У каждой сделки должен быть `source`.

```text
Source:
- Binance
- Bybit
- OKX
- Paper Trade
- Manual
- Crypto_radar Signal
```

Но лучше отображать это дружелюбно:

```text
Real Trade
Virtual Trade
Signal Trade
Manual Trade
```

Например бейджами:

```text
[Binance] [Real]
[Paper] [Virtual]
[Signal] [AI]
[Manual]
```

---

# Предлагаемая структура раздела Trades

```text
Trades
------------------------------------------------

Tabs:
[Active] [Journal] [Analytics]

Filters:
[All] [Real] [Virtual] [Signal] [Manual]
[Binance] [Bybit] [OKX]
[Long] [Short]
[Scalp] [Intraday] [Swing]
[Win] [Loss] [Breakeven]

------------------------------------------------

Active Trades / Journal List
```

---

# Как это будет выглядеть в навигации

## Для MVP

Я бы не выносил журнал отдельным пунктом меню.

Лучше так:

```text
Radar
Watchlist
Trades
Settings
```

А внутри Trades:

```text
Active
Journal
Analytics
```

Почему так лучше:

* не перегружаем главное меню;
* пользователь интуитивно понимает, что сделки и журнал находятся вместе;
* легко масштабировать;
* удобно для мобильной версии.

---

# Вариант для Desktop

Для desktop можно сделать так:

```text
Sidebar:

Radar
Watchlist
Trades
  - Active Trades
  - Trade Journal
  - Analytics
Scanner
Settings
```

То есть **Journal** может быть подпунктом внутри Trades.

---

# Вариант для Mobile

Для мобильной версии:

```text
Bottom Navigation:

Radar
Watchlist
Trades
Settings
```

Внутри Trades:

```text
Segmented Control:
[Active] [Journal] [Stats]
```

---

# Как сделки будут попадать в журнал

## Поток 1: Сделка с биржи

```text
User подключил Binance / Bybit / OKX
↓
Мы подтягиваем историю ордеров и позиций
↓
Сопоставляем сделки с сигналами Crypto_radar
↓
Закрытые сделки попадают в Journal
↓
Открытые сделки попадают в Active
```

---

## Поток 2: Виртуальная сделка

```text
Пользователь увидел сигнал
↓
Нажал Save Trade / Paper Trade
↓
Система создала виртуальную сделку
↓
Пока цена не дошла до Entry — статус Waiting Entry
↓
После входа — Active
↓
После TP/SL/Expiration — Journal
```

---

## Поток 3: Ручная сделка

```text
Пользователь нажал Add Trade
↓
Выбрал пару, направление, entry, SL, TP
↓
Сделка попала в Active
↓
После закрытия — в Journal
```

---

# Очень важная функция: связь сделки с сигналом

Для Crypto_radar это критично.

У каждой сделки должно быть поле:

```text
Linked Signal
```

Например:

```text
BTC/USDT Long
Trade Source: Binance
Linked Signal: EMA Pullback Signal #24819
```

Это позволит потом анализировать:

```text
Сколько сигналов реально отработали
Какие стратегии дают прибыль
Какие сигналы пользователь игнорирует
Какие сигналы лучше работают на Binance или Bybit
```

---

# Экран Trade Details

При клике на сделку открываем детальный экран.

```text
BTC/USDT Long
Source: Binance
Status: Closed
Result: +2.4%

Entry: 67,950
Exit: 69,580
Stop Loss: 67,420
Take Profit: 68,900 / 69,450

Duration: 4h 12m
Risk/Reward: 1:2.4
Strategy: EMA Pullback
Signal Confidence: 84%
```

Ниже:

```text
Trade Timeline

12:04 — Signal detected
12:08 — Entry reached
12:09 — Position opened on Binance
13:22 — TP1 hit
15:47 — Position closed
```

Еще ниже:

```text
AI Review

This was a strong trade because the entry followed the planned pullback.
The exit was slightly late, but the trade respected risk management.
```

---

# Журнал должен быть не просто таблицей

Обычный журнал:

```text
Date | Pair | Side | Entry | Exit | PnL
```

Это скучно и мало полезно.

Для Crypto_radar лучше сделать **умный журнал**:

```text
Journal = история сделок + обучение + улучшение стратегии
```

То есть после каждой сделки система должна показывать:

```text
Что сработало
Что не сработало
Был ли вход по плану
Нарушил ли пользователь риск
Какой паттерн повторяется
```

---

# Рекомендуемый MVP-экран Journal

```text
Trade Journal

Summary:
Total Trades: 128
Win Rate: 58%
Net PnL: +14.6%
Best Strategy: EMA Pullback

Filters:
[All] [Real] [Virtual] [Signal] [Manual]
[Binance] [Bybit] [OKX]
[7D] [30D] [90D]

------------------------------------------------

BTC/USDT Long
+2.4%
Binance · Real
EMA Pullback · 15m
TP2 Hit

------------------------------------------------

ETH/USDT Short
-0.8%
Paper · Virtual
RSI Divergence · 5m
SL Hit

------------------------------------------------

SOL/USDT Long
+1.1%
Manual
Breakout · 1h
Closed manually
```

---

# Analytics — что обязательно заложить сразу

Даже если в MVP аналитика будет простой, структуру данных нужно заложить с самого начала.

Минимальные метрики:

```text
Total Trades
Win Rate
Net PnL
Average Win
Average Loss
Profit Factor
Max Drawdown
Average R/R
Best Strategy
Worst Strategy
Real vs Virtual Performance
Exchange Performance
Timeframe Performance
```

---

# Real vs Virtual — отдельный важный блок

Очень полезный экран:

```text
Real vs Virtual

Real Trades:
Win Rate: 54%
Net PnL: +8.2%

Virtual Trades:
Win Rate: 67%
Net PnL: +18.4%
```

Это покажет пользователю разницу между:

```text
как стратегия работает теоретически
и как пользователь реально исполняет сделки
```

Это сильная фича.

---

# Как назвать раздел

Есть несколько вариантов:

## Вариант 1

```text
Trades
```

Внутри:

```text
Active
Journal
Analytics
```

Самый простой и понятный.

## Вариант 2

```text
Portfolio
```

Внутри:

```text
Positions
History
Analytics
```

Звучит более инвестиционно, но менее точно для трейдинга.

## Вариант 3

```text
Journal
```

Внутри:

```text
Active
Closed
Stats
```

Слишком узко. Не покрывает активные позиции.

---

# Моя рекомендация

Использовать раздел:

# **Trades**

А внутри:

```text
Active
Journal
Analytics
```

Это лучше всего подходит под продукт.

---

# Итоговая архитектура экранов после добавления журнала

```text
Radar
  - Signal Feed
  - Signal Filters
  - Market Mood

Signal Details
  - Trade Setup
  - AI Explanation
  - Confirmation Checklist
  - Save / Paper Trade / Open Exchange

Watchlist
  - Favorite Pairs
  - Pair Status
  - Active Signals

Trades
  - Active Trades
  - Trade Journal
  - Trade Analytics
  - Trade Details

Settings
  - Exchanges
  - Risk Profile
  - Notifications
  - Subscription
```

---

# Ключевая UX-логика

Когда пользователь нажимает на сигнал:

```text
[Save Trade]
[Paper Trade]
[Open Exchange]
```

## Save Trade

Сохраняет идею без открытия сделки.

## Paper Trade

Создает виртуальную сделку и отслеживает результат.

## Open Exchange

Открывает биржу или позже создает реальную сделку через API.

---

# Финальное решение

Журнал сделок лучше встроить в раздел **Trades**, а не выносить отдельным главным экраном.

Финальная структура:

```text
Trades
├── Active
│   ├── Real positions
│   ├── Paper trades
│   └── Saved signals
│
├── Journal
│   ├── Closed real trades
│   ├── Closed paper trades
│   ├── Manual trades
│   └── Linked signal trades
│
└── Analytics
    ├── Win rate
    ├── PnL
    ├── Best strategies
    ├── Real vs Virtual
    └── User behavior analysis
```

Самая сильная идея:

> **Журнал должен не просто хранить сделки, а показывать, какие сигналы и стратегии реально зарабатывают.**
