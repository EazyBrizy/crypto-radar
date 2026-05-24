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
- In-memory `SignalService` для активных и ручных сигналов.
- Архитектурный blueprint: `docs/architectureproject.md`.

Важно: сигналы, которые генерирует scanner, пока не сохраняются автоматически в API store. Сейчас API фиксирует MVP-контракт и ручной workflow работы с сигналами.

## Структура проекта

```text
backend/
  app/
    api/v1/              FastAPI routes
    core/                конфигурация и будущие инфраструктурные helpers
    models/              Pydantic-модели
    services/            scanner, market data, feature, strategy и signal services
    main.py              FastAPI entrypoint
docs/                    архитектура и продуктовые документы
infra/                   локальная инфраструктура
frontend/                заготовка под Next.js frontend
```

## Локальная установка

Из корня проекта:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

Если команда `python` недоступна в `PATH`, используй путь к установленному Python.

## Запуск API

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload
```

API будет доступен по адресу:

```text
http://127.0.0.1:8000
```

Интерактивная документация FastAPI:

```text
http://127.0.0.1:8000/docs
```

## Проверка endpoint

Health check:

```powershell
curl http://127.0.0.1:8000/health
```

Radar feed:

```powershell
curl http://127.0.0.1:8000/api/v1/radar
```

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
curl -X POST http://127.0.0.1:8000/api/v1/signals/sig_test/confirm
```

Отклонить сигнал:

```powershell
curl -X POST http://127.0.0.1:8000/api/v1/signals/sig_test/reject
```

Пока неизвестные `signal_id` возвращают `404` с сообщением `Сигнал не найден`.

## Ручной запуск scanner

Старый CLI entrypoint scanner пока оставлен:

```powershell
.venv\Scripts\python.exe backend\app\main.py
```

Он подключается к Bybit WebSocket, обрабатывает тики и выводит найденные сигналы в консоль.

## Переменные окружения

Создай локальный `.env` из безопасного примера:

```powershell
copy .env.example .env
```

Не коммить реальные API-ключи. Файл `.env` игнорируется git.
