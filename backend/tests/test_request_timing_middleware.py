import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.request_timing import add_request_timing_middleware


class RequestTimingMiddlewareTest(unittest.TestCase):
    def test_middleware_adds_request_id_and_response_time_headers(self) -> None:
        client = TestClient(_app())

        response = client.get("/timed", headers={"X-Request-Id": "req-test"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        self.assertEqual(response.headers["X-Request-Id"], "req-test")
        self.assertGreaterEqual(float(response.headers["X-Response-Time-Ms"]), 0)

    def test_slow_endpoint_emits_timing_without_breaking_response(self) -> None:
        client = TestClient(_app())
        original_threshold = settings.fastapi_slow_request_ms
        settings.fastapi_slow_request_ms = 0
        try:
            with self.assertLogs("app.request_timing", level="WARNING") as logs:
                response = client.get("/slow?api_key=secret-value")
        finally:
            settings.fastapi_slow_request_ms = original_threshold

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"slow": True})
        log_output = "\n".join(logs.output)
        self.assertIn("Slow FastAPI request: GET /slow status=200", log_output)
        self.assertIn("duration_ms=", log_output)
        self.assertIn("request_id=", log_output)
        self.assertNotIn("api_key", log_output)
        self.assertNotIn("secret-value", log_output)


def _app() -> FastAPI:
    app = FastAPI()
    add_request_timing_middleware(app)

    @app.get("/timed")
    async def timed() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/slow")
    async def slow() -> dict[str, bool]:
        return {"slow": True}

    return app


if __name__ == "__main__":
    unittest.main()
