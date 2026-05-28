Ниже — backend-архитектура для **Crypto_radar** как real-time SaaS: быстрый радар сигналов, стратегии, виртуальные сделки, журнал сделок, личный кабинет, подписки, масштабирование от **10 000 пользователей на старте** до **1 000 000+**.

---

# 1. Главный принцип backend для Crypto_radar

У нас не обычный CRUD-сервис. Это **event-driven real-time система**.

Пользовательский сценарий:

**Биржа → рыночные данные → стратегия → сигнал → frontend → вход в позицию → виртуальная сделка → журнал → аналитика**

Ключевое требование:
**сигнал должен появляться у пользователя сразу после обнаружения, без polling и обновления по таймеру.**

Поэтому backend должен быть построен не вокруг “запрос-ответ”, а вокруг потоков событий:

```text
Exchange WebSocket
      ↓
Market Data Ingestion
      ↓
Event Bus / Stream
      ↓
Strategy Engine
      ↓
Signal Engine
      ↓
Realtime Gateway
      ↓
Frontend WebSocket / SSE
```

FastAPI здесь подходит хорошо, потому что работает поверх ASGI-модели, совместимой с async HTTP и WebSocket. Uvicorn официально использует ASGI, а WebSocket в Uvicorn начинается как HTTP-соединение и затем апгрейдится до WebSocket-соединения, что как раз подходит для реактивной доставки сигналов на frontend. ([Uvicorn][1])

---

# 2. Рекомендуемый backend stack

## Базовый production stack

| Зона               | Технология                                         | Зачем                                                                |
| ------------------ | -------------------------------------------------- | -------------------------------------------------------------------- |
| API backend        | **Python 3.12+ / FastAPI**                         | Быстрый async API, WebSocket, OpenAPI, хорошая совместимость с ML/AI |
| ASGI server        | **Uvicorn / Gunicorn ASGI**                        | Production serving, WebSocket, async workers                         |
| Event bus          | **NATS JetStream на старте**, Kafka/Redpanda позже | Потоковая обработка сигналов и market data                           |
| Main DB            | **PostgreSQL 17/18**                               | Пользователи, подписки, сделки, настройки, стратегии                 |
| Time-series / OLAP | **ClickHouse**                                     | Свечи, тики, стаканы, сигналы, аналитика                             |
| Cache / hot state  | **Redis Cluster**                                  | Активные сессии, последние цены, rate limits, лидерборды             |
| Background jobs    | **Arq / Dramatiq / Celery**, позже Temporal        | Асинхронные задачи, пересчеты, уведомления                           |
| Auth               | **JWT + refresh tokens**, позже OIDC               | Личный кабинет, API security                                         |
| Payments           | Stripe / Paddle / Crypto payments layer            | Подписочная модель                                                   |
| Containerization   | Docker                                             | Изоляция сервисов                                                    |
| Orchestration      | Kubernetes                                         | Масштабирование, self-healing, rolling deploys                       |
| Observability      | OpenTelemetry + Prometheus + Grafana + Loki        | Метрики, логи, трейсы                                                |
| API Gateway        | Traefik / Envoy / NGINX                            | TLS, маршрутизация, rate limit                                       |
| CI/CD              | GitHub Actions / GitLab CI                         | Автоматический deploy                                                |
| IaC                | Terraform + Helm                                   | Инфраструктура как код                                               |

---

# 3. Почему не монолит

На старте можно сделать **modular monolith + event bus**, но архитектурно сразу заложить разделение доменов.

Не нужно с первого дня делать 25 микросервисов. Это усложнит разработку. Но нельзя писать один “комбайн”, где FastAPI одновременно:

* слушает биржи;
* считает стратегии;
* хранит свечи;
* отправляет WebSocket;
* считает PnL;
* обрабатывает подписки;
* делает backtest;
* шлет уведомления.

Правильный путь:

```text
Stage 1: Modular Monolith + выделенные воркеры
Stage 2: Service-oriented architecture
Stage 3: Full event-driven microservices
```

---

# 4. Backend-модули Crypto_radar

## 4.1. API Gateway / Backend API

Основной публичный backend для frontend.

Функции:

