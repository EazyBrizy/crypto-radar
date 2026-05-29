import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
import time
import urllib.parse
import urllib.request
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import List, Optional

import websockets

from app.schemas.candle import OHLCVCandle, Timeframe
from app.schemas.market import MarketData

logger = logging.getLogger(__name__)

BYBIT_WS_URL = "wss://stream.bybit.com/v5/public/linear"
BYBIT_API_URL = "https://api.bybit.com"
BYBIT_INSTRUMENTS_URL = "https://api.bybit.com/v5/market/instruments-info"
BYBIT_KLINE_URL = "https://api.bybit.com/v5/market/kline"
BYBIT_FEE_RATE_PATH = "/v5/account/fee-rate"
BYBIT_TICKERS_PATH = "/v5/market/tickers"
BYBIT_ORDERBOOK_PATH = "/v5/market/orderbook"
BYBIT_POSITION_LIST_PATH = "/v5/position/list"
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


class BybitApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class BybitFeeRate:
    category: str
    symbol: str | None
    maker_fee_rate: float
    taker_fee_rate: float


@dataclass(frozen=True)
class BybitInstrumentRule:
    category: str
    symbol: str
    min_order_size: float | None
    max_order_size: float | None
    min_notional: float | None
    qty_step: float | None
    tick_size: float | None
    max_leverage: int | None
    funding_interval_minutes: int | None
    raw_payload: dict


@dataclass(frozen=True)
class BybitTicker:
    category: str
    symbol: str
    bid1_price: float | None
    ask1_price: float | None
    mark_price: float | None
    funding_rate: float | None
    raw_payload: dict


@dataclass(frozen=True)
class BybitOrderBookSnapshot:
    category: str
    symbol: str
    bids: list[tuple[float, float]]
    asks: list[tuple[float, float]]
    raw_payload: dict


@dataclass(frozen=True)
class BybitPositionInfo:
    category: str
    symbol: str
    side: str | None
    size: float | None
    liquidation_price: float | None
    raw_payload: dict


