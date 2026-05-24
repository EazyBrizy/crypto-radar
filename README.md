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
cd backend
.venv\Scripts\python.exe app\main.py
```

Он подключается к Bybit WebSocket, обрабатывает тики и выводит найденные сигналы в консоль.

## Переменные окружения

Создай локальный `.env` из безопасного примера:

```powershell
copy .env.example .env
```

Не коммить реальные API-ключи. Файл `.env` игнорируется git.