* авторизация;
* пользовательский профиль;
* подписки;
* настройки радара;
* список стратегий;
* избранные пары;
* журнал сделок;
* виртуальные сделки;
* REST API для исторических данных;
* WebSocket/SSE endpoint для real-time данных.

Рекомендуемый стек:

```text
FastAPI
Pydantic v2
SQLAlchemy 2.0 async
Alembic
asyncpg
Redis client
NATS client
```

API не должен напрямую считать стратегии. Он должен быть тонким слоем между пользователем и системой.

---

## 4.2. Market Data Ingestion Service

Это один из самых важных компонентов.

Он подключается к биржам:

* Binance;
* Bybit;
* OKX;
* Coinbase;
* KuCoin;
* Gate;
* MEXC;
* позже DEX/on-chain.

Получает:

* trades;
* order book;
* tickers;
* candles;
* funding rate;
* open interest;
* liquidations;
* volume;
* spread;
* volatility.

Архитектура:

```text
Exchange WS Client
      ↓
Normalizer
      ↓
Deduplicator
      ↓
Validator
      ↓
Event Bus
      ↓
ClickHouse / Redis / Strategy Engine
```

Важно: каждая биржа имеет разный формат данных. Поэтому нужен слой нормализации.

Пример внутреннего события:

```json
{
  "event_type": "market.trade",
  "exchange": "binance",
  "symbol": "BTCUSDT",
  "price": 68320.5,
  "quantity": 0.14,
  "side": "buy",
  "event_time": "2026-05-26T12:00:01.123Z",
  "received_at": "2026-05-26T12:00:01.170Z"
}
```

---

## 4.3. Event Bus

Для Crypto_radar event bus — это центральная нервная система.

На старте я бы выбрал:

## **NATS JetStream**

Почему:

* проще Kafka;
* низкая задержка;
* хорош для real-time;
* есть persistence;
* есть replay;
* есть consumer groups;
* проще DevOps;
* отлично подходит для MVP и первой production-версии.

JetStream хранит сообщения и позволяет проигрывать их позже; в кластере можно включать репликацию для отказоустойчивости. NATS также поддерживает durable consumers, которые сохраняют прогресс чтения на стороне сервера и подходят для горизонтального масштабирования обработчиков. ([docs.nats.io][2])

### Когда переходить на Kafka / Redpanda

Kafka или Redpanda стоит рассматривать, когда:

* поток данных стал огромным;
* нужен долгий event log;
* много независимых consumer-групп;
* нужна строгая аналитическая event-streaming платформа;
* появились команды data engineering / ML / BI;
* ClickHouse, ML, backtest, alerting и audit читают одни и те же потоки.

Kafka остается фундаментальной платформой для high-throughput event streaming, но требует больше операционной экспертизы. В сравнительных исследованиях Kafka показывает очень высокий throughput, но сложнее в эксплуатации, тогда как Pulsar/NATS/другие брокеры дают другие компромиссы по latency, multi-tenancy и операционной сложности. ([arXiv][3])

### Рекомендация

```text
MVP / до 10k пользователей: NATS JetStream
Growth / 100k+: NATS JetStream + ClickHouse pipelines
Enterprise scale / 1M+: Kafka или Redpanda для long-term event streaming
```

---

# 5. Хранилища данных

## 5.1. PostgreSQL — системная база

PostgreSQL используем для данных, где важна целостность:

* users;
* auth sessions;
* subscriptions;
* billing;
* user settings;
* strategies;
* virtual positions;
* trade journal;
* alerts;
* permissions;
* audit log;
* API keys;
* portfolio connections.

PostgreSQL поддерживает partitioning, что полезно для больших таблиц, например сделок, событий пользователя и audit logs. Partitioning делит одну логическую таблицу на физические части и может резко улучшить запросы, когда данные фильтруются по активным диапазонам, например по времени. ([PostgreSQL][4])

Для масштабирования:

```text
1. Primary PostgreSQL
2. Read replicas
3. PgBouncer
4. Partitioning
5. Logical replication
6. Sharding по user_id на поздней стадии
```

PostgreSQL logical replication работает по модели publisher/subscriber и позволяет передавать изменения подписчикам, что пригодится для аналитики, миграций, CDC и разделения read-моделей. ([PostgreSQL][5])

