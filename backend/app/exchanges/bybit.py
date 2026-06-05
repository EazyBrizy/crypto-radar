import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
import time
import urllib.parse
import urllib.request
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from typing import Any, List, Optional

import websockets

from app.core.config import settings as default_settings
from app.schemas.candle import OHLCVCandle, Timeframe
from app.schemas.market import MarketData, TradeSide
from app.schemas.trade import ExecutionPlannedOrder

logger = logging.getLogger(__name__)

BYBIT_WS_URL = "wss://stream.bybit.com/v5/public/linear"
BYBIT_API_URL = "https://api.bybit.com"
BYBIT_INSTRUMENTS_URL = "https://api.bybit.com/v5/market/instruments-info"
BYBIT_KLINE_URL = "https://api.bybit.com/v5/market/kline"
BYBIT_FEE_RATE_PATH = "/v5/account/fee-rate"
BYBIT_WALLET_BALANCE_PATH = "/v5/account/wallet-balance"
BYBIT_TICKERS_PATH = "/v5/market/tickers"
BYBIT_ORDERBOOK_PATH = "/v5/market/orderbook"
BYBIT_POSITION_LIST_PATH = "/v5/position/list"
BYBIT_ORDER_CREATE_PATH = "/v5/order/create"
BYBIT_ORDER_REALTIME_PATH = "/v5/order/realtime"
BYBIT_TRADING_STOP_PATH = "/v5/position/trading-stop"
BYBIT_EXECUTION_LIST_PATH = "/v5/execution/list"
LIVE_ORDER_PLACEMENT_DISABLED_REASON = "Live order placement is disabled by backend configuration."
BYBIT_MAINNET_ORDER_PLACEMENT_DISABLED_REASON = (
    "Bybit mainnet order placement is disabled by backend configuration."
)
BYBIT_TESTNET_API_URL = "https://api-testnet.bybit.com"
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
class BybitCoinBalance:
    coin: str
    equity: Decimal | None
    usd_value: Decimal | None
    wallet_balance: Decimal | None
    available_to_withdraw: Decimal | None
    locked: Decimal | None
    borrow_amount: Decimal | None
    accrued_interest: Decimal | None
    total_order_im: Decimal | None
    total_position_im: Decimal | None
    total_position_mm: Decimal | None
    unrealised_pnl: Decimal | None
    raw_payload: Mapping[str, Any]


@dataclass(frozen=True)
class BybitWalletBalance:
    account_type: str
    total_equity: Decimal | None
    total_wallet_balance: Decimal | None
    total_margin_balance: Decimal | None
    total_available_balance: Decimal | None
    total_initial_margin: Decimal | None
    total_maintenance_margin: Decimal | None
    total_perp_upl: Decimal | None
    coins: tuple[BybitCoinBalance, ...]
    raw_payload: Mapping[str, Any]


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
class BybitInstrumentInfo:
    symbol: str
    category: str
    status: str | None
    base_coin: str | None
    quote_coin: str | None
    contract_type: str | None
    launch_time: int | None
    delivery_time: int | None
    price_filter: dict[str, Any]
    lot_size_filter: dict[str, Any]
    leverage_filter: dict[str, Any]
    raw_payload: dict[str, Any]


@dataclass(frozen=True)
class BybitTicker:
    category: str
    symbol: str
    bid1_price: float | None
    ask1_price: float | None
    mark_price: float | None
    funding_rate: float | None
    volume_24h: float | None
    turnover_24h: float | None
    raw_payload: dict
    open_interest: float | None = None
    open_interest_value: float | None = None


@dataclass(frozen=True)
class BybitUniverseInstrument:
    instrument: BybitInstrumentInfo
    ticker: BybitTicker | None
    symbol: str
    category: str
    status: str | None
    base_coin: str | None
    quote_coin: str | None
    contract_type: str | None
    launch_time: int | None
    delivery_time: int | None
    turnover_24h: Decimal | None
    volume_24h: Decimal | None
    last_price: Decimal | None
    mark_price: Decimal | None
    bid1_price: Decimal | None
    ask1_price: Decimal | None
    spread_bps: Decimal | None
    funding_rate: Decimal | None
    turnover_rank: int | None = None


@dataclass(frozen=True)
class BybitOrderBookSnapshot:
    category: str
    symbol: str
    bids: list[tuple[float, float]]
    asks: list[tuple[float, float]]
    raw_payload: dict
    timestamp_ms: int | None = None
    sequence_id: int | None = None


@dataclass(frozen=True)
class BybitPositionInfo:
    category: str
    symbol: str
    side: str | None
    size: Decimal | None
    raw_payload: dict
    entry_price: Decimal | None = None
    mark_price: Decimal | None = None
    liquidation_price: Decimal | None = None
    unrealized_pnl: Decimal | None = None
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    updated_time: int | None = None


@dataclass(frozen=True)
class BybitOrderInfo:
    category: str
    symbol: str
    side: str
    order_status: str
    order_id: str | None
    order_link_id: str | None
    order_type: str | None
    qty: Decimal | None
    cum_exec_qty: Decimal | None
    price: Decimal | None
    avg_price: Decimal | None
    trigger_price: Decimal | None
    reduce_only: bool
    created_time: int | None
    updated_time: int | None
    raw_payload: dict


@dataclass(frozen=True)
class BybitExecutionInfo:
    category: str
    symbol: str
    side: str
    exec_id: str
    order_id: str | None
    order_link_id: str | None
    exec_price: Decimal
    exec_qty: Decimal
    exec_fee: Decimal | None
    fee_currency: str | None
    is_maker: bool | None
    order_type: str | None
    exec_time: int | None
    raw_payload: dict


