.PHONY: smoke-virtual migrate migrations-current migrations-heads

migrate:
	powershell -ExecutionPolicy Bypass -Command "Push-Location backend; ..\\.venv\\Scripts\\python.exe -m alembic upgrade head; Pop-Location"

migrations-current:
	powershell -ExecutionPolicy Bypass -Command "Push-Location backend; ..\\.venv\\Scripts\\python.exe -m alembic current; Pop-Location"

migrations-heads:
	powershell -ExecutionPolicy Bypass -Command "Push-Location backend; ..\\.venv\\Scripts\\python.exe -m alembic heads; Pop-Location"

smoke-virtual:
	powershell -ExecutionPolicy Bypass -File ./scripts/smoke_virtual.ps1
