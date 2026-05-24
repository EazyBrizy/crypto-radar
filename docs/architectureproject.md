Ниже — базовый blueprint для **AI Crypto Trading Intelligence System** как SaaS уровня “crypto radar for traders”: realtime-сканер, сигналы, подтверждение входа, журнал сделок, AI-разбор и будущий автотрейдинг.

---

# 1. Позиционирование продукта

**Главная идея:**

> **“Находи сделки раньше толпы”**

Второй вариант, более трейдерский:

> **“Радар ликвидаций, плотностей и перекосов рынка”**

Продукт не должен выглядеть как “аналитическая панель для чтения графиков”. Он должен ощущаться как **боевой терминал принятия решений**:

1. Открыл Radar
2. Увидел сигнал
3. Кликнул → получил анализ
4. Подтвердил или отклонил вход
5. Видишь результат в журнале
6. AI показывает, где была ошибка или где можно было взять больше

Ключевое UX-правило:

> От открытия приложения до решения по сделке — **меньше 30 секунд**.

---

# 2. Главный продуктовый контур

## Основные модули

### 1. Radar

Главный экран.

Показывает не рынок целиком, а **только actionable opportunities**:

| Сигнал         |    Пара |   Биржа | Направление | Вероятность | R/R | Срочность |
| -------------- | ------: | ------: | ----------: | ----------: | --: | --------: |
| Breakout       | BTCUSDT | Binance |        Long |         72% | 2.8 |      High |
| Liquidity Grab | ETHUSDT |     OKX |       Short |         68% | 2.1 |    Medium |
| Knife Catch    | SOLUSDT |   Bybit |        Long |         61% | 3.4 |      High |

Главное: пользователь не должен сам искать. Система должна сказать:

> “Вот сделка. Вот почему. Вот риск. Вот сценарий отмены.”

---

### 2. Signal Detail

Экран анализа сигнала.

Должен отвечать на 6 вопросов:

1. Почему появился сигнал?
2. Где вход?
3. Где стоп?
4. Где тейк?
5. Что отменяет идею?
6. Сколько можно потерять?

Пример:

```text
BTCUSDT / Binance Futures

Тип: пробой сопротивления + всплеск объема
Направление: Long
Entry: 68,420–68,600
Stop: 67,950
TP1: 69,300
TP2: 70,200
Risk/Reward: 1:2.7
Confidence: 72%

Причина:
- Цена пробила локальное сопротивление
- Объем выше среднего на 38%
- Funding нейтральный
- Open Interest растет без резкого перегрева
- Ликвидность выше текущей цены
```

CTA:

```text
[Войти в сделку] [Виртуально протестировать] [Отклонить]
```

---

### 3. Trade Journal

Два журнала:

1. **Real Trades** — реальные сделки через подключенные биржи.
2. **Virtual Trades** — виртуальные сделки, которые система открыла или предложила внутри приложения.

Каждая сделка должна хранить:

| Поле         | Описание                     |
| ------------ | ---------------------------- |
| exchange     | Binance / OKX / Bybit        |
| symbol       | BTCUSDT                      |
| strategy     | Breakout / Knife / Liquidity |
| entry        | цена входа                   |
| stop_loss    | стоп                         |
| take_profit  | тейки                        |
| size         | размер позиции               |
| risk_percent | риск на сделку               |
| result       | win/loss/breakeven           |
| pnl          | прибыль/убыток               |
| screenshots  | снимки графика               |
| AI review    | разбор ошибки                |

---

### 4. AI Trade Review System

Это может стать одной из самых сильных фич.

AI должен не просто писать “хорошая сделка / плохая сделка”, а разбирать по шаблону:

```text
Trade Review

Что было сделано правильно:
- Вход был по тренду.
- Риск был ограничен.
- Сетап соответствовал стратегии Breakout.

Ошибки:
- Вход был поздним: цена уже прошла 0.8 ATR от зоны пробоя.
- Stop Loss был слишком близко к зоне ликвидности.
- TP1 можно было поставить раньше, возле локальной плотности.

Что улучшить:
- Ждать ретест зоны.
- Не входить после импульса больше 1 ATR.
- Переносить стоп только после закрытия свечи выше уровня.

What-if:
Если бы держал до TP2: +28%
Фактически закрыл: +12%
Потерянная возможность: +16%
```

---

# 3. Архитектура SaaS

Я бы проектировал систему не как монолит “FastAPI + база”, а как **event-driven realtime platform**.

## Общая схема

