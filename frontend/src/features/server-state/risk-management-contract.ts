import openApiDocument from "@/api/generated/openapi.json";

import type { RiskManagementSettings, RiskProfileName } from "./types";

type NumericFieldLimits = {
  max?: number;
  min: number;
  minExclusive: boolean;
};

type OpenApiSchemaNode = {
  anyOf?: OpenApiSchemaNode[];
  exclusiveMinimum?: number;
  maximum?: number;
  minimum?: number;
  type?: string;
};

type OpenApiDocument = {
  components?: {
    schemas?: Record<string, { properties?: Record<string, OpenApiSchemaNode> }>;
  };
};

export type RiskProfilePresetName = Exclude<RiskProfileName, "custom">;

const DEFAULT_STRATEGY_RISK_MULTIPLIERS: RiskManagementSettings["strategy_risk_multipliers"] = {
  trend_pullback_continuation: 1,
  volatility_squeeze_breakout: 0.75,
  liquidity_sweep_reversal: 1,
  trend_following: 1,
  breakout: 0.75,
  smart_money_setup: 1,
  scalping: 0.5,
  mean_reversion: 0.75,
  news_event_trade: 0.25
};

export const DEFAULT_RISK_MANAGEMENT_SETTINGS: RiskManagementSettings = {
  risk_profile: "balanced",
  risk_mode: "percent",
  risk_per_trade_percent: 1,
  fixed_risk_amount: null,
  fixed_risk_currency: "USDT",
  radar_display_mode: "all_market_opportunities",
  min_rr_ratio: 2,
  rr_guard_mode: "soft",
  discovery_rr_guard_mode: "soft",
  real_rr_guard_mode: "hard",
  virtual_rr_guard_mode: "soft",
  backtest_rr_guard_mode: "soft",
  strategy_rr_guard_modes: {},
  max_daily_loss_percent: 3,
  max_weekly_loss_percent: 7,
  max_account_drawdown_percent: 10,
  max_open_risk_percent: 5,
  max_correlated_risk_percent: 3,
  max_spread_bps: 50,
  max_slippage_bps: 150,
  max_price_deviation_bps: 100,
  max_orderbook_liquidity_ratio: 1,
  include_fees_in_risk: true,
  include_slippage_in_risk: true,
  stop_loss_required: true,
  take_profit_required: true,
  stop_loss_mode: "fixed_percent",
  default_stop_loss_percent: 1.5,
  atr_period: 14,
  atr_multiplier: 2,
  take_profit_mode: "risk_multiple",
  tp1_r_multiple: 1,
  tp2_r_multiple: 2,
  tp3_r_multiple: 3,
  partial_take_profit_enabled: true,
  tp1_close_percent: 30,
  tp2_close_percent: 40,
  tp3_close_percent: 30,
  move_sl_to_breakeven_after_r: 1,
  breakeven_offset_percent: 0.05,
  trailing_stop_enabled: true,
  trailing_mode: "atr",
  trailing_atr_multiplier: 1.5,
  trailing_stop_percent: 0.5,
  max_leverage: 3,
  min_liquidation_buffer_percent: 2,
  liquidation_buffer_required: true,
  spot_risk_per_trade_percent: 1,
  spot_max_position_size_percent: 20,
  spot_stop_required: true,
  futures_risk_per_trade_percent: 0.5,
  futures_max_leverage: 3,
  futures_max_open_risk_percent: 3,
  futures_liquidation_buffer_required: true,
  virtual_risk_mode: "same_as_real",
  virtual_risk_per_trade_percent: 1,
  virtual_starting_balance: 10000,
  virtual_slippage_model: "spread_based",
  virtual_fee_model: "exchange_based",
  virtual_trading_uses_realistic_execution: true,
  strategy_risk_multipliers: DEFAULT_STRATEGY_RISK_MULTIPLIERS,
  auto_reduce_risk_after_losses: true,
  allow_risk_increase_after_profit: false,
  increase_risk_after_profit_streak: false,
  max_risk_boost: 1.25
};

