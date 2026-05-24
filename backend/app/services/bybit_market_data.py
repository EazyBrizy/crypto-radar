import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from typing import List, Optional

import websockets

from app.models.schemas import MarketData

logger = logging.getLogger(__name__)

BYBIT_WS_URL = "wss://stream.bybit.com/v5/public/linear"
DEFAULT_SYMBOLS = ("DOGEUSDT",)
LINEAR_SYMBOL_ALIASES = {"PEPEUSDT": "1000PEPEUSDT"}
RECONNECT_DELAY_SEC = 5.0
HEARTBEAT_INTERVAL_SEC = 20.0


class BybitMarketDataService:
    """Collects public trade stream data from Bybit linear WebSocket."""

    def __init__(
        self,
        symbols: Optional[List[str]] = None,
        reconnect_delay: float = RECONNECT_DELAY_SEC,
    ) -> None:
        raw_symbols = list(symbols) if symbols else list(DEFAULT_SYMBOLS)
        normalized = [
            LINEAR_SYMBOL_ALIASES.get(symbol, symbol) for symbol in raw_symbols
        ]
        self._symbols = list(dict.fromkeys(normalized))
        self._reconnect_delay = reconnect_delay

    def _topics(self) -> List[str]:
        return [f"publicTrade.{symbol}" for symbol in self._symbols]

    async def connect(self) -> websockets.WebSocketClientProtocol:
        ws = await websockets.connect(
            BYBIT_WS_URL,
            ping_interval=HEARTBEAT_INTERVAL_SEC,
            ping_timeout=HEARTBEAT_INTERVAL_SEC,
        )
        subscribed: List[str] = []
        for topic in self._topics():
            await ws.send(json.dumps({"op": "subscribe", "args": [topic]}))
            subscribed.append(topic)
        logger.info(
            "Bybit WebSocket connection established; subscribed to %s",
            ", ".join(subscribed),
        )
        return ws

    def _build_market_data(self, trade: dict) -> Optional[MarketData]:
        try:
            return MarketData(
                symbol=trade["s"],
                price=float(trade["p"]),
                volume=float(trade["v"]),
                timestamp=int(trade["T"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Skipping malformed trade entry: %s", exc)
            return None

    def _parse_message(self, raw: str) -> List[MarketData]:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON from Bybit: %s", raw[:200])
            return []

        op = payload.get("op")
        if op == "subscribe":
            if payload.get("success") is False:
                logger.error(
                    "Bybit subscribe failed: %s — check symbol exists on linear perpetuals",
                    payload.get("ret_msg", payload),
                )
            return []
        if op in ("ping", "pong"):
            return []

        topic = payload.get("topic", "")
        if not topic.startswith("publicTrade."):
            return []

        data = payload.get("data")
        if not isinstance(data, list):
            return []

        trades: List[MarketData] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            market_data = self._build_market_data(item)
            if market_data is not None:
                trades.append(market_data)
        return trades

    async def _send_heartbeat(
        self,
        ws: websockets.WebSocketClientProtocol,
        stop: asyncio.Event,
    ) -> None:
        while not stop.is_set():
            await asyncio.sleep(HEARTBEAT_INTERVAL_SEC)
            if stop.is_set():
                return
            try:
                await ws.send(json.dumps({"op": "ping"}))
            except Exception as exc:
                logger.warning("Bybit heartbeat send failed: %s", exc)
                return

    async def listen(self) -> AsyncIterator[MarketData]:
        reconnect_attempt = 0
        while True:
            ws: Optional[websockets.WebSocketClientProtocol] = None
            stop = asyncio.Event()
            heartbeat_task: Optional[asyncio.Task[None]] = None
            try:
                ws = await self.connect()
                heartbeat_task = asyncio.create_task(
                    self._send_heartbeat(ws, stop)
                )
                async for message in ws:
                    for market_data in self._parse_message(message):
                        yield market_data
            except asyncio.CancelledError:
                raise
            except websockets.ConnectionClosed as exc:
                logger.warning("Bybit WebSocket disconnected: %s", exc)
            except Exception as exc:
                logger.exception("Bybit WebSocket error: %s", exc)
            finally:
                stop.set()
                if heartbeat_task is not None:
                    heartbeat_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await heartbeat_task
                if ws is not None:
                    await ws.close()

            reconnect_attempt += 1
            logger.info(
                "Bybit reconnect attempt %d in %.1f seconds",
                reconnect_attempt,
                self._reconnect_delay,
            )
            await asyncio.sleep(self._reconnect_delay)