```text
                ┌────────────────────┐
                │     Frontend        │
                │ Next.js / React     │
                └─────────┬──────────┘
                          │
                          ▼
                ┌────────────────────┐
                │  API Gateway        │
                │  FastAPI            │
                └─────────┬──────────┘
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
┌──────────────┐  ┌──────────────┐  ┌────────────────┐
│ Auth Service │  │ Billing      │  │ User Settings  │
│ JWT/OAuth    │  │ Stripe       │  │ Strategies     │
└──────────────┘  └──────────────┘  └────────────────┘

                          │
                          ▼
              ┌──────────────────────┐
              │ Event Bus / Queue     │
              │ Kafka / Redpanda      │
              └──────────┬───────────┘
                         │
       ┌─────────────────┼─────────────────┐
       ▼                 ▼                 ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────────┐
│ Market Data  │ │ Signal Engine│ │ Virtual Trading  │
│ Collectors   │ │ Strategies   │ │ Simulator        │
└──────────────┘ └──────────────┘ └──────────────────┘
       │                 │                 │
       ▼                 ▼                 ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────────┐
│ TimescaleDB  │ │ PostgreSQL   │ │ Trade Journal    │
│ ClickHouse   │ │ Redis Cache  │ │ PostgreSQL       │
└──────────────┘ └──────────────┘ └──────────────────┘

                          │
                          ▼
                ┌────────────────────┐
                │ AI Review Service   │
                │ LLM + rules + RAG   │
                └────────────────────┘
```

---

# 4. Рекомендуемый tech stack

## Backend

**Core API:**

```text
FastAPI
Pydantic
SQLAlchemy / SQLModel
Alembic
PostgreSQL
Redis
Celery / Dramatiq / Arq
Kafka или Redpanda
```

FastAPI подходит для API-слоя, WebSocket-эндпоинтов и личного кабинета. Но тяжелые задачи — сканирование, стратегии, AI-анализ, пересчет сигналов — нельзя держать в обычных `BackgroundTasks`. В официальной документации FastAPI прямо указано, что для тяжелых фоновых вычислений и распределенного выполнения стоит использовать более крупные инструменты вроде Celery с брокером Redis/RabbitMQ. ([fastapi.tiangolo.com][1])

## Realtime market data

```text
WebSocket collectors
Exchange adapters
Kafka / Redpanda event stream
Redis hot cache
ClickHouse / TimescaleDB for ticks, candles, orderbook snapshots
```

Почему так:

* WebSocket нужен для низкой задержки.
* Kafka/Redpanda нужен, чтобы отделить получение данных от анализа.
* Redis нужен для последних цен, активных сигналов, пользовательских фильтров.
* ClickHouse или TimescaleDB — для исторических свечей, тиков, order book snapshots.

Биржи имеют разные лимиты и правила API, поэтому нужен отдельный **Exchange Adapter Layer**. Например, OKX указывает REST и WebSocket API, рекомендует WebSocket для market data и order book depth, а также описывает лимиты подключений, подписок и rate limits по типам запросов. ([OKX][2])

---

# 5. Exchange Adapter Layer

Нельзя писать логику напрямую под Binance/OKX/Bybit в стратегиях. Нужен единый интерфейс.

## Интерфейс адаптера

```python
class ExchangeAdapter:
    async def get_symbols(self) -> list[str]:
        ...

    async def stream_trades(self, symbols: list[str]):
        ...

    async def stream_orderbook(self, symbols: list[str]):
        ...

    async def stream_candles(self, symbols: list[str], timeframe: str):
        ...

    async def get_account(self, user_id: str):
        ...

    async def place_order(self, order):
        ...

    async def cancel_order(self, order_id: str):
        ...
```

## Реализации

```text
BinanceAdapter
OKXAdapter
BybitAdapter
KuCoinAdapter
GateAdapter
```

## Важная логика

Каждый адаптер должен иметь:

```text
rate limit manager
connection manager
reconnect logic
heartbeat / ping-pong
symbol mapper
precision mapper
fee model
order type mapper
error normalizer
```

Пример нормализации символов:

```text
Binance: BTCUSDT
OKX: BTC-USDT-SWAP
Bybit: BTCUSDT
Internal: BTC/USDT:PERP
```

Внутри системы все должно приводиться к единому формату.

---

# 6. Realtime scanning pipeline

## Поток данных