---

## 5.2. ClickHouse — рыночные данные и аналитика

Для market data PostgreSQL не подходит как основное хранилище. Свечи, сделки, стаканы, сигналы и агрегаты будут расти слишком быстро.

Используем **ClickHouse**.

Что хранить в ClickHouse:

* raw trades;
* candles 1s / 1m / 5m / 1h;
* order book snapshots;
* funding history;
* open interest;
* liquidations;
* generated signals;
* strategy performance;
* backtest results;
* market regimes;
* volatility metrics.

ClickHouse лучше подходит для real-time OLAP и аналитики по миллиардам строк, тогда как TimescaleDB удобнее, если команда хочет остаться внутри PostgreSQL-экосистемы. Для Crypto_radar, где будут массовые рыночные события, быстрые агрегации и аналитические dashboards, ClickHouse — более правильный выбор. ([modern-datatools.com][6])

Пример таблицы:

```sql
CREATE TABLE market_trades
(
    exchange LowCardinality(String),
    symbol LowCardinality(String),
    price Float64,
    quantity Float64,
    side LowCardinality(String),
    event_time DateTime64(3),
    received_at DateTime64(3)
)
ENGINE = MergeTree
PARTITION BY toYYYYMMDD(event_time)
ORDER BY (exchange, symbol, event_time);
```

Для свечей:

```sql
CREATE TABLE candles_1m
(
    exchange LowCardinality(String),
    symbol LowCardinality(String),
    timeframe LowCardinality(String),
    open Float64,
    high Float64,
    low Float64,
    close Float64,
    volume Float64,
    candle_time DateTime
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(candle_time)
ORDER BY (exchange, symbol, timeframe, candle_time);
```

---

## 5.3. Redis — hot state

Redis не должен быть “главной базой”. Его роль:

* последние цены;
* последние сигналы;
* активные WebSocket subscriptions;
* rate limiting;
* online users;
* short-lived locks;
* idempotency keys;
* временные результаты стратегий;
* leaderboard cache;
* session cache.

Пример ключей:

```text
price:binance:BTCUSDT
signal:last:BTCUSDT
user:123:radar_filters
ws:subscriptions:BTCUSDT
rate_limit:user:123
```

---

# 6. Real-time доставка на frontend

Frontend не должен спрашивать backend каждые 2 секунды. Backend должен пушить данные сам.

## Основной вариант: WebSocket

Использовать для:

* live signals;
* live prices;
* live position updates;
* live trade journal updates;
* market scanner updates.

Пример каналов:

```text
/ws/radar
/ws/signals
/ws/positions
/ws/market/BTCUSDT
/ws/user-events
```

Сообщение:

```json
{
  "type": "signal.created",
  "payload": {
    "signal_id": "sig_123",
    "symbol": "BTCUSDT",
    "exchange": "binance",
    "strategy": "volume_breakout",
    "direction": "long",
    "confidence": 0.82,
    "entry_zone": [68200, 68400],
    "stop_loss": 67600,
    "take_profit": [69100, 70400],
    "created_at": "2026-05-26T12:00:00Z"
  }
}
```

## Альтернатива: SSE

SSE можно использовать для:

* уведомлений;
* простых one-way потоков;
* системных событий.

Но для радаров, подписок на пары, интерактивных пользовательских действий и reconnect logic лучше WebSocket.

---

# 7. Strategy Engine

Это отдельный сервис или группа воркеров.

Он не должен жить внутри API.

```text
Market events
    ↓
Feature builder
    ↓
Strategy rules
    ↓
Signal scoring
    ↓
Risk filter
    ↓
Signal event
```

## Что делает Strategy Engine

* считает индикаторы;
* проверяет условия стратегий;
* фильтрует шум;
* присваивает confidence score;
* рассчитывает entry / SL / TP;
* определяет риск;
* создает сигнал;
* публикует событие `signal.created`.

## Стратегии MVP

Из прошлой логики проекта я бы заложил поддержку:

1. **Volume breakout**
2. **Trend pullback**
3. **Liquidity sweep / Smart Money lite**

