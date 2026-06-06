from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID
import unittest

from app.services.strategy_testing.schemas import StrategyTestMetricRow, StrategyTestSignal, StrategyTestTrade
from app.services.strategy_testing.stores import (
    STRATEGY_TEST_METRICS_DDL,
    STRATEGY_TEST_SIGNALS_DDL,
    STRATEGY_TEST_TRADES_DDL,
    ClickHouseStrategyTestStore,
)


ROOT_DIR = Path(__file__).resolve().parents[2]
DDL_FILE = ROOT_DIR / "infra" / "clickhouse" / "init" / "004_strategy_test_analytics.sql"
RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
USER_ID = UUID("22222222-2222-4222-8222-222222222222")
ENTRY_AT = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
EXIT_AT = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)
CREATED_AT = datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc)


class FakeQueryResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def named_results(self) -> list[dict[str, Any]]:
        return list(self._rows)


class FakeClickHouseClient:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.commands: list[str] = []
        self.inserts: list[tuple[str, list[list[Any]], list[str]]] = []
        self.queries: list[tuple[str, dict[str, Any] | None]] = []
        self.rows = rows or []
        self.closed = False

    def command(self, command: str) -> None:
        self.commands.append(command)

    def insert(self, table: str, data: list[list[Any]], column_names: list[str]) -> None:
        self.inserts.append((table, data, column_names))

    def query(self, query: str, parameters: dict[str, Any] | None = None) -> FakeQueryResult:
        self.queries.append((query, parameters))
        return FakeQueryResult(self.rows)

    def close(self) -> None:
        self.closed = True


class ClickHouseStrategyTestStoreTest(unittest.TestCase):
    def test_ensure_schema_sends_all_strategy_test_ddls(self) -> None:
        client = FakeClickHouseClient()
        store = ClickHouseStrategyTestStore(lambda: client)

        store.ensure_schema()

        self.assertEqual(
            client.commands,
            [STRATEGY_TEST_TRADES_DDL, STRATEGY_TEST_SIGNALS_DDL, STRATEGY_TEST_METRICS_DDL],
        )
        self.assertTrue(client.closed)

    def test_write_trades_inserts_expected_columns(self) -> None:
        client = FakeClickHouseClient()
        store = ClickHouseStrategyTestStore(lambda: client)

        store.write_trades([_trade()])

        table, data, columns = client.inserts[0]
        row = data[0]
        self.assertEqual(table, "analytics.strategy_test_trades")
        self.assertEqual(columns, ClickHouseStrategyTestStore._trade_columns)
        self.assertEqual(row[columns.index("run_id")], RUN_ID)
        self.assertEqual(row[columns.index("trade_id")], "trade-1")
        self.assertEqual(row[columns.index("targets_json")], '[{"price":"110.5","weight":0.5}]')
        self.assertIn("тонкий рынок", row[columns.index("warnings_json")])
        self.assertEqual(row[columns.index("risk_rejected")], 0)
        self.assertEqual(row[columns.index("execution_rejected")], 1)
        self.assertTrue(client.closed)

    def test_write_metrics_inserts_expected_columns(self) -> None:
        client = FakeClickHouseClient()
        store = ClickHouseStrategyTestStore(lambda: client)

        store.write_metrics([_metric()])

        table, data, columns = client.inserts[0]
        row = data[0]
        self.assertEqual(table, "analytics.strategy_test_metrics")
        self.assertEqual(columns, ClickHouseStrategyTestStore._metric_columns)
        self.assertEqual(row[columns.index("metric_code")], "expectancy_r")
        self.assertEqual(row[columns.index("metadata_json")], '{"source":"lab","note":"проверка"}')
        self.assertTrue(client.closed)

    def test_list_trades_parses_json_decimal_and_datetime_fields(self) -> None:
        client = FakeClickHouseClient(rows=[_trade_row()])
        store = ClickHouseStrategyTestStore(lambda: client)

        trades = store.list_trades(RUN_ID, limit=25, offset=5)

        self.assertEqual(client.queries[0][1], {"run_id": RUN_ID, "limit": 25, "offset": 5})
        trade = trades[0]
        self.assertEqual(trade.run_id, RUN_ID)
        self.assertEqual(trade.entry_time, ENTRY_AT)
        self.assertEqual(trade.exit_time, EXIT_AT)
        self.assertEqual(trade.entry_price, Decimal("100.25"))
        self.assertEqual(trade.exit_price, Decimal("105.75"))
        self.assertEqual(trade.targets, [{"price": "110", "r": 2}])
        self.assertEqual(trade.warnings, ["тонкий рынок"])
        self.assertEqual(trade.features_snapshot, {"atr": "1.2"})
        self.assertEqual(trade.trade_plan, {"source": "strategy"})
        self.assertEqual(trade.tags, ["backtest", "lab"])
        self.assertFalse(trade.risk_rejected)
        self.assertTrue(trade.execution_rejected)

    def test_list_metrics_parses_metadata_json(self) -> None:
        client = FakeClickHouseClient(rows=[_metric_row()])
        store = ClickHouseStrategyTestStore(lambda: client)

        rows = store.list_metrics(RUN_ID)

        self.assertEqual(client.queries[0][1], {"run_id": RUN_ID})
        metric = rows[0]
        self.assertEqual(metric.metric_code, "winrate")
        self.assertEqual(metric.metric_value, 0.6)
        self.assertEqual(metric.sample_size, 10)
        self.assertEqual(metric.metadata, {"source": "grouped"})

    def test_strategy_test_clickhouse_store_write_and_read_signals(self) -> None:
        write_client = FakeClickHouseClient()
        write_store = ClickHouseStrategyTestStore(lambda: write_client)

        write_store.write_signals([_signal()])

        table, data, columns = write_client.inserts[0]
        row = data[0]
        self.assertEqual(table, "analytics.strategy_test_signals")
        self.assertEqual(columns, ClickHouseStrategyTestStore._signal_columns)
        self.assertEqual(row[columns.index("signal_id")], "signal-1")
        self.assertEqual(row[columns.index("entry_touched")], 1)
        self.assertEqual(row[columns.index("filled")], 0)
        self.assertIn('"source":"test"', row[columns.index("metadata_json")])
        self.assertTrue(write_client.closed)

        read_client = FakeClickHouseClient(rows=[_signal_row()])
        read_store = ClickHouseStrategyTestStore(lambda: read_client)

        signals = read_store.list_signals(RUN_ID, limit=25, offset=5)

        self.assertEqual(read_client.queries[0][1], {"run_id": RUN_ID, "limit": 25, "offset": 5})
        signal = signals[0]
        self.assertEqual(signal.signal_id, "signal-1")
        self.assertEqual(signal.signal_time, ENTRY_AT)
        self.assertEqual(signal.entry_min, Decimal("100.25"))
        self.assertEqual(signal.target_1, Decimal("110.50"))
        self.assertTrue(signal.entry_touched)
        self.assertFalse(signal.filled)
        self.assertTrue(signal.no_entry)
        self.assertEqual(signal.metadata, {"source": "test", "note": "РїСЂРѕРІРµСЂРєР°"})

    def test_clickhouse_init_file_contains_strategy_test_tables(self) -> None:
        schema = DDL_FILE.read_text(encoding="utf-8")

        self.assertIn("CREATE DATABASE IF NOT EXISTS analytics", schema)
        self.assertIn("CREATE TABLE IF NOT EXISTS analytics.strategy_test_trades", schema)
        self.assertIn("CREATE TABLE IF NOT EXISTS analytics.strategy_test_signals", schema)
        self.assertIn("CREATE TABLE IF NOT EXISTS analytics.strategy_test_metrics", schema)
        self.assertIn("ENGINE = MergeTree", schema)
        self.assertIn("ENGINE = ReplacingMergeTree(created_at)", schema)
        self.assertNotIn("DROP TABLE", schema)


