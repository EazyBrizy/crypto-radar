Ниже — целевая схема БД для **Crypto_radar** с разделением ответственности между **PostgreSQL**, **ClickHouse** и **Redis**.

## 1. Главный принцип разделения данных

| Слой           | Что храним                                                                                                                                                    | Почему                                                                                                                                                                  |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **PostgreSQL** | Пользователи, подписки, настройки, стратегии, конфигурации, сигналы как бизнес-сущности, виртуальные сделки, портфели, журнал сделок, биллинг, аудит          | Это transactional source of truth: нужны связи, FK, консистентность, транзакции, права доступа                                                                          |
| **ClickHouse** | Рыночные тики, сделки с бирж, свечи, order book, рассчитанные индикаторы, события сигналов, историческая аналитика, PnL-агрегации, backtest/runtime analytics | Это аналитическое хранилище для огромных объемов time-series данных. Семейство MergeTree рассчитано на высокий ingest и большие объемы данных. ([ClickHouse][1])        |
| **Redis**      | Горячие цены, последние сигналы, WebSocket fanout, краткоживущий кэш, rate limit, locks, consumer queues/streams                                              | Нужен для мгновенной доставки в UI и снижения нагрузки на Postgres/ClickHouse. Redis Streams подходят для append-only real-time событий и consumer groups. ([Redis][2]) |

**Ключевая идея:**
PostgreSQL отвечает на вопрос: **“что сейчас является состоянием системы?”**
ClickHouse отвечает: **“что происходило на рынке и как это анализировать?”**
Redis отвечает: **“что нужно отдать пользователю прямо сейчас?”**

---

# 2. Поток данных

```text
Биржи
  ↓
Market collectors / connectors
  ↓
Normalizer
  ↓
Redis Streams / Kafka-compatible bus
  ↓
┌───────────────────────────────┬─────────────────────────────┐
│ ClickHouse                    │ Signal Engine               │
│ raw ticks, trades, candles    │ indicators, strategies      │
└───────────────────────────────┴─────────────────────────────┘
                  ↓
        Signal generated
                  ↓
┌───────────────────────┬───────────────────────┬──────────────────────┐
│ PostgreSQL            │ ClickHouse             │ Redis Pub/Sub/Cache  │
│ signal state          │ signal analytics       │ instant UI delivery  │
└───────────────────────┴───────────────────────┴──────────────────────┘
```

Для мгновенного UI: сигнал создается в PostgreSQL как бизнес-сущность, событие пишется в ClickHouse для аналитики, а Redis сразу пушит событие в WebSocket-слой. Redis Pub/Sub подходит для fanout-сценариев, где publisher не знает конкретных subscribers. ([Redis][3])

---

# 3. PostgreSQL: основная OLTP-модель

