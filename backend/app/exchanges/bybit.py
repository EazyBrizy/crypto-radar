import asyncio
import contextlib
import json
import logging
import urllib.parse
import urllib.request
from collections.abc import AsyncIterator
from typing import List, Optional

import websockets

from app.schemas.candle import OHLCVCandle, Timeframe
from app.schemas.market import MarketData

logger = logging.getLogger(__name__)

BYBIT_WS_URL = "wss://stream.bybit.com/v5/public/linear"
BYBIT_INSTRUMENTS_URL = "https://api.bybit.com/v5/market/instruments-info"
BYBIT_KLINE_URL = "https://api.bybit.com/v5/market/kline"
DEFAULT_SYMBOLS = ("DOGEUSDT",)
LINEAR_SYMBOL_ALIASES = {"PEPEUSDT": "1000PEPEUSDT"}
RECONNECT_DELAY_SEC = 5.0
MAX_RECONNECT_DELAY_SEC = 60.0
HEARTBEAT_INTERVAL_SEC = 20.0
KLINE_INTERVAL_BY_TIMEFRAME: dict[Timeframe, str] = {
    "1m": "1",
    "5m": "5",
    "15m": "15",
    "1h": "60",
    "4h": "240",
    "1d": "D",
}
TIMEFRAME_MS: dict[Timeframe, int] = {
    "1m": 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}


def fetch_bybit_linear_symbols() -> list[str]:
    symbols: list[str] = []
    cursor = ""

    while True:
        params = {
            "category": "linear",
            "limit": "1000",
        }
        if cursor:
            params["cursor"] = cursor
        url = f"{BYBIT_INSTRUMENTS_URL}?{urllib.parse.urlencode(params)}"

        with urllib.request.urlopen(url, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))

        result = payload.get("result", {})
        instruments = result.get("list", [])
        if not isinstance(instruments, list):
            break

        for instrument in instruments:
            if not isinstance(instrument, dict):
                continue
            symbol = instrument.get("symbol")
            quote_coin = instrument.get("quoteCoin")
            status = instrument.get("status")
            if (
                isinstance(symbol, str)
                and symbol.endswith("USDT")
                and quote_coin == "USDT"
                and status == "Trading"
            ):
                symbols.append(symbol)

        cursor = result.get("nextPageCursor") or ""
        if not cursor:
            break

    return list(dict.fromkeys(symbols))


def fetch_bybit_klines(
    symbol: str,
    timeframe: Timeframe,
    limit: int = 250,
) -> list[OHLCVCandle]:
    interval = KLINE_INTERVAL_BY_TIMEFRAME[timeframe]
    params = {
        "category": "linear",
        "symbol": LINEAR_SYMBOL_ALIASES.get(symbol, symbol),
        "interval": interval,
        "limit": str(limit),
    }
    url = f"{BYBIT_KLINE_URL}?{urllib.parse.urlencode(params)}"

    with urllib.request.urlopen(url, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))

    rows = payload.get("result", {}).get("list", [])
    if not isinstance(rows, list):
        return []

    candles: list[OHLCVCandle] = []
    timeframe_ms = TIMEFRAME_MS[timeframe]
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            continue
        try:
            open_time = int(row[0])
            candles.append(
                OHLCVCandle(
                    exchange="bybit",
                    symbol=params["symbol"],
                    timeframe=timeframe,
                    open_time=open_time,
                    close_time=open_time + timeframe_ms - 1,
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                    trades=0,
                    is_closed=True,
                )
            )
        except (TypeError, ValueError) as exc:
            logger.warning("Skipping malformed Bybit kline for %s: %s", symbol, exc)

    return sorted(candles, key=lambda candle: candle.open_time)


class BybitAdapter:
    """Собирает публичный поток сделок Bybit linear через WebSocket."""

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

    async def get_symbols(self) -> list[str]:
        return list(self._symbols)

    def stream_trades(self, symbols: list[str]) -> AsyncIterator[MarketData]:
        return self.listen()

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
                exchange="bybit",
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
                    "Bybit subscribe failed: %s - check symbol exists on linear perpetuals",
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
            except (ConnectionResetError, OSError, TimeoutError) as exc:
                logger.warning("Bybit WebSocket network disconnect: %s", exc)
            except Exception as exc:
                logger.exception("Bybit WebSocket error: %s", exc)
            finally:
                stop.set()
                if heartbeat_task is not None:
                    heartbeat_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await heartbeat_task
                if ws is not None:
                    with contextlib.suppress(Exception):
                        await ws.close()

            reconnect_attempt += 1
            reconnect_delay = min(
                self._reconnect_delay * (2 ** min(reconnect_attempt - 1, 4)),
                MAX_RECONNECT_DELAY_SEC,
            )
            logger.info(
                "Bybit reconnect attempt %d in %.1f seconds",
                reconnect_attempt,
                reconnect_delay,
            )
            await asyncio.sleep(reconnect_delay)
