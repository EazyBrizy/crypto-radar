from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ForwardStrategyTestDeploymentContractTest(unittest.TestCase):
    def test_backend_docs_assign_forward_runtime_to_durable_worker_not_lifespan(self) -> None:
        backend_doc = (ROOT / "docs" / "BACKEND.md").read_text(encoding="utf-8")

        self.assertNotIn("The forward strategy-test worker is lifespan-managed", backend_doc)
        self.assertIn("durable `strategy-test-worker`", backend_doc)
        self.assertIn("FastAPI `/health` root endpoint reports no in-process forward worker", backend_doc)

    def test_docker_app_and_dev_profiles_have_one_strategy_test_worker_service(self) -> None:
        compose = (ROOT / "infra" / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertEqual(compose.count("strategy-test-worker:"), 1)
        self.assertIn('profiles: ["app", "dev"]', compose)
        self.assertIn('command: ["python", "-m", "app.workers.strategy_test_worker"]', compose)
        self.assertIn('CMD ["gunicorn", "app.main:app"', (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8"))
        self.assertNotIn("app.workers.forward_strategy_test_worker", compose)

    def test_local_dev_script_starts_durable_strategy_test_worker(self) -> None:
        script = (ROOT / "scripts" / "dev.ps1").read_text(encoding="utf-8")

        self.assertIn('-Name "strategy-test-worker"', script)
        self.assertIn('"app.workers.strategy_test_worker"', script)
        self.assertIn("-FilePath $BackendPython", script)
        self.assertIn("-WorkingDirectory $BackendDir", script)
        self.assertIn("-Environment $backendEnv", script)
        self.assertLess(
            script.index("Invoke-BackendCommand `"),
            script.index('-Name "strategy-test-worker"'),
        )

    def test_docs_explain_local_dev_strategy_test_worker_contract(self) -> None:
        workers_doc = (ROOT / "docs" / "WORKERS.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("local dev", workers_doc.lower())
        self.assertIn("strategy-test-worker", workers_doc)
        self.assertIn("One-Command Dev", readme)
        self.assertIn("strategy-test-worker", readme)
        self.assertIn("Strategy Testing without the worker stays queued", readme)
        self.assertIn("waiting_for_market_data", readme)


if __name__ == "__main__":
    unittest.main()
