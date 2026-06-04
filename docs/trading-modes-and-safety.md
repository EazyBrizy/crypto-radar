# Trading Modes And Safety Gates

Этот документ описывает безопасные режимы Crypto Radar: demo identity,
virtual/paper trading, real testnet trading и real mainnet trading.

## Краткая Карта Режимов

| Режим | Что происходит | Где деньги | Безопасность по умолчанию |
| --- | --- | --- | --- |
| `demo` identity | Внутренний демо-пользователь для локального MVP и bypass-auth UI. | Нет реального счета. | Включен для совместимости demo flows. |
| `virtual` / paper | Backend симулирует entry, fill, fees, slippage и lifecycle позиции. | PostgreSQL virtual portfolio и ledger. | Разрешен, но проходит RiskGate. |
| `real` dry-run | Backend строит реальный план ордеров без отправки на биржу. | Нет реального ордера. | Default adapter - dry-run. |
| `real-testnet` | Bybit live-capable adapter может отправлять ордера в testnet. | Testnet-счет биржи. | Требует явных live-флагов, testnet metadata и свежих snapshots. |
| `real-mainnet` | Bybit live-capable adapter может отправлять ордера в mainnet. | Реальные средства. | Выключен отдельным mainnet-флагом и должен включаться только вручную. |

`mode` в API сейчас принимает `virtual` или `real`. Разделение
`real-testnet` / `real-mainnet` определяется backend-адаптером, metadata
exchange connection и feature flags. По умолчанию реальная ветка остается
dry-run и не отправляет ордера на биржу.

## User Identity

`demo_user` - внутренний стабильный id demo flow. Frontend MVP bypass-auth
возвращает demo session с `user.id = "demo_user"`, а backend API по умолчанию
использует этот id в query/body параметрах.

`usr_demo` - legacy/external demo auth subject. Backend продолжает принимать
его через `resolve_app_user`, чтобы старые внешние auth subject и тесты не
ломались. Оба значения резолвятся в seeded demo user, но новые внутренние
вызовы должны использовать `demo_user`.

Demo identity не означает paper trading само по себе. Это только выбор
пользователя/tenant. Исполнение выбирается отдельно через `mode=virtual` или
`mode=real`.

## Pending Entry

Pending entry - это отложенное намерение пользователя войти только после
касания принятой entry zone. Оно хранит accepted snapshot сигнала, trade plan,
execution profile, mode и request.

Активные статусы:

- `pending`: пользователь принял setup, система ждет accepted entry zone.
- `triggered`: цена коснулась accepted entry zone, можно запускать свежие
  проверки перед fill/order.
- `filling`: fill/order path начался, но результат еще не финальный.
- `requires_reconfirmation`: принятый trade plan устарел и требует нового
  подтверждения пользователя.

Терминальные статусы:

- `filled`: entry завершился, intent связан с filled trade.
- `failed`: workflow не может продолжаться; причина должна быть в
  `failure_reason`.
- `cancelled`: пользователь или система отменили intent.
- `expired`: TTL intent истек до fill.

Смена score/confidence/status без изменения плана не требует reconfirmation.
Изменение `exchange`, `symbol`, `side`, entry, stop или targets меняет
`TradePlanFingerprint` и переводит активный intent в
`requires_reconfirmation`. Такой intent не должен создавать virtual trade или
real order из старого snapshot.

На trigger-time backend заново строит RiskGate context из текущего счета,
рынка/orderbook, exchange rules, fee context и текущего сигнала. Статус сигнала
или pending intent сам по себе не дает права на вход.

## Virtual / Paper Trading

`mode=virtual` открывает paper position через `app.services.virtual_trading`.
Этот сервис владеет virtual execution preview/confirmation и PostgreSQL
записями по virtual orders, fills, positions, balances, ledger, audit и outbox.

Virtual balance симулируется отдельно от реального счета:

- demo seed создает virtual portfolio и начальный USDT balance;
- настройки risk management могут задавать `virtual_starting_balance`;
- открытие сделки блокирует/списывает virtual balance через ledger;
- закрытие позиции обновляет balance, PnL, fee/slippage trace и protection
  state.