def _trade() -> StrategyTestTrade:
    return StrategyTestTrade(
        run_id=RUN_ID,
        trade_id="trade-1",
        user_id=USER_ID,
        mode="research_virtual",
        strategy_code="trend_pullback_continuation",
        strategy_version="v1",
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe="1h",
        direction="long",
        signal_score=82.5,
        market_regime="trend:strong:aligned",
        score_bucket="80-89",
        entry_time=ENTRY_AT,
        exit_time=EXIT_AT,
        entry_price=Decimal("100.25"),
        exit_price=Decimal("105.75"),
        stop_loss=Decimal("97.50"),
        targets=[{"price": Decimal("110.5"), "weight": 0.5}],
        selected_rr=2.0,
        realized_r=1.5,
        pnl=Decimal("55.50"),
        pnl_pct=0.055,
        fees=Decimal("0.20"),
        slippage=Decimal("0.10"),
        mfe_r=2.2,
        mae_r=-0.4,
        bars_to_entry=3,
        bars_in_trade=8,
        close_reason="target",
        outcome="win",
        risk_rejected=False,
        execution_rejected=True,
        warnings=["тонкий рынок"],
        features_snapshot={"atr": Decimal("1.2")},
        trade_plan={"source": "strategy"},
        tags=["backtest", "lab"],
        created_at=CREATED_AT,
    )


def _metric() -> StrategyTestMetricRow:
    return StrategyTestMetricRow(
        run_id=RUN_ID,
        user_id=USER_ID,
        mode="research_virtual",
        strategy_code="trend_pullback_continuation",
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe="1h",
        market_regime="trend:strong:aligned",
        score_bucket="80-89",
        direction="long",
        metric_code="expectancy_r",
        metric_value=0.25,
        sample_size=20,
        metadata={"source": "lab", "note": "проверка"},
        created_at=CREATED_AT,
    )