```text
Exchange WS
   ↓
Raw Market Event
   ↓
Normalizer
   ↓
Kafka Topic: market.trades
Kafka Topic: market.orderbook
Kafka Topic: market.candles
   ↓
Feature Builder
   ↓
Strategy Engine
   ↓
Signal Scoring
   ↓
Signal Store
   ↓
Frontend Radar
```

## Kafka topics

```text
market.trades.raw
market.orderbook.raw
market.candles.raw
market.liquidations.raw

market.trades.normalized
market.orderbook.normalized
market.candles.normalized

features.symbol.1m
features.symbol.5m

signals.created
signals.updated
signals.expired

trades.virtual.opened
trades.virtual.closed
trades.real.synced

ai.review.requested
ai.review.completed
```

---

# 7. Strategy Engine

Стратегии должны быть не “зашиты в коде”, а оформлены как модули.

## Базовый интерфейс стратегии

```python
class Strategy:
    name: str
    version: str
    required_data: list[str]

    async def evaluate(self, context: MarketContext) -> Signal | None:
        ...
```

## Примеры стратегий

### 1. Breakout

```text
Условия:
- Цена пробивает уровень сопротивления
- Объем выше среднего
- Закрытие свечи выше уровня
- Нет экстремального funding
- Есть пространство до ближайшей liquidity zone
```

### 2. Support / Resistance Bounce

```text
Условия:
- Цена подошла к уровню
- Объем замедляется
- Есть реакция от уровня
- Orderbook показывает плотность
- Risk/reward не меньше 1:2
```

### 3. Knife Catch

Очень опасная стратегия. Ее нужно отдавать только продвинутым пользователям.

```text
Условия:
- Резкое падение
- Касание зоны ликвидности
- Капитуляционный объем
- Замедление импульса
- Дивергенция или absorption
```

### 4. Liquidity Grab / Smart Money

```text
Условия:
- Снятие локального high/low
- Возврат под уровень
- Рост объема на проколе
- Отсутствие продолжения
- Потенциальный reversal
```

### 5. Order Book Density

```text
Условия:
- Крупная лимитная плотность
- Цена подходит к зоне
- Плотность не снимается
- Есть реакция market orders
```

---

# 8. Signal scoring

Сигнал не должен быть просто “buy/sell”. У него должен быть скоринг.

## Формула оценки

```text
Signal Score =
Trend Score
+ Volume Score
+ Liquidity Score
+ Orderbook Score
+ Risk/Reward Score
+ Volatility Score
- Overheat Penalty
- News/Event Risk Penalty
```

## Пример структуры сигнала

```json
{
  "id": "sig_123",
  "symbol": "BTC/USDT:PERP",
  "exchange": "binance",
  "strategy": "breakout_v1",
  "direction": "long",
  "entry_min": 68420,
  "entry_max": 68600,
  "stop_loss": 67950,
  "take_profit_1": 69300,
  "take_profit_2": 70200,
  "confidence": 0.72,
  "risk_reward": 2.7,
  "urgency": "high",
  "expires_at": "2026-05-24T12:30:00Z",
  "explanation": [
    "Resistance broken",
    "Volume above average",
    "Open interest rising",
    "Liquidity above current price"
  ]
}
```

---

# 9. Virtual Trading System

Это критически важный модуль, потому что он позволяет пользователю доверять системе без риска.

## Логика

```text
Сигнал появился
   ↓
Пользователь нажал “Виртуально протестировать”
или стратегия auto-paper включена
   ↓
Создается виртуальный ордер
   ↓
Реальный рынок двигается
   ↓
Система симулирует исполнение
   ↓
Учитывает комиссии, funding, slippage
   ↓
Закрывает по TP/SL/strategy exit
   ↓
Пишет результат в Virtual Journal
```

## Что обязательно учитывать

```text
комиссия биржи
slippage
spread
funding
частичное исполнение
ликвидационная цена для futures
risk per trade
max daily loss
max open positions
```

## Структура virtual position

```json
{
  "user_id": "user_1",
  "signal_id": "sig_123",
  "mode": "virtual",
  "exchange": "binance",
  "symbol": "BTC/USDT:PERP",
  "side": "long",
  "entry_price": 68480,
  "size_usd": 100,
  "leverage": 3,
  "stop_loss": 67950,
  "take_profit": [69300, 70200],
  "fees": 0.08,
  "status": "open"
}
```

---

# 10. Future Auto-Trading

Автотрейдинг нельзя включать в MVP как основную фичу. Его надо заложить архитектурно, но запускать постепенно.

## Этапы

### Этап 1 — Manual Confirm

