# Crypto Radar Frontend

Базовый интерфейс MVP построен по `docs/frontend.md` и принципам `docs/architectureproject.md`.

Основные экраны:

- `Radar` - Signal First лента сигналов.
- `Signal Details` - торговый план, причины, риск, Paper Trade / Ignore Signal.
- `Watchlist` - избранные пары и текущий сигнал.
- `Trades` - Active / Journal / Analytics.
- `Settings` - биржи, риск-профиль, уведомления, таймфреймы.

## Запуск

```powershell
cd frontend
npm install
npm run dev
```

Если `npm` не виден в текущем PowerShell:

```powershell
cd frontend
& "C:\Program Files\nodejs\npm.cmd" install
& "C:\Program Files\nodejs\npm.cmd" run dev
```

Открыть:

```text
http://127.0.0.1:5173
```

Backend должен быть запущен на:

```text
http://127.0.0.1:8000
```

По умолчанию frontend обращается к `http://127.0.0.1:8000`. Если нужен другой backend URL:

```powershell
$env:VITE_API_BASE_URL="http://127.0.0.1:8000"
npm run dev
```