В backend это должно быть не hardcoded в одном файле, а через strategy registry.

Пример:

```python
class Strategy(Protocol):
    name: str
    version: str

    async def on_candle(self, candle: Candle) -> list[Signal]:
        ...

    async def on_trade(self, trade: Trade) -> list[Signal]:
        ...
```

Стратегия должна быть версионируемой:

```text
volume_breakout:v1
volume_breakout:v2
smart_money_liquidity_sweep:v1
```

Почему это важно: если пользователь вошел по сигналу старой версии стратегии, мы должны понимать, какая именно логика его создала.

---

# 8. Signal Engine

Strategy Engine находит setup. Signal Engine решает, можно ли показывать сигнал пользователю.

Фильтры:

* ликвидность;
* spread;
* volatility;
* funding;
* биржа;
* blacklisted symbols;
* user plan;
* user filters;
* market regime;
* correlation risk;
* повторяющиеся сигналы;
* cooldown по символу;
* минимальный confidence.

Пример pipeline:

```text
Raw Strategy Signal
      ↓
Liquidity Filter
      ↓
Spread Filter
      ↓
Volatility Filter
      ↓
Risk Model
      ↓
User Segmentation
      ↓
Publish to Realtime Gateway
```

---

# 9. Virtual Trading Engine

Так как у вас будет виртуальная торговля, нужен отдельный движок.

Он должен:

* открывать виртуальные позиции;
* закрывать позиции;
* считать PnL;
* учитывать комиссии;
* учитывать slippage;
* учитывать funding;
* хранить историю;
* обновлять позицию в real-time;
* не влиять на рынок.

Важно: виртуальная сделка не должна считаться “идеальной”. Нужно симулировать исполнение.

Для мало ликвидных монет:

```text
entry_price = market_price + simulated_slippage
slippage = function(order_size, spread, order_book_depth, volatility)
```

То есть если пользователь “виртуально” покупает на $10 000 монету с тонким стаканом, backend должен показать худшее исполнение, а не просто цену последней сделки.

---

# 10. Trade Journal

Журнал сделок должен быть единым для:

* виртуальных сделок;
* импортированных сделок с бирж;
* будущих реальных сделок;
* ручных записей пользователя.

Модель:

```text
Trade
 ├── source: virtual | exchange | manual | bot
 ├── exchange
 ├── symbol
 ├── side
 ├── entry
 ├── exit
 ├── size
 ├── leverage
 ├── fees
 ├── pnl
 ├── strategy_id
 ├── signal_id
 ├── screenshots / notes
 └── tags
```

Журнал лучше хранить в PostgreSQL, а агрегированную аналитику — дублировать в ClickHouse.

---

# 11. Auth и безопасность

## Стек

```text
JWT access token
Refresh token rotation
HttpOnly cookies для web
Argon2id для паролей
2FA позже
OAuth позже
RBAC / ABAC
```

## Важные правила

* access token короткий: 5–15 минут;
* refresh token хранить безопасно;
* refresh token rotation;
* device sessions;
* revoke sessions;
* rate limit login;
* audit login events;
* защита от brute force.

## API keys бирж

Если пользователь подключает биржу:

* ключи шифровать;
* использовать envelope encryption;
* хранить отдельно от основной бизнес-логики;
* никогда не логировать;
* поддерживать read-only ключи на первом этапе;
* trading permission включать только позже.

---

# 12. Подписочная система

Backend должен поддерживать разные планы:

```text
Free
 ├── delayed signals
 ├── ограниченное число пар
 ├── базовые стратегии

Pro
 ├── realtime signals
 ├── больше бирж
 ├── virtual trading
 ├── journal analytics

Premium
 ├── smart money strategies
 ├── advanced filters
 ├── AI assistant
 ├── alerts

Enterprise / Fund
 ├── API access
 ├── team accounts
 ├── custom limits
```

В backend это не должно быть просто `if user.plan == "pro"` в коде. Нужна feature entitlement система:

```text
feature: realtime_signals
feature: max_symbols_watchlist
feature: advanced_strategies
feature: virtual_trading
feature: exchange_import
feature: ai_explanations
```

---

# 13. Масштабирование до 10 000 пользователей

На старте можно держать архитектуру так:

```text
Cloud Load Balancer
      ↓
API Gateway
      ↓
FastAPI API pods
      ↓
PostgreSQL primary + replica
Redis
NATS JetStream cluster
ClickHouse single node / small cluster
Strategy workers
Market ingestion workers
Realtime gateway workers
```

## Минимальный production размер

```text
API: 3 pods
Realtime Gateway: 3 pods
Market Ingestion: 2-4 pods
Strategy Workers: 4-8 pods
NATS JetStream: 3 nodes
Redis: 3 nodes / managed Redis
PostgreSQL: managed primary + read replica
ClickHouse: 1-3 nodes
```

## Почему отдельный Realtime Gateway

WebSocket-соединения долгоживущие. Если держать их в том же API, что и REST-запросы, будет сложнее масштабировать.

Лучше:

```text
REST API Service
Realtime Gateway Service
```

Realtime Gateway:

* держит WebSocket;
* подписывает пользователя на символы;
* фильтрует события по правам;
* читает события из NATS;
* пушит на frontend.

---

# 14. Масштабирование до 1 000 000+ пользователей

На уровне 1M+ пользователей архитектура должна стать multi-layer.

```text
Global CDN / Edge
      ↓
API Gateway / WAF
      ↓
Regional Kubernetes clusters
      ↓
Service mesh
      ↓
Event streaming layer
      ↓
Sharded databases
      ↓
OLAP lake / ClickHouse cluster
```

## Что придется добавить

### 1. Разделение регионов

```text
eu-west
us-east
ap-southeast
```

### 2. Sharding пользователей

```text
user_id % shard_count
```

### 3. Read models

Для frontend не нужно каждый раз читать сложные таблицы. Нужны подготовленные read-модели:

```text
user_dashboard_snapshot
user_active_positions
latest_signals_by_strategy
symbol_market_state
```

### 4. Отдельные кластеры ClickHouse

```text
raw_market_data_cluster
signals_analytics_cluster
user_analytics_cluster
```

### 5. Kafka / Redpanda

NATS может остаться для low-latency команд и событий, но для огромного event log лучше добавить Kafka/Redpanda.

### 6. Multi-tenant isolation

Для enterprise-клиентов:

```text
tenant_id
tenant quotas
tenant rate limits
tenant-specific strategy configs
tenant audit logs
```

---

# 15. Отказоустойчивость

## Основные правила

### Каждый сервис stateless

API, realtime gateway, workers — stateless.

State хранится в:

* PostgreSQL;
* Redis;
* NATS/Kafka;
* ClickHouse.

### Idempotency

Любой event может прийти повторно. Это нормально.

Нужно иметь:

```text
event_id
deduplication key
idempotency key
unique constraints
processed_events table
```

Пример:

```text
signal_id = hash(exchange + symbol + strategy + candle_time + direction)
```

Если воркер упал и обработал событие повторно — сигнал не должен дублироваться.

### Backpressure

Если поток данных слишком большой:

* сбрасываем неважные события;
* агрегируем trades в candles;
* ограничиваем order book depth;
* приоритизируем BTC/ETH/top pairs;
* деградируем gracefully.

### Circuit Breaker

Для каждой биржи:

```text
Binance adapter failed
      ↓
circuit open
      ↓
pause reconnect storm
      ↓
fallback to REST snapshot
      ↓
resume WebSocket
```

### Dead Letter Queue

События, которые не удалось обработать:

```text
market.raw.failed
signal.failed
journal.import.failed
billing.failed
```

---

# 16. Kubernetes architecture

## Namespaces

```text
crypto-radar-api
crypto-radar-data
crypto-radar-workers
crypto-radar-observability
crypto-radar-infra
```

## Scaling

Использовать:

* Horizontal Pod Autoscaler;
* KEDA для event-driven scaling;
* PodDisruptionBudget;
* readiness/liveness probes;
* resource requests/limits.

Обычный HPA часто реагирует уже после возникновения нагрузки. Современные исследования по Kubernetes autoscaling показывают, что реактивное масштабирование может опаздывать на всплесках, а более умные или прогнозные подходы снижают latency и лучше удерживают SLO. Для Crypto_radar это важно, потому что market spikes часто совпадают с моментами, когда пользователям больше всего нужны сигналы. ([arXiv][7])

