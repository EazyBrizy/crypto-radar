Да, для **Crypto_radar** нам нужна архитектура не “запросил данные → обновил экран раз в 5 секунд”, а **event-driven realtime UI**:

> Биржа / стратегия / сигнал → backend event → realtime channel → frontend store → UI обновился без перезагрузки и polling.

Ниже — рекомендуемый **production-grade frontend stack** под связку **Node.js + FastAPI**, с акцентом на скорость отображения сигналов, мгновенное обновление интерфейса и чистую современную архитектуру.

---

# 1. Главный принцип архитектуры

Для нашего продукта нельзя строить frontend вокруг периодического REST-запроса:

```text
GET /signals каждые 3 секунды
```

Это плохой подход для трейдингового продукта:

```text
Задержка
Лишняя нагрузка
Плавающая актуальность данных
Плохой UX
Сложность масштабирования
```

Нам нужен поток событий:

```text
Signal Engine
   ↓
FastAPI Realtime Gateway
   ↓
WebSocket / SSE
   ↓
Frontend Realtime Store
   ↓
Radar UI обновляется моментально
```

---

# 2. Рекомендуемый frontend stack

## Основной стек

```text
Runtime: Node.js
Framework: Next.js / React
Language: TypeScript
UI: Tailwind CSS + shadcn/ui + Radix UI
State: Zustand + TanStack Query
Realtime: WebSocket, optionally SSE
Charts: Lightweight Charts / TradingView Lightweight Charts
Tables: TanStack Table
Forms: React Hook Form + Zod
Validation: Zod
API Client: OpenAPI-generated TypeScript client
Testing: Vitest + Playwright
Monitoring: Sentry + OpenTelemetry
Package Manager: pnpm
Build/Deploy: Docker + CI/CD
```

---

# 3. Framework: Next.js или Vite?

У нас есть два нормальных варианта.

## Вариант A — Next.js

Рекомендую для SaaS.

Next.js подходит, если нам нужны:

```text
Личный кабинет
Авторизация
Подписки
Billing
SEO-страницы
Landing page
Dashboard
SSR для части страниц
Server Components
```

Next.js App Router использует современные возможности React, включая Server Components, Suspense и server-side rendering-подходы. Это полезно для SaaS-оболочки: кабинет, настройки, подписка, onboarding, billing. ([Next.js][1])

Но важный момент:

> Realtime Radar, графики, активные сделки и поток сигналов должны быть **Client Components**, а не Server Components.

То есть структура такая:

```text
Next.js
├── Server Components
│   ├── Layout
│   ├── Auth shell
│   ├── Settings
│   ├── Billing
│   └── Static/initial pages
│
└── Client Components
    ├── Radar
    ├── Signal Feed
    ├── Signal Details
    ├── Active Trades
    ├── Charts
    └── WebSocket connection
```

## Вариант B — Vite + React

Подходит, если мы хотим максимально быстрый чистый SPA-терминал без SSR.

Плюсы:

```text
Очень быстрый dev/build
Простая архитектура
Меньше магии
Отлично для realtime dashboard
```

Минусы:

```text
Нужно отдельно решать SSR/SEO/landing
Нужно отдельно строить auth shell
Меньше SaaS-возможностей из коробки
```

## Моя рекомендация

Для **Crypto_radar**:

```text
Next.js для SaaS-приложения
React Client Components для realtime-части
FastAPI для API, сигналов, торговой логики и realtime gateway
```

То есть **Next.js не должен считать сигналы**. Он отвечает за интерфейс, маршрутизацию, личный кабинет и UI.
**FastAPI отвечает за данные, сигналы, биржи, сделки, risk engine, WebSocket/SSE.**

---

# 4. Роль Node.js в проекте

Важно правильно разделить ответственность.

Node.js в нашем случае — это не главный backend для торговли. Он нужен для frontend-слоя:

```text
Node.js
├── Next.js runtime
├── SSR/BFF при необходимости
├── frontend build
├── auth/session handling
├── middleware
└── отдача UI
```

FastAPI — основной backend:

```text
FastAPI
├── Market data
├── Signal engine
├── Strategy engine
├── Exchange connectors
├── Paper trading
├── Real trades sync
├── User trade journal
├── Risk engine
├── WebSocket/SSE gateway
└── REST API
```

