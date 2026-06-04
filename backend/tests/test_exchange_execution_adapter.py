import unittest

from app.exchanges.base import DryRunExecutionAdapter, exchange_execution_capabilities
from app.exchanges.bybit import BybitRealExecutionAdapter
from app.schemas.trade import ExecutionPlannedOrder


class ExchangeExecutionAdapterTest(unittest.IsolatedAsyncioTestCase):
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
        self.assertFalse(bybit.guarantees_protective_after_entry)
        self.assertFalse(bybit.supports_reduce_only)

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

    async def test_bybit_real_adapter_skeleton_does_not_submit_orders(self) -> None:
        adapter = BybitRealExecutionAdapter()

        with self.assertRaises(NotImplementedError):
            await adapter.place_order(_planned_order(role="entry", client_order_id="entry-3"))


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
    )


if __name__ == "__main__":
    unittest.main()