@dataclass(frozen=True)
class BybitOrderCreateRequest:
    category: str
    symbol: str
    side: str
    order_type: str
    qty: Decimal
    price: Decimal | None = None
    time_in_force: str = "GTC"
    order_link_id: str = ""
    reduce_only: bool = False
    take_profit: Decimal | None = None
    stop_loss: Decimal | None = None
    tp_sl_mode: str | None = None
    position_idx: int = 0


@dataclass(frozen=True)
class BybitOrderAck:
    order_id: str
    order_link_id: str
    raw_payload: Mapping[str, Any]


class BybitRealExecutionAdapter:
    """Guarded Bybit V5 real execution adapter.

    The adapter is live-capable only after backend feature flags allow order
    placement. MVP execution relies on Bybit order/create native stopLoss for
    entry protection; fills remain owned by reconciliation, not by the ack.
    """

    name = "bybit_real"
    is_dry_run = False
    live_order_placement_implemented = True
    supports_bracket_orders = False
    supports_oco = False
    guarantees_protective_after_entry = True
    supports_reduce_only = True
    uses_entry_native_protection = True
    position_reconciliation_enabled = True

    def __init__(
        self,
        *,
        connection_metadata: Mapping[str, Any] | None = None,
        settings_override: Any | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
        base_url: str | None = None,
        recv_window: int = 5_000,
        timestamp_ms: int | None = None,
        urlopen=urllib.request.urlopen,
    ) -> None:
        self.connection_metadata = dict(connection_metadata or {})
        self._settings = settings_override or default_settings
        self._api_key = api_key
        self._api_secret = api_secret
        self._base_url = base_url
        self._recv_window = recv_window
        self._timestamp_ms = timestamp_ms
        self._urlopen = urlopen
        self._orders: dict[tuple[str, str, str], ExecutionPlannedOrder] = {}

    def live_order_placement_safety_reason(self) -> str | None:
        if not (
            _truthy_setting(self._settings, "enable_live_trading")
            and _truthy_setting(self._settings, "enable_bybit_live_order_placement")
        ):
            return LIVE_ORDER_PLACEMENT_DISABLED_REASON
        if not self._metadata_is_testnet() and not _truthy_setting(
            self._settings,
            "enable_bybit_mainnet_order_placement",
        ):
            return BYBIT_MAINNET_ORDER_PLACEMENT_DISABLED_REASON
        return None

    async def place_order(self, order: ExecutionPlannedOrder) -> ExecutionPlannedOrder:
        self._raise_order_placement_blocker()
        create_request = self._order_create_request(order)
        existing = self._orders.get(_planned_order_key(order))
        if existing is not None and existing.idempotency_key == order.idempotency_key:
            return existing.model_copy(
                update={"metadata": {**existing.metadata, "idempotent_replay": True}}
            )
        api_key, api_secret = self._credentials()
        ack = create_bybit_order(
            api_key=api_key,
            api_secret=api_secret,
            request=create_request,
            base_url=self._resolved_base_url(),
            recv_window=self._recv_window,
            timestamp_ms=self._timestamp_ms,
            urlopen=self._urlopen,
        )
        placed = order.model_copy(
            update={
                "status": "submitted",
                "exchange_order_id": ack.order_id,
                "filled_qty": None,
                "avg_fill_price": None,
                "remaining_qty": None,
                "fees": None,
                "metadata": {
                    **order.metadata,
                    "bybit_order_ack": {
                        "order_id": ack.order_id,
                        "order_link_id": ack.order_link_id,
                        "raw_payload": dict(ack.raw_payload),
                    },
                    "order_link_id": ack.order_link_id,
                },
            }
        )
        self._orders[_planned_order_key(placed)] = placed
        return placed

    async def place_protective_stop(self, order: ExecutionPlannedOrder) -> ExecutionPlannedOrder:
        self._raise_order_placement_blocker()
        stop_loss = _positive_decimal(order.stop_price, "stopLoss")
        take_profit = _optional_positive_decimal(order.metadata.get("native_take_profit"))
        api_key, api_secret = self._credentials()
        raw_payload = set_bybit_trading_stop(
            api_key=api_key,
            api_secret=api_secret,
            category=self._category_for_order(order),
            symbol=order.symbol,
            stop_loss=stop_loss,
            take_profit=take_profit,
            tp_sl_mode=_metadata_text(order.metadata, "tp_sl_mode") or "Full",
            position_idx=self._position_idx_for_order(order, _bybit_side(order.side)),
            base_url=self._resolved_base_url(),
            recv_window=self._recv_window,
            timestamp_ms=self._timestamp_ms,
            urlopen=self._urlopen,
        )
        placed = order.model_copy(
            update={
                "status": "submitted",
                "metadata": {
                    **order.metadata,
                    "bybit_trading_stop_ack": dict(raw_payload),
                },
            }
        )
        self._orders[_planned_order_key(placed)] = placed
        return placed

    async def place_take_profit(self, order: ExecutionPlannedOrder) -> ExecutionPlannedOrder:
        self._raise_order_placement_blocker()
        if not order.reduce_only:
            raise ValueError("Bybit take-profit order must be reduce-only.")
        if order.price is None:
            raise ValueError("Bybit take-profit order requires price.")
        take_profit_order = order.model_copy(update={"order_type": "limit"})
        return await self.place_order(take_profit_order)

    async def cancel_order(
        self,
        *,
        exchange: str,
        symbol: str,
        client_order_id: str,
    ) -> ExecutionPlannedOrder | None:
        raise NotImplementedError("Bybit real order cancellation is not implemented")

    async def replace_order(
        self,
        *,
        current_client_order_id: str,
        replacement: ExecutionPlannedOrder,
    ) -> ExecutionPlannedOrder:
        self._raise_order_placement_blocker()
        raise NotImplementedError("Bybit real order replace is not implemented")

    async def get_order(
        self,
        *,
        exchange: str,
        symbol: str,
        client_order_id: str,
    ) -> ExecutionPlannedOrder | None:
        return self._orders.get(
            (
                exchange.strip().lower(),
                symbol.strip().upper(),
                client_order_id,
            )
        )

    async def get_open_orders(
        self,
        *,
        exchange: str,
        symbol: str,
    ) -> list[ExecutionPlannedOrder]:
        exchange_key = exchange.strip().lower()
        symbol_key = symbol.strip().upper()
        return [
            order
            for key, order in self._orders.items()
            if key[0] == exchange_key
            and key[1] == symbol_key
            and order.status not in {"cancelled", "canceled", "rejected", "expired"}
        ]

    async def get_position(
        self,
        *,
        exchange: str,
        symbol: str,
    ) -> dict[str, Any] | None:
        raise NotImplementedError("Bybit real position lookup is not implemented")

    def _raise_order_placement_blocker(self) -> None:
        reason = self.live_order_placement_safety_reason()
        if reason is not None:
            raise NotImplementedError(reason)

    def _order_create_request(self, order: ExecutionPlannedOrder) -> BybitOrderCreateRequest:
        category = self._category_for_order(order)
        bybit_side = _bybit_side(order.side)
        bybit_order_type = _bybit_order_type(order.order_type)
        qty = _positive_decimal(order.quantity, "qty")
        price = None
        if bybit_order_type == "Limit":
            price = _positive_decimal(order.price, "price")
        stop_loss = _optional_positive_decimal(order.metadata.get("native_stop_loss"))
        take_profit = _optional_positive_decimal(order.metadata.get("native_take_profit"))
        if (
            order.role == "entry"
            and not order.reduce_only
            and _truthy_setting(self._settings, "require_protective_stop_for_live_entry")
            and stop_loss is None
        ):
            raise ValueError(
                "Bybit live entry requires native stopLoss when "
                "require_protective_stop_for_live_entry=true."
            )
        return BybitOrderCreateRequest(
            category=category,
            symbol=order.symbol,
            side=bybit_side,
            order_type=bybit_order_type,
            qty=qty,
            price=price,
            time_in_force=order.time_in_force or ("GTC" if bybit_order_type == "Limit" else "IOC"),
            order_link_id=order.client_order_id,
            reduce_only=order.reduce_only,
            take_profit=take_profit,
            stop_loss=stop_loss,
            tp_sl_mode=(
                _metadata_text(order.metadata, "tp_sl_mode")
                or ("Full" if stop_loss is not None or take_profit is not None else None)
            ),
            position_idx=self._position_idx_for_order(order, bybit_side),
        )

    def _category_for_order(self, order: ExecutionPlannedOrder) -> str:
        category = (
            _metadata_text(order.metadata, "category")
            or _metadata_text(self.connection_metadata, "category")
            or _metadata_text(self.connection_metadata, "position_category")
            or "linear"
        )
        return _normalize_private_category(category)

    def _position_idx_for_order(self, order: ExecutionPlannedOrder, side: str) -> int:
        raw_position_idx = (
            order.metadata.get("position_idx")
            if isinstance(order.metadata, Mapping)
            else None
        )
        if raw_position_idx is None:
            raw_position_idx = self.connection_metadata.get("position_idx")
        if raw_position_idx is not None:
            try:
                return int(raw_position_idx)
            except (TypeError, ValueError) as exc:
                raise ValueError("Bybit position_idx must be an integer.") from exc
        position_mode = (
            _metadata_text(order.metadata, "position_mode")
            or _metadata_text(self.connection_metadata, "position_mode")
            or _metadata_text(self.connection_metadata, "account_position_mode")
        )
        hedge_mode = self.connection_metadata.get("hedge_mode")
        if (
            isinstance(position_mode, str)
            and position_mode.strip().lower() in {"hedge", "hedged", "both_sides"}
        ) or _truthy_metadata_value(hedge_mode):
            return 1 if side == "Buy" else 2
        return 0

    def _credentials(self) -> tuple[str, str]:
        api_key = (self._api_key or getattr(self._settings, "bybit_api_key", "") or "").strip()
        api_secret = (self._api_secret or getattr(self._settings, "bybit_secret", "") or "").strip()
        if not api_key or not api_secret:
            raise ValueError("Bybit live order placement requires api_key and api_secret.")
        return api_key, api_secret

    def _resolved_base_url(self) -> str:
        if self._base_url:
            return self._base_url.rstrip("/")
        api_base_url = _metadata_text(self.connection_metadata, "api_base_url")
        if api_base_url:
            return api_base_url.rstrip("/")
        if self._metadata_is_testnet():
            return BYBIT_TESTNET_API_URL
        return BYBIT_API_URL

    def _metadata_is_testnet(self) -> bool:
        testnet_value = self.connection_metadata.get("testnet")
        if _truthy_metadata_value(testnet_value):
            return True
        environment = (
            self.connection_metadata.get("environment")
            or self.connection_metadata.get("network")
        )
        if isinstance(environment, str) and environment.strip().lower() == "testnet":
            return True
        return False