## 3.1. Расширения

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS btree_gin;
```

`jsonb` используем только там, где параметры реально динамические: настройки стратегий, exchange metadata, payload сигнала. Для поиска по `jsonb` можно использовать GIN-индексы. ([PostgreSQL][4])

---

## 3.2. Справочники рынка

### `market_exchanges`

Биржи: Binance, Bybit, OKX, Coinbase и т.д.

```sql
CREATE TABLE market_exchanges (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code            TEXT UNIQUE NOT NULL,
    name            TEXT NOT NULL,
    type            TEXT NOT NULL CHECK (type IN ('cex', 'dex')),
    status          TEXT NOT NULL DEFAULT 'active',
    api_base_url    TEXT,
    ws_base_url     TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### `market_assets`

```sql
CREATE TABLE market_assets (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol          TEXT NOT NULL,
    name            TEXT,
    asset_type      TEXT NOT NULL DEFAULT 'crypto',
    decimals        INT,
    coingecko_id    TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(symbol)
);
```

### `market_pairs`

```sql
CREATE TABLE market_pairs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    exchange_id     UUID NOT NULL REFERENCES market_exchanges(id),
    base_asset_id   UUID NOT NULL REFERENCES market_assets(id),
    quote_asset_id  UUID NOT NULL REFERENCES market_assets(id),
    symbol          TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active',
    min_qty         NUMERIC(38, 18),
    tick_size       NUMERIC(38, 18),
    lot_size        NUMERIC(38, 18),
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(exchange_id, symbol)
);
```

---

# 4. PostgreSQL: пользователи, доступ, подписки

## 4.1. `app_users`

```sql
CREATE TABLE app_users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           CITEXT UNIQUE NOT NULL,
    username        TEXT UNIQUE,
    status          TEXT NOT NULL DEFAULT 'active',
    locale          TEXT NOT NULL DEFAULT 'ru',
    timezone        TEXT NOT NULL DEFAULT 'Europe/Warsaw',
    risk_profile    TEXT DEFAULT 'balanced',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## 4.2. `user_profiles`

```sql
CREATE TABLE user_profiles (
    user_id         UUID PRIMARY KEY REFERENCES app_users(id) ON DELETE CASCADE,
    display_name    TEXT,
    avatar_url      TEXT,
    onboarding_done BOOLEAN NOT NULL DEFAULT false,
    settings        JSONB NOT NULL DEFAULT '{}',
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## 4.3. `subscription_plans`

```sql
CREATE TABLE subscription_plans (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code            TEXT UNIQUE NOT NULL,
    name            TEXT NOT NULL,
    price_monthly   NUMERIC(12, 2) NOT NULL,
    currency        TEXT NOT NULL DEFAULT 'USD',
    limits          JSONB NOT NULL DEFAULT '{}',
    features        JSONB NOT NULL DEFAULT '{}',
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Пример `limits`:

```json
{
  "max_watchlists": 10,
  "max_active_strategies": 5,
  "max_exchange_connections": 3,
  "realtime_signals": true,
  "backtest_depth_days": 90
}
```

## 4.4. `user_subscriptions`

```sql
CREATE TABLE user_subscriptions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES app_users(id),
    plan_id         UUID NOT NULL REFERENCES subscription_plans(id),
    status          TEXT NOT NULL CHECK (status IN ('trialing', 'active', 'past_due', 'canceled')),
    started_at      TIMESTAMPTZ NOT NULL,
    current_period_start TIMESTAMPTZ,
    current_period_end   TIMESTAMPTZ,
    external_provider TEXT,
    external_id     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

# 5. PostgreSQL: подключения к биржам

## 5.1. `user_exchange_connections`

API-ключи не храним в открытом виде. В БД только ссылка на секрет в Vault/KMS.

```sql
CREATE TABLE user_exchange_connections (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    exchange_id     UUID NOT NULL REFERENCES market_exchanges(id),
    label           TEXT NOT NULL,
    account_type    TEXT NOT NULL DEFAULT 'spot',
    key_ref         TEXT NOT NULL,
    permissions     JSONB NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'active',
    last_sync_at    TIMESTAMPTZ,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(user_id, exchange_id, label)
);
```

---

# 6. PostgreSQL: стратегии

## 6.1. `strategy_templates`

Базовые стратегии: breakout, trend-following, mean-reversion, smart-money, scalping и т.д.

```sql
CREATE TABLE strategy_templates (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code            TEXT UNIQUE NOT NULL,
    name            TEXT NOT NULL,
    category        TEXT NOT NULL,
    description     TEXT,
    risk_level      TEXT NOT NULL DEFAULT 'medium',
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## 6.2. `strategy_versions`

Версионирование обязательно. Нельзя пересчитывать старые сигналы новой логикой без фиксации версии.

```sql
CREATE TABLE strategy_versions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id     UUID NOT NULL REFERENCES strategy_templates(id),
    version         TEXT NOT NULL,
    config_schema   JSONB NOT NULL,
    default_params  JSONB NOT NULL,
    changelog       TEXT,
    status          TEXT NOT NULL DEFAULT 'draft',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(strategy_id, version)
);
```

## 6.3. `user_strategy_configs`

```sql
CREATE TABLE user_strategy_configs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    strategy_version_id UUID NOT NULL REFERENCES strategy_versions(id),
    name            TEXT NOT NULL,
    exchange_scope  JSONB NOT NULL DEFAULT '[]',
    pair_scope      JSONB NOT NULL DEFAULT '[]',
    timeframes      TEXT[] NOT NULL,
    params          JSONB NOT NULL DEFAULT '{}',
    risk_settings   JSONB NOT NULL DEFAULT '{}',
    is_enabled      BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Пример `params`:

```json
{
  "ema_fast": 20,
  "ema_slow": 50,
  "rsi_min": 45,
  "volume_spike_multiplier": 1.8,
  "atr_stop_multiplier": 1.5
}
```

---

# 7. PostgreSQL: сигналы

## 7.1. `trading_signals`

Это бизнес-сущность сигнала, которую видит пользователь.

```sql
CREATE TABLE trading_signals (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_key          TEXT UNIQUE NOT NULL,

    strategy_version_id UUID NOT NULL REFERENCES strategy_versions(id),
    exchange_id         UUID NOT NULL REFERENCES market_exchanges(id),
    pair_id             UUID NOT NULL REFERENCES market_pairs(id),

    timeframe           TEXT NOT NULL,
    direction           TEXT NOT NULL CHECK (direction IN ('long', 'short')),
    status              TEXT NOT NULL CHECK (
        status IN ('new', 'active', 'confirmed', 'expired', 'invalidated', 'closed')
    ),

    confidence          NUMERIC(5, 2) NOT NULL,
    score               NUMERIC(8, 4) NOT NULL,

    entry_price         NUMERIC(38, 18),
    stop_loss           NUMERIC(38, 18),
    take_profit         JSONB NOT NULL DEFAULT '[]',

    risk_reward         NUMERIC(10, 4),
    detected_at         TIMESTAMPTZ NOT NULL,
    expires_at          TIMESTAMPTZ,

    features_snapshot   JSONB NOT NULL DEFAULT '{}',
    explanation         TEXT,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Индексы:

```sql
CREATE INDEX idx_trading_signals_active
ON trading_signals (status, detected_at DESC);

CREATE INDEX idx_trading_signals_pair_time
ON trading_signals (pair_id, timeframe, detected_at DESC);

CREATE INDEX idx_trading_signals_strategy
ON trading_signals (strategy_version_id, detected_at DESC);

CREATE INDEX idx_trading_signals_features_gin
ON trading_signals USING GIN (features_snapshot);
```

## 7.2. `trading_signal_events`

История жизни сигнала.

```sql
CREATE TABLE trading_signal_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_id       UUID NOT NULL REFERENCES trading_signals(id) ON DELETE CASCADE,
    event_type      TEXT NOT NULL,
    old_status      TEXT,
    new_status      TEXT,
    payload         JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Эту таблицу лучше партиционировать по месяцу, потому что событий будет много. PostgreSQL поддерживает декларативное партиционирование, включая range/list/hash partitioning. ([PostgreSQL][5])

---

# 8. PostgreSQL: watchlists и пользовательские алерты

## 8.1. `user_watchlists`

```sql
CREATE TABLE user_watchlists (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    is_default      BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## 8.2. `user_watchlist_pairs`

```sql
CREATE TABLE user_watchlist_pairs (
    watchlist_id    UUID NOT NULL REFERENCES user_watchlists(id) ON DELETE CASCADE,
    pair_id         UUID NOT NULL REFERENCES market_pairs(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (watchlist_id, pair_id)
);
```

## 8.3. `user_alert_rules`

```sql
CREATE TABLE user_alert_rules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    pair_id         UUID REFERENCES market_pairs(id),
    strategy_version_id UUID REFERENCES strategy_versions(id),
    condition_type  TEXT NOT NULL,
    condition_body  JSONB NOT NULL,
    channels        TEXT[] NOT NULL DEFAULT ARRAY['websocket'],
    is_enabled      BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

# 9. PostgreSQL: виртуальная торговля

Важно: виртуальные сделки **не должны менять рыночные данные**. Они симулируются по внешним биржевым данным из Redis/ClickHouse. Особенно для низколиквидных монет мы не «рисуем» свечу своей виртуальной сделкой.

## 9.1. `portfolios`

```sql
CREATE TABLE portfolios (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    type            TEXT NOT NULL CHECK (type IN ('virtual', 'live')),
    name            TEXT NOT NULL,
    base_currency   TEXT NOT NULL DEFAULT 'USDT',
    status          TEXT NOT NULL DEFAULT 'active',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## 9.2. `portfolio_balances`

Текущее состояние балансов.

```sql
CREATE TABLE portfolio_balances (
    portfolio_id    UUID NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    asset_id        UUID NOT NULL REFERENCES market_assets(id),
    available       NUMERIC(38, 18) NOT NULL DEFAULT 0,
    locked          NUMERIC(38, 18) NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (portfolio_id, asset_id)
);
```

## 9.3. `portfolio_balance_ledger`

Append-only журнал всех изменений баланса.

```sql
CREATE TABLE portfolio_balance_ledger (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id    UUID NOT NULL REFERENCES portfolios(id),
    asset_id        UUID NOT NULL REFERENCES market_assets(id),
    delta_available NUMERIC(38, 18) NOT NULL DEFAULT 0,
    delta_locked    NUMERIC(38, 18) NOT NULL DEFAULT 0,
    reason          TEXT NOT NULL,
    ref_type        TEXT,
    ref_id          UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## 9.4. `orders`

```sql
CREATE TABLE orders (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES app_users(id),
    portfolio_id    UUID NOT NULL REFERENCES portfolios(id),
    signal_id       UUID REFERENCES trading_signals(id),
    exchange_id     UUID NOT NULL REFERENCES market_exchanges(id),
    pair_id         UUID NOT NULL REFERENCES market_pairs(id),

    mode            TEXT NOT NULL CHECK (mode IN ('virtual', 'live')),
    side            TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    order_type      TEXT NOT NULL CHECK (order_type IN ('market', 'limit', 'stop', 'take_profit')),
    status          TEXT NOT NULL CHECK (
        status IN ('created', 'submitted', 'partially_filled', 'filled', 'cancelled', 'rejected')
    ),

    quantity        NUMERIC(38, 18) NOT NULL,
    price           NUMERIC(38, 18),
    stop_price      NUMERIC(38, 18),
    time_in_force   TEXT,

    idempotency_key TEXT NOT NULL,
    metadata        JSONB NOT NULL DEFAULT '{}',

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE(user_id, idempotency_key)
);
```

## 9.5. `order_fills`

```sql
CREATE TABLE order_fills (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id        UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    price           NUMERIC(38, 18) NOT NULL,
    quantity        NUMERIC(38, 18) NOT NULL,
    fee_amount      NUMERIC(38, 18) NOT NULL DEFAULT 0,
    fee_asset_id    UUID REFERENCES market_assets(id),
    liquidity       TEXT CHECK (liquidity IN ('maker', 'taker', 'simulated')),
    source_event_id TEXT,
    filled_at       TIMESTAMPTZ NOT NULL
);
```

## 9.6. `positions`

```sql
CREATE TABLE positions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES app_users(id),
    portfolio_id    UUID NOT NULL REFERENCES portfolios(id),
    signal_id       UUID REFERENCES trading_signals(id),
    pair_id         UUID NOT NULL REFERENCES market_pairs(id),

    mode            TEXT NOT NULL CHECK (mode IN ('virtual', 'live')),
    side            TEXT NOT NULL CHECK (side IN ('long', 'short')),
    status          TEXT NOT NULL CHECK (status IN ('open', 'closed', 'liquidated')),

    quantity        NUMERIC(38, 18) NOT NULL,
    entry_avg_price NUMERIC(38, 18) NOT NULL,
    exit_avg_price  NUMERIC(38, 18),

    stop_loss       NUMERIC(38, 18),
    take_profit     JSONB NOT NULL DEFAULT '[]',

    opened_at       TIMESTAMPTZ NOT NULL,
    closed_at       TIMESTAMPTZ,

    realized_pnl    NUMERIC(38, 18) DEFAULT 0,
    fees_total      NUMERIC(38, 18) DEFAULT 0,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

# 10. PostgreSQL: импорт реального журнала сделок

Пользователь сможет подключить биржу и подтянуть реальные сделки. Сырые события лучше хранить в ClickHouse, а нормализованные сделки — в PostgreSQL.

## 10.1. `external_exchange_orders`

```sql
CREATE TABLE external_exchange_orders (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES app_users(id),
    connection_id       UUID NOT NULL REFERENCES user_exchange_connections(id),
    exchange_order_id   TEXT NOT NULL,
    pair_id             UUID NOT NULL REFERENCES market_pairs(id),
    side                TEXT NOT NULL,
    order_type          TEXT,
    status              TEXT,
    quantity            NUMERIC(38, 18),
    price               NUMERIC(38, 18),
    created_exchange_at TIMESTAMPTZ,
    updated_exchange_at TIMESTAMPTZ,
    imported_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata            JSONB NOT NULL DEFAULT '{}',
    UNIQUE(connection_id, exchange_order_id)
);
```

## 10.2. `external_exchange_trades`

```sql
CREATE TABLE external_exchange_trades (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES app_users(id),
    connection_id       UUID NOT NULL REFERENCES user_exchange_connections(id),
    exchange_trade_id   TEXT NOT NULL,
    exchange_order_id   TEXT,
    pair_id             UUID NOT NULL REFERENCES market_pairs(id),
    side                TEXT NOT NULL,
    price               NUMERIC(38, 18) NOT NULL,
    quantity            NUMERIC(38, 18) NOT NULL,
    fee_amount          NUMERIC(38, 18),
    fee_asset_id        UUID REFERENCES market_assets(id),
    traded_at           TIMESTAMPTZ NOT NULL,
    imported_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata            JSONB NOT NULL DEFAULT '{}',
    UNIQUE(connection_id, exchange_trade_id)
);
```

---

# 11. PostgreSQL: AI-объяснения сигналов

```sql
CREATE TABLE signal_ai_explanations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_id       UUID NOT NULL REFERENCES trading_signals(id) ON DELETE CASCADE,
    model_provider  TEXT NOT NULL,
    model_name      TEXT NOT NULL,
    prompt_hash     TEXT NOT NULL,
    explanation_md  TEXT NOT NULL,
    risk_notes      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

# 12. PostgreSQL: уведомления

## 12.1. `notifications`

```sql
CREATE TABLE notifications (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    type            TEXT NOT NULL,
    title           TEXT NOT NULL,
    body            TEXT,
    payload         JSONB NOT NULL DEFAULT '{}',
    is_read         BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## 12.2. `notification_deliveries`

```sql
CREATE TABLE notification_deliveries (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    notification_id UUID NOT NULL REFERENCES notifications(id) ON DELETE CASCADE,
    channel         TEXT NOT NULL,
    status          TEXT NOT NULL,
    provider_msg_id TEXT,
    sent_at         TIMESTAMPTZ,
    error           TEXT
);
```

---

# 13. PostgreSQL: outbox и аудит

## 13.1. `outbox_events`

Нужна для надежной доставки событий после транзакции.

```sql
CREATE TABLE outbox_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    aggregate_type  TEXT NOT NULL,
    aggregate_id    UUID NOT NULL,
    event_type      TEXT NOT NULL,
    payload         JSONB NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    attempts        INT NOT NULL DEFAULT 0,
    next_retry_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at    TIMESTAMPTZ
);
```

## 13.2. `audit_log`

```sql
CREATE TABLE audit_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES app_users(id),
    action          TEXT NOT NULL,
    entity_type     TEXT,
    entity_id       UUID,
    ip_address      INET,
    user_agent      TEXT,
    payload         JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Для user-specific таблиц стоит включать Row-Level Security, потому что PostgreSQL позволяет ограничивать видимость и изменение строк на уровне политик. ([PostgreSQL][6])

---

# 14. ClickHouse: рыночные данные и аналитика

## 14.1. База `market`

```sql
CREATE DATABASE IF NOT EXISTS market;
```

---

## 14.2. `market.raw_exchange_events`

Сырые события от бирж. Храним ограниченное время.

```sql
CREATE TABLE market.raw_exchange_events
(
    exchange        LowCardinality(String),
    event_type      LowCardinality(String),
    symbol          LowCardinality(String),
    event_ts        DateTime64(3, 'UTC'),
    ingest_ts       DateTime64(3, 'UTC'),
    source_id       String,
    sequence_id     Nullable(UInt64),
    raw_payload     String
)
ENGINE = MergeTree
PARTITION BY toYYYYMMDD(ingest_ts)
ORDER BY (exchange, event_type, symbol, ingest_ts, source_id)
TTL ingest_ts + INTERVAL 30 DAY DELETE;
```

ClickHouse TTL можно использовать не только для удаления старых строк, но и для управления жизненным циклом данных. ([ClickHouse][7])

---

## 14.3. `market.trades`

Все сделки с бирж.

```sql
CREATE TABLE market.trades
(
    exchange        LowCardinality(String),
    symbol          LowCardinality(String),
    trade_id        String,
    side            LowCardinality(String),
    price           Decimal(38, 18),
    quantity        Decimal(38, 18),
    trade_ts        DateTime64(3, 'UTC'),
    ingest_ts       DateTime64(3, 'UTC'),
    is_buyer_maker  Nullable(UInt8)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(trade_ts)
ORDER BY (exchange, symbol, trade_ts, trade_id);
```

Не делаем здесь `ReplacingMergeTree` как основной механизм точной дедупликации. В ClickHouse `ReplacingMergeTree` убирает дубликаты во время фоновых merge-процессов, но не гарантирует отсутствие дублей в момент чтения. ([ClickHouse][8])
Поэтому дедупликацию критичных событий делаем upstream: `exchange + symbol + trade_id`.

---

## 14.4. `market.orderbook_l2_deltas`

```sql
CREATE TABLE market.orderbook_l2_deltas
(
    exchange        LowCardinality(String),
    symbol          LowCardinality(String),
    sequence_id     UInt64,
    side            LowCardinality(String),
    price           Decimal(38, 18),
    quantity        Decimal(38, 18),
    event_ts        DateTime64(3, 'UTC'),
    ingest_ts       DateTime64(3, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMMDD(event_ts)
ORDER BY (exchange, symbol, event_ts, sequence_id, side, price)
TTL event_ts + INTERVAL 14 DAY DELETE;
```

---

## 14.5. `market.orderbook_snapshots`

```sql
CREATE TABLE market.orderbook_snapshots
(
    exchange        LowCardinality(String),
    symbol          LowCardinality(String),
    snapshot_ts     DateTime64(3, 'UTC'),
    ingest_ts       DateTime64(3, 'UTC'),
    bids            Array(Tuple(Decimal(38, 18), Decimal(38, 18))),
    asks            Array(Tuple(Decimal(38, 18), Decimal(38, 18))),
    sequence_id     Nullable(UInt64)
)
ENGINE = MergeTree
PARTITION BY toYYYYMMDD(snapshot_ts)
ORDER BY (exchange, symbol, snapshot_ts);
```

---

# 15. ClickHouse: свечи

## 15.1. `market.ohlcv_1m`

Для MVP можно писать свечи прямо из нашего candle-builder сервиса. Позже — строить materialized views из `market.trades`.

```sql
CREATE TABLE market.ohlcv_1m
(
    exchange        LowCardinality(String),
    symbol          LowCardinality(String),
    ts              DateTime('UTC'),
    open            Decimal(38, 18),
    high            Decimal(38, 18),
    low             Decimal(38, 18),
    close           Decimal(38, 18),
    volume_base     Decimal(38, 18),
    volume_quote    Decimal(38, 18),
    trades_count    UInt64,
    created_at      DateTime64(3, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(ts)
ORDER BY (exchange, symbol, ts);
```

## 15.2. `market.ohlcv_5m`, `market.ohlcv_15m`, `market.ohlcv_1h`, `market.ohlcv_1d`

Лучше создать отдельные таблицы под основные timeframe, потому что это ускорит чтение в UI и стратегиях.

```sql
CREATE TABLE market.ohlcv_5m AS market.ohlcv_1m
ENGINE = MergeTree
PARTITION BY toYYYYMM(ts)
ORDER BY (exchange, symbol, ts);
```

Для агрегированных свечей и метрик можно использовать materialized views. ClickHouse materialized views могут трансформировать и агрегировать данные при вставке, а `AggregatingMergeTree` подходит для incremental aggregation. ([ClickHouse][9])

---

# 16. ClickHouse: индикаторы и features

## 16.1. `market.indicator_values`

```sql
CREATE TABLE market.indicator_values
(
    exchange        LowCardinality(String),
    symbol          LowCardinality(String),
    timeframe       LowCardinality(String),
    ts              DateTime('UTC'),

    rsi_14          Nullable(Float64),
    ema_20          Nullable(Decimal(38, 18)),
    ema_50          Nullable(Decimal(38, 18)),
    ema_200         Nullable(Decimal(38, 18)),
    atr_14          Nullable(Decimal(38, 18)),
    volume_sma_20   Nullable(Decimal(38, 18)),

    features_json   String,
    calculated_at   DateTime64(3, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(ts)
ORDER BY (exchange, symbol, timeframe, ts);
```

Почему в ClickHouse, а не PostgreSQL: индикаторы будут пересчитываться массово по огромной истории. Это аналитическая нагрузка, не OLTP.

---

# 17. ClickHouse: события сигналов

## 17.1. `analytics.signal_events`

```sql
CREATE DATABASE IF NOT EXISTS analytics;

CREATE TABLE analytics.signal_events
(
    signal_id       UUID,
    signal_key      String,
    event_type      LowCardinality(String),

    exchange        LowCardinality(String),
    symbol          LowCardinality(String),
    timeframe       LowCardinality(String),
    strategy_code   LowCardinality(String),
    strategy_version String,

    direction       LowCardinality(String),
    confidence      Float64,
    score           Float64,

    entry_price     Decimal(38, 18),
    stop_loss       Nullable(Decimal(38, 18)),

    features_json   String,

    event_ts        DateTime64(3, 'UTC'),
    ingest_ts       DateTime64(3, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(event_ts)
ORDER BY (strategy_code, exchange, symbol, timeframe, event_ts);
```

---

## 17.2. `analytics.strategy_performance_daily`

```sql
CREATE TABLE analytics.strategy_performance_daily
(
    date            Date,
    strategy_code   LowCardinality(String),
    strategy_version String,
    exchange        LowCardinality(String),
    symbol          LowCardinality(String),
    timeframe       LowCardinality(String),

    signals_count   UInt64,
    wins_count      UInt64,
    losses_count    UInt64,
    avg_rr          Float64,
    avg_pnl_pct     Float64,
    max_drawdown_pct Float64
)
ENGINE = SummingMergeTree
PARTITION BY toYYYYMM(date)
ORDER BY (strategy_code, exchange, symbol, timeframe, date);
```

---

# 18. ClickHouse: виртуальные и реальные торговые события

## 18.1. `analytics.virtual_trade_events`

```sql
CREATE TABLE analytics.virtual_trade_events
(
    user_id         UUID,
    portfolio_id    UUID,
    order_id        UUID,
    position_id     Nullable(UUID),
    signal_id       Nullable(UUID),

    event_type      LowCardinality(String),
    exchange        LowCardinality(String),
    symbol          LowCardinality(String),
    side            LowCardinality(String),

    price           Decimal(38, 18),
    quantity        Decimal(38, 18),
    pnl             Nullable(Decimal(38, 18)),
    fee             Nullable(Decimal(38, 18)),

    event_ts        DateTime64(3, 'UTC'),
    ingest_ts       DateTime64(3, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(event_ts)
ORDER BY (user_id, portfolio_id, event_ts);
```

## 18.2. `analytics.external_trade_events`

```sql
CREATE TABLE analytics.external_trade_events
(
    user_id          UUID,
    connection_id    UUID,
    exchange         LowCardinality(String),
    symbol           LowCardinality(String),
    exchange_trade_id String,

    side             LowCardinality(String),
    price            Decimal(38, 18),
    quantity         Decimal(38, 18),
    fee              Nullable(Decimal(38, 18)),

    traded_at        DateTime64(3, 'UTC'),
    imported_at      DateTime64(3, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(traded_at)
ORDER BY (user_id, exchange, symbol, traded_at);
```

---

# 19. Redis: что именно держим

## 19.1. Горячие цены

```text
price:{exchange}:{symbol}
```

Value:

```json
{
  "price": "67250.12",
  "bid": "67249.80",
  "ask": "67250.50",
  "ts": "2026-05-26T09:10:00.123Z"
}
```

TTL: 5–30 секунд.

---

## 19.2. Последний order book top-N

```text
orderbook:{exchange}:{symbol}
```

TTL: 1–5 секунд.

---

## 19.3. Последние сигналы

```text
signals:latest
signals:latest:{strategy_code}
signals:latest:{exchange}:{symbol}
```

Для ранжирования можно использовать Redis Sorted Sets: они хранят уникальные элементы, упорядоченные по score. Это подходит для top signals, top movers, volatility ranking. ([Redis][10])

Пример:

```text
ZADD signals:latest 98.7 signal_uuid
```

Score = качество сигнала или timestamp.

---

## 19.4. WebSocket fanout

```text
pubsub:signals:new
pubsub:signals:update
pubsub:prices:{exchange}:{symbol}
pubsub:portfolio:{user_id}
```

---

## 19.5. Redis Streams

```text
stream:market:trades
stream:market:orderbook
stream:signals:generated
stream:orders:virtual
stream:notifications
```

Consumer groups:

```text
cg:clickhouse-writer
cg:signal-engine
cg:notification-service
cg:websocket-gateway
```

Redis Streams с consumer groups дают модель, где несколько consumers делят поток и подтверждают обработку сообщений. ([Redis][11])

---

## 19.6. Rate limits

```text
rate:user:{user_id}:api
rate:ip:{ip}:auth
rate:exchange:{exchange}:requests
```

---

## 19.7. Locks

```text
lock:portfolio:{portfolio_id}
lock:signal:{signal_id}:confirm
lock:exchange-sync:{connection_id}
```

---

# 20. Что партиционировать

## PostgreSQL

Партиционировать:

| Таблица                    | Ключ                                          |
| -------------------------- | --------------------------------------------- |
| `trading_signal_events`    | `created_at` monthly                          |
| `portfolio_balance_ledger` | `created_at` monthly                          |
| `order_fills`              | `filled_at` monthly                           |
| `external_exchange_trades` | `traded_at` monthly                           |
| `audit_log`                | `created_at` monthly                          |
| `outbox_events`            | `created_at` monthly или status-based cleanup |

Не партиционировать на старте:

| Таблица                 | Почему         |
| ----------------------- | -------------- |
| `app_users`             | не time-series |
| `market_assets`         | справочник     |
| `market_pairs`          | справочник     |
| `strategy_templates`    | мало строк     |
| `user_strategy_configs` | средний объем  |

---

## ClickHouse

Партиционировать:

| Таблица                | Ключ                    |
| ---------------------- | ----------------------- |
| `raw_exchange_events`  | `toYYYYMMDD(ingest_ts)` |
| `trades`               | `toYYYYMM(trade_ts)`    |
| `orderbook_l2_deltas`  | `toYYYYMMDD(event_ts)`  |
| `ohlcv_*`              | `toYYYYMM(ts)`          |
| `indicator_values`     | `toYYYYMM(ts)`          |
| `signal_events`        | `toYYYYMM(event_ts)`    |
| `virtual_trade_events` | `toYYYYMM(event_ts)`    |

---

# 21. Индексы PostgreSQL

Главные индексы:

```sql
CREATE INDEX idx_orders_user_created
ON orders (user_id, created_at DESC);

CREATE INDEX idx_orders_status
ON orders (status, created_at DESC);

CREATE INDEX idx_positions_user_status
ON positions (user_id, status, opened_at DESC);

CREATE INDEX idx_external_trades_user_time
ON external_exchange_trades (user_id, traded_at DESC);

CREATE INDEX idx_notifications_user_read
ON notifications (user_id, is_read, created_at DESC);

CREATE INDEX idx_outbox_pending
ON outbox_events (status, next_retry_at, created_at)
WHERE status = 'pending';
```

PostgreSQL поддерживает разные типы индексов, включая `btree`, `hash`, `gist`, `spgist`, `gin`, `brin`; для нашей модели основа — `btree`, а для `jsonb`-поиска — `GIN`. ([PostgreSQL][12])

---

# 22. Минимальная ER-логика

```text
app_users
  ├── user_subscriptions
  ├── user_exchange_connections
  ├── user_strategy_configs
  ├── user_watchlists
  ├── portfolios
  │     ├── portfolio_balances
  │     ├── portfolio_balance_ledger
  │     ├── orders
  │     │     └── order_fills
  │     └── positions
  ├── external_exchange_orders
  ├── external_exchange_trades
  └── notifications

strategy_templates
  └── strategy_versions
        ├── user_strategy_configs
        └── trading_signals

market_exchanges
  ├── market_pairs
  ├── user_exchange_connections
  └── trading_signals

market_assets
  └── market_pairs

trading_signals
  ├── trading_signal_events
  ├── signal_ai_explanations
  ├── orders
  └── positions
```

---

# 23. Что пишем куда: финальное разделение

## PostgreSQL

Писать сюда:

* пользователи;
* профили;
* подписки;
* тарифы;
* API-подключения к биржам;
* стратегии и версии стратегий;
* пользовательские настройки стратегий;
* watchlists;
* сигналы как бизнес-сущности;
* статус сигнала;
* подтверждение входа пользователем;
* виртуальные ордера;
* виртуальные позиции;
* текущие балансы;
* ledger балансов;
* импортированные реальные сделки пользователя;
* уведомления;
* audit log;
* outbox events.

---

## ClickHouse

Писать сюда:

* raw exchange websocket messages;
* trades/ticks;
* order book deltas;
* order book snapshots;
* candles;
* indicators;
* market features;
* signal events;
* strategy analytics;
* virtual trading analytics;
* real trading analytics;
* backtest results;
* агрегированные PnL-метрики;
* runtime performance metrics.

---

## Redis

Писать сюда:

* последние цены;
* best bid/ask;
* top-N order book;
* последние сигналы;
* временные рейтинги сигналов;
* WebSocket channels;
* Redis Streams для событий;
* rate limits;
* distributed locks;
* краткоживущий кэш пользовательских dashboard-данных.

---

# 24. MVP-версия

Для MVP достаточно:

## PostgreSQL MVP

1. `app_users`
2. `subscription_plans`
3. `user_subscriptions`
4. `market_exchanges`
5. `market_assets`
6. `market_pairs`
7. `strategy_templates`
8. `strategy_versions`
9. `user_strategy_configs`
10. `trading_signals`
11. `trading_signal_events`
12. `portfolios`
13. `portfolio_balances`
14. `portfolio_balance_ledger`
15. `orders`
16. `order_fills`
17. `positions`
18. `user_watchlists`
19. `user_watchlist_pairs`
20. `notifications`
21. `outbox_events`
22. `audit_log`

## ClickHouse MVP

1. `market.raw_exchange_events`
2. `market.trades`
3. `market.ohlcv_1m`
4. `market.ohlcv_5m`
5. `market.ohlcv_15m`
6. `market.ohlcv_1h`
7. `market.indicator_values`
8. `analytics.signal_events`
9. `analytics.virtual_trade_events`
10. `analytics.strategy_performance_daily`

## Redis MVP

1. `price:{exchange}:{symbol}`
2. `orderbook:{exchange}:{symbol}`
3. `signals:latest`
4. `signals:latest:{exchange}:{symbol}`
5. `stream:market:trades`
6. `stream:signals:generated`
7. `stream:orders:virtual`
8. `pubsub:signals:new`
9. `pubsub:portfolio:{user_id}`
10. `rate:user:{user_id}:api`

---

# 25. Важное архитектурное решение

Для старта можно использовать:

```text
Redis Streams → workers → PostgreSQL / ClickHouse / WebSocket
```

Но для масштаба **1M+ пользователей** лучше закладывать совместимость с Kafka/Redpanda/NATS JetStream. ClickHouse уже имеет официальные варианты интеграции с Kafka-compatible брокерами, включая Kafka engine и Kafka Connect Sink. ([ClickHouse][13])

То есть Redis оставляем как:

```text
hot cache + realtime fanout + locks + short-lived streams
```

А тяжелую event-streaming магистраль в будущем лучше вынести в:

```text
Kafka / Redpanda / NATS JetStream
```

---

# 26. Итоговая рекомендация

Для Crypto_radar я бы заложил такую финальную модель:

```text
PostgreSQL = бизнес-состояние и транзакции
ClickHouse = рынок, история, аналитика, индикаторы, performance
Redis = мгновенность интерфейса, hot cache, WebSocket, rate limit
```

Самая важная граница:

**Не хранить тики, order book и свечи в PostgreSQL.**
Это быстро убьет OLTP-базу.

**Не хранить пользователей, подписки, балансы и статусы ордеров только в ClickHouse.**
ClickHouse не должен быть source of truth для пользовательских транзакций.

**Не считать Redis постоянным хранилищем.**
Redis — ускоритель и real-time слой, а не база истины.

[1]: https://clickhouse.com/docs/engines/table-engines/mergetree-family/mergetree?utm_source=chatgpt.com "MergeTree table engine | ClickHouse Docs"
[2]: https://redis.io/docs/latest/develop/data-types/streams/?utm_source=chatgpt.com "Redis Streams | Docs"
[3]: https://redis.io/docs/latest/develop/pubsub/?utm_source=chatgpt.com "Redis Pub/sub | Docs"
[4]: https://www.postgresql.org/docs/current/datatype-json.html?utm_source=chatgpt.com "PostgreSQL: Documentation: 18: 8.14. JSON Types"
[5]: https://www.postgresql.org/docs/current/static/ddl-partitioning.html?utm_source=chatgpt.com "PostgreSQL: Documentation: 18: 5.12. Table Partitioning"
[6]: https://www.postgresql.org/docs/17/ddl-rowsecurity.html?utm_source=chatgpt.com "PostgreSQL: Documentation: 17: 5.9. Row Security Policies"
[7]: https://clickhouse.com/docs/guides/developer/ttl?utm_source=chatgpt.com "Manage data with TTL (Time-to-live) | ClickHouse Docs"
[8]: https://clickhouse.com/docs/engines/table-engines/mergetree-family/replacingmergetree?utm_source=chatgpt.com "ReplacingMergeTree table engine | ClickHouse Docs"
[9]: https://clickhouse.com/blog/using-materialized-views-in-clickhouse?utm_source=chatgpt.com "Using Materialized Views in ClickHouse"
[10]: https://redis.io/docs/latest/develop/data-types/sorted-sets?utm_source=chatgpt.com "Redis sorted sets | Docs"
[11]: https://redis.io/docs/latest/develop/use-cases/streaming/?utm_source=chatgpt.com "Redis streaming | Docs"
[12]: https://www.postgresql.org/docs/18/sql-createindex.html?utm_source=chatgpt.com "PostgreSQL: Documentation: 18: CREATE INDEX"
[13]: https://clickhouse.com/docs/integrations/kafka?utm_source=chatgpt.com "Integrating Kafka with ClickHouse"