Virtual fills симулируются на базе текущей цены, spread/slippage, fee model,
orderbook/liquidity inputs и simulation level. Нереалистичная execution quality
по умолчанию является предупреждением, а не самостоятельным veto. Последнее
право входа остается за RiskGate.

Paper lifecycle:

- active virtual statuses: `open`, `partially_closed`;
- terminal virtual statuses: `closed`, `stopped`, `invalidated`, `expired`,
  `cancelled`;
- price ticks/candles могут закрыть позицию по `stop_loss`, final
  `take_profit`, breakeven/trailing stop, invalidation или time stop;
- ручное закрытие идет через `POST /api/v1/trades/virtual/{trade_id}/close`.

Virtual trading не пишет synthetic candles/ticks/orderbook в shared market
storage. Private impact path относится только к конкретной simulated position.

## Real Trading

Real trading всегда строже virtual:

- live order placement выключен по умолчанию;
- default backend adapter - `DryRunExecutionAdapter`, который строит план без
  отправки ордера;
- live-capable Bybit adapter требует feature flags;
- testnet должен быть первым live окружением;
- mainnet требует отдельный opt-in flag;
- для live entry нужны exchange API credentials;
- raw exchange secrets не пишутся в PostgreSQL и не возвращаются из API;
- перед live entry нужен fresh wallet/account snapshot;
- protective stop обязателен до entry;
- fresh exchange instrument rules, fee-rate snapshot и market/orderbook data
  участвуют в readiness checks.

Для Bybit testnet live placement должны одновременно выполняться условия:

- backend использует live-capable `BybitRealExecutionAdapter`, а не dry-run;
- exchange connection metadata явно указывает testnet, например
  `{"testnet": true}` или `{"environment": "testnet"}`;
- `ENABLE_LIVE_TRADING=true`;
- `ENABLE_BYBIT_LIVE_ORDER_PLACEMENT=true`;
- API key/secret доступны через configured secret provider;
- account snapshot status = `fresh`, source = `exchange`;
- plan содержит protective stop и take-profit orders;
- `REQUIRE_PROTECTIVE_STOP_FOR_LIVE_ENTRY=true` остается включенным.

Для Bybit mainnet дополнительно требуется:

- exchange connection metadata не является testnet;
- `ENABLE_BYBIT_MAINNET_ORDER_PLACEMENT=true`;
- отдельный production approval/runbook вне локальной разработки.

Mainnet risk: наличие API key и `ENABLE_LIVE_TRADING=true` не должно быть
достаточным для реальных mainnet ордеров. Отдельный mainnet-флаг существует
именно для предотвращения случайного выката из testnet/dry-run в real funds.
Не включайте mainnet-флаг в shared `.env`, docker-compose defaults, CI, demo
окружениях или локальных примерах.

## Market Universe

Market universe хранится в PostgreSQL `market_pairs` и синхронизируется из
публичных exchange endpoints. Для Bybit linear используется
`POST /api/v1/market-universe/sync`, который берет tradable USDT pairs,
сортирует по `turnover_24h_desc` и может сохранить top slice в базу.

Поддерживаемые лимиты:

- `top_100`;
- `top_200` - backend default для scanner universe при `use_all_symbols=true`;
- `top_500`;
- `all`.

`GET /api/v1/market-universe/pairs` читает persisted universe и принимает
такие же limit filters. Настройки Radar с `use_all_symbols=true` используют
persisted Top 200, если он есть, а при отсутствии данных могут fallback к
публичному Bybit instruments list / MVP symbols.

Per-strategy pair selection:

- пустой `pair_scope` означает "все пары scanner universe"; market quality
  filter может быть hard pre-strategy exclusion;
- непустой `pair_scope` означает ручной watchlist стратегии; scanner добавляет
  эти пары в подписки, а quality issues становятся warning/context вместо
  автоматического исключения;
- explicit strategy pairs валидируются через `market_pairs`, поэтому перед
  выбором новых пар обычно нужно синхронизировать universe.

Scanner load растет примерно как:

```text
scan_pairs * timeframes * enabled_strategy_configs
```