def _truthy_setting(settings_obj: Any, name: str) -> bool:
    value = getattr(settings_obj, name, False)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(value)


def _truthy_metadata_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled", "testnet"}
    return bool(value)


def create_bybit_order(
    *,
    api_key: str,
    api_secret: str,
    request: BybitOrderCreateRequest,
    base_url: str = BYBIT_API_URL,
    recv_window: int = 5_000,
    timestamp_ms: int | None = None,
    urlopen=urllib.request.urlopen,
) -> BybitOrderAck:
    body = _order_create_payload(request)
    payload = _post_private_json(
        api_key=api_key,
        api_secret=api_secret,
        base_url=base_url,
        path=BYBIT_ORDER_CREATE_PATH,
        body=body,
        recv_window=recv_window,
        timestamp_ms=timestamp_ms,
        urlopen=urlopen,
        label="order-create",
    )
    result = payload.get("result", {})
    result_payload: Mapping[str, Any] = result if isinstance(result, Mapping) else {}
    order_id = str(result_payload.get("orderId") or "").strip()
    order_link_id = str(result_payload.get("orderLinkId") or request.order_link_id).strip()
    if not order_id:
        raise BybitApiError("Bybit order-create response did not include orderId")
    if not order_link_id:
        raise BybitApiError("Bybit order-create response did not include orderLinkId")
    return BybitOrderAck(
        order_id=order_id,
        order_link_id=order_link_id,
        raw_payload=payload,
    )


