import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import UUID, uuid4

from app.schemas.risk import RiskPreviewRequest, RiskStateResponse
from app.schemas.signal import RadarSignal
from app.schemas.user import RiskManagementSettings
from app.services.risk_fee_rate import RiskFeeRateSnapshot
from app.services.risk_gate import RiskContextService, RiskGateService
from app.services.risk_market_data import RiskMarketDataSnapshot
from app.services.risk_preview import RiskPreviewService
from app.services.risk_state import RiskReferenceSnapshot


class FakeSignalProvider:
    def __init__(self, signal: RadarSignal) -> None:
        self.signal = signal

    def get_signal(self, signal_id: str) -> RadarSignal | None:
        return self.signal if signal_id == self.signal.id else None


class FakeRiskStateService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def get_reference(self, **kwargs) -> RiskReferenceSnapshot:
        self.calls.append(kwargs)
        return RiskReferenceSnapshot(
            state=RiskStateResponse(
                user_id=kwargs["user_id"],
                mode=kwargs["mode"],
                protection_state="normal",
                current_equity=1_000,
                peak_equity=1_000,
                exchange_rule_status="fresh",
            ),
            exchange_min_order_size=0.001,
            exchange_min_notional=5.0,
            exchange_max_leverage=10,
            exchange_rule_status="fresh",
            open_risk_amount=0.0,
            correlated_open_risk_amount=0.0,
            daily_loss_amount=0.0,
            protection_state="normal",
        )


class FakeMarketDataService:
    def build_snapshot(self, **kwargs) -> RiskMarketDataSnapshot:
        return RiskMarketDataSnapshot(
            exchange=kwargs["exchange"],
            symbol=kwargs["symbol"],
            category="spot",
            entry_price=100.0,
            slippage_bps=2.0,
            best_bid=99.99,
            best_ask=100.01,
            spread_percent=0.02,
            spread_bps=2.0,
            orderbook_depth_usd=100_000.0,
            market_data_status="fresh",
            market_data_source="test",
        )


class FakeFeeRateService:
    def resolve(self, **kwargs) -> RiskFeeRateSnapshot:
        return RiskFeeRateSnapshot(
            fee_rate=0.0,
            maker_fee_rate=0.0,
            taker_fee_rate=0.0,
            source="test",
            exchange=kwargs["exchange"],
            category="spot",
            symbol=kwargs["symbol"],
        )


class FakeRiskAuditService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.record_id = uuid4()

    def record_decision(self, **kwargs) -> UUID:
        self.calls.append(kwargs)
        return self.record_id


class RiskPreviewServiceTest(unittest.TestCase):
    def test_manual_preview_records_audit_but_readonly_preview_does_not(self) -> None:
        signal = _signal()
        state_service = FakeRiskStateService()
        audit_service = FakeRiskAuditService()
        service = RiskPreviewService(
            signal_provider=FakeSignalProvider(signal),
            risk_context_service=RiskContextService(),
            risk_gate_service=RiskGateService(),
            state_service=state_service,
            audit_service=audit_service,
            market_data_service=FakeMarketDataService(),
            fee_rate_service=FakeFeeRateService(),
        )
        request = RiskPreviewRequest(
            signal_id=signal.id,
            mode="real",
            user_id="demo_user",
            instrument_type="spot",
            account_balance=1_000,
        )

        with patch(
            "app.services.risk_preview.get_user_risk_management_settings",
            lambda _user_id: _risk_settings(),
        ), patch(
            "app.services.risk_preview._strategy_risk_settings",
            lambda _signal, *, user_id: ({}, "not_configured"),
        ):
            manual_response = service.preview(request)
            readonly_decision = service.evaluate(request, record_audit=False)

        self.assertEqual(manual_response.risk_decision_id, str(audit_service.record_id))
        self.assertEqual(len(audit_service.calls), 1)
        self.assertEqual(
            manual_response.decision.model_dump(mode="json"),
            readonly_decision.model_dump(mode="json"),
        )
        self.assertEqual(
            [call["read_only"] for call in state_service.calls],
            [False, True],
        )


def _signal() -> RadarSignal:
    now = datetime.now(timezone.utc)
    return RadarSignal(
        id=str(uuid4()),
        symbol="BTCUSDT",
        exchange="bybit",
        strategy="trend_pullback_continuation",
        direction="long",
        confidence=0.82,
        status="active",
        score=82,
        timeframe="15m",
        entry_min=100.0,
        entry_max=100.0,
        stop_loss=98.0,
        take_profit_1=104.0,
        take_profit_2=106.0,
        risk_reward=3.0,
        created_at=now,
        updated_at=now,
    )


def _risk_settings() -> RiskManagementSettings:
    return RiskManagementSettings(
        risk_profile="balanced",
        risk_per_trade_percent=1.0,
        spot_risk_per_trade_percent=1.0,
        min_rr_ratio=2.0,
        max_daily_loss_percent=3.0,
        max_account_drawdown_percent=10.0,
        max_open_risk_percent=5.0,
        max_correlated_risk_percent=3.0,
        stop_loss_mode="structure",
        take_profit_mode="risk_multiple",
        real_requires_positive_edge=False,
        real_requires_fresh_market_data=False,
    )


if __name__ == "__main__":
    unittest.main()
