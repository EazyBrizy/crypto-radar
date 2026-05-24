# Crypto Radar

Crypto Radar - MVP-проект для realtime-сканирования крипторынка и ручной работы с торговыми сигналами.

Текущий фокус: **MVP 1 - Radar + Manual Signals**.

## Что уже сделано

- Коллектор публичных рыночных данных Bybit через WebSocket.
- Feature pipeline для цены, всплеска объема, изменения цены за 1 минуту и волатильности.
- Strategy engine с ранней логикой генерации сигналов.
- FastAPI entrypoint для backend.
- API routes для MVP-сигналов:
  - `GET /api/v1/radar`
  - `GET /api/v1/signals`
  - `GET /api/v1/signals/{signal_id}`
  - `POST /api/v1/signals/{signal_id}/confirm`
  - `POST /api/v1/signals/{signal_id}/reject`
  - `GET /api/v1/trades`
  - `GET /api/v1/trades/virtual`
  - `GET /api/v1/trades/real`
  - `GET /api/v1/trades/virtual/{trade_id}`
  - `POST /api/v1/trades/virtual/{trade_id}/close`
- In-memory `SignalService` для активных и ручных сигналов.
- `TradeService` для базового trade journal с repository boundary под будущую PostgreSQL-запись.
- Архитектурный blueprint: `docs/architectureproject.md`.

Важно: scanner сохраняет найденные сигналы в текущем процессе API. Хранилища сигналов и виртуальных сделок пока in-memory, поэтому после перезапуска backend данные очищаются.

## Структура проекта

```text
backend/
  app/
    api/v1/              FastAPI routes
    core/                конфигурация и будущие инфраструктурные helpers
    exchanges/           exchange adapters: base, bybit
    schemas/             Pydantic-схемы API и внутренних сообщений
    services/            бизнес-сервисы и scanner orchestration
    strategies/          strategy interfaces и текущая breakout-логика
    workers/             фоновые workers: signal worker
    main.py              FastAPI entrypoint
docs/                    архитектура и продуктовые документы
infra/                   локальная инфраструктура
frontend/                заготовка под Next.js frontend
```

## Локальная установка

Рекомендуемый вариант: создать виртуальное окружение внутри папки `backend`.

```powershell
cd backend
python -m venv --clear .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Если команда `python` недоступна в `PATH`, используй путь к установленному Python.

Флаг `--clear` важен, если окружение `.venv` уже существовало. Он очищает старые пакеты и защищает от ситуации, когда внутри окружения остаются бинарные зависимости от другой версии Python.

Если ты запускаешь команды из корня проекта, путь к `requirements.txt` должен быть полным:

```powershell
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

## Запуск API

```powershell
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

API будет доступен по адресу:

```text
http://127.0.0.1:8000
```

Интерактивная документация FastAPI:

```text
http://127.0.0.1:8000/docs
```

При запуске API по умолчанию стартует фоновый scanner, который слушает Bybit WebSocket и сохраняет найденные сигналы в `SignalService`. Эти сигналы появляются в `/api/v1/radar`.

Чтобы временно запустить API без подключения к Bybit, добавь в `.env`:

```env
CRYPTO_RADAR_SCANNER_ENABLED=false
```

Важно: реальные сигналы появляются только когда strategy engine действительно находит подходящую ситуацию на рынке. Поэтому `/api/v1/radar` может вернуть пустой список сразу после запуска.

## Проверка endpoint

Health check:

```powershell
curl http://127.0.0.1:8000/health
```

Ответ покажет общий статус API, состояние фонового scanner и количество сигналов, которые runner успел сохранить в текущем процессе.

Radar feed:

```powershell
curl http://127.0.0.1:8000/api/v1/radar
```

## Проверка OHLCV-свечей и выбора рынка

Поддерживаемые биржи, пары и таймфреймы:

```powershell
curl http://127.0.0.1:8000/api/v1/exchanges
```

Текущая конфигурация Radar:

```powershell
curl http://127.0.0.1:8000/api/v1/radar/config
```

Выбрать конкретные пары и таймфреймы:

```powershell
curl -X PUT http://127.0.0.1:8000/api/v1/radar/config `
  -H "Content-Type: application/json" `
  -d "{\"exchanges\":[\"bybit\"],\"symbols\":[\"BTCUSDT\",\"ETHUSDT\"],\"use_all_symbols\":false,\"timeframes\":[\"1m\",\"15m\",\"1h\"]}"
```

Использовать все доступные пары поддерживаемых бирж:

```powershell
curl -X PUT http://127.0.0.1:8000/api/v1/radar/config `
  -H "Content-Type: application/json" `
  -d "{\"exchanges\":[\"bybit\"],\"symbols\":[],\"use_all_symbols\":true,\"timeframes\":[\"1m\",\"5m\",\"15m\",\"1h\",\"4h\",\"1d\"]}"
```

