import unittest
from datetime import datetime, timezone
from uuid import uuid4

from app.domain.signal_status import OPEN_SIGNAL_STATUSES
from app.repositories.signal_repository import SignalWriteResult
from app.schemas.signal import RadarSignal, SignalEdgeSnapshot, SignalExecutionGateSnapshot, StrategySignal
from app.services.signal_deduplication import SignalDeduplicationService, dedup_key, rank_signal
from app.services.signal_service import NullSignalAnalyticsWriter, NullSignalHotStore, SignalService


class SignalDeduplicationServiceTest(unittest.TestCase):
    def test_keep_when_no_existing_signal_has_same_market_direction(self) -> None:
        candidate = _signal(signal_id="candidate")

        decision = SignalDeduplicationService().decide(candidate, [])

        self.assertEqual(decision.action, "keep")
        self.assertIsNone(decision.suppressed_by_signal_id)
        self.assertEqual(decision.replaced_signal_ids, ())
        self.assertEqual(dedup_key(candidate), ("bybit", "BTCUSDT", "long"))

    def test_suppress_when_existing_signal_ranks_higher_for_same_market_direction(self) -> None:
        existing = _signal(signal_id="existing", score=94)
        candidate = _signal(signal_id="candidate", score=82)

        decision = SignalDeduplicationService().decide(candidate, [existing])

        self.assertEqual(decision.action, "suppress")
        self.assertEqual(decision.suppressed_by_signal_id, existing.id)
        self.assertEqual(decision.replaced_signal_ids, ())
        self.assertEqual(decision.metadata["suppressed_by_rank"], list(rank_signal(existing)))

    def test_replace_when_candidate_ranks_higher_for_same_market_direction(self) -> None:
        existing = _signal(signal_id="existing", score=78, strategy="liquidity_sweep_reversal")
        candidate = _signal(signal_id="candidate", score=92)

        decision = SignalDeduplicationService().decide(candidate, [existing])

        self.assertEqual(decision.action, "replace")
        self.assertIsNone(decision.suppressed_by_signal_id)
        self.assertEqual(decision.replaced_signal_ids, (existing.id,))
        self.assertEqual(decision.metadata["replaced_ranks"], {existing.id: list(rank_signal(existing))})

    def test_opposite_direction_does_not_dedupe(self) -> None:
        existing = _signal(signal_id="existing", direction="short", score=99)
        candidate = _signal(signal_id="candidate", direction="long", score=82)

        decision = SignalDeduplicationService().decide(candidate, [existing])

        self.assertEqual(decision.action, "keep")
        self.assertEqual(decision.replaced_signal_ids, ())

    def test_different_symbol_does_not_dedupe(self) -> None:
        existing = _signal(signal_id="existing", symbol="ETHUSDT", score=99)
        candidate = _signal(signal_id="candidate", symbol="BTC/USDT", score=82)

        decision = SignalDeduplicationService().decide(candidate, [existing])

        self.assertEqual(decision.action, "keep")
        self.assertEqual(dedup_key(candidate), ("bybit", "BTCUSDT", "long"))

    def test_closed_candle_ranks_above_open_candle_when_other_fields_match(self) -> None:
        existing = _signal(signal_id="existing", candle_state="open")
        candidate = _signal(signal_id="candidate", candle_state="closed")

        decision = SignalDeduplicationService().decide(candidate, [existing])

        self.assertEqual(decision.action, "replace")
        self.assertEqual(decision.replaced_signal_ids, (existing.id,))
        self.assertGreater(rank_signal(candidate), rank_signal(existing))