// Mirrors backend/app/services/risk_management.py RISK_PROFILE_PRESETS.
export const RISK_PROFILE_PRESETS: Record<RiskProfilePresetName, RiskManagementSettings> = {
  conservative: {
    ...DEFAULT_RISK_MANAGEMENT_SETTINGS,
    risk_profile: "conservative",
    risk_per_trade_percent: 0.5,
    max_daily_loss_percent: 1.5,
    max_account_drawdown_percent: 8,
    max_open_risk_percent: 3,
    strategy_risk_multipliers: DEFAULT_STRATEGY_RISK_MULTIPLIERS
  },
  balanced: {
    ...DEFAULT_RISK_MANAGEMENT_SETTINGS,
    risk_profile: "balanced",
    strategy_risk_multipliers: DEFAULT_STRATEGY_RISK_MULTIPLIERS
  },
  aggressive: {
    ...DEFAULT_RISK_MANAGEMENT_SETTINGS,
    risk_profile: "aggressive",
    risk_per_trade_percent: 1.5,
    min_rr_ratio: 1.5,
    max_daily_loss_percent: 4,
    max_account_drawdown_percent: 15,
    max_open_risk_percent: 7,
    strategy_risk_multipliers: DEFAULT_STRATEGY_RISK_MULTIPLIERS
  }
};

export const RISK_MANAGEMENT_SCHEMA_LIMITS = {
  fixed_risk_amount: numericFieldLimits("RiskManagementPatch", "fixed_risk_amount"),
  futures_max_leverage: numericFieldLimits("RiskManagementPatch", "futures_max_leverage"),
  max_leverage: numericFieldLimits("RiskManagementPatch", "max_leverage"),
  risk_per_trade_percent: numericFieldLimits("RiskManagementPatch", "risk_per_trade_percent")
} as const;

export const STRATEGY_EXECUTION_SCHEMA_LIMITS = {
  fixed_risk_amount: numericFieldLimits("StrategyExecutionSettings-Input", "fixed_risk_amount"),
  leverage: numericFieldLimits("StrategyExecutionSettings-Input", "leverage"),
  risk_percent: numericFieldLimits("StrategyExecutionSettings-Input", "risk_percent")
} as const;

export function cloneRiskManagementSettings(
  settings: RiskManagementSettings = DEFAULT_RISK_MANAGEMENT_SETTINGS
): RiskManagementSettings {
  return {
    ...settings,
    strategy_risk_multipliers: { ...settings.strategy_risk_multipliers },
    strategy_rr_guard_modes: { ...settings.strategy_rr_guard_modes }
  };
}

export function riskProfilePreset(profile: RiskProfileName): RiskManagementSettings {
  if (profile === "custom") {
    return cloneRiskManagementSettings({
      ...DEFAULT_RISK_MANAGEMENT_SETTINGS,
      risk_profile: "custom"
    });
  }

  return cloneRiskManagementSettings(RISK_PROFILE_PRESETS[profile]);
}

function numericFieldLimits(schemaName: string, fieldName: string): NumericFieldLimits {
  const document = openApiDocument as OpenApiDocument;
  const fieldSchema = document.components?.schemas?.[schemaName]?.properties?.[fieldName];
  const numericSchema = (fieldSchema?.anyOf ?? [fieldSchema]).find(
    (schema): schema is OpenApiSchemaNode => schema?.type === "number" || schema?.type === "integer"
  );

  if (!numericSchema) {
    throw new Error(`Missing numeric OpenAPI schema for ${schemaName}.${fieldName}`);
  }

  const min = numericSchema.minimum ?? numericSchema.exclusiveMinimum;
  if (typeof min !== "number") {
    throw new Error(`Missing minimum OpenAPI limit for ${schemaName}.${fieldName}`);
  }

  return {
    max: numericSchema.maximum,
    min,
    minExclusive: typeof numericSchema.exclusiveMinimum === "number"
  };
}
