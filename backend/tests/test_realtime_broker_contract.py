import asyncio
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


async def _wait_for_message(websocket: JsonCollectingWebSocket) -> None:
    while not websocket.sent:
        await asyncio.sleep(0)


if __name__ == "__main__":
    unittest.main()