---

# 17. Observability

Для Crypto_radar observability критична. Мы должны видеть не только “API работает”, а всю задержку сигнала.

## Главные метрики

```text
exchange_ws_latency_ms
market_event_lag_ms
strategy_processing_time_ms
signal_generation_latency_ms
event_bus_lag
websocket_connected_users
websocket_delivery_latency_ms
clickhouse_insert_lag
postgres_query_latency
redis_latency
worker_queue_depth
```

## Самая важная метрика

```text
signal_end_to_end_latency_ms
```

То есть:

```text
биржа создала событие → пользователь увидел сигнал
```

OpenTelemetry подходит как стандартный слой для traces, metrics и logs; его удобно использовать вместе с Prometheus/Grafana/Loki или managed observability-платформами. ([Reddit][8])

---

# 18. Совместимость с frontend

Предыдущий frontend-стек у вас должен работать так:

```text
Frontend
 ├── REST API: настройки, история, профиль, журнал
 ├── WebSocket: live prices, signals, positions
 ├── SSE: уведомления, системные события
 ├── TanStack Query: server state
 ├── Zustand/Jotai: local realtime state
 └── Lightweight Charts: графики
```

Backend должен отдавать:

## REST

```text
GET /api/v1/signals
GET /api/v1/strategies
GET /api/v1/trades
GET /api/v1/positions
GET /api/v1/market/candles
POST /api/v1/virtual-trades
POST /api/v1/radar/filters
```

## WebSocket

```text
/ws/v1/radar
/ws/v1/market
/ws/v1/user
```

## OpenAPI

FastAPI автоматически дает OpenAPI schema, что удобно для генерации frontend-клиента.

---

# 19. API design

## REST для состояния

```http
GET /api/v1/signals?symbol=BTCUSDT&strategy=volume_breakout
```

## WebSocket для событий

```json
{
  "action": "subscribe",
  "channel": "signals",
  "filters": {
    "symbols": ["BTCUSDT", "ETHUSDT"],
    "strategies": ["volume_breakout"]
  }
}
```

Ответ:

```json
{
  "type": "subscription.confirmed",
  "channel": "signals"
}
```

Событие:

```json
{
  "type": "signal.created",
  "data": {
    "symbol": "BTCUSDT",
    "direction": "long",
    "confidence": 0.82
  }
}
```

---

# 20. Domain events

Нужно заранее договориться о событиях.

```text
market.trade.received
market.candle.closed
market.orderbook.updated
strategy.setup.detected
signal.created
signal.invalidated
virtual_position.opened
virtual_position.updated
virtual_position.closed
trade.imported
subscription.updated
alert.triggered
```

Каждое событие:

```json
{
  "event_id": "evt_...",
  "event_type": "signal.created",
  "version": 1,
  "occurred_at": "2026-05-26T12:00:00Z",
  "producer": "signal-engine",
  "payload": {}
}
```

---

# 21. Data pipeline

## Горячий путь

Это путь, где важна минимальная задержка.

```text
Exchange WS
  → Normalizer
  → NATS
  → Strategy Engine
  → Signal Engine
  → Realtime Gateway
  → Frontend
```

## Холодный путь

Это путь для хранения и аналитики.

```text
Exchange WS
  → NATS
  → Batch writer
  → ClickHouse
  → Analytics API
  → Dashboards
```

## User path

```text
Frontend
  → FastAPI
  → PostgreSQL
  → event
  → NATS
  → Realtime Gateway
```

---

# 22. Backtesting

Backtesting нельзя мешать с real-time engine.

Нужен отдельный сервис:

```text
Backtest API
Backtest Worker Pool
Historical Data Reader
Result Writer
```

Данные:

* candles из ClickHouse;
* комиссии;
* slippage model;
* funding;
* volatility;
* spread;
* liquidity.

Результаты backtest лучше хранить:

```text
PostgreSQL: metadata
ClickHouse: detailed equity curve / trades / metrics
```

---

# 23. AI Assistant backend

AI-модуль лучше отделить.

Он не должен напрямую лезть в сырые таблицы.

