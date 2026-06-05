import unittest
from unittest.mock import patch

from app.core.migrations import MigrationStatus, warn_if_migrations_outdated


class MigrationStartupCheckTest(unittest.TestCase):
    def test_status_matches_script_heads(self) -> None:
        status = MigrationStatus(
            current_heads=("202606050002",),
            script_heads=("202606050002",),
        )

        self.assertTrue(status.is_at_head)

    def test_warns_when_database_is_not_at_head(self) -> None:
        status = MigrationStatus(
            current_heads=("202606050001",),
            script_heads=("202606050002",),
        )

        with (
            patch("app.core.migrations.check_migration_status", return_value=status),
            self.assertLogs("app.core.migrations", level="WARNING") as logs,
        ):
            warn_if_migrations_outdated()

        self.assertIn("not at Alembic head", logs.output[0])
        self.assertIn("alembic upgrade head", logs.output[0])

    def test_warns_when_status_check_cannot_run(self) -> None:
        with (
            patch("app.core.migrations.check_migration_status", side_effect=RuntimeError("db down")),
            self.assertLogs("app.core.migrations", level="WARNING") as logs,
        ):
            warn_if_migrations_outdated()

        self.assertIn("Could not verify Alembic migration status", logs.output[0])
        self.assertIn("alembic current", logs.output[0])


if __name__ == "__main__":
    unittest.main()