def _signal() -> StrategyTestSignal:
    return StrategyTestSignal(
        run_id=RUN_ID,
        user_id=USER_ID,
        mode="research_virtual",
        scenario_id="trend_pullback_continuation:bybit:BTCUSDT:1h",
        strategy_code="trend_pullback_continuation",
        strategy_version="v1",
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe="1h",
        direction="long",
        signal_id="signal-1",
        signal_time=ENTRY_AT,
        signal_score=82.5,
        feed_kind="execution_signal",
        gate_status="passed",
        status="actionable",
        trigger_passed=True,
        edge_status="positive",
        selected_rr=2.0,
        entry_min=Decimal("100.25"),
        entry_max=Decimal("101.25"),
        stop_loss=Decimal("97.50"),
        target_1=Decimal("110.50"),
        outcome="no_entry",
        outcome_reason="entry_not_touched",
        entry_touched=True,
        filled=False,
        risk_rejected=False,
        execution_rejected=False,
        no_entry=True,
        bars_to_entry=3,
        bars_to_outcome=8,
        metadata={"source": "test", "note": "РїСЂРѕРІРµСЂРєР°"},
        created_at=CREATED_AT,
    )


def _trade_row() -> dict[str, Any]:
    return {
        "run_id": RUN_ID,
        "trade_id": "trade-1",
        "user_id": USER_ID,
        "mode": "research_virtual",
        "strategy_code": "trend_pullback_continuation",
        "strategy_version": "v1",
        "exchange": "bybit",
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "direction": "long",
        "signal_score": "82.5",
        "market_regime": "trend:strong:aligned",
        "score_bucket": "80-89",
        "entry_time": ENTRY_AT.replace(tzinfo=None),
        "exit_time": EXIT_AT.isoformat(),
        "entry_price": "100.25",
        "exit_price": Decimal("105.75"),
        "stop_loss": None,
        "targets_json": '[{"price":"110","r":2}]',
        "selected_rr": "2.0",
        "realized_r": "1.5",
        "pnl": "55.50",
        "pnl_pct": "0.055",
        "fees": Decimal("0.20"),
        "slippage": "0.10",
        "mfe_r": "2.2",
        "mae_r": "-0.4",
        "bars_to_entry": "3",
        "bars_in_trade": 8,
        "close_reason": "target",
        "outcome": "win",
        "risk_rejected": "0",
        "execution_rejected": 1,
        "warnings_json": '["тонкий рынок"]',
        "features_snapshot_json": '{"atr":"1.2"}',
        "trade_plan_json": '{"source":"strategy"}',
        "tags": ("backtest", "lab"),
        "created_at": CREATED_AT,
    }


def _metric_row() -> dict[str, Any]:
    return {
        "run_id": RUN_ID,
        "user_id": USER_ID,
        "mode": "research_virtual",
        "strategy_code": "trend_pullback_continuation",
        "exchange": "bybit",
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "market_regime": "trend:strong:aligned",
        "score_bucket": "80-89",
        "direction": "long",
        "metric_code": "winrate",
        "metric_value": "0.6",
        "sample_size": "10",
        "metadata_json": '{"source":"grouped"}',
        "created_at": CREATED_AT.replace(tzinfo=None),
    }


def _signal_row() -> dict[str, Any]:
    return {
        "run_id": RUN_ID,
        "user_id": USER_ID,
        "mode": "research_virtual",
        "scenario_id": "trend_pullback_continuation:bybit:BTCUSDT:1h",
        "strategy_code": "trend_pullback_continuation",
        "strategy_version": "v1",
        "exchange": "bybit",
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "direction": "long",
        "signal_id": "signal-1",
        "signal_time": ENTRY_AT.replace(tzinfo=None),
        "signal_score": "82.5",
        "feed_kind": "execution_signal",
        "gate_status": "passed",
        "status": "actionable",
        "trigger_passed": "1",
        "edge_status": "positive",
        "selected_rr": "2.0",
        "entry_min": "100.25",
        "entry_max": Decimal("101.25"),
        "stop_loss": "97.50",
        "target_1": Decimal("110.50"),
        "outcome": "no_entry",
        "outcome_reason": "entry_not_touched",
        "entry_touched": "1",
        "filled": 0,
        "risk_rejected": 0,
        "execution_rejected": "0",
        "no_entry": "1",
        "bars_to_entry": "3",
        "bars_to_outcome": 8,
        "metadata_json": '{"source":"test","note":"РїСЂРѕРІРµСЂРєР°"}',
        "created_at": CREATED_AT,
    }


if __name__ == "__main__":
    unittest.main()