Правильная схема:

```text
User question
    ↓
AI Orchestrator
    ↓
Permission check
    ↓
Context Builder
    ↓
Market summary / signal / trade journal
    ↓
LLM
    ↓
Answer
```

AI должен видеть только разрешенный контекст пользователя.

Примеры:

* “почему появился сигнал?”
* “какой риск у этой сделки?”
* “почему стратегия дала просадку?”
* “что улучшить в моем журнале?”

---

# 24. Рекомендуемая структура репозитория

На старте можно monorepo:

```text
crypto-radar-backend/
  apps/
    api/
    realtime_gateway/
    market_ingestion/
    strategy_worker/
    signal_worker/
    virtual_trading_worker/
    backtest_worker/
  packages/
    domain/
    db/
    event_bus/
    exchange_adapters/
    strategies/
    indicators/
    risk/
    common/
  migrations/
  deploy/
    helm/
    k8s/
  tests/
    unit/
    integration/
    load/
```

---

# 25. Python backend libraries

## API

```text
fastapi
uvicorn
pydantic
pydantic-settings
sqlalchemy
asyncpg
alembic
redis
nats-py
httpx
orjson
```

## Data / indicators

```text
numpy
pandas / polars
ta-lib / pandas-ta
numba
scipy
```

Для high-performance indicator calculation лучше постепенно переходить к:

```text
Polars
NumPy
Numba
Rust extensions позже
```

## Testing

```text
pytest
pytest-asyncio
testcontainers
hypothesis
locust
```

## Observability

```text
opentelemetry-sdk
prometheus-client
structlog
sentry-sdk
```

---

# 26. Performance rules

## Что нельзя делать

Плохо:

```text
Frontend polling каждую секунду
FastAPI считает стратегии внутри request
PostgreSQL хранит все trades
Redis используется как основная база
Один сервис делает всё
Нет idempotency
Нет DLQ
Нет lag metrics
Нет версионирования стратегий
```

## Что нужно делать

Хорошо:

```text
WebSocket push
Event-driven pipeline
ClickHouse для market data
PostgreSQL для бизнес-данных
Redis только hot cache
Strategy workers отдельно
Realtime gateway отдельно
NATS/Kafka для событий
Observability с первого дня
```

---

# 27. Deployment environments

```text
local
dev
staging
production
```

## Local

```text
Docker Compose:
- api
- postgres
- redis
- nats
- clickhouse
- grafana
```

## Staging

Максимально похоже на production:

```text
Kubernetes
Managed PostgreSQL
Managed Redis
NATS cluster
ClickHouse test cluster
```

## Production

```text
Kubernetes
Managed PostgreSQL
Managed Redis
NATS/Kafka cluster
ClickHouse cluster
Object storage
CDN
WAF
```

---

# 28. CI/CD

Pipeline:

```text
1. lint
2. type check
3. unit tests
4. integration tests
5. build Docker image
6. security scan
7. push image
8. deploy staging
9. smoke tests
10. deploy production
```

Инструменты:

```text
ruff
mypy / pyright
pytest
docker buildx
trivy
helm
terraform
github actions
```

---

# 29. Load testing

Нужно тестировать не только REST, но и WebSocket.

## Целевые тесты

```text
10 000 concurrent WebSocket users
100 000 subscribed symbols/events
1 000 signals/sec burst
market data ingestion spike
worker crash recovery
NATS replay
ClickHouse insert pressure
PostgreSQL failover
Redis failover
```

Инструменты:

```text
k6
Locust
Gatling
custom WebSocket load generator
```

---

# 30. Минимальная production architecture для MVP