```text
Система дает сигнал
Пользователь сам нажимает “Войти”
```

### Этап 2 — Semi-Auto

```text
Пользователь заранее разрешает:
- конкретные стратегии
- конкретные пары
- max risk
- max leverage
- max daily loss

Но каждый вход еще требует подтверждения.
```

### Этап 3 — Auto Paper Trading

```text
Система автоматически открывает только виртуальные сделки.
```

### Этап 4 — Auto Real Trading

```text
Система может открывать реальные сделки,
но только в рамках risk policy.
```

## Risk Policy

Перед любой реальной сделкой должен быть Risk Guard:

```text
max risk per trade: 1%
max daily loss: 3%
max leverage: 5x
max open positions: 3
cooldown after loss: 30 min
no trade during high volatility spike
no trade if spread too wide
no trade if exchange API unstable
```

---

# 11. AI Layer

AI не должен принимать решение “войти или не войти” самостоятельно. Он должен:

```text
объяснять сигнал
сравнивать сценарии
разбирать сделку
искать ошибки
генерировать what-if
объяснять риск
помогать пользователю улучшать стратегию
```

## AI-модули

```text
Signal Explainer
Trade Reviewer
Strategy Coach
What-if Simulator
User Behavior Analyzer
```

## AI Review Pipeline

```text
Trade closed
   ↓
Collect trade data
   ↓
Collect market context before/during/after trade
   ↓
Build structured review prompt
   ↓
LLM analysis
   ↓
Save review
   ↓
Show to user
```

## AI не должен делать

```text
гарантировать прибыль
обещать точность
давать “финансовый совет” без risk context
открывать сделки без risk guard
```

---

# 12. Frontend

## Рекомендованный stack

```text
Next.js
React
TypeScript
TailwindCSS
shadcn/ui
Recharts / Lightweight Charts
WebSocket client
Zustand / TanStack Query
```

## Основные страницы

```text
/login
/onboarding
/radar
/signals/[id]
/trades
/trades/[id]
/virtual-trading
/strategies
/exchanges
/billing
/settings
```

## Главный layout

```text
Left sidebar:
- Radar
- Signals
- Virtual Trading
- Trade Journal
- AI Reviews
- Strategies
- Exchanges
- Billing

Top bar:
- выбранные биржи
- выбранные пары
- риск-профиль
- статус подписки
- статус WebSocket

Main area:
- realtime signal feed
```

---

# 13. Подписочная модель

Stripe Billing подходит для recurring subscriptions, trials, usage-based billing, customer portal и управления жизненным циклом подписок. В документации Stripe также указано, что доступ к продукту можно выдавать через активные entitlements подписки. ([Документы Stripe][3])

## Тарифы

### Free

```text
1 биржа
5 сигналов в день
только basic strategies
virtual trading limited
без AI review
```

### Pro — $29–$49/month

```text
3 биржи
realtime radar
до 100 сигналов в день
basic + intermediate strategies
virtual trading
trade journal
AI review limited
```

### Advanced — $99–$149/month

```text
все биржи
unlimited radar
smart money strategies
liquidity radar
orderbook density
AI trade review
what-if simulator
strategy customization
```

### Elite — $299+/month

```text
semi-auto trading
advanced risk engine
custom strategies
webhook alerts
API access
priority data
team workspace
```

---

# 14. Личный кабинет пользователя

## User settings

```text
выбранные биржи
избранные пары
таймфреймы
активные стратегии
risk profile
уведомления
язык
тема
подписка
API keys
```

## Exchange connection

API-ключи хранить только в зашифрованном виде.

```text
user_exchange_accounts
- user_id
- exchange
- api_key_encrypted
- api_secret_encrypted
- permissions
- trading_enabled
- created_at
```

Для MVP лучше сначала разрешить ключи **read-only**, а торговые права включать позже.

---

# 15. Безопасность

Для такого продукта безопасность — не “потом”, а фундамент.

## Обязательно

```text
2FA
JWT access + refresh tokens
encrypted API keys
separate secrets vault
IP allowlist recommendation
read-only API keys by default
trading permission warning
audit logs
withdrawals never supported
rate limit per user
risk guard before execution
```

## Запретить на уровне продукта

```text
withdrawal permissions
copying user API keys into logs
unlimited leverage
auto-trading without limits
one-click all-in trades
```

---

# 16. Масштабирование: 10,000 → 1,000,000 пользователей

## До 10,000 пользователей

Можно стартовать так:

```text
FastAPI monolith modular
PostgreSQL
Redis
1–3 market data workers
Celery/Arq workers
TimescaleDB или ClickHouse
Docker Compose / single Kubernetes cluster
```

## 10,000–100,000 пользователей

Разделить сервисы:

```text
api-service
auth-service
billing-service
market-data-service
signal-engine-service
notification-service
virtual-trading-service
ai-review-service
```

## 100,000–1,000,000+ пользователей

Нужна полноценная event-driven архитектура:

```text
Kubernetes
Kafka/Redpanda
ClickHouse cluster
PostgreSQL read replicas
Redis Cluster
separate strategy workers
separate websocket gateways
multi-region read layer
observability stack
```

## Что масштабируется отдельно

```text
market data ingestion
strategy evaluation
signal delivery
user notifications
AI reviews
trade journal queries
billing
```

---

# 17. Базы данных

## PostgreSQL

Для бизнес-данных:

```text
users
subscriptions
exchange_accounts
strategies
signals
trades
virtual_trades
ai_reviews
billing_events
```

## Redis

Для горячих данных:

```text
latest prices
active signals
user sessions
rate limits
temporary strategy state
websocket subscriptions
```

## ClickHouse / TimescaleDB

Для market data:

```text
ticks
candles
orderbook snapshots
liquidations
open interest
funding rates
volume profiles
```

---

# 18. MVP roadmap

## MVP 1 — Radar + Manual Signals

Цель: пользователь видит сигналы и может принять решение.

```text
FastAPI backend
Next.js frontend
Auth
Stripe subscriptions
Binance/OKX/Bybit market data
Radar screen
Signal detail screen
Basic strategies:
- breakout
- support/resistance
- volume spike
- liquidity sweep
Manual confirm/reject
Basic trade journal
```

## MVP 2 — Virtual Trading

```text
virtual order engine
virtual position tracking
fees/slippage model
virtual trade journal
strategy performance stats
```

## MVP 3 — AI Trade Review

```text
AI review after closed trade
what-if scenarios
mistake detection
strategy coaching
```

## MVP 4 — Strategy Marketplace / Custom Strategies

```text
enable/disable strategies
strategy settings
risk profiles
user-created strategy rules
```

## MVP 5 — Semi-Auto / Auto Trading

```text
API key trading permissions
risk guard
manual approval
auto paper trading
limited real auto-trading
```

---

# 19. Минимальная структура backend-проекта

```text
app/
  main.py
  core/
    config.py
    security.py
    database.py
    redis.py
  api/
    v1/
      auth.py
      users.py
      radar.py
      signals.py
      trades.py
      strategies.py
      exchanges.py
      billing.py
  models/
    user.py
    signal.py
    trade.py
    subscription.py
    strategy.py
  services/
    signal_service.py
    trade_service.py
    ai_review_service.py
    billing_service.py
  exchanges/
    base.py
    binance.py
    okx.py
    bybit.py
  strategies/
    base.py
    breakout.py
    support_resistance.py
    liquidity_grab.py
    knife_catch.py
  workers/
    market_data_worker.py
    signal_worker.py
    virtual_trade_worker.py
    ai_review_worker.py
  schemas/
    signal.py
    trade.py
    user.py
```

---

# 20. Самое важное продуктово

Не пытаться сразу строить “супер-AI автотрейдера”.

Правильный порядок:

```text
1. Сначала Radar, который реально находит интересные ситуации.
2. Потом объяснение сигнала.
3. Потом виртуальная проверка.
4. Потом журнал и AI-разбор.
5. Потом кастомные стратегии.
6. Только потом автотрейдинг.
```

Главный продуктовый крючок:

> Пользователь должен каждый день видеть:
> “Вот сделки, которые я бы сам не успел найти.”

А главный retention-крючок:

> “Вот почему ты заработал меньше, чем мог, и как исправить это в следующий раз.”

Для MVP я бы зафиксировал такой первый оффер:

> **AI Crypto Radar: realtime-сигналы по ликвидности, пробоям и перекосам рынка с виртуальной проверкой и AI-разбором сделок.**

[1]: https://fastapi.tiangolo.com/tutorial/background-tasks/?utm_source=chatgpt.com "Background Tasks - FastAPI"
[2]: https://www.okx.com/docs-v5/en/?utm_source=chatgpt.com "OKX API guide | OKX technical support | OKX"
[3]: https://docs.stripe.com/billing/subscriptions/creating?utm_source=chatgpt.com "How subscriptions work | Stripe Documentation"