class SignalServiceWriteSideDedupTest(unittest.TestCase):
    def test_weaker_candidate_is_persisted_as_suppressed_and_returned_terminal(self) -> None:
        existing = _signal(signal_id="existing", score=95)
        repository = _DedupRepository(seed=[existing], next_id="candidate")
        service = SignalService(
            repository=repository,
            analytics_writer=NullSignalAnalyticsWriter(),
            hot_store=NullSignalHotStore(),
        )

        radar_signal, created = service.upsert_strategy_signal(_strategy_signal(score=82))

        self.assertTrue(created)
        self.assertEqual(radar_signal.id, "candidate")
        self.assertEqual(radar_signal.status, "invalidated")
        self.assertEqual(radar_signal.status_reason, "dedup_suppressed_by_better_signal")
        self.assertEqual(repository.dedup_metadata["candidate"]["action"], "suppress")
        self.assertEqual(repository.dedup_metadata["candidate"]["suppressed_by_signal_id"], "existing")

    def test_stronger_candidate_invalidates_replaced_open_signal(self) -> None:
        existing = _signal(signal_id="existing", score=78, strategy="liquidity_sweep_reversal")
        repository = _DedupRepository(seed=[existing], next_id="candidate")
        service = SignalService(
            repository=repository,
            analytics_writer=NullSignalAnalyticsWriter(),
            hot_store=NullSignalHotStore(),
        )

        radar_signal, created = service.upsert_strategy_signal(_strategy_signal(score=92))

        self.assertTrue(created)
        self.assertEqual(radar_signal.status, "actionable")
        self.assertEqual(repository.signals["existing"].status, "invalidated")
        self.assertEqual(repository.signals["existing"].status_reason, "dedup_replaced_by_better_signal")
        self.assertEqual(repository.dedup_metadata["candidate"]["action"], "replace")
        self.assertEqual(repository.dedup_metadata["candidate"]["replaced_signal_ids"], ["existing"])


def _signal(
    *,
    signal_id: str,
    symbol: str = "BTCUSDT",
    direction: str = "long",
    strategy: str = "trend_pullback_continuation",
    score: int = 82,
    status: str = "actionable",
    candle_state: str = "closed",
    feed_kind: str = "execution_signal",
    edge_status: str = "positive",
    selected_rr: float = 2.4,
) -> RadarSignal:
    now = datetime(2026, 6, 6, tzinfo=timezone.utc)
    return RadarSignal(
        id=signal_id,
        symbol=symbol,
        exchange="bybit",
        strategy=strategy,
        direction=direction,
        confidence=0.82,
        score=score,
        status=status,
        timeframe="15m",
        candle_state=candle_state,
        entry_min=100.0,
        entry_max=101.0,
        stop_loss=98.0,
        take_profit_1=104.0,
        take_profit_2=106.0,
        selected_rr=selected_rr,
        created_at=now,
        updated_at=now,
        execution_gate=SignalExecutionGateSnapshot(
            status="passed" if feed_kind == "execution_signal" else "blocked",
            feed_kind=feed_kind,
            can_notify=feed_kind == "execution_signal",
            can_enter_now=feed_kind == "execution_signal",
            can_arm_pending=feed_kind == "execution_signal",
            can_show_in_execution_feed=feed_kind == "execution_signal",
        ),
        edge=SignalEdgeSnapshot(
            status=edge_status,
            sample_size=80,
            min_sample_size=50,
            expectancy_after_costs_r=0.18 if edge_status == "positive" else None,
            profit_factor=1.4 if edge_status == "positive" else None,
            confidence_score=0.8,
            source="outcome",
        ),
    )


def _strategy_signal(*, score: int) -> StrategySignal:
    timestamp = int(datetime(2026, 6, 6, tzinfo=timezone.utc).timestamp())
    return StrategySignal(
        exchange="bybit",
        symbol="BTCUSDT",
        strategy="trend_pullback_continuation",
        direction="LONG",
        confidence=score / 100,
        timestamp=timestamp,
        score=score,
        status="actionable",
        timeframe="15m",
        candle_state="closed",
        entry_min=100.0,
        entry_max=101.0,
        stop_loss=98.0,
        take_profit_1=104.0,
        take_profit_2=106.0,
        selected_rr=2.4,
        execution_gate=SignalExecutionGateSnapshot(
            status="passed",
            feed_kind="execution_signal",
            can_notify=True,
            can_enter_now=True,
            can_arm_pending=True,
            can_show_in_execution_feed=True,
        ),
        edge=SignalEdgeSnapshot(
            status="positive",
            sample_size=80,
            min_sample_size=50,
            expectancy_after_costs_r=0.18,
            profit_factor=1.4,
            confidence_score=0.8,
            source="outcome",
        ),
    )