```text
                    ┌────────────────────┐
                    │      Frontend       │
                    │ Next.js / React     │
                    └─────────┬──────────┘
                              │
                ┌─────────────┴─────────────┐
                │ API Gateway / Load Balancer│
                └───────┬───────────┬───────┘
                        │           │
              ┌─────────▼───┐   ┌───▼────────────┐
              │ FastAPI API │   │ Realtime Gateway│
              └──────┬──────┘   └──────┬─────────┘
                     │                 │
       ┌─────────────▼──────┐     ┌────▼─────┐
       │ PostgreSQL          │     │ NATS JS  │
       └─────────────┬──────┘     └────┬─────┘
                     │                 │
              ┌──────▼──────┐   ┌──────▼────────┐
              │ Redis        │   │ Strategy      │
              └─────────────┘   │ Workers       │
                                └──────┬────────┘
                                       │
                               ┌───────▼────────┐
                               │ Signal Engine  │
                               └───────┬────────┘
                                       │
                               ┌───────▼────────┐
                               │ ClickHouse     │
                               └────────────────┘

Market Ingestion Workers feed NATS + ClickHouse
```

---

# 31. Что делать в первую очередь

## Этап 1 — Backend foundation

Сделать:

* FastAPI API;
* PostgreSQL schema;
* Redis;
* NATS JetStream;
* WebSocket gateway;
* базовая авторизация;
* market ingestion для Binance/Bybit;
* ClickHouse candles/trades;
* один strategy worker;
* signal.created event;
* frontend получает сигнал через WebSocket.

Цель этапа:

```text
Биржа → стратегия → сигнал → пользователь
```

---

## Этап 2 — Trading intelligence

Добавить:

* 3 MVP стратегии;
* confidence scoring;
* фильтр ликвидности;
* виртуальные сделки;
* журнал сделок;
* PnL;
* strategy performance;
* alerts.

---

## Этап 3 — SaaS

Добавить:

* подписки;
* тарифные ограничения;
* billing;
* team accounts позже;
* audit logs;
* email/telegram notifications;
* admin panel.

---

## Этап 4 — Scale

Добавить:

* Kubernetes autoscaling;
* ClickHouse cluster;
* read replicas;
* Kafka/Redpanda при необходимости;
* multi-region;
* advanced observability;
* AI assistant.

---

# 32. Итоговая рекомендация

Для Crypto_radar я бы выбрал такой backend stack:

```text
FastAPI
Uvicorn / Gunicorn ASGI
PostgreSQL
Redis Cluster
NATS JetStream
ClickHouse
Kubernetes
OpenTelemetry
Prometheus
Grafana
Loki
Terraform
Helm
```

Главная архитектурная идея:

```text
REST API — для состояния
WebSocket — для live данных
NATS/Kafka — для событий
PostgreSQL — для бизнес-данных
ClickHouse — для market data и аналитики
Redis — для hot state
Workers — для стратегий, сигналов и виртуальной торговли
```

Такой подход совместим с быстрым frontend на React/Next.js, позволяет показывать сигналы мгновенно, не требует polling, выдержит стартовую нагрузку и не сломается при росте до полноценной SaaS-платформы уровня Nansen/Glassnode, но сфокусированной именно на трейдерах.

[1]: https://uvicorn.dev/concepts/asgi/?utm_source=chatgpt.com "ASGI - Uvicorn"
[2]: https://docs.nats.io/nats-concepts/jetstream?utm_source=chatgpt.com "JetStream | NATS Docs"
[3]: https://arxiv.org/abs/2510.04404?utm_source=chatgpt.com "Next-Generation Event-Driven Architectures: Performance, Scalability, and Intelligent Orchestration Across Messaging Frameworks"
[4]: https://www.postgresql.org/docs/18/ddl-partitioning.html?utm_source=chatgpt.com "PostgreSQL: Documentation: 18: 5.12. Table Partitioning"
[5]: https://www.postgresql.org/docs/18/logical-replication.html?utm_source=chatgpt.com "PostgreSQL: Documentation: 18: Chapter 29. Logical Replication"
[6]: https://www.modern-datatools.com/compare/timescaledb-vs-clickhouse?utm_source=chatgpt.com "TimescaleDB vs ClickHouse: SQL or OLAP Speed (2026) | Modern DataTools"
[7]: https://arxiv.org/abs/2604.19705?utm_source=chatgpt.com "Predictive Autoscaling for Node.js on Kubernetes: Lower Latency, Right-Sized Capacity"
[8]: https://www.reddit.com/r/Observability/comments/1qh9nip/i_built_a_public_metricregistry_to_help_search/?utm_source=chatgpt.com "I built a public metric-registry to help search and know details about metrics from various tools and platforms"
