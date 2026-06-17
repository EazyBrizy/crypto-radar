import re
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT_DIR / "infra" / "docker-compose.yml"
SMOKE_SCRIPT = ROOT_DIR / "scripts" / "smoke_strategy_tests.ps1"


class StrategySmokeComposeContractTest(unittest.TestCase):
    def test_docker_dev_services_do_not_claim_local_app_ports_by_default(self) -> None:
        compose = COMPOSE_FILE.read_text(encoding="utf-8")

        self.assertIn('"${FRONTEND_DEV_HOST_PORT:-13000}:3000"', compose)
        self.assertIn('"${BACKEND_DEV_HOST_PORT:-18000}:8000"', compose)

    def test_strategy_smoke_uses_non_default_dev_ports(self) -> None:
        script = SMOKE_SCRIPT.read_text(encoding="utf-8")

        self.assertIn('SMOKE_FRONTEND_DEV_HOST_PORT" -Default "13000"', script)
        self.assertIn('SMOKE_BACKEND_DEV_HOST_PORT" -Default "18000"', script)
        self.assertIn("$env:FRONTEND_DEV_HOST_PORT", script)
        self.assertIn("$env:BACKEND_DEV_HOST_PORT", script)

    def test_strategy_smoke_removes_app_containers_after_run(self) -> None:
        script = SMOKE_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("function Remove-SmokeAppContainers", script)
        self.assertIn('"rm", "-f", "-s", "backend-dev", "strategy-test-worker"', script)
        self.assertRegex(
            script,
            re.compile(r"finally\s*\{(?s:.)*Remove-SmokeAppContainers"),
        )


if __name__ == "__main__":
    unittest.main()