def set_bybit_trading_stop(
    *,
    api_key: str,
    api_secret: str,
    category: str,
    symbol: str,
    stop_loss: Decimal,
    take_profit: Decimal | None = None,
    tp_sl_mode: str = "Full",
    position_idx: int = 0,
    base_url: str = BYBIT_API_URL,
    recv_window: int = 5_000,
    timestamp_ms: int | None = None,
    urlopen=urllib.request.urlopen,
) -> Mapping[str, Any]:
    body: dict[str, Any] = {
        "category": _normalize_private_category(category),
        "symbol": _normalize_private_symbol(symbol),
        "stopLoss": _decimal_to_bybit_string(_positive_decimal(stop_loss, "stopLoss")),
        "tpslMode": tp_sl_mode.strip() or "Full",
        "positionIdx": int(position_idx),
    }
    if take_profit is not None:
        body["takeProfit"] = _decimal_to_bybit_string(
            _positive_decimal(take_profit, "takeProfit")
        )
    return _post_private_json(
        api_key=api_key,
        api_secret=api_secret,
        base_url=base_url,
        path=BYBIT_TRADING_STOP_PATH,
        body=body,
        recv_window=recv_window,
        timestamp_ms=timestamp_ms,
        urlopen=urlopen,
        label="trading-stop",
    )


def fetch_bybit_orders(
    *,
    api_key: str,
    api_secret: str,
    category: str = "linear",
    symbol: str | None = None,
    order_id: str | None = None,
    order_link_id: str | None = None,
    open_only: int | None = None,
    base_url: str = BYBIT_API_URL,
    recv_window: int = 5_000,
    timestamp_ms: int | None = None,
    urlopen=urllib.request.urlopen,
) -> list[BybitOrderInfo]:
    normalized_category = _normalize_public_category(category)
    params = {"category": normalized_category, "limit": "50"}
    if symbol:
        params["symbol"] = _normalize_symbol(symbol)
    if order_id:
        params["orderId"] = order_id.strip()
    if order_link_id:
        params["orderLinkId"] = order_link_id.strip()
    if open_only is not None:
        params["openOnly"] = str(int(open_only))

    rows = _fetch_private_cursor_rows(
        api_key=api_key,
        api_secret=api_secret,
        base_url=base_url,
        path=BYBIT_ORDER_REALTIME_PATH,
        params=params,
        recv_window=recv_window,
        timestamp_ms=timestamp_ms,
        urlopen=urlopen,
        label="order-realtime",
        stop_after_first_page=bool(order_id or order_link_id),
    )
    return [_parse_bybit_order(normalized_category, row) for row in rows if isinstance(row, dict)]


def fetch_bybit_open_orders(
    *,
    api_key: str,
    api_secret: str,
    category: str = "linear",
    symbol: str | None = None,
    base_url: str = BYBIT_API_URL,
    recv_window: int = 5_000,
    timestamp_ms: int | None = None,
    urlopen=urllib.request.urlopen,
) -> list[BybitOrderInfo]:
    return fetch_bybit_orders(
        api_key=api_key,
        api_secret=api_secret,
        category=category,
        symbol=symbol,
        open_only=0,
        base_url=base_url,
        recv_window=recv_window,
        timestamp_ms=timestamp_ms,
        urlopen=urlopen,
    )


def fetch_bybit_closed_orders(
    *,
    api_key: str,
    api_secret: str,
    category: str = "linear",
    symbol: str | None = None,
    base_url: str = BYBIT_API_URL,
    recv_window: int = 5_000,
    timestamp_ms: int | None = None,
    urlopen=urllib.request.urlopen,
) -> list[BybitOrderInfo]:
    return fetch_bybit_orders(
        api_key=api_key,
        api_secret=api_secret,
        category=category,
        symbol=symbol,
        open_only=1,
        base_url=base_url,
        recv_window=recv_window,
        timestamp_ms=timestamp_ms,
        urlopen=urlopen,
    )