Критичный путь сигналов не должен идти так:

```text
FastAPI → Node.js → Frontend
```

Лучше так:

```text
FastAPI Realtime Gateway → Browser
```

Node.js не должен быть лишним посредником для realtime-сигналов, если в этом нет необходимости. Чем меньше промежуточных слоев в realtime-пути, тем меньше задержка.

---

# 5. Realtime: WebSocket или SSE?

Есть два основных варианта.

---

## Вариант 1 — WebSocket

WebSocket подходит, когда нужна двусторонняя связь:

```text
Сервер отправляет сигналы
Пользователь подписывается на пары
Пользователь меняет фильтры
Пользователь подтверждает paper trade
Пользователь открывает позицию
Пользователь получает order status
Пользователь получает trade lifecycle updates
```

FastAPI официально поддерживает WebSocket endpoints. ([FastAPI][2])

Для Crypto_radar WebSocket нужен для:

```text
Live signals
Active trade updates
Order status
Paper trade lifecycle
Exchange position updates
User-specific subscriptions
```

Пример логики:

```text
Client connects:
ws://api.crypto-radar.com/ws

Client sends:
{
  "type": "subscribe",
  "channels": ["signals", "trades", "portfolio"],
  "pairs": ["BTCUSDT", "ETHUSDT"],
  "timeframes": ["5m", "15m"]
}

Server pushes:
{
  "type": "signal.created",
  "payload": {
    "pair": "BTCUSDT",
    "side": "LONG",
    "confidence": 84,
    "entryZone": [67850, 68100]
  }
}
```

---

## Вариант 2 — SSE

SSE, Server-Sent Events, подходит, когда данные идут только от сервера к клиенту. Это нативный browser API через `EventSource`, где сервер может пушить новые события в браузер без polling. ([MDN Web Docs][3])

SSE хорошо подходит для:

```text
Public market feed
Signal feed
Notifications
Read-only dashboard updates
```

Но SSE однонаправленный: клиент не отправляет сообщения в этот же канал. ([mdn2.netlify.app][4])

---

## Что выбрать нам?

Для Crypto_radar я бы выбрал:

```text
WebSocket — основной realtime channel
SSE — опционально для read-only public feeds
REST — для initial load, history, settings, journal
```

То есть:

```text
REST:
- initial dashboard load
- user profile
- settings
- historical signals
- trade journal
- billing

WebSocket:
- new signal created
- signal updated
- price touched entry zone
- trade activated
- TP hit
- SL hit
- order status changed
- connection health

SSE:
- публичная лента market status
- read-only уведомления
- fallback mode
```

---

# 6. Frontend data architecture

Нельзя всё хранить в одном Redux-store. Для современного frontend лучше разделить состояние.

## 1. Server state — TanStack Query

Для данных, которые приходят с backend через REST:

```text
User profile
Settings
Watchlist
Journal history
Closed trades
Subscription status
Historical signals
Exchange connections
```

Используем **TanStack Query**, потому что он решает кэширование, синхронизацию, background updates, deduplication, stale data и управление server state. ([tanstack.com][5])

Пример:

```ts
useQuery({
  queryKey: ['signals', filters],
  queryFn: () => api.signals.list(filters),
  staleTime: 10_000,
})
```

---

## 2. Client/UI state — Zustand

Для локального состояния интерфейса:

```text
Открытый sidebar
Активная вкладка
Выбранный сигнал
Фильтры Radar
Состояние модалок
Текущий layout
Realtime connection state
```

Пример:

```ts
type RadarStore = {
  selectedSignalId: string | null
  filters: RadarFilters
  connectionStatus: 'connected' | 'reconnecting' | 'offline'
  setSelectedSignal: (id: string) => void
}
```

---

## 3. Realtime event store

Для realtime-событий лучше сделать отдельный слой:

```text
WebSocket Client
   ↓
Event Router
   ↓
Signal Store / Trade Store
   ↓
UI selectors
```

Не надо прямо в компоненте писать:

```ts
ws.onmessage = ...
```

Это быстро превратится в хаос.

Правильно:

```text
src/realtime/
├── socket-client.ts
├── event-router.ts
├── subscriptions.ts
├── reconnect-policy.ts
├── heartbeat.ts
└── event-types.ts
```

---

# 7. Как должен работать realtime flow

## Первичная загрузка

