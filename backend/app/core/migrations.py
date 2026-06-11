import logging
from dataclasses import dataclass
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from app.core.database import engine

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MigrationStatus:
    current_heads: tuple[str, ...]
    script_heads: tuple[str, ...]

    @property
    def is_at_head(self) -> bool:
        return set(self.current_heads) == set(self.script_heads)


def check_migration_status() -> MigrationStatus:
    script_heads = _script_heads()
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        current_heads = tuple(sorted(context.get_current_heads()))
    return MigrationStatus(
        current_heads=current_heads,
        script_heads=script_heads,
    )


def warn_if_migrations_outdated() -> None:
    try:
        status = check_migration_status()
    except Exception as exc:
        logger.warning(
            "Could not verify Alembic migration status at startup: %s. "
            "Run `cd backend; ..\\.venv\\Scripts\\python.exe -m alembic current` "
            "and compare with `cd backend; ..\\.venv\\Scripts\\python.exe -m alembic heads`.",
            exc,
        )
        return

    if status.is_at_head:
        return

    logger.warning(
        "Database migrations are not at Alembic head: current=%s head=%s. "
        "Run `cd backend; ..\\.venv\\Scripts\\python.exe -m alembic upgrade head` before local checks.",
        _format_heads(status.current_heads),
        _format_heads(status.script_heads),
    )


def _script_heads() -> tuple[str, ...]:
    config = Config(str(_alembic_ini_path()))
    script = ScriptDirectory.from_config(config)
    return tuple(sorted(script.get_heads()))


def _alembic_ini_path() -> Path:
    return Path(__file__).resolve().parents[2] / "alembic.ini"


def _format_heads(heads: tuple[str, ...]) -> str:
    return ",".join(heads) if heads else "<none>"