def fetch_bybit_executions(
    *,
    api_key: str,
    api_secret: str,
    category: str = "linear",
    symbol: str | None = None,
    order_id: str | None = None,
    order_link_id: str | None = None,
    base_url: str = BYBIT_API_URL,
    recv_window: int = 5_000,
    timestamp_ms: int | None = None,
    urlopen=urllib.request.urlopen,
) -> list[BybitExecutionInfo]:
    normalized_category = _normalize_public_category(category)
    params = {"category": normalized_category, "limit": "50"}
    if symbol:
        params["symbol"] = _normalize_symbol(symbol)
    if order_id:
        params["orderId"] = order_id.strip()
    if order_link_id:
        params["orderLinkId"] = order_link_id.strip()

    rows = _fetch_private_cursor_rows(
        api_key=api_key,
        api_secret=api_secret,
        base_url=base_url,
        path=BYBIT_EXECUTION_LIST_PATH,
        params=params,
        recv_window=recv_window,
        timestamp_ms=timestamp_ms,
        urlopen=urlopen,
        label="execution-list",
    )
    executions: list[BybitExecutionInfo] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        parsed = _parse_bybit_execution(normalized_category, row)
        if parsed is not None:
            executions.append(parsed)
    return executions


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
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{BYBIT_FEE_RATE_PATH}?{query_string}",
        headers=_private_request_headers(
            api_key=api_key,
            api_secret=api_secret,
            recv_window=recv_window,
            timestamp_ms=timestamp_ms,
            signed_payload=query_string,
        ),
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


def fetch_bybit_wallet_balance(
    *,
    api_key: str,
    api_secret: str,
    account_type: str = "UNIFIED",
    coin: str | None = "USDT",
    base_url: str = BYBIT_API_URL,
    recv_window: int = 5_000,
    timestamp_ms: int | None = None,
    urlopen=urllib.request.urlopen,
) -> BybitWalletBalance:
    normalized_account_type = account_type.strip()
    params = {"accountType": normalized_account_type}
    if coin is not None and coin.strip():
        params["coin"] = coin.strip()
    payload = _get_private_json(
        api_key=api_key,
        api_secret=api_secret,
        base_url=base_url,
        path=BYBIT_WALLET_BALANCE_PATH,
        params=params,
        recv_window=recv_window,
        timestamp_ms=timestamp_ms,
        urlopen=urlopen,
        label="wallet-balance",
    )
    result = payload.get("result", {})
    result_payload: Mapping[str, Any] = result if isinstance(result, Mapping) else {}
    rows = result_payload.get("list", [])
    if not isinstance(rows, list) or not rows:
        return BybitWalletBalance(
            account_type=normalized_account_type,
            total_equity=None,
            total_wallet_balance=None,
            total_margin_balance=None,
            total_available_balance=None,
            total_initial_margin=None,
            total_maintenance_margin=None,
            total_perp_upl=None,
            coins=(),
            raw_payload=result_payload,
        )
    wallet_payload = rows[0]
    if not isinstance(wallet_payload, Mapping):
        return BybitWalletBalance(
            account_type=normalized_account_type,
            total_equity=None,
            total_wallet_balance=None,
            total_margin_balance=None,
            total_available_balance=None,
            total_initial_margin=None,
            total_maintenance_margin=None,
            total_perp_upl=None,
            coins=(),
            raw_payload=result_payload,
        )
    coins: list[BybitCoinBalance] = []
    coin_rows = wallet_payload.get("coin", [])
    if isinstance(coin_rows, list):
        for coin_payload in coin_rows:
            if isinstance(coin_payload, Mapping):
                parsed_coin = _parse_coin_balance(coin_payload)
                if parsed_coin is not None:
                    coins.append(parsed_coin)
    row_account_type = wallet_payload.get("accountType")
    return BybitWalletBalance(
        account_type=str(row_account_type) if row_account_type else normalized_account_type,
        total_equity=_decimal_or_none(wallet_payload.get("totalEquity")),
        total_wallet_balance=_decimal_or_none(wallet_payload.get("totalWalletBalance")),
        total_margin_balance=_decimal_or_none(wallet_payload.get("totalMarginBalance")),
        total_available_balance=_decimal_or_none(wallet_payload.get("totalAvailableBalance")),
        total_initial_margin=_decimal_or_none(wallet_payload.get("totalInitialMargin")),
        total_maintenance_margin=_decimal_or_none(wallet_payload.get("totalMaintenanceMargin")),
        total_perp_upl=_decimal_or_none(wallet_payload.get("totalPerpUPL")),
        coins=tuple(coins),
        raw_payload=wallet_payload,
    )


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


def fetch_bybit_instruments_info(
    *,
    category: str = "linear",
    quote_coin: str | None = "USDT",
    status: str | None = "Trading",
    base_url: str = BYBIT_API_URL,
    limit: int = 1000,
    urlopen=urllib.request.urlopen,
) -> tuple[BybitInstrumentInfo, ...]:
    normalized_category = _normalize_public_category(category)
    if limit <= 0:
        raise ValueError("Bybit instruments-info limit must be positive")
    params = {"category": normalized_category, "limit": str(limit)}
    quote_filter = quote_coin.strip().upper() if quote_coin is not None else None
    status_filter = status.strip().lower() if status is not None else None

    instruments: list[BybitInstrumentInfo] = []
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
        if not isinstance(result, dict):
            break
        rows = result.get("list", [])
        if not isinstance(rows, list):
            break
        for row in rows:
            if not isinstance(row, dict):
                continue
            parsed = _parse_instrument_info(normalized_category, row)
            if parsed is None:
                continue
            if quote_filter is not None and (parsed.quote_coin or "").upper() != quote_filter:
                continue
            if status_filter is not None and (parsed.status or "").lower() != status_filter:
                continue
            instruments.append(parsed)
        cursor = result.get("nextPageCursor") or ""
        if not cursor:
            break
    return tuple(instruments)


