# Backend stack Crypto Radar

Локальный backend stack собирается через Docker Compose и следует идее из
`docs/backendStakTecnology.md`: REST для состояния, WebSocket/SSE для live
данных, NATS JetStream для событий, PostgreSQL для бизнес-данных, ClickHouse
для market data, Redis для hot state, отдельные workers для тяжелой логики.

## Проверка Docker

```powershell
docker --version
docker compose version
docker info
```

## Базовая инфраструктура

```powershell
docker compose -f infra/docker-compose.yml --profile infra up -d postgres redis nats clickhouse
```

Сервисы:

- PostgreSQL: `localhost:5432`
- Redis: `localhost:6379`
- NATS JetStream: `localhost:4222`, monitoring `http://127.0.0.1:8222`
- ClickHouse: HTTP `localhost:8123`, native `localhost:9000`

## Observability

```powershell
docker compose -f infra/docker-compose.yml --profile observability up -d prometheus loki grafana otel-collector
```

Сервисы:

- Prometheus: `http://127.0.0.1:9090`
- Grafana: `http://127.0.0.1:3001`
- Loki: `http://127.0.0.1:3100`
- OpenTelemetry Collector: `localhost:4317`, `localhost:4318`

## Backend image

```powershell
docker compose -f infra/docker-compose.yml build backend
docker run --rm crypto-radar-backend python -m compileall app
```

Для smoke-test без запуска scanner:

```powershell
docker run --rm -p 18000:8000 -e CRYPTO_RADAR_SCANNER_ENABLED=false crypto-radar-backend
```

Проверка:

```powershell
Invoke-WebRequest -Uri http://127.0.0.1:18000/health -UseBasicParsing
```

## Остановка

```powershell
docker compose -f infra/docker-compose.yml down
```

Чтобы удалить локальные volume с данными:

```powershell
docker compose -f infra/docker-compose.yml down -v
```

## Python 3.12

Dockerfile уже использует `python:3.12-slim`. Локальная venv может оставаться
на Python 3.11.9 до отдельной миграции. Переход считается безопасным после
успешной сборки backend image и установки зависимостей в контейнере.

Для локального перехода:

```powershell
# Run from the repository root.
Remove-Item -Recurse -Force .venv
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
Push-Location backend
..\.venv\Scripts\python.exe -m unittest discover tests
Pop-Location
```

Если `py -3.12` недоступен, нужно вызвать установленный `python.exe` из Python
3.12 напрямую.
