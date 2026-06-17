import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
DEV_SCRIPT = ROOT_DIR / "scripts" / "dev.ps1"


class DevScriptContractTest(unittest.TestCase):
    def test_default_run_starts_infra_before_migrations(self) -> None:
        script = DEV_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("[switch]$NoInfra", script)
        self.assertIn("$StartInfra = $WithInfra -or -not $NoInfra", script)
        self.assertIn(
            'Invoke-DockerCompose -Arguments @("--profile", "infra", "up", "-d", "postgres", "redis", "nats", "clickhouse")',
            script,
        )
        self.assertLess(
            script.index("if ($StartInfra)"),
            script.index("Invoke-BackendCommand `"),
        )

    def test_default_run_clears_docker_dev_app_containers_before_port_checks(self) -> None:
        script = DEV_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("function Remove-DockerDevAppContainers", script)
        self.assertIn('"backend-dev", "frontend-dev", "strategy-test-worker"', script)
        self.assertLess(
            script.index("Remove-DockerDevAppContainers"),
            script.index("if (Test-PortBusy -Port $BackendPort)"),
        )


if __name__ == "__main__":
    unittest.main()