def fetch_bybit_fee_rates(
    *,
    api_key: str,
    api_secret: str,
    category: str,
    symbol: str | None = None,
    base_url: str = BYBIT_API_URL,
    recv_window: int = 5_000,
    timestamp_ms: int | None = None,
    urlopen=urllib.request.urlopen,
) -> list[BybitFeeRate]:
    normalized_category = category.strip().lower()
    if normalized_category not in {"spot", "linear", "inverse", "option"}:
        raise ValueError("Bybit fee category must be spot, linear, inverse, or option")
    params = {"category": normalized_category}
    if symbol:
        params["symbol"] = LINEAR_SYMBOL_ALIASES.get(symbol.strip().upper(), symbol.strip().upper())
    query_string = urllib.parse.urlencode(params)
    timestamp = str(timestamp_ms or int(time.time() * 1000))
    recv_window_value = str(recv_window)
    signature_payload = f"{timestamp}{api_key}{recv_window_value}{query_string}"
    signature = hmac.new(
        api_secret.encode("utf-8"),
        signature_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{BYBIT_FEE_RATE_PATH}?{query_string}",
        headers={
            "X-BAPI-API-KEY": api_key,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": recv_window_value,
            "X-BAPI-SIGN": signature,
        },
        method="GET",
    )

    try:
        with urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, TimeoutError, json.JSONDecodeError) as exc:
        raise BybitApiError(f"Bybit fee-rate request failed: {exc}") from exc

    ret_code = payload.get("retCode")
    if ret_code != 0:
        raise BybitApiError(f"Bybit fee-rate request failed: {ret_code} {payload.get('retMsg')}")
    rows = payload.get("result", {}).get("list", [])
    if not isinstance(rows, list):
        return []

    rates: list[BybitFeeRate] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            row_symbol = row.get("symbol")
            rates.append(
                BybitFeeRate(
                    category=str(row.get("category") or normalized_category),
                    symbol=str(row_symbol) if row_symbol else None,
                    maker_fee_rate=float(row["makerFeeRate"]),
                    taker_fee_rate=float(row["takerFeeRate"]),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Skipping malformed Bybit fee-rate row: %s", exc)
    return rates


def fetch_bybit_instrument_rules(
    *,
    category: str = "linear",
    symbol: str | None = None,
    base_url: str = BYBIT_API_URL,
    urlopen=urllib.request.urlopen,
) -> list[BybitInstrumentRule]:
    normalized_category = _normalize_public_category(category)
    params = {"category": normalized_category, "limit": "1000"}
    if symbol:
        params["symbol"] = _normalize_symbol(symbol)

    rules: list[BybitInstrumentRule] = []
    cursor = ""
    while True:
        request_params = dict(params)
        if cursor:
            request_params["cursor"] = cursor
        payload = _get_public_json(
            base_url=base_url,
            path="/v5/market/instruments-info",
            params=request_params,
            urlopen=urlopen,
            label="instruments-info",
        )
        result = payload.get("result", {})
        rows = result.get("list", [])
        if not isinstance(rows, list):
            break
        for row in rows:
            if isinstance(row, dict):
                parsed = _parse_instrument_rule(normalized_category, row)
                if parsed is not None:
                    rules.append(parsed)
        cursor = result.get("nextPageCursor") or ""
        if symbol or not cursor:
            break
    return rules


def fetch_bybit_tickers(
    *,
    category: str = "linear",
    symbol: str | None = None,
    base_url: str = BYBIT_API_URL,
    urlopen=urllib.request.urlopen,
) -> list[BybitTicker]:
    normalized_category = _normalize_public_category(category)
    params = {"category": normalized_category}
    if symbol:
        params["symbol"] = _normalize_symbol(symbol)
    payload = _get_public_json(
        base_url=base_url,
        path=BYBIT_TICKERS_PATH,
        params=params,
        urlopen=urlopen,
        label="tickers",
    )
    rows = payload.get("result", {}).get("list", [])
    if not isinstance(rows, list):
        return []
    tickers: list[BybitTicker] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_symbol = row.get("symbol")
        if not isinstance(row_symbol, str):
            continue
        tickers.append(
            BybitTicker(
                category=normalized_category,
                symbol=row_symbol,
                bid1_price=_float_or_none(row.get("bid1Price")),
                ask1_price=_float_or_none(row.get("ask1Price")),
                mark_price=_float_or_none(row.get("markPrice")),
                funding_rate=_float_or_none(row.get("fundingRate")),
                raw_payload=row,
            )
        )
    return tickers


def fetch_bybit_orderbook(
    *,
    category: str = "linear",
    symbol: str,
    limit: int = 50,
    base_url: str = BYBIT_API_URL,
    urlopen=urllib.request.urlopen,
) -> BybitOrderBookSnapshot:
    normalized_category = _normalize_public_category(category)
    payload = _get_public_json(
        base_url=base_url,
        path=BYBIT_ORDERBOOK_PATH,
        params={
            "category": normalized_category,
            "symbol": _normalize_symbol(symbol),
            "limit": str(limit),
        },
        urlopen=urlopen,
        label="orderbook",
    )
    result = payload.get("result", {})
    if not isinstance(result, dict):
        result = {}
    return BybitOrderBookSnapshot(
        category=normalized_category,
        symbol=str(result.get("s") or _normalize_symbol(symbol)),
        bids=_parse_book_side(result.get("b")),
        asks=_parse_book_side(result.get("a")),
        raw_payload=result,
    )


def fetch_bybit_positions(
    *,
    api_key: str,
    api_secret: str,
    category: str = "linear",
    symbol: str | None = None,
    base_url: str = BYBIT_API_URL,
    recv_window: int = 5_000,
    timestamp_ms: int | None = None,
    urlopen=urllib.request.urlopen,
) -> list[BybitPositionInfo]:
    normalized_category = _normalize_public_category(category)
    params = {"category": normalized_category}
    if symbol:
        params["symbol"] = _normalize_symbol(symbol)
    payload = _get_private_json(
        api_key=api_key,
        api_secret=api_secret,
        base_url=base_url,
        path=BYBIT_POSITION_LIST_PATH,
        params=params,
        recv_window=recv_window,
        timestamp_ms=timestamp_ms,
        urlopen=urlopen,
        label="position-list",
    )
    rows = payload.get("result", {}).get("list", [])
    if not isinstance(rows, list):
        return []
    positions: list[BybitPositionInfo] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_symbol = row.get("symbol")
        if not isinstance(row_symbol, str):
            continue
        positions.append(
            BybitPositionInfo(
                category=normalized_category,
                symbol=row_symbol,
                side=str(row["side"]) if row.get("side") else None,
                size=_float_or_none(row.get("size")),
                liquidation_price=_float_or_none(row.get("liqPrice")),
                raw_payload=row,
            )
        )
    return positions


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


def _normalize_public_category(category: str) -> str:
    normalized = category.strip().lower()
    if normalized not in {"spot", "linear", "inverse", "option"}:
        raise ValueError("Bybit category must be spot, linear, inverse, or option")
    return normalized


def _normalize_symbol(symbol: str) -> str:
    value = symbol.strip().upper()
    return LINEAR_SYMBOL_ALIASES.get(value, value)


def _get_public_json(
    *,
    base_url: str,
    path: str,
    params: dict[str, str],
    urlopen,
    label: str,
) -> dict:
    url = f"{base_url.rstrip('/')}{path}?{urllib.parse.urlencode(params)}"
    try:
        with urlopen(url, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, TimeoutError, json.JSONDecodeError) as exc:
        raise BybitApiError(f"Bybit {label} request failed: {exc}") from exc
    ret_code = payload.get("retCode")
    if ret_code != 0:
        raise BybitApiError(f"Bybit {label} request failed: {ret_code} {payload.get('retMsg')}")
    return payload


def _get_private_json(
    *,
    api_key: str,
    api_secret: str,
    base_url: str,
    path: str,
    params: dict[str, str],
    recv_window: int,
    timestamp_ms: int | None,
    urlopen,
    label: str,
) -> dict:
    query_string = urllib.parse.urlencode(params)
    timestamp = str(timestamp_ms or int(time.time() * 1000))
    recv_window_value = str(recv_window)
    signature_payload = f"{timestamp}{api_key}{recv_window_value}{query_string}"
    signature = hmac.new(
        api_secret.encode("utf-8"),
        signature_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}?{query_string}",
        headers={
            "X-BAPI-API-KEY": api_key,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": recv_window_value,
            "X-BAPI-SIGN": signature,
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, TimeoutError, json.JSONDecodeError) as exc:
        raise BybitApiError(f"Bybit {label} request failed: {exc}") from exc
    ret_code = payload.get("retCode")
    if ret_code != 0:
        raise BybitApiError(f"Bybit {label} request failed: {ret_code} {payload.get('retMsg')}")
    return payload


def _parse_instrument_rule(
    category: str,
    row: dict,
) -> BybitInstrumentRule | None:
    symbol = row.get("symbol")
    if not isinstance(symbol, str) or not symbol:
        return None
    lot_filter = row.get("lotSizeFilter")
    price_filter = row.get("priceFilter")
    leverage_filter = row.get("leverageFilter")
    lot_filter = lot_filter if isinstance(lot_filter, dict) else {}
    price_filter = price_filter if isinstance(price_filter, dict) else {}
    leverage_filter = leverage_filter if isinstance(leverage_filter, dict) else {}
    min_notional = _float_or_none(
        lot_filter.get("minNotionalValue")
        or lot_filter.get("minOrderAmt")
        or lot_filter.get("minOrderValue")
    )
    return BybitInstrumentRule(
        category=category,
        symbol=symbol,
        min_order_size=_float_or_none(
            lot_filter.get("minOrderQty")
            or lot_filter.get("minTradingQty")
            or row.get("minTradeQty")
        ),
        max_order_size=_float_or_none(
            lot_filter.get("maxOrderQty")
            or lot_filter.get("maxTradingQty")
            or row.get("maxTradeQty")
        ),
        min_notional=min_notional,
        qty_step=_float_or_none(lot_filter.get("qtyStep") or row.get("qtyStep")),
        tick_size=_float_or_none(price_filter.get("tickSize") or row.get("tickSize")),
        max_leverage=_int_or_none(leverage_filter.get("maxLeverage")),
        funding_interval_minutes=_int_or_none(row.get("fundingInterval")),
        raw_payload=row,
    )


def _parse_book_side(value: object) -> list[tuple[float, float]]:
    if not isinstance(value, list):
        return []
    levels: list[tuple[float, float]] = []
    for level in value:
        if not isinstance(level, list) or len(level) < 2:
            continue
        price = _float_or_none(level[0])
        size = _float_or_none(level[1])
        if price is not None and size is not None:
            levels.append((price, size))
    return levels


def _float_or_none(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: object) -> int | None:
    parsed = _float_or_none(value)
    return int(parsed) if parsed is not None else None


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
