# PostgreSQL Migrations

Alembic migrations own PostgreSQL schema changes. Runtime market data and
analytics tables belong in ClickHouse DDL under `infra/clickhouse/init`.

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m alembic -c backend\alembic.ini history
.\.venv\Scripts\python.exe -m alembic -c backend\alembic.ini upgrade head
.\.venv\Scripts\python.exe -m alembic -c backend\alembic.ini revision --autogenerate -m "add table name"
```

Or run from `backend`:

```powershell
..\.venv\Scripts\python.exe -m alembic -c alembic.ini history
..\.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head
```

The migration environment reads `DATABASE_URL` through `app.core.config`, so the
same `.env` value used by the backend is used by Alembic.