Когда пользователь открывает Radar:

```text
1. Next.js загружает приложение
2. TanStack Query делает initial REST-запрос:
   GET /api/signals/active
3. UI сразу показывает последние актуальные сигналы
4. WebSocket подключается
5. Клиент отправляет subscribe
6. Все новые события идут через WebSocket
```

Это важно: WebSocket не должен быть единственным источником начального состояния.

Правильный flow:

```text
Initial snapshot через REST
Live updates через WebSocket
Periodic reconciliation редко, например раз в 1–5 минут или при reconnect
```

Это не polling для UI, а защита от рассинхронизации.

---

# 8. Архитектура обновления сигнала

Допустим backend нашел сигнал.

```text
Signal Engine detected signal
↓
FastAPI saves signal to DB
↓
Publishes event to message broker
↓
Realtime Gateway receives event
↓
Pushes to subscribed clients
↓
Frontend event router receives signal.created
↓
Zustand/TanStack cache updated
↓
Signal card appears at top of Radar
```

Frontend не спрашивает:

```text
Есть новые сигналы?
```

Backend сам пушит:

```text
Вот новый сигнал.
```

---

# 9. Рекомендуемая схема realtime events

Нужно сразу стандартизировать события.

```ts
type RealtimeEvent =
  | SignalCreatedEvent
  | SignalUpdatedEvent
  | SignalInvalidatedEvent
  | TradeActivatedEvent
  | TradeClosedEvent
  | PriceTouchedEntryEvent
  | OrderStatusChangedEvent
  | ConnectionHeartbeatEvent
```

Пример события:

```json
{
  "id": "evt_01HX...",
  "type": "signal.created",
  "version": 1,
  "timestamp": "2026-05-25T10:12:41.231Z",
  "payload": {
    "signalId": "sig_123",
    "pair": "BTCUSDT",
    "exchange": "BINANCE",
    "side": "LONG",
    "strategy": "EMA_PULLBACK",
    "confidence": 84,
    "risk": "MEDIUM",
    "entryZone": {
      "from": 67850,
      "to": 68100
    },
    "stopLoss": 67420,
    "takeProfit": [68900, 69450],
    "timeframe": "15m"
  }
}
```

Обязательно нужны:

```text
event id
event type
version
timestamp
payload
```

Почему это важно:

```text
Можно дедуплицировать события
Можно восстанавливаться после reconnect
Можно логировать
Можно тестировать
Можно делать replay
```

---

# 10. UI rendering: как сделать интерфейс быстрым

Realtime UI может тормозить не из-за WebSocket, а из-за плохого рендера.

Нам нужны правила:

## 1. Не перерисовывать весь Radar при каждом событии

Плохо:

```text
Пришел новый price tick → перерендерился весь dashboard
```

Хорошо:

```text
Обновилась только нужная карточка
```

Для этого:

```text
Zustand selectors
React.memo
useMemo
useCallback
normalized store
virtualized lists
```

---

## 2. Нормализованное состояние

Не храним массивы как главный источник:

```ts
signals: Signal[]
```

Лучше:

```ts
signalsById: Record<string, Signal>
signalIds: string[]
```

Так проще обновлять одну карточку.

---

## 3. Виртуализация списков

Если на Radar будет 500–3000 сигналов/событий, обычный список начнет тормозить.

Используем:

```text
@tanstack/react-virtual
```

Для:

```text
Signal Feed
Trade Journal
Event Timeline
Scanner Table
```

---

## 4. Отдельный слой для частых price updates

Цена может меняться очень часто. Нельзя обновлять всю карточку на каждый тик.

Разделяем:

```text
Signal state — обновляется при изменении сигнала
Price state — обновляется часто
UI visual update — throttled/requestAnimationFrame
```

Для цены можно использовать отдельный lightweight store и обновлять UI через `requestAnimationFrame`, чтобы не забивать React-событиями.

---

# 11. Charts

Для графиков я бы не использовал тяжелый TradingView Advanced Chart на старте.

## Для MVP

```text
TradingView Lightweight Charts
```

Подходит для:

```text
Candles
Volume
Entry zone
SL/TP lines
EMA overlays
Signal markers
```

Плюсы:

```text
Быстро
Легко
Хорошо подходит для realtime
Не перегружает UI
```

## Позже

Можно добавить:

```text
TradingView Charting Library
```

Но только если будет реальная необходимость в полноценном терминале.

---

# 12. UI Kit

Рекомендую:

```text
Tailwind CSS
shadcn/ui
Radix UI
Lucide Icons
Framer Motion — осторожно, только для микро-анимаций
```

Почему:

```text
Tailwind — быстрый и контролируемый styling
shadcn/ui — не тяжелая библиотека, а копируемые компоненты
Radix — accessibility и primitives
Lucide — легкие иконки
```

Для нашего продукта важно не делать “красивые тяжелые анимации”.
Интерфейс должен ощущаться как:

```text
быстрый
тихий
четкий
точный
```

---

# 13. Работа с REST API

Для FastAPI обязательно генерировать TypeScript client из OpenAPI.

Нельзя вручную писать типы отдельно на backend и frontend.

Правильно:

```text
FastAPI OpenAPI schema
        ↓
openapi-typescript / Orval
        ↓
Generated TypeScript client
        ↓
Frontend API layer
```

Структура:

```text
src/api/
├── generated/
├── client.ts
├── signals.api.ts
├── trades.api.ts
├── journal.api.ts
├── settings.api.ts
└── exchanges.api.ts
```

Плюсы:

```text
Единые типы
Меньше ошибок
Быстрее разработка
Легче рефакторинг
```

---

# 14. Валидация данных

На frontend используем:

```text
Zod
```

Для:

```text
форм
фильтров
query params
runtime validation realtime events
```

Особенно важно валидировать WebSocket-события, потому что realtime payload не должен ломать UI.

Пример:

```ts
const SignalCreatedSchema = z.object({
  id: z.string(),
  type: z.literal('signal.created'),
  timestamp: z.string(),
  payload: z.object({
    signalId: z.string(),
    pair: z.string(),
    side: z.enum(['LONG', 'SHORT']),
    confidence: z.number(),
  }),
})
```

---

# 15. Таблицы и журнал сделок

Для таблиц:

```text
TanStack Table
TanStack Virtual
```

Используем для:

```text
Trade Journal
Scanner
Exchange orders
Signal history
```

Почему не обычная HTML table:

```text
нужны фильтры
сортировка
колонки
виртуализация
пагинация
массовые данные
```

---

# 16. Routing

Если используем Next.js:

```text
Next.js App Router
```

Структура:

```text
app/
├── dashboard/
│   ├── radar/
│   ├── watchlist/
│   ├── trades/
│   │   ├── active/
│   │   ├── journal/
│   │   └── analytics/
│   ├── settings/
│   └── layout.tsx
├── auth/
├── billing/
└── page.tsx
```

Если используем Vite SPA:

```text
TanStack Router
```

TanStack Router дает type-safe routing, route loaders, search params и хорошую интеграцию с TanStack Query. ([tanstack.dev][6])

---

# 17. Auth

Для SaaS лучше сразу заложить нормальную auth-архитектуру.

Варианты:

```text
Clerk
Auth.js
Keycloak
Custom FastAPI JWT auth
```

Для MVP я бы выбрал:

```text
Auth.js / Clerk для быстрого старта
или
Custom FastAPI JWT + refresh tokens для полного контроля
```

Для трейдинговой системы с API-ключами бирж я бы в долгую шел к:

```text
Custom auth через FastAPI
JWT access token
HttpOnly refresh cookie
2FA
Session management
Device management
API key encryption
```

---

# 18. WebSocket auth

Для WebSocket нельзя относиться к авторизации как к обычному REST.

Нужно:

```text
1. Пользователь логинится
2. Получает access token
3. WebSocket подключается с auth token
4. Backend валидирует пользователя
5. Backend подписывает клиента только на его данные
```

Пример:

```text
wss://api.crypto-radar.com/ws?token=short_lived_ws_token
```

Лучше использовать **short-lived WebSocket token**, а не основной refresh/access token.

---

# 19. Reconnect logic

Realtime UI должен переживать:

```text
плохой интернет
сон ноутбука
переключение вкладки
смену сети
обрыв WebSocket
перезапуск backend worker
```

Frontend должен иметь:

```text
exponential backoff
heartbeat
lastEventId
resubscribe after reconnect
snapshot refresh after reconnect
connection status badge
```

Пример UX:

```text
Connected
Reconnecting...
Live data delayed
Offline mode
```

---

# 20. Состояние соединения в интерфейсе

В трейдинговом продукте пользователь должен видеть актуальность данных.

В Radar сверху можно показывать:

```text
Live · Connected
Last update: 250ms ago
```

Если соединение потеряно:

```text
Reconnecting...
Data may be delayed
```

Если долго нет связи:

```text
Offline
Trading actions disabled
```

Это повышает доверие.

---

# 21. Оптимальная frontend-структура проекта

```text
src/
├── app/                         # Next.js routes
├── shared/
│   ├── ui/                      # base UI components
│   ├── lib/                     # utils
│   ├── config/
│   └── types/
│
├── entities/
│   ├── signal/
│   │   ├── model/
│   │   ├── api/
│   │   ├── ui/
│   │   └── types.ts
│   │
│   ├── trade/
│   ├── exchange/
│   ├── user/
│   └── strategy/
│
├── features/
│   ├── subscribe-to-signals/
│   ├── create-paper-trade/
│   ├── save-signal/
│   ├── open-position/
│   ├── filter-signals/
│   └── connect-exchange/
│
├── widgets/
│   ├── radar-feed/
│   ├── signal-card/
│   ├── market-mood/
│   ├── active-trades-list/
│   ├── trade-journal-table/
│   └── signal-chart/
│
├── pages/
│   ├── radar/
│   ├── trades/
│   ├── watchlist/
│   └── settings/
│
├── realtime/
│   ├── socket-client.ts
│   ├── event-router.ts
│   ├── event-types.ts
│   ├── subscriptions.ts
│   ├── heartbeat.ts
│   └── reconnect.ts
│
├── api/
│   ├── generated/
│   ├── client.ts
│   └── query-client.ts
│
└── stores/
    ├── radar.store.ts
    ├── realtime.store.ts
    ├── ui.store.ts
    └── trade.store.ts
```

Это похоже на Feature-Sliced Design, но без фанатизма.

---

# 22. Как обновлять Signal Feed без перезагрузки

## Событие: новый сигнал

```ts
case 'signal.created':
  signalStore.addSignal(event.payload)
  queryClient.setQueryData(['signals', 'active'], old => {
    return insertSignalToTop(old, event.payload)
  })
```

## Событие: сигнал обновился

```ts
case 'signal.updated':
  signalStore.updateSignal(event.payload.signalId, event.payload.patch)
```

## Событие: сигнал стал невалидным

```ts
case 'signal.invalidated':
  signalStore.markInvalid(event.payload.signalId)
```

## Событие: цена дошла до entry

```ts
case 'signal.entry_touched':
  signalStore.updateStatus(signalId, 'ENTRY_TOUCHED')
  notificationStore.push(...)
```

---

# 23. Notifications

Нужны два типа уведомлений.

## In-app notifications

```text
Новый сигнал
Entry touched
TP1 hit
SL hit
Trade closed
Exchange disconnected
```

## Push notifications

Позже:

```text
Web Push
Mobile Push
Telegram bot
Email
```

Для web MVP:

```text
In-app toast
Sound toggle
Browser notification permission
```

---

# 24. Performance budget

Нужно сразу ввести технические ограничения.

Для Radar:

```text
Initial dashboard render: < 1.5 sec
Signal card update after event: < 100 ms на frontend
WebSocket reconnect: автоматический
Large list: virtualized
No full dashboard rerender on tick
Bundle split by routes
Charts loaded lazily
```

Для UI:

```text
Main bundle не должен тащить charts на страницу Settings
Trade Journal не должен грузить весь history сразу
Signal Details chart должен lazy-load
Heavy analytics должны грузиться отдельным chunk
```

---

# 25. Что нельзя делать

Не надо:

```text
Использовать setInterval для обновления сигналов
Хранить все данные в Redux без разделения server/client state
Делать WebSocket logic внутри React-компонентов
Обновлять весь dashboard на каждый price tick
Передавать весь стакан/рынок в React state без throttling
Использовать огромные chart libraries на главном экране
Держать realtime через Next.js API routes как основной канал
Писать типы API вручную отдельно от FastAPI
```

---

# 26. Связка с FastAPI

Frontend ожидает от FastAPI три типа API.

## 1. REST API

