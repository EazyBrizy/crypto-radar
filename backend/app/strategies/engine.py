import asyncio
from typing import Any, List, Mapping

from app.schemas.market import AlphaMarketContext, Features
from app.schemas.risk import StrategyExecutionSettings
from app.schemas.signal import StrategySignal
from app.services.edge_calibration import edge_calibration_service
from app.services.market_regime import MarketWideRegimeContext
from app.services.signal_execution_gate import signal_execution_gate_service
from app.services.support_resistance import SupportResistanceSnapshot
from app.strategies.pipeline import MarketQualityInput, StrategyEvaluationContext, StrategySignalPipeline
from app.strategies.plugins import StrategyPluginDiagnostics, StrategyPluginRegistry, default_strategy_plugin_registry


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
    "trade_plan_missing_context_policy",
    "trade_plan_missing_score_policy",
    "virtual_rr_guard_mode",
    "virtual_risk_per_trade_percent",
}


class StrategyEngine:
    """Запускает MVP-набор стратегий и возвращает отсортированные сигналы."""

    def __init__(self, strategy_registry: StrategyPluginRegistry | None = None) -> None:
        self._strategy_registry = strategy_registry or default_strategy_plugin_registry
        self._strategies = self._strategy_registry.trading_plugins
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
        market_wide_context: MarketWideRegimeContext | None = None,
    ) -> List[StrategySignal]:
        signals: List[StrategySignal] = []
        for strategy in self._strategies:
            runtime_config = strategy_configs.get(strategy.name) if strategy_configs is not None else None
            if strategy_configs is not None and runtime_config is None:
                continue
            market_params = _strategy_logic_params(
                getattr(runtime_config, "params", {}) if runtime_config is not None else {}
            )
            execution_settings = StrategyExecutionSettings.model_validate(
                (getattr(runtime_config, "risk_settings", {}) if runtime_config is not None else {}) or {}
            )
            pipeline_settings = _pipeline_settings_for_pipeline_only(market_params, execution_settings)
            if alpha_context is not None:
                market_params["alpha_context"] = alpha_context
                pipeline_settings["alpha_context"] = alpha_context
            if support_resistance_by_timeframe:
                market_params["support_resistance_by_timeframe"] = support_resistance_by_timeframe
                pipeline_settings["support_resistance_by_timeframe"] = support_resistance_by_timeframe
            context = StrategyEvaluationContext(
                signal_features=features,
                alpha_context=alpha_context,
                context_features=context_features,
                context_features_by_timeframe=context_features_by_timeframe or {},
                support_resistance_by_timeframe=support_resistance_by_timeframe or {},
                market_quality=market_quality,
                market_wide_context=market_wide_context,
                strategy_params=market_params,
                execution_settings=execution_settings,
                pipeline_settings=pipeline_settings,
                pair_scope_configured=bool(getattr(runtime_config, "pair_scope_configured", False)),
                rr_guard_context=rr_guard_context,
            )
            candidates = await strategy.evaluate(features, market_params)
            for candidate in candidates:
                finalized = self._pipeline.finalize(candidate, context)
                if finalized is not None:
                    edge = await edge_calibration_service.evaluate_signal_edge(finalized)
                    finalized = finalized.model_copy(update={"edge": edge})
                    finalized = finalized.model_copy(
                        update={
                            "execution_gate": signal_execution_gate_service.evaluate(
                                finalized,
                                strict_edge_mode=_bool_param(pipeline_settings, "strict_edge_mode", False),
                            )
                        }
                    )
                    signals.append(finalized)
            await asyncio.sleep(0)
        return sorted(signals, key=lambda signal: signal.score, reverse=True)

    def generate_diagnostics(
        self,
        features: Features,
        strategy_configs: Mapping[str, Any] | None = None,
    ) -> list[StrategyPluginDiagnostics]:
        diagnostics: list[StrategyPluginDiagnostics] = []
        for plugin in self._strategy_registry.diagnostic_plugins:
            runtime_config = strategy_configs.get(plugin.name) if strategy_configs is not None else None
            params = getattr(runtime_config, "params", {}) if runtime_config is not None else {}
            diagnostics.append(plugin.diagnostics(features, params))
        return diagnostics


def _strategy_logic_params(values: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in dict(values or {}).items()
        if key not in EXECUTION_PROFILE_PARAM_KEYS
    }


def _pipeline_settings_for_pipeline_only(
    market_params: Mapping[str, Any],
    execution_settings: StrategyExecutionSettings,
) -> dict[str, Any]:
    pipeline_settings = dict(market_params)
    pipeline_settings.update(execution_settings.to_legacy_dict(exclude_unset=True))
    return pipeline_settings


def _bool_param(values: Mapping[str, Any], key: str, default: bool) -> bool:
    value = values.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value) if value is not None else default