`MAX_SCANNER_PAIRS` ограничивает число scanner pairs. Если лимит превышен и
`TRUNCATE_SCANNER_PAIRS_OVER_LIMIT=false`, старт scanner блокируется с
warning. Если truncation включен, universe обрезается до лимита, что безопаснее
для локальной нагрузки, но может скрыть часть рынка.

## Environment Variables

Безопасные defaults должны оставаться такими:

```env
ENABLE_LIVE_TRADING=false
ENABLE_BYBIT_LIVE_ORDER_PLACEMENT=false
ENABLE_BYBIT_MAINNET_ORDER_PLACEMENT=false
REQUIRE_PROTECTIVE_STOP_FOR_LIVE_ENTRY=true
EXCHANGE_ACCOUNT_SNAPSHOT_TTL_SECONDS=15
MAX_SCANNER_PAIRS=200
TRUNCATE_SCANNER_PAIRS_OVER_LIMIT=false
```

Назначение:

- `ENABLE_LIVE_TRADING`: глобальный backend gate для live real execution.
  `false` блокирует live-capable adapters; dry-run real planning может работать
  без отправки ордеров.
- `ENABLE_BYBIT_LIVE_ORDER_PLACEMENT`: биржевой gate для Bybit live order
  placement. Для testnet нужен вместе с `ENABLE_LIVE_TRADING=true`.
- `ENABLE_BYBIT_MAINNET_ORDER_PLACEMENT`: отдельный mainnet opt-in. Держать
  `false` в demo, local, CI и testnet-first окружениях.
- `REQUIRE_PROTECTIVE_STOP_FOR_LIVE_ENTRY`: требует native stopLoss/protective
  stop для live entry. Не отключать для mainnet.
- `EXCHANGE_ACCOUNT_SNAPSHOT_TTL_SECONDS`: TTL кэша wallet/account snapshot.
  Live readiness требует fresh snapshot; слишком высокий TTL повышает риск
  устаревшего balance/equity.
- `MAX_SCANNER_PAIRS`: верхняя граница scanner universe для защиты CPU,
  WebSocket subscriptions, warmup OHLCV и strategy checks.
- `TRUNCATE_SCANNER_PAIRS_OVER_LIMIT`: `false` блокирует scanner при
  превышении лимита; `true` обрезает universe до `MAX_SCANNER_PAIRS`.

Не документируйте и не коммитьте реальные значения `BYBIT_API_KEY`,
`BYBIT_SECRET`, `BINANCE_API_KEY` или других exchange secrets. Для примеров
используйте только placeholders, а production secret storage должен выдавать
`key_ref`, а не raw secret.

## Safe Runbook

Для demo/paper:

1. Оставьте все live flags в `false`.
2. Запустите backend/frontend с demo user.
3. Используйте `mode=virtual` для подтверждения сигналов.
4. Проверяйте journal через `/api/v1/trades/virtual`.

Для real dry-run:

1. Оставьте live flags в `false`.
2. Используйте `mode=real`, чтобы получить risk/readiness/plan result без
   отправки exchange order.
3. Исправьте blockers по RiskGate, exchange rules, fee rates и snapshots.

Для real testnet:

1. Сначала синхронизируйте market universe и instrument rules.
2. Подключите exchange connection с testnet metadata.
3. Убедитесь, что secret provider содержит testnet API credentials.
4. Включите только `ENABLE_LIVE_TRADING=true` и
   `ENABLE_BYBIT_LIVE_ORDER_PLACEMENT=true`.
5. Не включайте `ENABLE_BYBIT_MAINNET_ORDER_PLACEMENT`.
6. Проверьте fresh wallet/account snapshot и protective stop в execution plan.

Для real mainnet:

1. Пройдите тот же путь на testnet.
2. Проверьте production secret provider, permissions ключа, account snapshot,
   reconciliation и observability.
3. Включайте `ENABLE_BYBIT_MAINNET_ORDER_PLACEMENT=true` только в явно
   утвержденном mainnet окружении.
4. После включения следите за readiness failures, partial fills,
   reconciliation-required events и protective-order guarantees.
