import asyncio
from typing import Any, List, Mapping

from app.schemas.market import AlphaMarketContext, Features
from app.schemas.signal import StrategySignal
from app.services.support_resistance import SupportResistanceSnapshot
from app.strategies.breakout import VolatilitySqueezeBreakoutStrategy
from app.strategies.liquidity_sweep import LiquiditySweepReversalStrategy
from app.strategies.pipeline import MarketQualityInput, StrategyEvaluationContext, StrategySignalPipeline
from app.strategies.trend_pullback import TrendPullbackContinuationStrategy


EXECUTION_PROFILE_PARAM_KEYS = {
    "account_balance",
    "account_equity",
    "available_balance",
    "backtest_rr_guard_mode",
    "discovery_rr_guard_mode",
    "fixed_risk_amount",
    "fixed_risk_currency",
    "futures_risk_per_trade_percent",
    "futures_max_leverage",
    "futures_max_open_risk_percent",
    "instrument_type",
    "leverage",
    "margin",
    "max_account_drawdown_percent",
    "max_correlated_risk_percent",
    "max_daily_loss_percent",
    "max_open_risk_percent",
    "max_weekly_loss_percent",
    "min_rr_ratio",
    "radar_display_mode",
    "real_rr_guard_mode",
    "required_margin",
    "rr_guard_mode",
    "rr_target",
    "risk_mode",
    "risk_percent",
    "risk_per_trade_percent",
    "size_usd",
    "spot_risk_per_trade_percent",
    "virtual_rr_guard_mode",
    "virtual_risk_per_trade_percent",
}


class StrategyEngine:
    """Запускает MVP-набор стратегий и возвращает отсортированные сигналы."""

    def __init__(self) -> None:
        self._strategies = [
            TrendPullbackContinuationStrategy(),
            VolatilitySqueezeBreakoutStrategy(),
            LiquiditySweepReversalStrategy(),
        ]
        self._pipeline = StrategySignalPipeline()

    @property
    def strategy_count(self) -> int:
        return len(self._strategies)

    @property
    def strategy_names(self) -> list[str]:
        return [strategy.name for strategy in self._strategies]

    async def generate_signals(
        self,
        features: Features,
        context_features: Features | None = None,
        context_features_by_timeframe: Mapping[str, Features] | None = None,
        support_resistance_by_timeframe: Mapping[str, SupportResistanceSnapshot] | None = None,
        market_quality: MarketQualityInput | None = None,
        strategy_configs: Mapping[str, Any] | None = None,
        rr_guard_context: str = "discovery",
        alpha_context: AlphaMarketContext | None = None,
    ) -> List[StrategySignal]:
        signals: List[StrategySignal] = []
        for strategy in self._strategies:
            runtime_config = strategy_configs.get(strategy.name) if strategy_configs is not None else None
            if strategy_configs is not None and runtime_config is None:
                continue
            setup_params = _strategy_logic_params(
                getattr(runtime_config, "params", {}) if runtime_config is not None else {}
            )
            pipeline_params = dict(setup_params)
            pipeline_params.update(getattr(runtime_config, "risk_settings", {}) if runtime_config is not None else {})
            if alpha_context is not None:
                setup_params["alpha_context"] = alpha_context
                pipeline_params["alpha_context"] = alpha_context
            if support_resistance_by_timeframe:
                setup_params["support_resistance_by_timeframe"] = support_resistance_by_timeframe
                pipeline_params["support_resistance_by_timeframe"] = support_resistance_by_timeframe
            context = StrategyEvaluationContext(
                signal_features=features,
                alpha_context=alpha_context,
                context_features=context_features,
                context_features_by_timeframe=context_features_by_timeframe or {},
                support_resistance_by_timeframe=support_resistance_by_timeframe or {},
                market_quality=market_quality,
                strategy_params=pipeline_params,
                pair_scope_configured=bool(getattr(runtime_config, "pair_scope_configured", False)),
                rr_guard_context=rr_guard_context,
            )
            candidates = await strategy.evaluate(features, setup_params)
            for candidate in candidates:
                finalized = self._pipeline.finalize(candidate, context)
                if finalized is not None:
                    signals.append(finalized)
            await asyncio.sleep(0)
        return sorted(signals, key=lambda signal: signal.score, reverse=True)


def _strategy_logic_params(values: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in dict(values or {}).items()
        if key not in EXECUTION_PROFILE_PARAM_KEYS
    }
