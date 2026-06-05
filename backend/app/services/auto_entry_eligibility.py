from __future__ import annotations

from app.schemas.signal import NoTradeFilterResult, SignalAutoEntrySnapshot, StrategySignal
from app.schemas.trade_plan import TradePlanCompletenessResult
from app.services.risk_reward_assessment import RiskRewardAssessment


class AutoEntryEligibilityService:
    # TODO(migration-v2.2): remove this legacy StrategySignal.auto_entry snapshot builder.
    """Builds explicit auto-entry disable snapshots from finalized pipeline gates."""

    def evaluate(
        self,
        *,
        signal: StrategySignal,
        risk_reward: RiskRewardAssessment,
        completeness: TradePlanCompletenessResult,
        no_trade_result: NoTradeFilterResult,
        candle_state: str,
        mode: str,
        status_reason: str | None = None,
        actionability_block_reason: str | None = None,
        actionability_block_message: str | None = None,
    ) -> SignalAutoEntrySnapshot | None:
        disabled_message = self._disabled_message(
            risk_reward=risk_reward,
            completeness=completeness,
            no_trade_result=no_trade_result,
            candle_state=candle_state,
            mode=mode,
            status_reason=status_reason,
            actionability_block_reason=actionability_block_reason,
            actionability_block_message=actionability_block_message,
        )
        if disabled_message is None:
            return None
        return SignalAutoEntrySnapshot(
            enabled=False,
            status="cancelled",
            message=disabled_message,
        )

    def _disabled_message(
        self,
        *,
        risk_reward: RiskRewardAssessment,
        completeness: TradePlanCompletenessResult,
        no_trade_result: NoTradeFilterResult,
        candle_state: str,
        mode: str,
        status_reason: str | None,
        actionability_block_reason: str | None,
        actionability_block_message: str | None,
    ) -> str | None:
        if actionability_block_message is not None:
            return actionability_block_message
        if candle_state == "open" and actionability_block_reason == "forming_candle":
            return "forming_candle: forming candle preview is not actionable until the candle closes"
        if no_trade_result.blocked:
            return status_reason or _no_trade_message(no_trade_result)
        if _is_production_mode(mode) and not completeness.complete:
            return status_reason or _incomplete_trade_plan_message(completeness)
        if risk_reward.blocked:
            return risk_reward.reason
        return None


def _is_production_mode(mode: str) -> bool:
    normalized = mode.strip().lower().replace("-", "_")
    return normalized in {"production", "production_like", "real"}


def _incomplete_trade_plan_message(completeness: TradePlanCompletenessResult) -> str:
    missing = ", ".join(completeness.missing) if completeness.missing else "structural trade plan"
    return f"Trade plan incomplete: {missing}; production actionability is blocked."


def _no_trade_message(no_trade_result: NoTradeFilterResult) -> str:
    blockers = "; ".join(no_trade_result.blockers) if no_trade_result.blockers else "No-trade filter blocked this entry."
    return f"No-trade hard block: {blockers}"


auto_entry_eligibility_service = AutoEntryEligibilityService()