def fetch_bybit_market_universe(
    *,
    category: str = "linear",
    quote_coin: str = "USDT",
    base_url: str = BYBIT_API_URL,
    urlopen=urllib.request.urlopen,
) -> tuple[BybitUniverseInstrument, ...]:
    normalized_category = _normalize_public_category(category)
    instruments = fetch_bybit_instruments_info(
        category=normalized_category,
        quote_coin=quote_coin,
        status="Trading",
        base_url=base_url,
        urlopen=urlopen,
    )
    tickers = fetch_bybit_tickers(
        category=normalized_category,
        base_url=base_url,
        urlopen=urlopen,
    )
    tickers_by_symbol = {ticker.symbol.upper(): ticker for ticker in tickers}

    universe: list[BybitUniverseInstrument] = []
    for instrument in instruments:
        ticker = tickers_by_symbol.get(instrument.symbol.upper())
        bid1_price = _ticker_decimal(ticker, "bid1Price", attr="bid1_price")
        ask1_price = _ticker_decimal(ticker, "ask1Price", attr="ask1_price")
        universe.append(
            BybitUniverseInstrument(
                instrument=instrument,
                ticker=ticker,
                symbol=instrument.symbol,
                category=instrument.category,
                status=instrument.status,
                base_coin=instrument.base_coin,
                quote_coin=instrument.quote_coin,
                contract_type=instrument.contract_type,
                launch_time=instrument.launch_time,
                delivery_time=instrument.delivery_time,
                turnover_24h=_ticker_decimal(ticker, "turnover24h", attr="turnover_24h"),
                volume_24h=_ticker_decimal(ticker, "volume24h", attr="volume_24h"),
                last_price=_ticker_decimal(ticker, "lastPrice"),
                mark_price=_ticker_decimal(ticker, "markPrice", attr="mark_price"),
                bid1_price=bid1_price,
                ask1_price=ask1_price,
                spread_bps=_spread_bps_decimal(bid1_price, ask1_price),
                funding_rate=_ticker_decimal(ticker, "fundingRate", attr="funding_rate"),
            )
        )
    return tuple(_rank_universe_by_turnover(universe))


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
                volume_24h=_float_or_none(row.get("volume24h")),
                turnover_24h=_float_or_none(row.get("turnover24h")),
                raw_payload=row,
                open_interest=_float_or_none(row.get("openInterest")),
                open_interest_value=_float_or_none(row.get("openInterestValue")),
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
        timestamp_ms=_int_or_none(result.get("ts")),
        sequence_id=_int_or_none(result.get("seq") or result.get("u")),
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
                size=_decimal_or_none(row.get("size")),
                raw_payload=row,
                entry_price=_decimal_or_none(row.get("avgPrice")),
                mark_price=_decimal_or_none(row.get("markPrice")),
                liquidation_price=_decimal_or_none(row.get("liqPrice")),
                unrealized_pnl=_decimal_or_none(row.get("unrealisedPnl")),
                stop_loss=_decimal_or_none(row.get("stopLoss")),
                take_profit=_decimal_or_none(row.get("takeProfit")),
                updated_time=_int_or_none(row.get("updatedTime")),
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


def _fetch_private_cursor_rows(
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
    stop_after_first_page: bool = False,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor = ""
    while True:
        request_params = dict(params)
        if cursor:
            request_params["cursor"] = cursor
        payload = _get_private_json(
            api_key=api_key,
            api_secret=api_secret,
            base_url=base_url,
            path=path,
            params=request_params,
            recv_window=recv_window,
            timestamp_ms=timestamp_ms,
            urlopen=urlopen,
            label=label,
        )
        result = payload.get("result", {})
        if not isinstance(result, dict):
            break
        page_rows = result.get("list", [])
        if isinstance(page_rows, list):
            rows.extend(row for row in page_rows if isinstance(row, dict))
        cursor = str(result.get("nextPageCursor") or "")
        if stop_after_first_page or not cursor:
            break
    return rows


def _parse_bybit_order(category: str, row: dict[str, Any]) -> BybitOrderInfo:
    return BybitOrderInfo(
        category=str(row.get("category") or category),
        symbol=str(row.get("symbol") or ""),
        side=str(row.get("side") or ""),
        order_status=str(row.get("orderStatus") or ""),
        order_id=_text_or_none(row.get("orderId")),
        order_link_id=_text_or_none(row.get("orderLinkId")),
        order_type=_text_or_none(row.get("orderType")),
        qty=_decimal_or_none(row.get("qty")),
        cum_exec_qty=_decimal_or_none(row.get("cumExecQty")),
        price=_decimal_or_none(row.get("price")),
        avg_price=_decimal_or_none(row.get("avgPrice")),
        trigger_price=_decimal_or_none(row.get("triggerPrice")),
        reduce_only=_truthy_metadata_value(row.get("reduceOnly")),
        created_time=_int_or_none(row.get("createdTime")),
        updated_time=_int_or_none(row.get("updatedTime")),
        raw_payload=row,
    )


def _parse_bybit_execution(category: str, row: dict[str, Any]) -> BybitExecutionInfo | None:
    exec_id = _text_or_none(row.get("execId"))
    price = _decimal_or_none(row.get("execPrice"))
    quantity = _decimal_or_none(row.get("execQty"))
    if exec_id is None or price is None or quantity is None:
        return None
    return BybitExecutionInfo(
        category=str(row.get("category") or category),
        symbol=str(row.get("symbol") or ""),
        side=str(row.get("side") or ""),
        exec_id=exec_id,
        order_id=_text_or_none(row.get("orderId")),
        order_link_id=_text_or_none(row.get("orderLinkId")),
        exec_price=price,
        exec_qty=quantity,
        exec_fee=_decimal_or_none(row.get("execFee")),
        fee_currency=_text_or_none(row.get("feeCurrency")),
        is_maker=_bool_or_none(row.get("isMaker")),
        order_type=_text_or_none(row.get("orderType")),
        exec_time=_int_or_none(row.get("execTime")),
        raw_payload=row,
    )


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


def _post_private_json(
    *,
    api_key: str,
    api_secret: str,
    base_url: str,
    path: str,
    body: Mapping[str, Any],
    recv_window: int,
    timestamp_ms: int | None,
    urlopen,
    label: str,
) -> dict:
    json_body = json.dumps(body, separators=(",", ":"))
    headers = {
        **_private_request_headers(
            api_key=api_key,
            api_secret=api_secret,
            recv_window=recv_window,
            timestamp_ms=timestamp_ms,
            signed_payload=json_body,
        ),
        "Content-Type": "application/json",
    }
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=json_body.encode("utf-8"),
        headers=headers,
        method="POST",
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
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}?{query_string}",
        headers=_private_request_headers(
            api_key=api_key,
            api_secret=api_secret,
            recv_window=recv_window,
            timestamp_ms=timestamp_ms,
            signed_payload=query_string,
        ),
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


