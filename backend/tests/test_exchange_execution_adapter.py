import hashlib
import hmac
import json
import unittest
from dataclasses import dataclass
from decimal import Decimal

from app.core.config import Settings
from app.exchanges.base import DryRunExecutionAdapter, exchange_execution_capabilities
from app.exchanges.bybit import (
    BYBIT_EXECUTION_LIST_PATH,
    BYBIT_MAINNET_ORDER_PLACEMENT_DISABLED_REASON,
    BYBIT_ORDER_CREATE_PATH,
    BYBIT_ORDER_REALTIME_PATH,
    BYBIT_TRADING_STOP_PATH,
    LIVE_ORDER_PLACEMENT_DISABLED_REASON,
    BybitRealExecutionAdapter,
    fetch_bybit_executions,
    fetch_bybit_orders,
)
from app.schemas.trade import ExecutionPlannedOrder


class ExchangeExecutionAdapterTest(unittest.IsolatedAsyncioTestCase):
    async def test_backend_live_trading_settings_default_to_safe_values(self) -> None:
        fields = Settings.model_fields

        self.assertFalse(fields["enable_live_trading"].default)
        self.assertFalse(fields["enable_bybit_live_order_placement"].default)
        self.assertFalse(fields["enable_bybit_mainnet_order_placement"].default)
        self.assertEqual(fields["bybit_http_timeout_seconds"].default, 4.0)
        self.assertTrue(fields["require_protective_stop_for_live_entry"].default)

    async def test_dry_run_adapter_returns_planned_order_without_submission(self) -> None:
        adapter = DryRunExecutionAdapter()
        order = _planned_order(role="entry", client_order_id="entry-1")

        result = await adapter.place_order(order)

        self.assertEqual(result.status, "dry_run")
        self.assertTrue(result.metadata["dry_run"])
        self.assertEqual(result.client_order_id, order.client_order_id)
        self.assertEqual(
            await adapter.get_order(
                exchange=order.exchange,
                symbol=order.symbol,
                client_order_id=order.client_order_id,
            ),
            result,
        )

    async def test_adapters_declare_protective_order_capabilities(self) -> None:
        dry_run = exchange_execution_capabilities(DryRunExecutionAdapter())
        self.assertFalse(dry_run.supports_bracket_orders)
        self.assertFalse(dry_run.supports_oco)
        self.assertFalse(dry_run.guarantees_protective_after_entry)
        self.assertTrue(dry_run.supports_reduce_only)

        bybit = exchange_execution_capabilities(BybitRealExecutionAdapter())
        self.assertFalse(bybit.supports_bracket_orders)
        self.assertFalse(bybit.supports_oco)
        self.assertTrue(bybit.guarantees_protective_after_entry)
        self.assertTrue(bybit.supports_reduce_only)

    async def test_bybit_live_order_defaults_block_submission(self) -> None:
        adapter = BybitRealExecutionAdapter(settings_override=_live_trading_settings())

        self.assertEqual(
            adapter.live_order_placement_safety_reason(),
            LIVE_ORDER_PLACEMENT_DISABLED_REASON,
        )
        with self.assertRaises(NotImplementedError) as raised:
            await adapter.place_order(_planned_order(role="entry", client_order_id="entry-disabled"))

        self.assertEqual(str(raised.exception), LIVE_ORDER_PLACEMENT_DISABLED_REASON)

    async def test_bybit_testnet_requires_both_live_flags(self) -> None:
        metadata = {"testnet": True}

        for settings in (
            _live_trading_settings(enable_live_trading=True),
            _live_trading_settings(enable_bybit_live_order_placement=True),
        ):
            adapter = BybitRealExecutionAdapter(
                connection_metadata=metadata,
                settings_override=settings,
            )
            self.assertEqual(
                adapter.live_order_placement_safety_reason(),
                LIVE_ORDER_PLACEMENT_DISABLED_REASON,
            )

        adapter = BybitRealExecutionAdapter(
            connection_metadata=metadata,
            settings_override=_live_trading_settings(
                enable_live_trading=True,
                enable_bybit_live_order_placement=True,
            ),
        )

        self.assertIsNone(adapter.live_order_placement_safety_reason())

    async def test_bybit_mainnet_requires_separate_order_placement_flag(self) -> None:
        enabled_testnet_flags = _live_trading_settings(
            enable_live_trading=True,
            enable_bybit_live_order_placement=True,
        )
        adapter = BybitRealExecutionAdapter(
            connection_metadata={"testnet": False},
            settings_override=enabled_testnet_flags,
        )

        self.assertEqual(
            adapter.live_order_placement_safety_reason(),
            BYBIT_MAINNET_ORDER_PLACEMENT_DISABLED_REASON,
        )

        mainnet_adapter = BybitRealExecutionAdapter(
            connection_metadata={"environment": "mainnet"},
            settings_override=_live_trading_settings(
                enable_live_trading=True,
                enable_bybit_live_order_placement=True,
                enable_bybit_mainnet_order_placement=True,
            ),
        )

        self.assertIsNone(mainnet_adapter.live_order_placement_safety_reason())

    async def test_dry_run_adapter_handles_protective_and_take_profit_orders(self) -> None:
        adapter = DryRunExecutionAdapter()
        stop = _planned_order(
            role="protective_stop",
            client_order_id="stop-1",
            side="sell",
            order_type="stop",
            reduce_only=True,
            stop_price=95.0,
        )
        take_profit = _planned_order(
            role="take_profit",
            client_order_id="tp-1",
            side="sell",
            order_type="take_profit",
            reduce_only=True,
            price=110.0,
            close_percent=50.0,
        )

        stop_result = await adapter.place_protective_stop(stop)
        tp_result = await adapter.place_take_profit(take_profit)

        self.assertEqual(stop_result.status, "dry_run")
        self.assertTrue(stop_result.reduce_only)
        self.assertEqual(tp_result.status, "dry_run")
        self.assertEqual(tp_result.close_percent, 50.0)

    async def test_dry_run_adapter_cancel_marks_planned_order_cancelled(self) -> None:
        adapter = DryRunExecutionAdapter()
        order = await adapter.place_order(_planned_order(role="entry", client_order_id="entry-2"))

        cancelled = await adapter.cancel_order(
            exchange=order.exchange,
            symbol=order.symbol,
            client_order_id=order.client_order_id,
        )

        self.assertIsNotNone(cancelled)
        assert cancelled is not None
        self.assertEqual(cancelled.status, "cancelled")

    async def test_cancel_replace_is_guarded(self) -> None:
        adapter = DryRunExecutionAdapter()
        stop = await adapter.place_protective_stop(
            _planned_order(
                role="protective_stop",
                client_order_id="stop-replace-1",
                side="sell",
                order_type="stop",
                reduce_only=True,
                stop_price=95.0,
            )
        )
        replacement = _planned_order(
            role="protective_stop",
            client_order_id="stop-replace-2",
            side="sell",
            order_type="stop",
            reduce_only=True,
            stop_price=94.0,
        )

        replaced = await adapter.replace_order(
            current_client_order_id=stop.client_order_id,
            replacement=replacement,
        )

        self.assertEqual(replaced.status, "dry_run")
        self.assertEqual(replaced.metadata["replaces_client_order_id"], stop.client_order_id)
        old = await adapter.get_order(
            exchange=stop.exchange,
            symbol=stop.symbol,
            client_order_id=stop.client_order_id,
        )
        self.assertIsNotNone(old)
        assert old is not None
        self.assertEqual(old.status, "cancelled")

        with self.assertRaises(ValueError):
            await adapter.replace_order(
                current_client_order_id=replaced.client_order_id,
                replacement=_planned_order(role="entry", client_order_id="entry-replace-bad"),
            )

    async def test_bybit_testnet_order_create_posts_signed_body(self) -> None:
        captured = {}

        def fake_urlopen(request, timeout: int):
            captured["request"] = request
            captured["timeout"] = timeout
            return _Response(
                {
                    "retCode": 0,
                    "retMsg": "OK",
                    "result": {"orderId": "bybit-order-1", "orderLinkId": "entry-3"},
                }
            )

        adapter = BybitRealExecutionAdapter(
            connection_metadata={"testnet": True},
            settings_override=_live_trading_settings(
                enable_live_trading=True,
                enable_bybit_live_order_placement=True,
            ),
            api_key="api_key",
            api_secret="api_secret",
            timestamp_ms=1_676_360_412_362,
            urlopen=fake_urlopen,
        )
        order = _planned_order(
            role="entry",
            client_order_id="entry-3",
            price=None,
            metadata={"native_stop_loss": 95.0, "category": "linear"},
        )

        placed = await adapter.place_order(order)

        request = captured["request"]
        body = request.data.decode("utf-8")
        payload = json.loads(body)
        expected_signature = hmac.new(
            b"api_secret",
            f"1676360412362api_key5000{body}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(request.full_url, f"https://api-testnet.bybit.com{BYBIT_ORDER_CREATE_PATH}")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("X-bapi-api-key"), "api_key")
        self.assertEqual(request.get_header("X-bapi-timestamp"), "1676360412362")
        self.assertEqual(request.get_header("X-bapi-sign"), expected_signature)
        self.assertEqual(captured["timeout"], 4.0)
        self.assertEqual(
            payload,
            {
                "category": "linear",
                "symbol": "BTCUSDT",
                "side": "Buy",
                "orderType": "Market",
                "qty": "1",
                "timeInForce": "IOC",
                "orderLinkId": "entry-3",
                "reduceOnly": False,
                "positionIdx": 0,
                "stopLoss": "95",
                "tpslMode": "Full",
            },
        )
        self.assertEqual(placed.status, "submitted")
        self.assertEqual(placed.exchange_order_id, "bybit-order-1")
        self.assertEqual(placed.client_order_id, "entry-3")
        self.assertIsNone(placed.filled_qty)
        self.assertEqual(placed.metadata["order_link_id"], "entry-3")

    async def test_bybit_limit_order_without_price_is_rejected_before_http(self) -> None:
        calls = 0

        def fake_urlopen(request, timeout: int):
            nonlocal calls
            calls += 1
            return _Response({"retCode": 0, "retMsg": "OK", "result": {}})

        adapter = _enabled_bybit_adapter(urlopen=fake_urlopen)
        order = _planned_order(
            role="entry",
            client_order_id="limit-no-price",
            order_type="limit",
            price=None,
            metadata={"native_stop_loss": 95.0},
        )

        with self.assertRaises(ValueError):
            await adapter.place_order(order)

        self.assertEqual(calls, 0)

    async def test_bybit_live_entry_requires_native_stop_loss_when_guard_enabled(self) -> None:
        calls = 0

        def fake_urlopen(request, timeout: int):
            nonlocal calls
            calls += 1
            return _Response({"retCode": 0, "retMsg": "OK", "result": {}})

        adapter = _enabled_bybit_adapter(urlopen=fake_urlopen)

        with self.assertRaises(ValueError) as raised:
            await adapter.place_order(_planned_order(role="entry", client_order_id="missing-sl"))

        self.assertIn("requires native stopLoss", str(raised.exception))
        self.assertEqual(calls, 0)

    async def test_bybit_trading_stop_posts_signed_body(self) -> None:
        captured = {}

        def fake_urlopen(request, timeout: int):
            captured["request"] = request
            return _Response({"retCode": 0, "retMsg": "OK", "result": {}})

        adapter = _enabled_bybit_adapter(urlopen=fake_urlopen)
        stop = _planned_order(
            role="protective_stop",
            client_order_id="stop-1",
            side="sell",
            order_type="stop",
            reduce_only=True,
            stop_price=95.0,
            metadata={"native_take_profit": Decimal("110.5"), "tp_sl_mode": "Full"},
        )

        placed = await adapter.place_protective_stop(stop)

        request = captured["request"]
        body = request.data.decode("utf-8")
        payload = json.loads(body)
        expected_signature = hmac.new(
            b"api_secret",
            f"1676360412362api_key5000{body}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(request.full_url, f"https://api-testnet.bybit.com{BYBIT_TRADING_STOP_PATH}")
        self.assertEqual(request.get_header("X-bapi-sign"), expected_signature)
        self.assertEqual(
            payload,
            {
                "category": "linear",
                "symbol": "BTCUSDT",
                "stopLoss": "95",
                "tpslMode": "Full",
                "positionIdx": 0,
                "takeProfit": "110.5",
            },
        )
        self.assertEqual(placed.status, "submitted")
        self.assertIn("bybit_trading_stop_ack", placed.metadata)

    async def test_bybit_order_realtime_fetches_by_order_link_id(self) -> None:
        captured = {}

        def fake_urlopen(request, timeout: int):
            captured["request"] = request
            captured["timeout"] = timeout
            return _Response(
                {
                    "retCode": 0,
                    "retMsg": "OK",
                    "result": {
                        "list": [
                            {
                                "symbol": "BTCUSDT",
                                "side": "Buy",
                                "orderStatus": "PartiallyFilled",
                                "orderId": "bybit-order-1",
                                "orderLinkId": "entry-3",
                                "orderType": "Market",
                                "qty": "1",
                                "cumExecQty": "0.4",
                                "avgPrice": "101",
                                "reduceOnly": False,
                                "updatedTime": "1676360412362",
                            }
                        ]
                    },
                }
            )

        orders = fetch_bybit_orders(
            api_key="api_key",
            api_secret="api_secret",
            category="linear",
            symbol="BTCUSDT",
            order_link_id="entry-3",
            base_url="https://api-testnet.bybit.com",
            timestamp_ms=1_676_360_412_362,
            urlopen=fake_urlopen,
        )

        request = captured["request"]
        self.assertIn(BYBIT_ORDER_REALTIME_PATH, request.full_url)
        self.assertIn("orderLinkId=entry-3", request.full_url)
        self.assertEqual(captured["timeout"], 4.0)
        self.assertEqual(orders[0].cum_exec_qty, Decimal("0.4"))
        self.assertEqual(orders[0].avg_price, Decimal("101"))

    async def test_bybit_execution_list_uses_cursor_pagination(self) -> None:
        requests = []
        payloads = [
            {
                "retCode": 0,
                "retMsg": "OK",
                "result": {
                    "nextPageCursor": "next-cursor",
                    "list": [
                        {
                            "symbol": "BTCUSDT",
                            "side": "Buy",
                            "execId": "exec-1",
                            "orderId": "order-1",
                            "orderLinkId": "entry-3",
                            "execPrice": "100",
                            "execQty": "0.25",
                            "execFee": "0.01",
                            "feeCurrency": "USDT",
                            "isMaker": False,
                            "orderType": "Market",
                            "execTime": "1676360412362",
                        }
                    ],
                },
            },
            {
                "retCode": 0,
                "retMsg": "OK",
                "result": {
                    "nextPageCursor": "",
                    "list": [
                        {
                            "symbol": "BTCUSDT",
                            "side": "Buy",
                            "execId": "exec-2",
                            "orderId": "order-1",
                            "orderLinkId": "entry-3",
                            "execPrice": "103.25",
                            "execQty": "0.35",
                            "execFee": "0.02",
                            "feeCurrency": "USDT",
                            "isMaker": True,
                            "orderType": "Market",
                            "execTime": "1676360412363",
                        }
                    ],
                },
            },
        ]

        def fake_urlopen(request, timeout: int):
            requests.append(request)
            return _Response(payloads[len(requests) - 1])

        executions = fetch_bybit_executions(
            api_key="api_key",
            api_secret="api_secret",
            category="linear",
            symbol="BTCUSDT",
            order_link_id="entry-3",
            base_url="https://api-testnet.bybit.com",
            timestamp_ms=1_676_360_412_362,
            urlopen=fake_urlopen,
        )

        self.assertEqual(len(requests), 2)
        self.assertIn(BYBIT_EXECUTION_LIST_PATH, requests[0].full_url)
        self.assertIn("orderLinkId=entry-3", requests[0].full_url)
        self.assertIn("cursor=next-cursor", requests[1].full_url)
        self.assertEqual([execution.exec_id for execution in executions], ["exec-1", "exec-2"])
        self.assertEqual(executions[1].exec_qty, Decimal("0.35"))
        self.assertTrue(executions[1].is_maker)


@dataclass(frozen=True)
class _LiveTradingSettings:
    enable_live_trading: bool = False
    enable_bybit_live_order_placement: bool = False
    enable_bybit_mainnet_order_placement: bool = False
    require_protective_stop_for_live_entry: bool = True


class _Response:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def _live_trading_settings(
    *,
    enable_live_trading: bool = False,
    enable_bybit_live_order_placement: bool = False,
    enable_bybit_mainnet_order_placement: bool = False,
    require_protective_stop_for_live_entry: bool = True,
) -> _LiveTradingSettings:
    return _LiveTradingSettings(
        enable_live_trading=enable_live_trading,
        enable_bybit_live_order_placement=enable_bybit_live_order_placement,
        enable_bybit_mainnet_order_placement=enable_bybit_mainnet_order_placement,
        require_protective_stop_for_live_entry=require_protective_stop_for_live_entry,
    )


def _enabled_bybit_adapter(*, urlopen) -> BybitRealExecutionAdapter:
    return BybitRealExecutionAdapter(
        connection_metadata={"testnet": True},
        settings_override=_live_trading_settings(
            enable_live_trading=True,
            enable_bybit_live_order_placement=True,
        ),
        api_key="api_key",
        api_secret="api_secret",
        timestamp_ms=1_676_360_412_362,
        urlopen=urlopen,
    )


def _planned_order(
    *,
    role: str,
    client_order_id: str,
    side: str = "buy",
    order_type: str = "market",
    reduce_only: bool = False,
    price: float | None = 100.0,
    stop_price: float | None = None,
    close_percent: float | None = None,
    metadata: dict | None = None,
) -> ExecutionPlannedOrder:
    return ExecutionPlannedOrder(
        role=role,
        exchange="bybit",
        symbol="BTCUSDT",
        side=side,
        order_type=order_type,
        quantity=1.0,
        price=price,
        stop_price=stop_price,
        reduce_only=reduce_only,
        close_percent=close_percent,
        client_order_id=client_order_id,
        idempotency_key=f"idempotency:{client_order_id}",
        metadata=metadata or {},
    )


if __name__ == "__main__":
    unittest.main()
