from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID
import unittest

from app.services.strategy_testing.schemas import StrategyTestMetricRow, StrategyTestSignalEvent, StrategyTestTrade
from app.services.strategy_testing.stores import (
    STRATEGY_TEST_ANALYTICS_ALTER_DDLS,
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
    def test_ensure_schema_sends_strategy_test_ddls(self) -> None:
        client = FakeClickHouseClient()
        store = ClickHouseStrategyTestStore(lambda: client)

        store.ensure_schema()

        self.assertEqual(
            client.commands,
            [
                STRATEGY_TEST_TRADES_DDL,
                STRATEGY_TEST_METRICS_DDL,
                STRATEGY_TEST_SIGNALS_DDL,
                *STRATEGY_TEST_ANALYTICS_ALTER_DDLS,
            ],
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

    def test_write_trades_inserts_deterministic_analytics_keys(self) -> None:
        client = FakeClickHouseClient()
        store = ClickHouseStrategyTestStore(lambda: client)

        store.write_trades([_trade()])

        _table, data, columns = client.inserts[0]
        row = data[0]
        self.assertIn("scenario_key", columns)
        self.assertIn("event_key", columns)
        self.assertIn("run_attempt", columns)
        self.assertEqual(
            row[columns.index("scenario_key")],
            "trend_pullback_continuation::bybit::BTCUSDT::1h",
        )
        self.assertEqual(row[columns.index("event_key")], "trade-1")
        self.assertEqual(row[columns.index("run_attempt")], 0)

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

    def test_write_metrics_inserts_scenario_key_and_attempt(self) -> None:
        client = FakeClickHouseClient()
        store = ClickHouseStrategyTestStore(lambda: client)

        store.write_metrics([_metric()])

        _table, data, columns = client.inserts[0]
        row = data[0]
        self.assertIn("scenario_key", columns)
        self.assertIn("run_attempt", columns)
        self.assertEqual(
            row[columns.index("scenario_key")],
            "trend_pullback_continuation::bybit::BTCUSDT::1h",
        )
        self.assertEqual(row[columns.index("run_attempt")], 0)

    def test_write_signal_events_inserts_expected_columns(self) -> None:
        client = FakeClickHouseClient()
        store = ClickHouseStrategyTestStore(lambda: client)

        store.write_signal_events([_signal_event()])

        table, data, columns = client.inserts[0]
        row = data[0]
        self.assertEqual(table, "analytics.strategy_test_signals")
        self.assertEqual(columns, ClickHouseStrategyTestStore._signal_event_columns)
        self.assertEqual(row[columns.index("run_id")], RUN_ID)
        self.assertEqual(row[columns.index("synthetic_signal_id")], "signal-1")
        self.assertEqual(row[columns.index("execution_candidate")], 1)
        self.assertEqual(row[columns.index("no_entry")], 1)
        self.assertEqual(row[columns.index("features_snapshot_json")], '{"atr":"1.2"}')
        self.assertTrue(client.closed)

    def test_write_signal_events_inserts_deterministic_analytics_keys(self) -> None:
        client = FakeClickHouseClient()
        store = ClickHouseStrategyTestStore(lambda: client)

        store.write_signal_events([_signal_event()])

        _table, data, columns = client.inserts[0]
        row = data[0]
        self.assertIn("scenario_key", columns)
        self.assertIn("event_key", columns)
        self.assertIn("run_attempt", columns)
        self.assertEqual(
            row[columns.index("scenario_key")],
            "trend_pullback_continuation::bybit::BTCUSDT::1h",
        )
        self.assertEqual(row[columns.index("event_key")], "signal-1")
        self.assertEqual(row[columns.index("run_attempt")], 0)

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
        query = client.queries[0][0]
        self.assertIn("argMax", query)
        self.assertIn("GROUP BY", query)
        self.assertIn("event_key", query)

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
        query = client.queries[0][0]
        self.assertIn("argMax", query)
        self.assertIn("GROUP BY", query)
        self.assertIn("scenario_key", query)

    def test_list_metric_rows_deduplicates_by_metric_key(self) -> None:
        client = FakeClickHouseClient(rows=[_metric_row()])
        store = ClickHouseStrategyTestStore(lambda: client)

        rows = store.list_metric_rows(RUN_ID)

        self.assertEqual(rows[0].metric_code, "winrate")
        query = client.queries[0][0]
        self.assertIn("argMax", query)
        self.assertIn("GROUP BY", query)
        self.assertIn("metric_code", query)

    def test_list_signal_events_parses_json_decimal_and_flags(self) -> None:
        client = FakeClickHouseClient(rows=[_signal_event_row()])
        store = ClickHouseStrategyTestStore(lambda: client)

        rows = store.list_signal_events(RUN_ID, limit=25, offset=5)

        self.assertEqual(client.queries[0][1], {"run_id": RUN_ID, "limit": 25, "offset": 5})
        event = rows[0]
        self.assertEqual(event.synthetic_signal_id, "signal-1")
        self.assertEqual(event.candle_time, ENTRY_AT)
        self.assertEqual(event.entry_min, Decimal("100.25"))
        self.assertTrue(event.execution_candidate)
        self.assertFalse(event.filled)
        self.assertTrue(event.no_entry)
        self.assertEqual(event.features_snapshot, {"atr": "1.2"})
        self.assertEqual(event.metadata, {"source": "backtest"})
        query = client.queries[0][0]
        self.assertIn("argMax", query)
        self.assertIn("GROUP BY", query)
        self.assertIn("event_key", query)

    def test_sample_methods_use_paginated_dedup_queries(self) -> None:
        signal_client = FakeClickHouseClient(rows=[_signal_event_row()])
        signal_store = ClickHouseStrategyTestStore(lambda: signal_client)
        trade_client = FakeClickHouseClient(rows=[_trade_row()])
        trade_store = ClickHouseStrategyTestStore(lambda: trade_client)

        signal_rows = signal_store.list_signal_event_samples(RUN_ID, limit=7, offset=3)
        trade_rows = trade_store.list_trade_samples(RUN_ID, limit=11, offset=5)

        self.assertEqual(signal_rows[0].synthetic_signal_id, "signal-1")
        self.assertEqual(trade_rows[0].trade_id, "trade-1")
        self.assertEqual(signal_client.queries[0][1], {"run_id": RUN_ID, "limit": 7, "offset": 3})
        self.assertEqual(trade_client.queries[0][1], {"run_id": RUN_ID, "limit": 11, "offset": 5})
        self.assertIn("GROUP BY run_id, scenario_key, event_key", signal_client.queries[0][0])
        self.assertIn("GROUP BY run_id, scenario_key, event_key", trade_client.queries[0][0])

    def test_aggregate_signal_funnel_deduplicates_in_clickhouse(self) -> None:
        client = FakeClickHouseClient(
            rows=[
                {
                    "signals_count": 4,
                    "execution_candidates": 3,
                    "entry_touched": 2,
                    "filled": 1,
                    "closed": 1,
                    "wins": 1,
                    "losses": 0,
                    "no_entry": 2,
                    "risk_rejected": 1,
                    "execution_rejected": 1,
                }
            ]
        )
        store = ClickHouseStrategyTestStore(lambda: client)

        funnel = store.aggregate_signal_funnel(RUN_ID)

        self.assertEqual(client.queries[0][1], {"run_id": RUN_ID})
        self.assertEqual(funnel.signals_count, 4)
        self.assertEqual(funnel.execution_candidates, 3)
        self.assertEqual(funnel.entry_touch_rate, 0.5)
        self.assertEqual(funnel.execution_rejection_rate, 1 / 3)
        query = client.queries[0][0]
        self.assertIn("argMax", query)
        self.assertIn("GROUP BY run_id, scenario_key, event_key", query)

    def test_summarize_funnel_uses_clickhouse_counts(self) -> None:
        client = FakeClickHouseClient(rows=[_signal_summary_row()])
        store = ClickHouseStrategyTestStore(lambda: client)

        funnel = store.summarize_funnel(RUN_ID)

        self.assertEqual(funnel.signals_count, 12050)
        self.assertEqual(funnel.execution_candidates, 8000)
        self.assertEqual(funnel.no_entry, 3000)
        query = client.queries[0][0]
        self.assertIn("countIf", query)
        self.assertIn("argMax", query)
        self.assertIn("GROUP BY strategy_code, exchange, symbol, timeframe, direction, market_regime, score_bucket", query)

    def test_summarize_signal_events_returns_grouped_dimensions(self) -> None:
        client = FakeClickHouseClient(rows=[_signal_summary_row()])
        store = ClickHouseStrategyTestStore(lambda: client)

        summary = store.summarize_signal_events(RUN_ID)

        self.assertEqual(summary.signals_count, 12050)
        self.assertEqual(summary.groups[0]["strategy_code"], "trend_pullback_continuation")
        self.assertEqual(summary.groups[0]["score_bucket"], "80-89")
        self.assertEqual(summary.groups[0]["signals_count"], 12050)

    def test_summarize_trades_returns_grouped_dimensions(self) -> None:
        client = FakeClickHouseClient(rows=[_trade_summary_row()])
        store = ClickHouseStrategyTestStore(lambda: client)

        summary = store.summarize_trades(RUN_ID)

        self.assertEqual(summary.trades_count, 40)
        self.assertEqual(summary.executed_trades_count, 38)
        self.assertEqual(summary.wins, 25)
        self.assertEqual(summary.groups[0]["exchange"], "bybit")
        query = client.queries[0][0]
        self.assertIn("countIf", query)
        self.assertIn("sum", query)
        self.assertIn("argMax", query)
        self.assertIn("GROUP BY strategy_code, exchange, symbol, timeframe, direction, market_regime, score_bucket", query)

    def test_clickhouse_init_file_contains_strategy_test_tables(self) -> None:
        schema = DDL_FILE.read_text(encoding="utf-8")

        self.assertIn("CREATE DATABASE IF NOT EXISTS analytics", schema)
        self.assertIn("CREATE TABLE IF NOT EXISTS analytics.strategy_test_trades", schema)
        self.assertIn("CREATE TABLE IF NOT EXISTS analytics.strategy_test_metrics", schema)
        self.assertIn("CREATE TABLE IF NOT EXISTS analytics.strategy_test_signals", schema)
        self.assertIn("scenario_key String", schema)
        self.assertIn("event_key String", schema)
        self.assertIn("run_attempt UInt32", schema)
        self.assertIn("ALTER TABLE analytics.strategy_test_trades ADD COLUMN IF NOT EXISTS scenario_key String", schema)
        self.assertIn("ALTER TABLE analytics.strategy_test_signals ADD COLUMN IF NOT EXISTS event_key String", schema)
        self.assertIn("ALTER TABLE analytics.strategy_test_metrics ADD COLUMN IF NOT EXISTS run_attempt UInt32", schema)
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


def _signal_event() -> StrategyTestSignalEvent:
    return StrategyTestSignalEvent(
        run_id=RUN_ID,
        user_id=USER_ID,
        mode="research_virtual",
        test_type="historical_backtest",
        strategy_code="trend_pullback_continuation",
        strategy_version="v1",
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe="1h",
        direction="long",
        signal_id=None,
        synthetic_signal_id="signal-1",
        signal_key="bybit:BTCUSDT:1h:trend_pullback_continuation:long:1",
        event_time=ENTRY_AT,
        candle_time=ENTRY_AT,
        signal_score=82.5,
        market_regime="trend:strong:aligned",
        score_bucket="80-89",
        status="actionable",
        gate_status="passed",
        feed_kind="execution_signal",
        trigger_passed=True,
        trigger_reason_code="closed_candle_trigger_passed",
        execution_candidate=True,
        entry_touched=False,
        filled=False,
        closed=False,
        outcome="no_entry",
        funnel_stage="no_entry",
        risk_rejected=False,
        execution_rejected=False,
        no_entry=True,
        rejection_reason_code=None,
        blocked_reason_code="not_selected",
        selected_rr=2.0,
        entry_min=Decimal("100.25"),
        entry_max=Decimal("100.50"),
        stop_loss=Decimal("97.50"),
        features_snapshot={"atr": "1.2"},
        trade_plan={"source": "strategy"},
        metadata={"source": "backtest"},
        tags=["backtest", "signal_event"],
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


def _signal_event_row() -> dict[str, Any]:
    return {
        "run_id": RUN_ID,
        "user_id": USER_ID,
        "mode": "research_virtual",
        "test_type": "historical_backtest",
        "strategy_code": "trend_pullback_continuation",
        "strategy_version": "v1",
        "exchange": "bybit",
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "direction": "long",
        "signal_id": None,
        "synthetic_signal_id": "signal-1",
        "signal_key": "bybit:BTCUSDT:1h:trend_pullback_continuation:long:1",
        "event_time": ENTRY_AT.replace(tzinfo=None),
        "candle_time": ENTRY_AT.isoformat(),
        "signal_score": "82.5",
        "market_regime": "trend:strong:aligned",
        "score_bucket": "80-89",
        "status": "actionable",
        "gate_status": "passed",
        "feed_kind": "execution_signal",
        "trigger_passed": 1,
        "trigger_reason_code": "closed_candle_trigger_passed",
        "execution_candidate": "1",
        "entry_touched": "0",
        "filled": 0,
        "closed": 0,
        "outcome": "no_entry",
        "funnel_stage": "no_entry",
        "risk_rejected": 0,
        "execution_rejected": "0",
        "no_entry": 1,
        "rejection_reason_code": None,
        "blocked_reason_code": "not_selected",
        "selected_rr": "2.0",
        "entry_min": "100.25",
        "entry_max": Decimal("100.50"),
        "stop_loss": None,
        "features_snapshot_json": '{"atr":"1.2"}',
        "trade_plan_json": '{"source":"strategy"}',
        "metadata_json": '{"source":"backtest"}',
        "tags": ("backtest", "signal_event"),
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


def _signal_summary_row() -> dict[str, Any]:
    return {
        "strategy_code": "trend_pullback_continuation",
        "exchange": "bybit",
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "direction": "long",
        "market_regime": "trend:strong:aligned",
        "score_bucket": "80-89",
        "signals_count": 12050,
        "execution_candidates": 8000,
        "entry_touched": 5000,
        "filled": 4500,
        "closed": 4400,
        "wins": 2400,
        "losses": 2000,
        "no_entry": 3000,
        "risk_rejected": 250,
        "execution_rejected": 150,
        "false_signals": 3000,
    }


def _trade_summary_row() -> dict[str, Any]:
    return {
        "strategy_code": "trend_pullback_continuation",
        "exchange": "bybit",
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "direction": "long",
        "market_regime": "trend:strong:aligned",
        "score_bucket": "80-89",
        "trades_count": 40,
        "executed_trades_count": 38,
        "wins": 25,
        "losses": 13,
        "risk_rejected": 1,
        "execution_rejected": 1,
        "realized_r_sum": 8.5,
        "realized_r_count": 38,
        "pnl_total": "122.5",
        "fees_total": "4.0",
        "slippage_total": "1.5",
    }


if __name__ == "__main__":
    unittest.main()