def _private_request_headers(
    *,
    api_key: str,
    api_secret: str,
    recv_window: int,
    timestamp_ms: int | None,
    signed_payload: str,
) -> dict[str, str]:
    timestamp = str(timestamp_ms or int(time.time() * 1000))
    recv_window_value = str(recv_window)
    signature_payload = f"{timestamp}{api_key}{recv_window_value}{signed_payload}"
    signature = hmac.new(
        api_secret.encode("utf-8"),
        signature_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "X-BAPI-API-KEY": api_key,
        "X-BAPI-TIMESTAMP": timestamp,
        "X-BAPI-RECV-WINDOW": recv_window_value,
        "X-BAPI-SIGN": signature,
    }


def _order_create_payload(request: BybitOrderCreateRequest) -> dict[str, Any]:
    category = _normalize_private_category(request.category)
    symbol = _normalize_private_symbol(request.symbol)
    side = _normalize_bybit_side(request.side)
    order_type = _normalize_bybit_order_type(request.order_type)
    qty = _positive_decimal(request.qty, "qty")
    order_link_id = request.order_link_id.strip()
    if not order_link_id:
        raise ValueError("Bybit orderLinkId is required.")
    time_in_force = request.time_in_force.strip()
    if not time_in_force:
        raise ValueError("Bybit timeInForce is required.")
    payload: dict[str, Any] = {
        "category": category,
        "symbol": symbol,
        "side": side,
        "orderType": order_type,
        "qty": _decimal_to_bybit_string(qty),
        "timeInForce": time_in_force,
        "orderLinkId": order_link_id,
        "reduceOnly": bool(request.reduce_only),
        "positionIdx": int(request.position_idx),
    }
    if order_type == "Limit":
        payload["price"] = _decimal_to_bybit_string(_positive_decimal(request.price, "price"))
    elif request.price is not None:
        raise ValueError("Bybit Market order payload must not include price.")
    if request.stop_loss is not None:
        payload["stopLoss"] = _decimal_to_bybit_string(
            _positive_decimal(request.stop_loss, "stopLoss")
        )
    if request.take_profit is not None:
        payload["takeProfit"] = _decimal_to_bybit_string(
            _positive_decimal(request.take_profit, "takeProfit")
        )
    if request.tp_sl_mode is not None and request.tp_sl_mode.strip():
        payload["tpslMode"] = request.tp_sl_mode.strip()
    return payload


def _normalize_private_category(category: str) -> str:
    normalized = category.strip().lower()
    if normalized != "linear":
        raise ValueError("Bybit live order placement MVP supports only linear category.")
    return normalized


def _normalize_private_symbol(symbol: str) -> str:
    value = symbol.strip()
    if not value:
        raise ValueError("Bybit order symbol is required.")
    if value != value.upper():
        raise ValueError("Bybit order symbol must be uppercase.")
    return LINEAR_SYMBOL_ALIASES.get(value, value)


def _bybit_side(side: str) -> str:
    normalized = side.strip().lower()
    if normalized == "buy":
        return "Buy"
    if normalized == "sell":
        return "Sell"
    raise ValueError("Bybit order side must be buy or sell.")


def _normalize_bybit_side(side: str) -> str:
    normalized = side.strip().lower()
    if normalized in {"buy", "sell"}:
        return _bybit_side(normalized)
    if side in {"Buy", "Sell"}:
        return side
    raise ValueError("Bybit order side must be Buy or Sell.")


def _bybit_order_type(order_type: str) -> str:
    normalized = order_type.strip().lower()
    if normalized == "market":
        return "Market"
    if normalized in {"limit", "take_profit"}:
        return "Limit"
    raise ValueError("Bybit order type must be market or limit for order/create.")


