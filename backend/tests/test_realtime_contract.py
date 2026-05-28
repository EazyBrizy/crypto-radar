import json
import unittest

from starlette.websockets import WebSocketDisconnect

from app.api.v1.realtime import realtime_websocket


class JsonCheckingWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def accept(self) -> None:
        return None

    async def send_json(self, data: dict) -> None:
        json.dumps(data)
        self.sent.append(data)

    async def receive_json(self) -> dict:
        raise WebSocketDisconnect()


class RealtimeContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_websocket_connection_message_uses_realtime_event_envelope(self) -> None:
        websocket = JsonCheckingWebSocket()

        await realtime_websocket(websocket)

        event = websocket.sent[0]
        self.assertTrue(event["id"].startswith("evt_"))
        self.assertEqual(event["type"], "connection.heartbeat")
        self.assertEqual(event["version"], 1)
        self.assertIsInstance(event["timestamp"], str)
        self.assertEqual(event["payload"]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