При `use_all_symbols=true` Bybit symbols берутся из публичного `instruments-info`. Если Bybit REST временно недоступен, приложение использует fallback MVP-список.

Проверить свечи по всем символам:

```powershell
curl "http://127.0.0.1:8000/api/v1/candles?exchange=bybit&timeframe=1m&limit=20"
```

Проверить свечи по конкретной паре:

```powershell
curl "http://127.0.0.1:8000/api/v1/candles?exchange=bybit&symbol=BTCUSDT&timeframe=15m&limit=20"
```

Доступные таймфреймы:

```text
1m, 5m, 15m, 1h, 4h, 1d
```

Важно: свечи строятся из realtime trade stream с момента запуска приложения. Сразу после старта исторических свечей еще нет, поэтому подожди 10-30 секунд и повтори запрос.

Все сигналы:

```powershell
curl http://127.0.0.1:8000/api/v1/signals
```

Детали сигнала:

```powershell
curl http://127.0.0.1:8000/api/v1/signals/sig_test
```

Подтвердить сигнал:

```powershell
curl -X POST http://127.0.0.1:8000/api/v1/signals/sig_test/confirm `
  -H "Content-Type: application/json" `
  -d "{\"mode\":\"virtual\",\"account_balance\":10000,\"risk_percent\":1,\"leverage\":2}"
```

В режиме `virtual` API открывает виртуальную сделку, рассчитывает entry с учетом slippage, размер позиции по risk percent, комиссии, stop loss, take profit и проверяет лимит открытых виртуальных позиций. Ответ содержит обновленный сигнал и созданную виртуальную сделку.

Режим `real` пока является заглушкой:

```powershell
curl -X POST http://127.0.0.1:8000/api/v1/signals/sig_test/confirm `
  -H "Content-Type: application/json" `
  -d "{\"mode\":\"real\"}"
```

Ожидаемый результат: `501 Not Implemented`. Реальное исполнение будет подключаться позже через Exchange Adapter Layer и Risk Guard.

Отклонить сигнал:

```powershell
curl -X POST http://127.0.0.1:8000/api/v1/signals/sig_test/reject `
  -H "Content-Type: application/json" `
  -d "{\"reason\":\"Риск выше моего плана\"}"
```

Пока неизвестные `signal_id` возвращают `404` с сообщением `Сигнал не найден`.

Проверить журнал виртуальных сделок:

```powershell
curl http://127.0.0.1:8000/api/v1/trades
```

```powershell
curl http://127.0.0.1:8000/api/v1/trades/virtual
```

Проверить журнал реальных сделок:

```powershell
curl http://127.0.0.1:8000/api/v1/trades/real
```

В MVP real journal возвращает пустой список, потому что реальное исполнение пока заглушено.

Проверить конкретную виртуальную сделку:

```powershell
curl http://127.0.0.1:8000/api/v1/trades/virtual/vtr_test
```

Закрыть виртуальную сделку вручную:

```powershell
curl -X POST http://127.0.0.1:8000/api/v1/trades/virtual/vtr_test/close `
  -H "Content-Type: application/json" `
  -d "{\"exit_price\":105000,\"reason\":\"manual_close\"}"
```

Trade Journal подготовлен к записи в базу: добавлены SQLAlchemy-модель `TradeJournalRecord`, единая схема `TradeJournalEntry`, repository boundary и `SqlAlchemyTradeRepository`. Сейчас используется in-memory repository, чтобы локальный MVP запускался без обязательного PostgreSQL.

## Ручной запуск scanner

Старый CLI entrypoint scanner пока оставлен:

```powershell
cd backend
.venv\Scripts\python.exe app\main.py
```

Он подключается к Bybit WebSocket, строит OHLCV-свечи, считает derived-индикаторы по свечным сериям и выводит найденные сигналы в консоль.

## Как сейчас связаны свечи и сигналы

Поток данных работает так:

```text
Bybit trade stream
  -> CandleService: OHLCV по exchange/symbol/timeframe
  -> FeatureEngine: EMA, RSI, ATR, Donchian, BB width, volume spike, wick ratios
  -> StrategyEngine: Trend Pullback, Squeeze Breakout, Liquidity Sweep
  -> SignalService: /api/v1/radar и /api/v1/signals
```

Каждый сигнал теперь получает `exchange`, `symbol` и реальный `timeframe` из свечной серии. Если в `/api/v1/radar` пока пусто, это нормально: стратегиям нужна история свечей. Например, `Trend Pullback Continuation` ждёт до 200 свечей, `Squeeze Breakout` - около 60, `Liquidity Sweep` - около 30.

## Переменные окружения

Создай локальный `.env` из безопасного примера:

```powershell
copy .env.example .env
```

Не коммить реальные API-ключи. Файл `.env` игнорируется git.
