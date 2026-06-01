import unittest

from app.exchanges.base import DryRunExecutionAdapter
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