class _DedupRepository:
    def __init__(self, *, seed: list[RadarSignal], next_id: str) -> None:
        self.signals = {signal.id: signal for signal in seed}
        self.next_id = next_id
        self.dedup_metadata: dict[str, dict[str, object]] = {}

    def upsert_strategy_signal(self, signal: StrategySignal, **_: object) -> SignalWriteResult:
        now = datetime(2026, 6, 6, tzinfo=timezone.utc)
        radar_signal = RadarSignal(
            id=self.next_id,
            symbol=signal.symbol,
            exchange=signal.exchange,
            strategy=signal.strategy,
            direction=signal.direction.lower(),
            confidence=signal.confidence,
            score=signal.score,
            status=signal.status,
            timeframe=signal.timeframe,
            candle_state=signal.candle_state,
            entry_min=signal.entry_min,
            entry_max=signal.entry_max,
            stop_loss=signal.stop_loss,
            take_profit_1=signal.take_profit_1,
            take_profit_2=signal.take_profit_2,
            selected_rr=signal.selected_rr,
            execution_gate=signal.execution_gate,
            edge=signal.edge,
            created_at=now,
            updated_at=now,
        )
        self.signals[radar_signal.id] = radar_signal
        return _write_result(radar_signal, created=True, event_type="signal.created")

    def list_open_signals_for_market_direction(
        self,
        *,
        exchange: str,
        symbol: str,
        direction: str,
        since: datetime,
        limit: int = 200,
    ) -> list[RadarSignal]:
        normalized_symbol = symbol.replace("/", "").replace(":PERP", "").upper()
        return [
            signal
            for signal in self.signals.values()
            if signal.status in OPEN_SIGNAL_STATUSES
            and signal.exchange.lower() == exchange.lower()
            and signal.symbol.replace("/", "").replace(":PERP", "").upper() == normalized_symbol
            and signal.direction.lower() == direction.lower()
        ][:limit]

    def update_signal_dedup_metadata(self, signal_id: str, dedup: dict[str, object]) -> SignalWriteResult | None:
        signal = self.signals.get(signal_id)
        if signal is None:
            return None
        self.dedup_metadata[signal_id] = dedup
        return _write_result(signal, created=False, event_type="signal.updated")

    def transition_signal(
        self,
        signal_id: str,
        *,
        new_status: str,
        event_type: str,
        reason: str | None = None,
        lifecycle: dict[str, object] | None = None,
        signal_updates: dict[str, object] | None = None,
    ) -> SignalWriteResult | None:
        signal = self.signals.get(signal_id)
        if signal is None:
            return None
        if signal_updates and isinstance(signal_updates.get("dedup"), dict):
            self.dedup_metadata[signal_id] = signal_updates["dedup"]  # type: ignore[assignment]
        updated = signal.model_copy(
            update={
                "status": new_status,
                "status_reason": reason,
                "updated_at": datetime(2026, 6, 6, tzinfo=timezone.utc),
            }
        )
        self.signals[signal_id] = updated
        return _write_result(updated, created=False, event_type=event_type)


def _write_result(signal: RadarSignal, *, created: bool, event_type: str) -> SignalWriteResult:
    return SignalWriteResult(
        signal=signal,
        created=created,
        event_type=event_type,
        analytics_event={
            "event_type": event_type,
            "signal_id": uuid4(),
            "signal_key": signal.id,
        },
    )


if __name__ == "__main__":
    unittest.main()
