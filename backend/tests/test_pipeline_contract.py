import unittest
from pathlib import Path

from app.schemas.pipeline import (
    KAFKA_TOPICS,
    PIPELINE_STAGES,
    NormalizedTradeEvent,
    RawMarketEvent,
    normalized_topic_for,
    raw_topic_for,
)
from app.schemas.signal import NoTradeFilterResult, SignalLayerCheck


EXPECTED_PIPELINE_STAGES = (
    "Exchange WS",
    "Raw Market Event",
    "Normalizer",
    "Kafka Topic: market.trades",
    "Kafka Topic: market.orderbook",
    "Kafka Topic: market.candles",
    "Feature Builder",
    "Strategy Engine",
    "Signal Scoring",
    "Signal Store",
    "Frontend Radar",
)

EXPECTED_KAFKA_TOPICS = (
    "market.trades.raw",
    "market.orderbook.raw",
    "market.candles.raw",
    "market.liquidations.raw",
    "market.trades.normalized",
    "market.orderbook.normalized",
    "market.candles.normalized",
    "features.symbol.1m",
    "features.symbol.5m",
    "signals.created",
    "signals.updated",
    "signals.expired",
    "trades.virtual.opened",
    "trades.virtual.closed",
    "trades.real.synced",
    "ai.review.requested",
    "ai.review.completed",
)


class PipelineContractTest(unittest.TestCase):
    def test_pipeline_stages_match_architecture_project(self) -> None:
        self.assertEqual(PIPELINE_STAGES, EXPECTED_PIPELINE_STAGES)

    def test_kafka_topics_match_architecture_project(self) -> None:
        self.assertEqual(KAFKA_TOPICS, EXPECTED_KAFKA_TOPICS)

    def test_architecture_project_contains_contract_topics(self) -> None:
        architecture = (
            Path(__file__).resolve().parents[2] / "docs" / "architectureproject.md"
        ).read_text(encoding="utf-8")

        for stage in EXPECTED_PIPELINE_STAGES:
            self.assertIn(stage, architecture)
        for topic in EXPECTED_KAFKA_TOPICS:
            self.assertIn(topic, architecture)

    def test_topic_lookup_uses_architecture_names(self) -> None:
        self.assertEqual(raw_topic_for("trade"), "market.trades.raw")
        self.assertEqual(raw_topic_for("orderbook"), "market.orderbook.raw")
        self.assertEqual(raw_topic_for("candle"), "market.candles.raw")
        self.assertEqual(raw_topic_for("liquidation"), "market.liquidations.raw")

        self.assertEqual(normalized_topic_for("trade"), "market.trades.normalized")
        self.assertEqual(
            normalized_topic_for("orderbook"),
            "market.orderbook.normalized",
        )
        self.assertEqual(normalized_topic_for("candle"), "market.candles.normalized")

    def test_raw_and_normalized_events_validate_expected_shape(self) -> None:
        raw = RawMarketEvent(
            topic="market.trades.raw",
            key="bybit:BTCUSDT",
            emitted_at=1_717_000_000_000,
            exchange="bybit",
            source_symbol="BTCUSDT",
            event_type="trade",
            received_at=1_717_000_000_000,
            payload={"p": "68000", "v": "0.1"},
        )
        self.assertEqual(raw.topic, "market.trades.raw")

        normalized = NormalizedTradeEvent(
            key="bybit:BTC/USDT:PERP",
            emitted_at=1_717_000_000_010,
            exchange="bybit",
            symbol="BTC/USDT:PERP",
            price=68_000,
            volume=0.1,
            side="buy",
            event_time=1_717_000_000_000,
        )
        self.assertEqual(normalized.topic, "market.trades.normalized")

    def test_no_trade_filter_result_contract_exposes_blockers(self) -> None:
        result = NoTradeFilterResult(
            enabled=True,
            blocked=True,
            hard_block=True,
            blockers=["Spread 84.0 bps is above entry limit 25.0 bps"],
            checks=[
                SignalLayerCheck(
                    name="high_spread",
                    status="failed",
                    reason="Spread 84.0 bps is above entry limit 25.0 bps",
                )
            ],
            metadata={"blocker_codes": ["high_spread"]},
        )

        payload = result.model_dump(mode="json")

        self.assertTrue(payload["blocked"])
        self.assertEqual(payload["checks"][0]["name"], "high_spread")
        self.assertEqual(payload["metadata"]["blocker_codes"], ["high_spread"])


if __name__ == "__main__":
    unittest.main()