```text
GET /api/signals/active
GET /api/signals/{id}
GET /api/trades/active
GET /api/trades/journal
POST /api/trades/paper
POST /api/signals/{id}/save
GET /api/settings
PATCH /api/settings
```

## 2. WebSocket API

```text
/ws
```

Каналы:

```text
signals
trades
orders
portfolio
notifications
market-status
```

## 3. OpenAPI schema

```text
/openapi.json
```

Из нее генерируем frontend client.

---

# 27. Message broker между backend и realtime

Хотя вопрос про frontend, важно понимать: frontend будет быстрым только если backend правильно пушит события.

На backend желательно:

```text
Signal Engine
↓
NATS / Redis Streams / Kafka
↓
Realtime Gateway
↓
WebSocket clients
```

Для MVP:

```text
Redis Streams или NATS
```

Для масштабирования:

```text
NATS JetStream или Kafka
```

FastAPI не должен сам “помнить всех клиентов” в одном процессе, если мы планируем 10k+ пользователей. Нужен внешний pub/sub слой.

---

# 28. Рекомендуемая схема для MVP

```text
Frontend:
Next.js + React + TypeScript
Tailwind + shadcn/ui
Zustand
TanStack Query
TradingView Lightweight Charts
TanStack Table
WebSocket client

Backend:
FastAPI
PostgreSQL
Redis / Redis Streams
Celery / Arq / Dramatiq for jobs
WebSocket gateway
OpenAPI schema

Infra:
Docker
Nginx / Traefik
Cloudflare
Sentry
OpenTelemetry
Prometheus + Grafana
```

---

# 29. Рекомендуемая схема для production scale

```text
Browser
↓
Next.js App
↓
REST → FastAPI API
WebSocket → FastAPI Realtime Gateway
↓
NATS JetStream / Kafka
↓
Signal Engine / Market Data Workers / Trade Engine
↓
PostgreSQL / TimescaleDB / ClickHouse / Redis
```

---

# 30. Финальный выбор стека

Я бы зафиксировал такой стек:

```text
Frontend Runtime:
Node.js 22 LTS

Framework:
Next.js + React + TypeScript

UI:
Tailwind CSS
shadcn/ui
Radix UI
Lucide Icons

State:
TanStack Query — server state
Zustand — client/realtime UI state

Realtime:
Native WebSocket client
SSE только для read-only fallback/public feeds

Charts:
TradingView Lightweight Charts

Tables:
TanStack Table
TanStack Virtual

Forms:
React Hook Form
Zod

API:
OpenAPI-generated TypeScript client from FastAPI

Testing:
Vitest
React Testing Library
Playwright

Monitoring:
Sentry
OpenTelemetry
Web Vitals

Build:
pnpm
Docker
CI/CD
```

---

# 31. Главная архитектурная рекомендация

Для Crypto_radar я бы строил frontend так:

```text
REST = начальное состояние и история
WebSocket = живые события
Zustand = мгновенное обновление UI
TanStack Query = кэш и server state
React Client Components = интерактивный realtime Radar
Next.js = SaaS shell, routing, auth, billing
FastAPI = источник данных и realtime gateway
```

Ключевая формула:

> **Не обновлять интерфейс по таймеру. Обновлять интерфейс по событию.**

Идеальный поток:

```text
Сигнал появился на backend
↓
Событие ушло в WebSocket
↓
Frontend получил event
↓
Signal Store обновился
↓
Карточка сигнала появилась в Radar
↓
Пользователь видит ее почти моментально
```

Именно так нужно строить интерфейс Crypto_radar “по канонам современной разработки”, без костылей и polling.

[1]: https://nextjs.org/docs/app?utm_source=chatgpt.com "Next.js Docs: App Router | Next.js"
[2]: https://fastapi.tiangolo.com/advanced/websockets/ "WebSockets - FastAPI"
[3]: https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events?utm_source=chatgpt.com "Server-sent events - Web APIs | MDN"
[4]: https://mdn2.netlify.app/en-us/docs/web/api/eventsource/?utm_source=chatgpt.com "EventSource - Web APIs | MDN"
[5]: https://tanstack.com/query/docs/docs?utm_source=chatgpt.com "Overview | TanStack Query React Docs"
[6]: https://tanstack.dev/router/latest/docs?utm_source=chatgpt.com "Overview | TanStack Router React Docs"
