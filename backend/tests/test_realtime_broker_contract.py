import asyncio
import inspect
import unittest

from app.services.message_broker import RedisMessageBroker
from app.services.realtime_gateway import RealtimeGateway
from app.services.realtime_events import create_realtime_event


class JsonCollectingWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def accept(self) -> None:
        return None

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)


class RealtimeBrokerContractTest(unittest.IsolatedAsyncioTestCase):
    def test_broker_publish_does_not_fallback_to_default_str(self) -> None:
        source = inspect.getsource(RedisMessageBroker.publish)

        self.assertIn("encode_realtime_event", source)
        self.assertNotIn("default=str", source)

    async def test_gateway_pushes_broker_events_to_subscribed_clients(self) -> None:
        broker = RedisMessageBroker(enable_redis=False)
        gateway = RealtimeGateway()
        websocket = JsonCollectingWebSocket()

        gateway.start_broker_bridge(broker)
        await gateway.connect_websocket(websocket)
        await broker.publish(
            create_realtime_event(
                "signal.created",
                {
                    "signal": {"id": "sig_test"},
                    "signalId": "sig_test",
                },
            )
        )

        await asyncio.wait_for(_wait_for_message(websocket), timeout=1)
        await gateway.stop_broker_bridge(broker)

        self.assertEqual(websocket.sent[0]["type"], "signal.created")
        self.assertTrue(websocket.sent[0]["id"].startswith("evt_"))
        self.assertEqual(websocket.sent[0]["version"], 1)
        self.assertIsInstance(websocket.sent[0]["timestamp"], str)
        self.assertEqual(websocket.sent[0]["payload"]["signalId"], "sig_test")

    async def test_gateway_pushes_broker_events_published_from_worker_thread(self) -> None:
        broker = RedisMessageBroker(enable_redis=False)
        gateway = RealtimeGateway()
        websocket = JsonCollectingWebSocket()

        gateway.start_broker_bridge(broker)
        await gateway.connect_websocket(websocket)
        await asyncio.to_thread(
            lambda: asyncio.run(
                broker.publish(
                    create_realtime_event(
                        "pending_entry.updated",
                        {
                            "pending_entry_id": "intent_test",
                            "signal_id": "sig_test",
                            "user_id": "user_test",
                            "status": "triggered",
                            "mode": "virtual",
                            "reason": None,
                            "message": None,
                            "updated_at": "2026-06-04T10:00:00+00:00",
                        },
                    )
                )
            )
        )

        await asyncio.wait_for(_wait_for_message(websocket), timeout=1)
        await gateway.stop_broker_bridge(broker)

        self.assertEqual(websocket.sent[0]["type"], "pending_entry.updated")
        self.assertEqual(websocket.sent[0]["payload"]["pending_entry_id"], "intent_test")


async def _wait_for_message(websocket: JsonCollectingWebSocket) -> None:
    while not websocket.sent:
        await asyncio.sleep(0)


if __name__ == "__main__":
    unittest.main()