def _normalize_bybit_order_type(order_type: str) -> str:
    normalized = order_type.strip().lower()
    if normalized in {"market", "limit"}:
        return "Market" if normalized == "market" else "Limit"
    if order_type in {"Market", "Limit"}:
        return order_type
    raise ValueError("Bybit order type must be Market or Limit.")


def _metadata_text(metadata: Mapping[str, Any], name: str) -> str | None:
    value = metadata.get(name)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _optional_positive_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return _positive_decimal(value, "decimal")


def _positive_decimal(value: Any, label: str) -> Decimal:
    parsed = _decimal_or_none(value)
    if parsed is None or parsed <= 0:
        raise ValueError(f"Bybit {label} must be a positive Decimal value.")
    return parsed


def _decimal_to_bybit_string(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _planned_order_key(order: ExecutionPlannedOrder) -> tuple[str, str, str]:
    return (
        order.exchange.strip().lower(),
        order.symbol.strip().upper(),
        order.client_order_id,
    )


def _parse_instrument_info(
    category: str,
    row: dict[str, Any],
) -> BybitInstrumentInfo | None:
    symbol = row.get("symbol")
    if not isinstance(symbol, str) or not symbol:
        return None
    price_filter = row.get("priceFilter")
    lot_size_filter = row.get("lotSizeFilter")
    leverage_filter = row.get("leverageFilter")
    return BybitInstrumentInfo(
        category=category,
        symbol=symbol,
        status=_text_or_none(row.get("status")),
        base_coin=_text_or_none(row.get("baseCoin")),
        quote_coin=_text_or_none(row.get("quoteCoin")),
        contract_type=_text_or_none(row.get("contractType")),
        launch_time=_int_or_none(row.get("launchTime")),
        delivery_time=_int_or_none(row.get("deliveryTime")),
        price_filter=dict(price_filter) if isinstance(price_filter, dict) else {},
        lot_size_filter=dict(lot_size_filter) if isinstance(lot_size_filter, dict) else {},
        leverage_filter=dict(leverage_filter) if isinstance(leverage_filter, dict) else {},
        raw_payload=row,
    )


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


def _ticker_decimal(
    ticker: BybitTicker | None,
    raw_key: str,
    *,
    attr: str | None = None,
) -> Decimal | None:
    if ticker is None:
        return None
    parsed = _decimal_or_none(ticker.raw_payload.get(raw_key))
    if parsed is not None or attr is None:
        return parsed
    return _decimal_or_none(getattr(ticker, attr, None))


def _spread_bps_decimal(
    bid1_price: Decimal | None,
    ask1_price: Decimal | None,
) -> Decimal | None:
    if (
        bid1_price is None
        or ask1_price is None
        or bid1_price <= 0
        or ask1_price <= 0
        or ask1_price < bid1_price
    ):
        return None
    mid = (ask1_price + bid1_price) / Decimal("2")
    if mid <= 0:
        return None
    return (ask1_price - bid1_price) / mid * Decimal("10000")


def _rank_universe_by_turnover(
    universe: list[BybitUniverseInstrument],
) -> list[BybitUniverseInstrument]:
    ordered = sorted(universe, key=_universe_turnover_sort_key)
    ranked: list[BybitUniverseInstrument] = []
    rank = 1
    for instrument in ordered:
        if instrument.turnover_24h is None:
            ranked.append(instrument)
            continue
        ranked.append(replace(instrument, turnover_rank=rank))
        rank += 1
    return ranked


def _universe_turnover_sort_key(
    instrument: BybitUniverseInstrument,
) -> tuple[bool, Decimal, str]:
    turnover = instrument.turnover_24h
    return (turnover is None, -(turnover or Decimal("0")), instrument.symbol)


def _parse_coin_balance(row: Mapping[str, Any]) -> BybitCoinBalance | None:
    coin = row.get("coin")
    if not isinstance(coin, str) or not coin:
        return None
    return BybitCoinBalance(
        coin=coin,
        equity=_decimal_or_none(row.get("equity")),
        usd_value=_decimal_or_none(row.get("usdValue")),
        wallet_balance=_decimal_or_none(row.get("walletBalance")),
        available_to_withdraw=_decimal_or_none(row.get("availableToWithdraw")),
        locked=_decimal_or_none(row.get("locked")),
        borrow_amount=_decimal_or_none(row.get("borrowAmount")),
        accrued_interest=_decimal_or_none(row.get("accruedInterest")),
        total_order_im=_decimal_or_none(row.get("totalOrderIM")),
        total_position_im=_decimal_or_none(row.get("totalPositionIM")),
        total_position_mm=_decimal_or_none(row.get("totalPositionMM")),
        unrealised_pnl=_decimal_or_none(row.get("unrealisedPnl")),
        raw_payload=row,
    )


def _normalize_trade_side(value: object) -> TradeSide | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized == "buy":
        return "buy"
    if normalized == "sell":
        return "sell"
    return None


def _float_or_none(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _text_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _bool_or_none(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False
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
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

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
        self._connected = True
        return ws

    def _build_market_data(self, trade: dict) -> Optional[MarketData]:
        try:
            return MarketData(
                exchange="bybit",
                symbol=trade["s"],
                price=float(trade["p"]),
                volume=float(trade["v"]),
                timestamp=int(trade["T"]),
                side=_normalize_trade_side(trade.get("S")),
                trade_id=str(trade["i"]) if trade.get("i") is not None else None,
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
                self._connected = False

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
