"use client";

import { AlertTriangle, Bell, BookOpen, CheckSquare, ChevronDown, FlaskConical, Gauge, Info, KeyRound, ListChecks, Radio, RefreshCw, Save, Send, Shield, SlidersHorizontal, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";

import { Badge } from "@/components/Badge";
import { StrategyTestingPanel } from "@/features/strategy-testing/StrategyTestingPanel";
import { useI18n, type I18nKey } from "@/i18n";
import {
  RISK_MANAGEMENT_SCHEMA_LIMITS,
  RISK_PROFILE_PRESETS,
  STRATEGY_EXECUTION_SCHEMA_LIMITS,
  cloneRiskManagementSettings,
  riskProfilePreset,
  type RiskProfilePresetName
} from "@/features/server-state/risk-management-contract";
import type {
  AccountRiskSnapshot,
  AlertRule,
  AlertRuleDraft,
  ExchangeConnection,
  ExchangeConnectionDraft,
  ExchangeWalletBalance,
  MarketPairOption,
  MarketUniverseLimit,
  MarketUniversePair,
  RadarDisplayMode,
  RiskManagementSettings,
  RiskAmountMode,
  RiskProfileName,
  RRGuardMode,
  StopLossMode,
  StrategyConfig,
  StrategyConfigPatch,
  StrategyPairScope,
  TrailingMode,
  VirtualFeeModel,
  VirtualRiskMode,
  VirtualSlippageModel,
  UserProfile,
  UserSettingsPatch,
  VirtualSimulationLevel
} from "@/features/server-state/types";
import {
  useMarketUniversePairsQuery,
  useSyncMarketUniverseMutation
} from "@/features/server-state/use-server-state";
import type { RadarConfig, RiskProtectionMode, RiskStateResponse } from "@/types";

interface SettingsPageProps {
  config: RadarConfig | null;
  availablePairs: MarketPairOption[];
  strategyConfigs: StrategyConfig[];
  alertRules: AlertRule[];
  exchangeConnections: ExchangeConnection[];
  exchangeAccountSnapshots: Record<string, AccountRiskSnapshot | null>;
  exchangeBalanceLoading: Record<string, boolean>;
  exchangeWalletBalances: Record<string, ExchangeWalletBalance | null>;
  userProfile: UserProfile | null;
  riskState: RiskStateResponse | null;
  busy: boolean;
  onCreateAlert: (draft: AlertRuleDraft) => Promise<unknown>;
  onToggleAlert: (alertId: string, isEnabled: boolean) => Promise<unknown>;
  onDeleteAlert: (alertId: string) => Promise<unknown>;
  onTestAlert: (alertId: string) => Promise<unknown>;
  onCreateExchangeConnection: (draft: ExchangeConnectionDraft) => Promise<unknown>;
  onUpdateExchangeConnection: (connectionId: string, patch: Partial<ExchangeConnectionDraft> & { status?: string }) => Promise<unknown>;
  onToggleExchangeConnection: (connectionId: string, isActive: boolean) => Promise<unknown>;
  onDeleteExchangeConnection: (connectionId: string) => Promise<unknown>;
  onRefreshExchangeBalance: (connectionId: string) => Promise<unknown>;
  onTestExchangeConnection: (connectionId: string) => Promise<unknown>;
  onSyncExchangeConnection: (connectionId: string) => Promise<unknown>;
  onSelectSimulationLevel: (simulationLevel: VirtualSimulationLevel) => Promise<unknown>;
  onUpdateStrategyConfig: (configId: string, patch: StrategyConfigPatch) => Promise<unknown>;
  onUpdateRiskManagement: (patch: UserSettingsPatch) => Promise<unknown>;
}

type TKey = (key: I18nKey, params?: Record<string, string | number | boolean | null | undefined>) => string;

const SIMULATION_LEVELS: Array<{
  value: VirtualSimulationLevel;
  label: string;
  caption: string;
  status: "active" | "stub";
}> = [
  {
    value: "mvp",
    label: "MVP",
    caption: "Virtual depth, spread, slippage",
    status: "active"
  },
  {
    value: "advanced",
    label: "Advanced",
    caption: "Virtual queue, fees, liquidity",
    status: "stub"
  },
  {
    value: "pro",
    label: "Pro",
    caption: "Replay, Monte Carlo",
    status: "stub"
  }
];

const RISK_PROFILES: Array<{
  value: RiskProfileName;
  label: string;
  caption: string;
}> = [
  { value: "conservative", label: "Conservative", caption: "Lower risk limits" },
  { value: "balanced", label: "Balanced", caption: "Default profile" },
  { value: "aggressive", label: "Aggressive", caption: "Wider risk budget" },
  { value: "custom", label: "Custom", caption: "Manual limits" }
];

const RISK_AMOUNT_MODES: Array<{ value: RiskAmountMode; label: string }> = [
  { value: "percent", label: "Percent" },
  { value: "fixed", label: "Fixed" }
];

const RADAR_DISPLAY_MODES: Array<{ value: RadarDisplayMode; label: string }> = [
  { value: "all_market_opportunities", label: "All market opportunities" },
  { value: "market_ideas", label: "Market ideas" },
  { value: "watchlist", label: "Watchlist" },
  { value: "execution_ready", label: "Execution-ready only" },
  { value: "blocked", label: "Blocked ideas" }
];

const STRATEGY_TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"];
const MARKET_UNIVERSE_LIMITS: Array<{ value: MarketUniverseLimit; label: string }> = [
  { value: "top_100", label: "Top 100" },
  { value: "top_200", label: "Top 200" },
  { value: "top_500", label: "Top 500" },
  { value: "all", label: "All" }
];
const MARKET_UNIVERSE_CATEGORIES = [
  { value: "linear", label: "USDT Perpetual" }
];
const MARKET_UNIVERSE_SORTS = [
  { value: "turnover_24h_desc", label: "24h turnover" }
];
const MARKET_UNIVERSE_TIERS = [
  { value: "", label: "All tiers" },
  { value: "high", label: "High" },
  { value: "medium", label: "Medium" },
  { value: "low", label: "Low" },
  { value: "unknown", label: "Unknown" }
];
const DEFAULT_MARKET_UNIVERSE_FILTERS = {
  category: "linear",
  exchange: "bybit",
  limit: "top_100" as MarketUniverseLimit,
  liquidity_tier: "",
  quote: "USDT",
  search: "",
  sort: "turnover_24h_desc",
  status: "active/trading"
};
const MARKET_UNIVERSE_EXCHANGE_LABELS = {
  bybit: "Bybit"
} as const;
const EMPTY_MARKET_UNIVERSE_PAIRS: MarketUniversePair[] = [];
const EXECUTION_PROFILE_HELP = {
  fixedRisk: "Fixed risk is the maximum loss budget in the selected currency. Backend RiskGate still caps and sizes the trade.",
  leverage: "Leverage changes required margin and futures liquidation checks. It does not reduce trade risk.",
  percentRisk: "Percent risk is the equity percentage the profile may risk per trade before backend caps and multipliers.",
  radarMode: "All shows every market setup. Execution-ready shows only opportunities passing a read-only RiskGate preview now.",
  rrGuard: "Hard can block execution, soft records a warning, and off records RR only.",
  virtualVsReal: "Virtual is simulation/paper execution. Real execution reruns RiskGate and readiness checks on fresh account, market, and exchange-rule data."
} as const;
const MAX_BODY_ATR_DEFAULTS: Record<string, number> = {
  trend_pullback_continuation: 2.0,
  volatility_squeeze_breakout: 2.5,
  liquidity_sweep_reversal: 2.0
};
const MAX_RANGE_ATR_DEFAULTS: Record<string, number> = {
  trend_pullback_continuation: 3.0,
  volatility_squeeze_breakout: 3.5,
  liquidity_sweep_reversal: 3.8
};
const RR_TARGET_DEFAULTS: Record<string, "final" | "nearest"> = {
  trend_pullback_continuation: "final",
  volatility_squeeze_breakout: "final",
  liquidity_sweep_reversal: "nearest"
};
const RR_GUARD_MODES: Array<{
  value: RRGuardMode;
  labelKey: I18nKey;
}> = [
  { value: "soft", labelKey: "settings.soft" },
  { value: "hard", labelKey: "settings.hard" },
  { value: "off", labelKey: "common.off" }
];
const SQUEEZE_BREAKOUT_FIELD_LABELS: Array<{
  key: string;
  label: string;
  step: string;
  min: string;
  max?: string;
  defaultValue: number;
}> = [
  { key: "bb_width_percentile_threshold", label: "BB squeeze %", step: "1", min: "0", max: "100", defaultValue: 20 },
  { key: "volume_spike_multiplier", label: "Volume x", step: "0.1", min: "0", defaultValue: 1.5 },
  { key: "min_close_position", label: "Close strength", step: "0.05", min: "0", max: "1", defaultValue: 0.7 },
  { key: "max_breakout_wick_ratio", label: "Max wick", step: "0.05", min: "0", max: "1", defaultValue: 0.35 },
  { key: "max_squeeze_range_atr", label: "Range ATR", step: "0.1", min: "1", defaultValue: 5 }
];

const LIQUIDITY_SWEEP_FIELD_LABELS: Array<{
  key: string;
  label: string;
  step: string;
  min: string;
  max?: string;
  defaultValue: number;
}> = [
  { key: "min_sweep_wick_ratio", label: "Min wick", step: "0.05", min: "0", max: "1", defaultValue: 0.45 },
  { key: "sweep_volume_spike_multiplier", label: "Sweep volume x", step: "0.1", min: "0", defaultValue: 1.3 },
  { key: "confirmation_volume_spike", label: "Confirm volume x", step: "0.1", min: "0", defaultValue: 1.1 },
  { key: "sweep_aggressive_close_position", label: "Close strength", step: "0.05", min: "0", max: "1", defaultValue: 0.6 },
  { key: "sweep_stop_atr", label: "Stop ATR", step: "0.1", min: "0", defaultValue: 0.3 },
  { key: "min_level_retests", label: "Level retests", step: "1", min: "0", defaultValue: 2 },
  { key: "sweep_level_confluence_atr", label: "HTF level ATR", step: "0.1", min: "0", defaultValue: 0.5 }
];

type RiskNumericField =
  | "risk_per_trade_percent"
  | "min_rr_ratio"
  | "max_daily_loss_percent"
  | "max_weekly_loss_percent"
  | "max_account_drawdown_percent"
  | "max_open_risk_percent"
  | "max_correlated_risk_percent"
  | "max_spread_bps"
  | "max_slippage_bps"
  | "max_price_deviation_bps"
  | "max_orderbook_liquidity_ratio"
  | "default_stop_loss_percent"
  | "atr_period"
  | "atr_multiplier"
  | "tp1_r_multiple"
  | "tp2_r_multiple"
  | "tp3_r_multiple"
  | "tp1_close_percent"
  | "tp2_close_percent"
  | "tp3_close_percent"
  | "move_sl_to_breakeven_after_r"
  | "breakeven_offset_percent"
  | "trailing_atr_multiplier"
  | "trailing_stop_percent"
  | "max_leverage"
  | "min_liquidation_buffer_percent"
  | "spot_risk_per_trade_percent"
  | "spot_max_position_size_percent"
  | "futures_risk_per_trade_percent"
  | "futures_max_leverage"
  | "futures_max_open_risk_percent"
  | "virtual_risk_per_trade_percent"
  | "virtual_starting_balance"
  | "max_risk_boost";

type RiskGuardField =
  | "rr_guard_mode"
  | "discovery_rr_guard_mode"
  | "virtual_rr_guard_mode"
  | "backtest_rr_guard_mode"
  | "real_rr_guard_mode";

type RiskValidationField =
  | "fixed_risk_amount"
  | "futures_max_leverage"
  | "max_leverage"
  | "risk_per_trade_percent";

type RiskValidationErrors = Partial<Record<RiskValidationField, string>>;

type NumericInputLimits = {
  max?: number;
  min: number;
  minExclusive: boolean;
};

const RR_GUARD_FIELD_LABELS: Array<{
  key: RiskGuardField;
  label: string;
}> = [
  { key: "rr_guard_mode", label: "Generic R:R guard" },
  { key: "discovery_rr_guard_mode", label: "Signal discovery R:R guard" },
  { key: "virtual_rr_guard_mode", label: "Virtual / paper R:R guard" },
  { key: "backtest_rr_guard_mode", label: "Backtest R:R guard" },
  { key: "real_rr_guard_mode", label: "Real execution R:R guard" }
];

const RISK_PROFILE_FIELD_LABELS: Array<{
  key: RiskNumericField;
  label: string;
  suffix: string;
  step: string;
}> = [
  { key: "risk_per_trade_percent", label: "Risk / trade", suffix: "%", step: "0.05" },
  { key: "max_daily_loss_percent", label: "Daily Stop-Loss", suffix: "%", step: "0.1" },
  { key: "max_weekly_loss_percent", label: "Weekly Stop-Loss", suffix: "%", step: "0.5" },
  { key: "max_account_drawdown_percent", label: "Max drawdown", suffix: "%", step: "0.5" },
  { key: "max_open_risk_percent", label: "Open risk cap", suffix: "%", step: "0.1" },
  { key: "max_correlated_risk_percent", label: "Correlated risk", suffix: "%", step: "0.1" }
];

const TRADE_RULE_FIELD_LABELS: Array<{
  key: RiskNumericField;
  label: string;
  suffix: string;
  step: string;
}> = [
  { key: "min_rr_ratio", label: "Min R:R for execution / reporting", suffix: "R", step: "0.1" },
  { key: "max_spread_bps", label: "Max spread", suffix: "bps", step: "1" },
  { key: "max_slippage_bps", label: "Max slippage", suffix: "bps", step: "5" },
  { key: "max_price_deviation_bps", label: "Max price drift", suffix: "bps", step: "5" },
  { key: "max_orderbook_liquidity_ratio", label: "Max book use", suffix: "x", step: "0.05" }
];

const STOP_LOSS_MODES: Array<{
  value: StopLossMode;
  label: string;
  caption: string;
}> = [
  { value: "fixed_percent", label: "Fixed %", caption: "Simple MVP stop" },
  { value: "atr", label: "ATR", caption: "Volatility-based" },
  { value: "structure", label: "Structure", caption: "Signal invalidation" }
];

const STOP_LOSS_FIELD_LABELS: Array<{
  key: RiskNumericField;
  label: string;
  suffix: string;
  step: string;
}> = [
  { key: "default_stop_loss_percent", label: "Fixed stop", suffix: "%", step: "0.1" },
  { key: "atr_period", label: "ATR period", suffix: "", step: "1" },
  { key: "atr_multiplier", label: "ATR multiplier", suffix: "x", step: "0.25" }
];

const TAKE_PROFIT_FIELD_LABELS: Array<{
  key: RiskNumericField;
  label: string;
  suffix: string;
  step: string;
}> = [
  { key: "tp1_r_multiple", label: "TP1", suffix: "R", step: "0.25" },
  { key: "tp2_r_multiple", label: "TP2", suffix: "R", step: "0.25" },
  { key: "tp3_r_multiple", label: "TP3", suffix: "R", step: "0.25" }
];

const PARTIAL_TAKE_PROFIT_FIELD_LABELS: Array<{
  key: RiskNumericField;
  label: string;
  suffix: string;
  step: string;
}> = [
  { key: "tp1_close_percent", label: "TP1 close", suffix: "%", step: "5" },
  { key: "tp2_close_percent", label: "TP2 close", suffix: "%", step: "5" },
  { key: "tp3_close_percent", label: "TP3 close", suffix: "%", step: "5" }
];

const BREAKEVEN_FIELD_LABELS: Array<{
  key: RiskNumericField;
  label: string;
  suffix: string;
  step: string;
}> = [
  { key: "move_sl_to_breakeven_after_r", label: "Move after", suffix: "R", step: "0.25" },
  { key: "breakeven_offset_percent", label: "Offset", suffix: "%", step: "0.01" }
];

const TRAILING_MODES: Array<{
  value: TrailingMode;
  label: string;
  caption: string;
}> = [
  { value: "atr", label: "ATR", caption: "Swing-friendly trailing" },
  { value: "percent", label: "Percent", caption: "Scalping trailing" },
  { value: "structure", label: "Structure", caption: "Trail behind market structure" }
];

const TRAILING_FIELD_LABELS: Array<{
  key: RiskNumericField;
  label: string;
  suffix: string;
  step: string;
}> = [
  { key: "trailing_atr_multiplier", label: "ATR trail", suffix: "x", step: "0.25" },
  { key: "trailing_stop_percent", label: "Percent trail", suffix: "%", step: "0.1" }
];

const FUTURES_FIELD_LABELS: Array<{
  key: RiskNumericField;
  label: string;
  suffix: string;
  step: string;
}> = [
  { key: "max_leverage", label: "Max leverage", suffix: "x", step: "1" },
  { key: "min_liquidation_buffer_percent", label: "Liq. buffer", suffix: "%", step: "0.25" }
];

const TRADE_TYPE_FIELD_LABELS: Array<{
  key: RiskNumericField;
  label: string;
  suffix: string;
  step: string;
}> = [
  { key: "spot_risk_per_trade_percent", label: "Spot risk", suffix: "%", step: "0.05" },
  { key: "spot_max_position_size_percent", label: "Spot max size", suffix: "%", step: "0.5" },
  { key: "futures_risk_per_trade_percent", label: "Futures risk", suffix: "%", step: "0.05" },
  { key: "futures_max_leverage", label: "Futures max lev.", suffix: "x", step: "1" },
  { key: "futures_max_open_risk_percent", label: "Futures open risk", suffix: "%", step: "0.1" },
  { key: "virtual_risk_per_trade_percent", label: "Virtual risk", suffix: "%", step: "0.05" },
  { key: "virtual_starting_balance", label: "Virtual balance", suffix: "USDT", step: "100" }
];

const SPOT_TRADE_TYPE_FIELD_LABELS = TRADE_TYPE_FIELD_LABELS.filter((field) =>
  field.key === "spot_risk_per_trade_percent" || field.key === "spot_max_position_size_percent"
);

const FUTURES_TRADE_TYPE_FIELD_LABELS = TRADE_TYPE_FIELD_LABELS.filter((field) =>
  field.key === "futures_risk_per_trade_percent" ||
  field.key === "futures_max_leverage" ||
  field.key === "futures_max_open_risk_percent"
);

const VIRTUAL_TRADE_TYPE_FIELD_LABELS = TRADE_TYPE_FIELD_LABELS.filter((field) =>
  field.key === "virtual_risk_per_trade_percent" || field.key === "virtual_starting_balance"
);

const VIRTUAL_RISK_MODES: Array<{ value: VirtualRiskMode; label: string }> = [
  { value: "same_as_real", label: "Same as real" },
  { value: "custom", label: "Separate" }
];

const VIRTUAL_SLIPPAGE_MODELS: Array<{ value: VirtualSlippageModel; label: string }> = [
  { value: "none", label: "None" },
  { value: "fixed_percent", label: "Fixed" },
  { value: "spread_based", label: "Spread" },
  { value: "orderbook_based", label: "Orderbook" },
  { value: "volatility_based", label: "Volatility" }
];

const VIRTUAL_FEE_MODELS: Array<{ value: VirtualFeeModel; label: string }> = [
  { value: "exchange_based", label: "Exchange" },
  { value: "manual", label: "Manual" }
];

type RiskSettingsTab = "profile" | "rules" | "futures" | "virtual" | "guide";
type SettingsSectionId = "exchanges" | "strategies" | "risk" | "simulation" | "strategyTesting" | "alerts" | "timeframes";

const RISK_SETTINGS_TABS: Array<{ value: RiskSettingsTab; label: string }> = [
  { value: "profile", label: "Risk Profile" },
  { value: "rules", label: "Trade Rules" },
  { value: "futures", label: "Futures Protection" },
  { value: "virtual", label: "Virtual Trading" },
  { value: "guide", label: "Guide" }
];

const STRATEGY_MULTIPLIER_LABELS: Record<string, string> = {
  trend_following: "Trend-following",
  trend_pullback_continuation: "Trend pullback",
  breakout: "Breakout",
  scalping: "Scalping",
  mean_reversion: "Mean reversion",
  smart_money_setup: "Smart Money",
  news_event_trade: "News/Event"
};

interface RiskGuideItem {
  title: string;
  body: string;
  tip?: string;
}

interface RiskGuideSection {
  title: string;
  intro: string;
  items: RiskGuideItem[];
}

const RISK_BLOCKER_GUIDE: RiskGuideItem[] = [
  {
    title: "Open risk cap",
    body: "Сумма риска по уже открытым позициям плюс новый риск выше лимита. Часто это причина, когда в virtual уже накопились позиции.",
    tip: "Закройте старые virtual-позиции, снизьте Risk / trade или поднимите Open risk cap только для тестового профиля."
  },
  {
    title: "Correlated risk",
    body: "Новая сделка усиливает тот же кластер: например несколько L1 long или majors short. Это не отдельный риск, а один directional risk.",
    tip: "Для обучения можно поднять Correlated risk, но в real лучше оставлять его ниже Open risk cap."
  },
  {
    title: "Min R:R for execution / reporting",
    body: "Backend пересчитывает R:R от реальной цены входа, стопа, комиссий и проскальзывания. Если цена ушла, бумажный 2R может стать 1.3R.",
    tip: "Для MVP-тестов допустимо временно поставить 1.5R, но для real 2R остается более дисциплинированным уровнем."
  },
  {
    title: "Spread, slippage, price drift",
    body: "Если bid/ask, ожидаемое исполнение или уход цены от сигнала ломают план сделки, risk-gate блокирует вход.",
    tip: "Расширяйте эти лимиты осторожно: они напрямую увеличивают фактический убыток при стопе."
  },
  {
    title: "Futures liquidation guard",
    body: "Для futures сделка должна иметь стоп раньше ликвидации и достаточный буфер. Плечо уменьшает маржу, но не уменьшает риск сделки.",
    tip: "Снижайте leverage или увеличивайте дистанцию до стопа, если liquidation guard не проходит."
  }
];

const RISK_GUIDE_SECTIONS: RiskGuideSection[] = [
  {
    title: "1. Risk Profile",
    intro: "Главный блок отвечает за размер риска и общие лимиты аккаунта. Здесь система решает, сколько можно потерять, а не сколько купить.",
    items: [
      {
        title: "Conservative / Balanced / Aggressive / Custom",
        body: "Пресеты быстро задают набор лимитов. Conservative сужает риск, Balanced является базовым профилем, Aggressive дает больше свободы, Custom открывает ручное редактирование всех полей.",
        tip: "Если нужно понять, почему сделки не проходят, переключайтесь в Custom и меняйте по одному лимиту."
      },
      {
        title: "Risk / trade",
        body: "Процент equity, который пользователь готов потерять при срабатывании стопа. Это не размер позиции. Backend считает position size от этого риска, стопа, комиссий и проскальзывания.",
        tip: "Если позиции слишком большие или быстро забивается Open risk cap, уменьшайте это значение."
      },
      {
        title: "Daily Stop-Loss",
        body: "Дневной лимит убытка. После достижения лимита real entries должны переходить в close-only, чтобы можно было только закрывать или уменьшать риск.",
        tip: "Значение 0 выключает именно этот лимит. Для real лучше выключать только осознанно."
      },
      {
        title: "Weekly Stop-Loss",
        body: "Недельный лимит убытка. Защищает от серии плохих дней, когда дневной стоп несколько раз подряд уже был достигнут.",
        tip: "Значение 0 выключает недельную блокировку."
      },
      {
        title: "Max drawdown",
        body: "Максимальная просадка от peak equity. Если лимит достигнут, protection state может снизить риск, включить virtual-only или заблокировать новые входы.",
        tip: "Значение 0 выключает лимит просадки, но peak equity все равно сохраняется."
      },
      {
        title: "Open risk cap",
        body: "Максимальный суммарный риск всех открытых позиций. Если уже открыто несколько сделок по 1%, новая сделка добавляет еще риск к общей корзине.",
        tip: "Значение 0 выключает этот лимит. Если сейчас не открывается ни одна сделка, первым делом проверьте Open risk."
      },
      {
        title: "Correlated risk",
        body: "Лимит по связанным активам и направлению: majors, L1, L2, meme, DeFi, AI и другие группы. BTC long, ETH long и SOL long не считаются полностью независимыми.",
        tip: "Значение 0 выключает кластерный лимит. Для real лучше держать его ниже общего Open risk cap."
      },
      {
        title: "Fees included / Slippage included",
        body: "Комиссии и проскальзывание входят в effective risk per unit. Это уменьшает разрешенный position size, зато не дает превысить риск при реальном исполнении.",
        tip: "В MVP для новичков эти флаги намеренно включены как защитный стандарт."
      },
      {
        title: "Stop required / TP required",
        body: "Без стопа risk-gate не может посчитать position size. Take-profit нужен для проверки минимального Risk/Reward.",
        tip: "Если стратегия еще не умеет давать стоп или TP, такая сделка должна оставаться только аналитическим сигналом."
      },
      {
        title: "Spot risk",
        body: "Отдельный риск на spot-сделку. Spot не имеет liquidation price, но все равно учитывает стоп, комиссии, проскальзывание и максимальный размер позиции.",
        tip: "Spot max size ограничивает долю депозита, которую можно занять одной spot-позицией."
      },
      {
        title: "Adaptive risk",
        body: "Автоматическое снижение риска после серии убытков или просадки. Adaptive multiplier умножает финальный риск до расчета позиции.",
        tip: "Risk increase после прибыли лучше держать выключенным для MVP и новичков."
      }
    ]
  },
  {
    title: "2. Trade Rules",
    intro: "Эти настройки проверяют качество сделки перед входом: достаточно ли прибыли к риску и не испортилось ли исполнение.",
    items: [
      {
        title: "Min R:R for execution / reporting",
        body: "Минимальное качество сделки по соотношению цели и стопа. Backend пересматривает это качество по актуальной цене входа.",
        tip: "Значение 0 выключает эту проверку. Если рынок ушел от entry, backend все равно покажет изменившийся риск в карточке."
      },
      {
        title: "Max spread",
        body: "Максимально допустимая ширина bid/ask. Широкий spread означает дорогой вход и выход.",
        tip: "Значение 0 выключает spread-блокировку. Для low-cap лучше тестировать отдельно в virtual."
      },
      {
        title: "Max slippage",
        body: "Ожидаемое ухудшение цены исполнения. Оно добавляется к effective risk, поэтому влияет на position size и блокировки.",
        tip: "Значение 0 выключает slippage-блокировку. Если часто блокирует slippage, проверьте orderbook depth и размер позиции."
      },
      {
        title: "Max price drift",
        body: "Максимальное отклонение текущей цены от сигнальной цены. Защищает от входа после того, как сигнал уже устарел.",
        tip: "Значение 0 выключает блокировку по уходу цены от сигнала."
      },
      {
        title: "Max book use",
        body: "Доля видимой ликвидности стакана, которую может потребить расчетный размер позиции. Чем выше доля, тем больше market impact.",
        tip: "Значение 0 выключает лимит использования стакана, но отсутствие стакана для real все равно остается риском."
      },
      {
        title: "Stop-loss mode",
        body: "Fixed % ставит простой стоп от entry. ATR учитывает волатильность монеты. Structure берет стоп из структуры сигнала: swing, support/resistance, liquidity zone.",
        tip: "Для MVP проще Fixed %, для крипты на разных монетах чаще лучше ATR или Structure."
      },
      {
        title: "Fixed stop / ATR period / ATR multiplier",
        body: "Fixed stop задает дистанцию стопа в процентах. ATR period задает период расчета волатильности. ATR multiplier умножает ATR и получает стоп-дистанцию.",
        tip: "Чем дальше стоп, тем меньше position size при том же Risk / trade."
      },
      {
        title: "TP1 / TP2 / TP3",
        body: "Цели выхода по уровням риска. Они помогают заранее описать план фиксации прибыли.",
        tip: "Средняя цель обычно используется как базовая проверка качества сделки."
      },
      {
        title: "Partial take-profit",
        body: "Разрешает закрывать позицию частями: например TP1 30%, TP2 40%, TP3 30%. Это превращает сигнал в полный exit plan.",
        tip: "Сумма процентов должна логически давать 100%, иначе план выхода будет неоднозначным."
      },
      {
        title: "Breakeven",
        body: "Move after задает, после какого R переносить стоп в безубыток. Offset добавляет небольшой запас, чтобы покрыть комиссии.",
        tip: "Небольшой offset нужен, чтобы безубыток не съедали комиссии."
      },
      {
        title: "Trailing stop",
        body: "Трейлинг двигает защитный стоп вслед за ценой. ATR подходит для swing, percent для скальпинга, structure для Price Action.",
        tip: "Включайте трейлинг только если стратегия действительно предполагает удержание позиции после TP1/TP2."
      },
      {
        title: "Strategy multipliers",
        body: "Множители снижают или оставляют базовый риск в зависимости от стратегии. Scalping может быть 0.5x, breakout 0.75x, trend-following 1.0x.",
        tip: "Чем рискованнее стратегия, тем ниже должен быть ее множитель."
      }
    ]
  },
  {
    title: "3. Futures Protection",
    intro: "Futures требуют отдельной защиты, потому что liquidation price может наступить раньше стоп-лосса.",
    items: [
      {
        title: "Max leverage",
        body: "Максимальное плечо, которое разрешает приложение. Плечо уменьшает required margin, но не уменьшает риск до стопа.",
        tip: "Для MVP дефолт 3x. Новым пользователям не стоит давать больше 5x без явного подтверждения."
      },
      {
        title: "Liq. buffer",
        body: "Минимальная дистанция между stop-loss и liquidation price. Для long ликвидация должна быть ниже стопа, для short выше стопа.",
        tip: "Значение 0 выключает минимальный буфер, но проверка ликвидации раньше стопа остается защитой."
      },
      {
        title: "Liquidation buffer required",
        body: "Если включено, risk-gate не должен считать futures-сделку безопасной без проверки ликвидации.",
        tip: "Для production real trading это обязательная защита."
      },
      {
        title: "Futures risk",
        body: "Отдельный риск на futures-сделку. Обычно ниже общего Risk / trade, потому что добавляются ликвидация, funding и резкие движения.",
        tip: "Если real/virtual futures слишком часто блокируются, начинайте с Futures open risk и Open risk cap, а не с leverage."
      },
      {
        title: "Futures open risk",
        body: "Отдельный лимит открытого риска для futures. Он может быть жестче общего лимита аккаунта.",
        tip: "Значение 0 выключает futures open risk cap."
      }
    ]
  },
  {
    title: "4. Virtual Trading",
    intro: "Virtual должен имитировать реальную торговлю, но может иметь отдельный учебный профиль риска.",
    items: [
      {
        title: "Same as real / Separate",
        body: "Same as real использует реальные риск-настройки. Separate позволяет тестировать мягче или агрессивнее без изменения real-профиля.",
        tip: "Если сейчас все блокируется в paper trading, временно выберите Separate и настройте virtual-лимиты отдельно."
      },
      {
        title: "Virtual risk",
        body: "Риск на одну virtual-сделку. Работает только в Separate mode.",
        tip: "Для обучения можно поставить 0.5-1%, а не 10%, чтобы Open risk cap не забивался за одну-две сделки."
      },
      {
        title: "Virtual balance",
        body: "Стартовый баланс virtual-аккаунта. От него считаются risk amount, margin, daily/open risk и размер позиции.",
        tip: "Если баланс маленький, даже небольшие старые позиции могут выглядеть как огромный open risk."
      },
      {
        title: "Slippage model",
        body: "None не добавляет проскальзывание, Fixed добавляет постоянный буфер, Spread использует bid/ask, Orderbook оценивает глубину, Volatility учитывает волатильность.",
        tip: "Для MVP лучший учебный режим: spread-based плюс фиксированный буфер."
      },
      {
        title: "Fee model",
        body: "Exchange берет комиссии из Bybit fee cache. Manual использует ручной fallback.",
        tip: "Если fee cache недоступен, backend использует conservative fallback и показывает warning."
      },
      {
        title: "Realistic execution",
        body: "Virtual учитывает spread, fee, slippage, depth и fill ratio. Это делает paper trading ближе к real flow.",
        tip: "Для проверки стратегии лучше оставлять включенным, даже если из-за этого часть сделок блокируется."
      }
    ]
  }
];

export function SettingsPage({
  config,
  availablePairs,
  strategyConfigs,
  alertRules,
  exchangeConnections,
  exchangeAccountSnapshots,
  exchangeBalanceLoading,
  exchangeWalletBalances,
  userProfile,
  riskState,
  busy,
  onCreateAlert,
  onToggleAlert,
  onDeleteAlert,
  onTestAlert,
  onCreateExchangeConnection,
  onUpdateExchangeConnection,
  onToggleExchangeConnection,
  onDeleteExchangeConnection,
  onRefreshExchangeBalance,
  onTestExchangeConnection,
  onSyncExchangeConnection,
  onSelectSimulationLevel,
  onUpdateStrategyConfig,
  onUpdateRiskManagement
}: SettingsPageProps) {
  const { t, tKey, tReason } = useI18n();
  const [openSettingsSections, setOpenSettingsSections] = useState<Set<SettingsSectionId>>(() => new Set());
  const [openStrategyIds, setOpenStrategyIds] = useState<Set<string>>(() => new Set());
  const [strategyPairDrafts, setStrategyPairDrafts] = useState<Record<string, StrategyPairScope[]>>({});
  const [strategySaveErrors, setStrategySaveErrors] = useState<Record<string, string>>({});
  const [pairId, setPairId] = useState("");
  const [conditionType, setConditionType] = useState("price_above");
  const [targetPrice, setTargetPrice] = useState("");
  const supportedExchanges = useMemo(
    () => config?.exchanges?.length ? config.exchanges : ["bybit"],
    [config]
  );
  const [exchangeCode, setExchangeCode] = useState(supportedExchanges[0] ?? "bybit");
  const [connectionLabel, setConnectionLabel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [apiPassphrase, setApiPassphrase] = useState("");
  const [connectionEnvironment, setConnectionEnvironment] = useState<ExchangeConnection["environment"]>("testnet");
  const [connectionOrderMode, setConnectionOrderMode] = useState<ExchangeConnection["order_placement_mode"]>("dry_run");
  const [mainnetExplicitConfirm, setMainnetExplicitConfirm] = useState(false);
  const [connectionDeleteCandidate, setConnectionDeleteCandidate] = useState<ExchangeConnection | null>(null);
  const [connectionDeleteError, setConnectionDeleteError] = useState<string | null>(null);
  const [riskTab, setRiskTab] = useState<RiskSettingsTab>("profile");
  const selectedPair = useMemo(
    () => availablePairs.find((pair) => pair.id === pairId) ?? availablePairs[0] ?? null,
    [availablePairs, pairId]
  );
  const availableStrategyExchanges = useMemo(
    () => dedupeStrings([
      ...supportedExchanges,
      ...availablePairs.map((pair) => pair.exchange)
    ]),
    [availablePairs, supportedExchanges]
  );
  const enabledStrategyCount = useMemo(
    () => strategyConfigs.filter((strategyConfig) => strategyConfig.is_enabled).length,
    [strategyConfigs]
  );
  const visibleExchangeConnections = useMemo(
    () => exchangeConnections.filter(isVisibleExchangeConnection),
    [exchangeConnections]
  );
  const strategyPairSourceKey = useMemo(
    () =>
      strategyConfigs
        .map((strategyConfig) => `${strategyConfig.id}:${pairScopeListKey(strategyConfig.pairs)}`)
        .join("|"),
    [strategyConfigs]
  );
  const simulationLevel = userProfile?.settings.virtual_trading.simulation_level ?? "mvp";
  const riskManagement = userProfile?.settings.risk_management ?? cloneRiskManagementSettings();
  const riskManagementKey = [
    riskManagement.risk_profile,
    riskManagement.risk_mode,
    riskManagement.risk_per_trade_percent,
    riskManagement.fixed_risk_amount,
    riskManagement.fixed_risk_currency,
    riskManagement.radar_display_mode,
    riskManagement.min_rr_ratio,
    riskManagement.rr_guard_mode,
    riskManagement.discovery_rr_guard_mode,
    riskManagement.real_rr_guard_mode,
    riskManagement.virtual_rr_guard_mode,
    riskManagement.backtest_rr_guard_mode,
    JSON.stringify(riskManagement.strategy_rr_guard_modes),
    riskManagement.max_daily_loss_percent,
    riskManagement.max_weekly_loss_percent,
    riskManagement.max_account_drawdown_percent,
    riskManagement.max_open_risk_percent,
    riskManagement.max_correlated_risk_percent,
    riskManagement.max_spread_bps,
    riskManagement.max_slippage_bps,
    riskManagement.max_price_deviation_bps,
    riskManagement.max_orderbook_liquidity_ratio,
    riskManagement.stop_loss_required,
    riskManagement.take_profit_required,
    riskManagement.stop_loss_mode,
    riskManagement.default_stop_loss_percent,
    riskManagement.atr_period,
    riskManagement.atr_multiplier,
    riskManagement.take_profit_mode,
    riskManagement.tp1_r_multiple,
    riskManagement.tp2_r_multiple,
    riskManagement.tp3_r_multiple,
    riskManagement.partial_take_profit_enabled,
    riskManagement.tp1_close_percent,
    riskManagement.tp2_close_percent,
    riskManagement.tp3_close_percent,
    riskManagement.move_sl_to_breakeven_after_r,
    riskManagement.breakeven_offset_percent,
    riskManagement.trailing_stop_enabled,
    riskManagement.trailing_mode,
    riskManagement.trailing_atr_multiplier,
    riskManagement.trailing_stop_percent,
    riskManagement.max_leverage,
    riskManagement.min_liquidation_buffer_percent,
    riskManagement.liquidation_buffer_required,
    riskManagement.spot_risk_per_trade_percent,
    riskManagement.spot_max_position_size_percent,
    riskManagement.spot_stop_required,
    riskManagement.futures_risk_per_trade_percent,
    riskManagement.futures_max_leverage,
    riskManagement.futures_max_open_risk_percent,
    riskManagement.futures_liquidation_buffer_required,
    riskManagement.virtual_risk_mode,
    riskManagement.virtual_risk_per_trade_percent,
    riskManagement.virtual_starting_balance,
    riskManagement.virtual_slippage_model,
    riskManagement.virtual_fee_model,
    riskManagement.virtual_trading_uses_realistic_execution,
    JSON.stringify(riskManagement.strategy_risk_multipliers),
    riskManagement.auto_reduce_risk_after_losses,
    riskManagement.allow_risk_increase_after_profit,
    riskManagement.increase_risk_after_profit_streak,
    riskManagement.max_risk_boost
  ].join(":");
  const [riskDraftState, setRiskDraftState] = useState<{
    key: string;
    value: RiskManagementSettings;
  } | null>(null);
  const riskDraft = riskDraftState?.key === riskManagementKey ? riskDraftState.value : riskManagement;
  const customRiskEnabled = riskManagement.risk_profile === "custom";
  const riskValidationErrors = useMemo(() => validateRiskDraft(riskDraft), [riskDraft]);
  const riskDraftValid = Object.keys(riskValidationErrors).length === 0;

  useEffect(() => {
    setStrategyPairDrafts(
      Object.fromEntries(
        strategyConfigs.map((strategyConfig) => [
          strategyConfig.id,
          dedupeStrategyPairs(strategyConfig.pairs)
        ])
      )
    );
  }, [strategyPairSourceKey, strategyConfigs]);

  function updateRiskDraft(values: Partial<RiskManagementSettings>) {
    setRiskDraftState({
      key: riskManagementKey,
      value: {
        ...riskDraft,
        ...values,
        risk_profile: "custom"
      }
    });
  }

  function updateStrategyRiskMultiplier(strategy: string, multiplier: number) {
    updateRiskDraft({
      strategy_risk_multipliers: {
        ...riskDraft.strategy_risk_multipliers,
        [strategy]: multiplier
      }
    });
  }

  function toggleSettingsSection(sectionId: SettingsSectionId) {
    setOpenSettingsSections((current) => {
      const next = new Set(current);
      if (next.has(sectionId)) {
        next.delete(sectionId);
      } else {
        next.add(sectionId);
      }
      return next;
    });
  }

  function toggleStrategyRow(strategyId: string) {
    setOpenStrategyIds((current) => {
      const next = new Set(current);
      if (next.has(strategyId)) {
        next.delete(strategyId);
      } else {
        next.add(strategyId);
      }
      return next;
    });
  }

  function updateStrategyPairDraft(strategyId: string, pairs: StrategyPairScope[]) {
    setStrategyPairDrafts((current) => ({
      ...current,
      [strategyId]: dedupeStrategyPairs(pairs)
    }));
    setStrategySaveErrors((current) => omitRecordKey(current, strategyId));
  }

  async function handleCreateAlert() {
    if (!selectedPair || !targetPrice) return;
    await onCreateAlert({
      pair_id: selectedPair.id,
      condition_type: conditionType,
      condition_body: { price: Number(targetPrice) },
      channels: ["websocket"],
      is_enabled: true
    });
    setTargetPrice("");
  }

  async function handleCreateExchangeConnection() {
    if (!exchangeCode || !connectionLabel || !apiKey || !apiSecret) return;
    await onCreateExchangeConnection({
      exchange_code: exchangeCode,
      label: connectionLabel,
      account_type: "spot",
      api_key: apiKey,
      api_secret: apiSecret,
      api_passphrase: apiPassphrase || null,
      permissions: { read: true, trade: isRealOrderMode(connectionOrderMode) },
      environment: connectionEnvironment,
      order_placement_mode: connectionOrderMode,
      mainnet_explicitly_enabled: connectionEnvironment === "mainnet" && isMainnetOrderMode(connectionOrderMode) && mainnetExplicitConfirm
    });
    setConnectionLabel("");
    setApiKey("");
    setApiSecret("");
    setApiPassphrase("");
    setConnectionEnvironment("testnet");
    setConnectionOrderMode("dry_run");
    setMainnetExplicitConfirm(false);
  }

  function requestDeleteExchangeConnection(connection: ExchangeConnection) {
    setConnectionDeleteCandidate(connection);
    setConnectionDeleteError(null);
  }

  function cancelDeleteExchangeConnection() {
    setConnectionDeleteCandidate(null);
    setConnectionDeleteError(null);
  }

  async function handleDeleteExchangeConnection() {
    if (!connectionDeleteCandidate) return;
    try {
      await onDeleteExchangeConnection(connectionDeleteCandidate.id);
      setConnectionDeleteCandidate(null);
      setConnectionDeleteError(null);
    } catch (error) {
      setConnectionDeleteError(exchangeConnectionDeleteErrorMessage(error, tKey));
    }
  }

  async function handleApplyStrategyConfig(event: FormEvent<HTMLFormElement>, configItem: StrategyConfig) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const exchanges = dedupeStrings(formData.getAll("exchanges").map(String));
    const timeframes = dedupeStrings(formData.getAll("timeframes").map(String));
    if (exchanges.length === 0 || timeframes.length === 0) return;

    const params: Record<string, unknown> = {};
    const contextTimeframeMap: Record<string, string> = {};
    for (const [key, rawValue] of formData.entries()) {
      const value = String(rawValue);
      if (key.startsWith("param:")) {
        const numericValue = Number(value);
        if (Number.isFinite(numericValue) && numericValue >= 0) {
          params[key.slice("param:".length)] = numericValue;
        }
      }
      if (key.startsWith("context:") && value) {
        contextTimeframeMap[key.slice("context:".length)] = value;
      }
    }
    params.context_timeframe_map = contextTimeframeMap;

    const minRrRatio = Number(formData.get("risk:min_rr_ratio") ?? riskManagement.min_rr_ratio ?? 2);
    const rrGuardMode = normalizeRRGuardMode(
      formData.get("risk:rr_guard_mode"),
      riskManagement.discovery_rr_guard_mode
    );
    const riskMode = formData.get("risk:risk_mode") === "fixed" ? "fixed" : "percent";
    const riskPercent = Number(formData.get("risk:risk_percent"));
    const fixedRiskAmount = Number(formData.get("risk:fixed_risk_amount"));
    const leverage = Number(formData.get("risk:leverage"));
    const radarDisplayMode = normalizeRadarDisplayMode(formData.get("risk:radar_display_mode"));
    const riskSettings: NonNullable<StrategyConfigPatch["risk_settings"]> = {
      risk_mode: riskMode,
      fixed_risk_currency: String(formData.get("risk:fixed_risk_currency") ?? "USDT").trim().toUpperCase() || "USDT",
      radar_display_mode: radarDisplayMode,
      min_rr_ratio: Number.isFinite(minRrRatio) && minRrRatio >= 0 ? minRrRatio : riskManagement.min_rr_ratio,
      rr_guard_mode: rrGuardMode,
      rr_target: String(formData.get("risk:rr_target") ?? defaultRrTarget(configItem.strategy_code)) === "nearest"
        ? "nearest"
        : "final",
      hide_failed_rr_signals: formData.has("risk:hide_failed_rr_signals"),
      show_only_active_setups: formData.has("risk:show_only_active_setups")
    };
    if (Number.isFinite(riskPercent) && riskPercent > 0) {
      riskSettings.risk_percent = riskPercent;
    }
    if (Number.isFinite(fixedRiskAmount) && fixedRiskAmount > 0) {
      riskSettings.fixed_risk_amount = fixedRiskAmount;
    }
    if (Number.isFinite(leverage) && leverage >= 1) {
      riskSettings.leverage = leverage;
    }
    try {
      await onUpdateStrategyConfig(configItem.id, {
        is_enabled: formData.has("is_enabled"),
        exchanges,
        pairs: strategyPairDrafts[configItem.id] ?? dedupeStrategyPairs(configItem.pairs),
        timeframes,
        params,
        risk_settings: riskSettings
      });
      setStrategySaveErrors((current) => omitRecordKey(current, configItem.id));
    } catch (exc) {
      setStrategySaveErrors((current) => ({
        ...current,
        [configItem.id]: strategyUpdateErrorMessage(exc, tKey)
      }));
    }
  }

  async function handleSelectRiskProfile(profile: RiskProfileName) {
    setRiskDraftState({
      key: riskManagementKey,
      value: riskProfilePreset(profile)
    });
    await onUpdateRiskManagement({ risk_profile: profile });
  }

  async function handleSaveCustomRisk() {
    if (!riskDraftValid) return;

    await onUpdateRiskManagement({
      risk_profile: "custom",
      risk_management: {
        risk_profile: "custom",
        risk_mode: riskDraft.risk_mode,
        risk_per_trade_percent: riskDraft.risk_per_trade_percent,
        fixed_risk_amount: riskDraft.fixed_risk_amount,
        fixed_risk_currency: riskDraft.fixed_risk_currency,
        radar_display_mode: riskDraft.radar_display_mode,
        min_rr_ratio: riskDraft.min_rr_ratio,
        rr_guard_mode: riskDraft.rr_guard_mode,
        discovery_rr_guard_mode: riskDraft.discovery_rr_guard_mode,
        real_rr_guard_mode: riskDraft.real_rr_guard_mode,
        virtual_rr_guard_mode: riskDraft.virtual_rr_guard_mode,
        backtest_rr_guard_mode: riskDraft.backtest_rr_guard_mode,
        strategy_rr_guard_modes: riskDraft.strategy_rr_guard_modes,
        max_daily_loss_percent: riskDraft.max_daily_loss_percent,
        max_weekly_loss_percent: riskDraft.max_weekly_loss_percent,
        max_account_drawdown_percent: riskDraft.max_account_drawdown_percent,
        max_open_risk_percent: riskDraft.max_open_risk_percent,
        max_correlated_risk_percent: riskDraft.max_correlated_risk_percent,
        max_spread_bps: riskDraft.max_spread_bps,
        max_slippage_bps: riskDraft.max_slippage_bps,
        max_price_deviation_bps: riskDraft.max_price_deviation_bps,
        max_orderbook_liquidity_ratio: riskDraft.max_orderbook_liquidity_ratio,
        stop_loss_required: riskDraft.stop_loss_required,
        take_profit_required: riskDraft.take_profit_required,
        stop_loss_mode: riskDraft.stop_loss_mode,
        default_stop_loss_percent: riskDraft.default_stop_loss_percent,
        atr_period: riskDraft.atr_period,
        atr_multiplier: riskDraft.atr_multiplier,
        take_profit_mode: riskDraft.take_profit_mode,
        tp1_r_multiple: riskDraft.tp1_r_multiple,
        tp2_r_multiple: riskDraft.tp2_r_multiple,
        tp3_r_multiple: riskDraft.tp3_r_multiple,
        partial_take_profit_enabled: riskDraft.partial_take_profit_enabled,
        tp1_close_percent: riskDraft.tp1_close_percent,
        tp2_close_percent: riskDraft.tp2_close_percent,
        tp3_close_percent: riskDraft.tp3_close_percent,
        move_sl_to_breakeven_after_r: riskDraft.move_sl_to_breakeven_after_r,
        breakeven_offset_percent: riskDraft.breakeven_offset_percent,
        trailing_stop_enabled: riskDraft.trailing_stop_enabled,
        trailing_mode: riskDraft.trailing_mode,
        trailing_atr_multiplier: riskDraft.trailing_atr_multiplier,
        trailing_stop_percent: riskDraft.trailing_stop_percent,
        max_leverage: riskDraft.max_leverage,
        min_liquidation_buffer_percent: riskDraft.min_liquidation_buffer_percent,
        liquidation_buffer_required: riskDraft.liquidation_buffer_required,
        spot_risk_per_trade_percent: riskDraft.spot_risk_per_trade_percent,
        spot_max_position_size_percent: riskDraft.spot_max_position_size_percent,
        spot_stop_required: riskDraft.spot_stop_required,
        futures_risk_per_trade_percent: riskDraft.futures_risk_per_trade_percent,
        futures_max_leverage: riskDraft.futures_max_leverage,
        futures_max_open_risk_percent: riskDraft.futures_max_open_risk_percent,
        futures_liquidation_buffer_required: riskDraft.futures_liquidation_buffer_required,
        virtual_risk_mode: riskDraft.virtual_risk_mode,
        virtual_risk_per_trade_percent: riskDraft.virtual_risk_per_trade_percent,
        virtual_starting_balance: riskDraft.virtual_starting_balance,
        virtual_slippage_model: riskDraft.virtual_slippage_model,
        virtual_fee_model: riskDraft.virtual_fee_model,
        virtual_trading_uses_realistic_execution: riskDraft.virtual_trading_uses_realistic_execution,
        strategy_risk_multipliers: riskDraft.strategy_risk_multipliers,
        auto_reduce_risk_after_losses: riskDraft.auto_reduce_risk_after_losses,
        allow_risk_increase_after_profit: riskDraft.allow_risk_increase_after_profit,
        increase_risk_after_profit_streak: riskDraft.increase_risk_after_profit_streak,
        max_risk_boost: riskDraft.max_risk_boost
      }
    });
  }

  return (
    <>
      <section className="wide-panel">
      <div className="page-head">
        <div>
          <span className="muted">{tKey("settings.eyebrow")}</span>
          <h1>{tKey("settings.title")}</h1>
        </div>
      </div>

      <div className="settings-grid">
        <SettingsAccordionSection
          id="exchanges"
          icon={<Radio size={18} />}
          onToggle={() => toggleSettingsSection("exchanges")}
          open={openSettingsSections.has("exchanges")}
          summary={tKey("settings.connectionCount", {
            count: visibleExchangeConnections.length,
            suffix: visibleExchangeConnections.length === 1 ? "" : "s"
          })}
          title={tKey("settings.exchanges")}
        >
          <div className="inline-form stacked">
            <select
              aria-label={tKey("common.exchange")}
              disabled={busy}
              onChange={(event) => setExchangeCode(event.target.value)}
              value={exchangeCode}
            >
              {supportedExchanges.map((exchange) => (
                <option key={exchange} value={exchange}>{exchange}</option>
              ))}
            </select>
            <input
              aria-label={tKey("exchange.connectionLabel")}
              disabled={busy}
              onChange={(event) => setConnectionLabel(event.target.value)}
              placeholder={tKey("exchange.connectionLabel")}
              value={connectionLabel}
            />
            <select
              aria-label={tKey("exchange.connectionEnvironment")}
              disabled={busy}
              onChange={(event) => {
                setConnectionEnvironment(event.target.value === "mainnet" ? "mainnet" : "testnet");
                setMainnetExplicitConfirm(false);
              }}
              value={connectionEnvironment}
            >
              <option value="testnet">{tKey("settings.testnet")}</option>
              <option value="mainnet">{tKey("settings.mainnet")}</option>
            </select>
            <select
              aria-label={tKey("exchange.orderPlacementMode")}
              disabled={busy}
              onChange={(event) => {
                setConnectionOrderMode(normalizeOrderPlacementMode(event.target.value));
                setMainnetExplicitConfirm(false);
              }}
              value={connectionOrderMode}
            >
              <option value="disabled">{tKey("common.disabled")}</option>
              <option value="dry_run">{tKey("settings.dryRun")}</option>
              <option value="dry_run_orders">{tKey("settings.dryRunOrders")}</option>
              <option value="testnet_real_orders">{tKey("settings.testnetRealOrders")}</option>
              <option value="mainnet_small_size">{tKey("settings.mainnetSmallSize")}</option>
              <option value="mainnet_scaled">{tKey("settings.mainnetScaled")}</option>
              <option value="live">{tKey("settings.live")}</option>
            </select>
            <input
              aria-label={tKey("exchange.apiKey")}
              disabled={busy}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder={tKey("exchange.apiKey")}
              value={apiKey}
            />
            <input
              aria-label={tKey("exchange.apiSecret")}
              disabled={busy}
              onChange={(event) => setApiSecret(event.target.value)}
              placeholder={tKey("exchange.apiSecret")}
              type="password"
              value={apiSecret}
            />
            <input
              aria-label={tKey("exchange.apiPassphrase")}
              disabled={busy}
              onChange={(event) => setApiPassphrase(event.target.value)}
              placeholder={tKey("exchange.apiPassphrase")}
              type="password"
              value={apiPassphrase}
            />
            {connectionEnvironment === "mainnet" && isMainnetOrderMode(connectionOrderMode) ? (
              <label className="toggle-row compact-toggle mainnet-confirm-toggle">
                <input
                  checked={mainnetExplicitConfirm}
                  disabled={busy}
                  onChange={(event) => setMainnetExplicitConfirm(event.target.checked)}
                  type="checkbox"
                />
                <span>{tKey("settings.confirmMainnetLive")}</span>
              </label>
            ) : null}
            <button
              className="primary-action"
              disabled={
                busy
                || !connectionLabel
                || !apiKey
                || !apiSecret
                || (connectionEnvironment === "mainnet" && isMainnetOrderMode(connectionOrderMode) && !mainnetExplicitConfirm)
              }
              onClick={handleCreateExchangeConnection}
              type="button"
            >
              <KeyRound size={16} />
              {tKey("settings.connect")}
            </button>
          </div>
          <div className="connection-list">
            {visibleExchangeConnections.length === 0 ? <div className="empty-state compact-empty">{tKey("settings.noExchangeConnections")}</div> : null}
            {visibleExchangeConnections.map((connection) => {
              const walletBalance = exchangeWalletBalances[connection.id] ?? null;
              const accountSnapshot = exchangeAccountSnapshots[connection.id] ?? null;
              const balancePending = Boolean(exchangeBalanceLoading[connection.id]);
              const snapshotStatus = accountSnapshot?.status ?? walletBalance?.status ?? "missing";
              const connectionBadge = exchangeConnectionExecutionBadge(connection);
              const balanceWarnings = uniqueStrings([
                ...(accountSnapshot?.warnings ?? []),
                ...(walletBalance?.warnings ?? [])
              ]);
              return (
                <div className="connection-row" key={connection.id}>
                  <div className="connection-main">
                    <strong>{connection.label}</strong>
                    <span>{connection.exchange_code}:{connection.account_type} / {connection.environment}</span>
                    <span>{tKey(orderPlacementModeKey(connection.order_placement_mode))}</span>
                    <code>{shortKeyRef(connection.key_ref)}</code>
                  </div>
                  <div className="connection-balance-panel">
                    <div className="connection-balance-metrics">
                      <span>
                        <small>{tKey("exchange.equity")}</small>
                        <strong>{formatBalanceAmount(walletBalance?.total_equity ?? accountSnapshot?.account_equity)}</strong>
                      </span>
                      <span>
                        <small>{tKey("exchange.available")}</small>
                        <strong>{formatBalanceAmount(walletBalance?.total_available_balance ?? accountSnapshot?.available_balance)}</strong>
                      </span>
                      <span>
                        <small>{tKey("exchange.walletBalance")}</small>
                        <strong>{formatBalanceAmount(walletBalance?.total_wallet_balance ?? accountSnapshot?.wallet_balance)}</strong>
                      </span>
                    </div>
                    <div className="connection-freshness-row">
                      <Badge tone={snapshotStatusTone(snapshotStatus)}>{snapshotStatus}</Badge>
                      <span>{tKey("exchange.snapshotAge", { value: formatSnapshotAge(accountSnapshot?.fetched_at ?? walletBalance?.fetched_at) })}</span>
                    </div>
                    {balanceWarnings.length ? (
                      <div className="connection-warning-list">
                        {balanceWarnings.map((warning) => (
                          <span key={warning}>{warning}</span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                  <div className="connection-safety-panel">
                    <Badge tone={connectionBadge.tone}>{tKey(connectionBadge.labelKey)}</Badge>
                    <span>{connection.can_place_orders ? tKey("exchange.ordersEnabled") : tReason(safetyBlockerSummary(connection))}</span>
                  </div>
                  <Badge tone={connection.status === "active" ? "green" : "red"}>{connection.status}</Badge>
                  <select
                    aria-label={`${tKey("exchange.orderPlacementMode")} ${connection.label}`}
                    className="compact-select"
                    disabled={busy}
                    onChange={(event) => onUpdateExchangeConnection(connection.id, {
                      order_placement_mode: normalizeOrderPlacementMode(event.target.value),
                      ...(!isMainnetOrderMode(normalizeOrderPlacementMode(event.target.value)) ? { mainnet_explicitly_enabled: false } : {})
                    })}
                    value={connection.order_placement_mode}
                  >
                    <option value="disabled">{tKey("common.disabled")}</option>
                    <option value="dry_run">{tKey("settings.dryRun")}</option>
                    <option value="dry_run_orders">{tKey("settings.dryRunOrders")}</option>
                    <option value="testnet_real_orders">{tKey("settings.testnetRealOrders")}</option>
                    <option value="mainnet_small_size">{tKey("settings.mainnetSmallSize")}</option>
                    <option value="mainnet_scaled">{tKey("settings.mainnetScaled")}</option>
                    <option value="live">{tKey("settings.live")}</option>
                  </select>
                  {connection.environment === "mainnet" ? (
                    <label className="toggle-row compact-toggle mainnet-confirm-toggle">
                      <input
                        checked={connection.mainnet_explicitly_enabled}
                        disabled={busy || !isMainnetOrderMode(connection.order_placement_mode)}
                        onChange={(event) => onUpdateExchangeConnection(connection.id, {
                          mainnet_explicitly_enabled: event.target.checked
                        })}
                        type="checkbox"
                      />
                      <span>{tKey("settings.mainnetLive")}</span>
                    </label>
                  ) : null}
                  <label className="toggle-row compact-toggle">
                    <input
                      checked={connection.status === "active"}
                      disabled={busy}
                      onChange={(event) => onToggleExchangeConnection(connection.id, event.target.checked)}
                      type="checkbox"
                    />
                    <span>{connection.status === "active" ? tKey("common.on") : tKey("common.off")}</span>
                  </label>
                  <button
                    className="secondary-action compact-action balance-refresh-button"
                    disabled={busy || balancePending}
                    onClick={() => onRefreshExchangeBalance(connection.id)}
                    title={tKey("exchange.refreshBalance")}
                    type="button"
                  >
                    <RefreshCw size={15} />
                    {tKey("exchange.refreshBalance")}
                  </button>
                  <button className="icon-button compact" disabled={busy} onClick={() => onTestExchangeConnection(connection.id)} title={tKey("settings.test")} type="button">
                    <Send size={15} />
                  </button>
                  <button className="icon-button compact" disabled={busy} onClick={() => onSyncExchangeConnection(connection.id)} title={tKey("settings.sync")} type="button">
                    <RefreshCw size={15} />
                  </button>
                  <button
                    aria-label={`${tKey("common.delete")} ${connection.label}`}
                    className="icon-button compact danger"
                    disabled={busy}
                    onClick={() => requestDeleteExchangeConnection(connection)}
                    title={tKey("common.delete")}
                    type="button"
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
              );
            })}
          </div>
        </SettingsAccordionSection>

        <SettingsAccordionSection
          className="strategy-settings-section"
          id="strategies"
          icon={<SlidersHorizontal size={18} />}
          onToggle={() => toggleSettingsSection("strategies")}
          open={openSettingsSections.has("strategies")}
          summary={tKey("settings.strategyCount", { enabled: enabledStrategyCount, total: strategyConfigs.length })}
          title={tKey("settings.strategies")}
        >
          <div className="strategy-config-list">
            {strategyConfigs.length === 0 ? <div className="empty-state compact-empty">{tKey("settings.noStrategyConfigs")}</div> : null}
            {strategyConfigs.map((strategyConfig) => {
              const strategyExchangeOptions = dedupeStrings([
                ...availableStrategyExchanges,
                ...strategyConfig.exchanges
              ]);
              const contextTimeframeMap = getContextTimeframeMap(strategyConfig.params);
              const strategyOpen = openStrategyIds.has(strategyConfig.id);
              const activeSetupsOnly = Boolean(strategyConfig.risk_settings.show_only_active_setups);
              const pairDraft = strategyPairDrafts[strategyConfig.id] ?? strategyConfig.pairs;
              const pairSummary = pairDraft.length ? `Выбрано ${pairDraft.length} пар` : "Все пары из scanner universe";
              return (
                <form
                  className={`strategy-config-row ${strategyOpen ? "open" : ""}`}
                  key={`${strategyConfig.id}:${strategyConfig.updated_at}`}
                  onSubmit={(event) => handleApplyStrategyConfig(event, strategyConfig)}
                >
                <button
                  aria-expanded={strategyOpen}
                  className="strategy-config-header strategy-config-summary"
                  onClick={() => toggleStrategyRow(strategyConfig.id)}
                  type="button"
                >
                  <div>
                    <strong>{strategyConfig.strategy_name}</strong>
                    <span>
                      {[
                        strategyConfig.exchanges.join(", "),
                        strategyConfig.timeframes.join(", "),
                        pairSummary
                      ].join(" | ")}
                    </span>
                    <span className="hidden">
                      {strategyConfig.exchanges.join(", ")}
                      {" / "}
                      {strategyConfig.exchanges.join(", ")}
                      {" / "}
                      {strategyConfig.timeframes.join(", ")}
                      {" / "}
                      {pairSummary}
                    </span>
                  </div>
                  <div className="strategy-summary-badges">
                    <Badge tone={strategyConfig.is_enabled ? "green" : "yellow"}>
                      {strategyConfig.is_enabled ? tKey("common.on") : tKey("common.off")}
                    </Badge>
                    {activeSetupsOnly ? <Badge tone="blue">{tKey("settings.activeOnly")}</Badge> : null}
                    <ChevronDown className="settings-chevron" size={17} />
                  </div>
                </button>

                {strategyOpen ? (
                  <div className="strategy-config-body">
                    <div className="strategy-switch-strip">
                      <label className="strategy-scope-chip strategy-enable-chip">
                        <input
                          defaultChecked={strategyConfig.is_enabled}
                          disabled={busy}
                          name="is_enabled"
                          type="checkbox"
                        />
                        <span>{tKey("settings.enabled")}</span>
                      </label>
                      <label className="strategy-scope-chip strategy-enable-chip">
                        <input
                          defaultChecked={activeSetupsOnly}
                          disabled={busy}
                          name="risk:show_only_active_setups"
                          type="checkbox"
                        />
                        <span>{tKey("settings.onlyActiveSetups")}</span>
                      </label>
                    </div>

                <div className="strategy-scope-grid">
                  <div>
                    <span>{tKey("settings.exchanges")}</span>
                    <div className="strategy-chip-row">
                      {strategyExchangeOptions.map((exchange) => (
                        <label className="strategy-scope-chip" key={`${strategyConfig.id}:exchange:${exchange}`}>
                          <input
                            defaultChecked={strategyConfig.exchanges.includes(exchange)}
                            disabled={busy}
                            name="exchanges"
                            type="checkbox"
                            value={exchange}
                          />
                          <span>{exchange}</span>
                        </label>
                      ))}
                    </div>
                  </div>
                  <div>
                    <span>{tKey("settings.timeframes")}</span>
                    <div className="strategy-chip-row">
                      {STRATEGY_TIMEFRAMES.map((timeframe) => (
                        <label className="strategy-scope-chip" key={`${strategyConfig.id}:timeframe:${timeframe}`}>
                          <input
                            defaultChecked={strategyConfig.timeframes.includes(timeframe)}
                            disabled={busy}
                            name="timeframes"
                            type="checkbox"
                            value={timeframe}
                          />
                          <span>{timeframe}</span>
                        </label>
                      ))}
                    </div>
                  </div>
                  <div className="strategy-context-grid">
                    <span>{tKey("settings.contextTf")}</span>
                    <div className="strategy-context-row">
                      {strategyConfig.timeframes.map((timeframe) => (
                        <label className="strategy-context-select" key={`${strategyConfig.id}:context:${timeframe}`}>
                          <span>{timeframe}</span>
                          <select
                            defaultValue={contextTimeframeMap[timeframe] ?? ""}
                            disabled={busy}
                            name={`context:${timeframe}`}
                          >
                            <option value="">{tKey("common.default")}</option>
                            {contextTimeframeOptions(timeframe).map((option) => (
                              <option key={option} value={option}>{option}</option>
                            ))}
                          </select>
                        </label>
                      ))}
                    </div>
                  </div>
                </div>

                <StrategyPairSelector
                  busy={busy}
                  onChange={(pairs) => updateStrategyPairDraft(strategyConfig.id, pairs)}
                  selectedPairs={pairDraft}
                  strategyId={strategyConfig.id}
                />

                <div className="strategy-quality-grid">
                  <label>
                    <span>{tKey("settings.min24hVolume")}</span>
                    <input
                      defaultValue={String(Number(strategyConfig.params.min_24h_volume_quote ?? 10_000_000))}
                      disabled={busy}
                      inputMode="decimal"
                      name="param:min_24h_volume_quote"
                      type="number"
                    />
                  </label>
                  <label>
                    <span>{tKey("settings.maxSpreadBps")}</span>
                    <input
                      defaultValue={String(Number(strategyConfig.params.max_spread_bps ?? 25))}
                      disabled={busy}
                      inputMode="decimal"
                      name="param:max_spread_bps"
                      type="number"
                    />
                  </label>
                  <label>
                    <span>{tKey("settings.minHistory")}</span>
                    <input
                      defaultValue={String(Number(strategyConfig.params.min_history ?? 50))}
                      disabled={busy}
                      inputMode="numeric"
                      name="param:min_history"
                      type="number"
                    />
                  </label>
                  <label>
                    <span>{tKey("settings.minSrAtr")}</span>
                    <input
                      defaultValue={String(Number(strategyConfig.params.context_obstacle_min_atr ?? 1))}
                      disabled={busy}
                      inputMode="decimal"
                      min="0"
                      name="param:context_obstacle_min_atr"
                      step="0.1"
                      type="number"
                    />
                  </label>
                  <label>
                    <span>{tKey("settings.srStrength")}</span>
                    <input
                      defaultValue={String(Number(strategyConfig.params.context_level_min_strength ?? 25))}
                      disabled={busy}
                      inputMode="decimal"
                      max="100"
                      min="0"
                      name="param:context_level_min_strength"
                      step="1"
                      type="number"
                    />
                  </label>
                  <label>
                    <span>{tKey("settings.maxBodyAtr")}</span>
                    <input
                      defaultValue={String(Number(strategyConfig.params.max_body_atr ?? defaultMaxBodyAtr(strategyConfig.strategy_code)))}
                      disabled={busy}
                      inputMode="decimal"
                      min="0.5"
                      name="param:max_body_atr"
                      step="0.1"
                      type="number"
                    />
                  </label>
                  <label>
                    <span>{tKey("settings.maxRangeAtr")}</span>
                    <input
                      defaultValue={String(Number(strategyConfig.params.max_range_atr ?? defaultMaxRangeAtr(strategyConfig.strategy_code)))}
                      disabled={busy}
                      inputMode="decimal"
                      min="1"
                      name="param:max_range_atr"
                      step="0.1"
                      type="number"
                    />
                  </label>
                  {strategyConfig.strategy_code === "volatility_squeeze_breakout"
                    ? SQUEEZE_BREAKOUT_FIELD_LABELS.map((field) => (
                        <label key={`${strategyConfig.id}:${field.key}`}>
                          <span>{field.label}</span>
                          <input
                            defaultValue={String(Number(strategyConfig.params[field.key] ?? field.defaultValue))}
                            disabled={busy}
                            inputMode="decimal"
                            max={field.max}
                            min={field.min}
                            name={`param:${field.key}`}
                            step={field.step}
                            type="number"
                          />
                        </label>
                      ))
                    : null}
                  {strategyConfig.strategy_code === "liquidity_sweep_reversal"
                    ? LIQUIDITY_SWEEP_FIELD_LABELS.map((field) => (
                        <label key={`${strategyConfig.id}:${field.key}`}>
                          <span>{field.label}</span>
                          <input
                            defaultValue={String(Number(strategyConfig.params[field.key] ?? field.defaultValue))}
                            disabled={busy}
                            inputMode="decimal"
                            max={field.max}
                            min={field.min}
                            name={`param:${field.key}`}
                            step={field.step}
                            type="number"
                          />
                        </label>
                      ))
                    : null}
                  <label>
                    <span title={t(EXECUTION_PROFILE_HELP.percentRisk)}>{tKey("settings.riskMode")}</span>
                    <select
                      defaultValue={String(strategyConfig.risk_settings.risk_mode ?? "percent")}
                      disabled={busy}
                      name="risk:risk_mode"
                    >
                      {RISK_AMOUNT_MODES.map((mode) => (
                        <option key={mode.value} value={mode.value}>{t(mode.label)}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span title={t(EXECUTION_PROFILE_HELP.percentRisk)}>{tKey("settings.strategyRiskPercent")}</span>
                    <input
                      defaultValue={strategyConfig.risk_settings.risk_percent == null ? "" : String(strategyConfig.risk_settings.risk_percent)}
                      disabled={busy}
                      inputMode="decimal"
                      max={STRATEGY_EXECUTION_SCHEMA_LIMITS.risk_percent.max}
                      min={STRATEGY_EXECUTION_SCHEMA_LIMITS.risk_percent.min}
                      name="risk:risk_percent"
                      step="0.05"
                      type="number"
                    />
                  </label>
                  <label>
                    <span title={t(EXECUTION_PROFILE_HELP.fixedRisk)}>{tKey("settings.fixedRisk")}</span>
                    <input
                      defaultValue={strategyConfig.risk_settings.fixed_risk_amount == null ? "" : String(strategyConfig.risk_settings.fixed_risk_amount)}
                      disabled={busy}
                      inputMode="decimal"
                      min={STRATEGY_EXECUTION_SCHEMA_LIMITS.fixed_risk_amount.min}
                      name="risk:fixed_risk_amount"
                      step="1"
                      type="number"
                    />
                  </label>
                  <label>
                    <span>{tKey("settings.fixedCurrency")}</span>
                    <input
                      defaultValue={String(strategyConfig.risk_settings.fixed_risk_currency ?? "USDT")}
                      disabled={busy}
                      maxLength={16}
                      name="risk:fixed_risk_currency"
                    />
                  </label>
                  <label>
                    <span title={t(EXECUTION_PROFILE_HELP.leverage)}>{tKey("settings.leverage")}</span>
                    <input
                      defaultValue={strategyConfig.risk_settings.leverage == null ? "" : String(strategyConfig.risk_settings.leverage)}
                      disabled={busy}
                      inputMode="decimal"
                      max={STRATEGY_EXECUTION_SCHEMA_LIMITS.leverage.max}
                      min={STRATEGY_EXECUTION_SCHEMA_LIMITS.leverage.min}
                      name="risk:leverage"
                      step="1"
                      type="number"
                    />
                  </label>
                  <label>
                    <span title={t(EXECUTION_PROFILE_HELP.radarMode)}>{tKey("settings.radarMode")}</span>
                    <select
                      defaultValue={String(strategyConfig.risk_settings.radar_display_mode ?? "execution_ready")}
                      disabled={busy}
                      name="risk:radar_display_mode"
                    >
                      {RADAR_DISPLAY_MODES.map((mode) => (
                        <option key={mode.value} value={mode.value}>{t(mode.label)}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>{tKey("settings.minRrExecutionReporting")}</span>
                    <input
                      defaultValue={String(Number(strategyConfig.risk_settings.min_rr_ratio ?? riskManagement.min_rr_ratio ?? 2))}
                      disabled={busy}
                      inputMode="decimal"
                      min="0"
                      name="risk:min_rr_ratio"
                      step="0.1"
                      type="number"
                    />
                  </label>
                  <label>
                    <span>{tKey("settings.rrTarget")}</span>
                    <select
                      defaultValue={String(strategyConfig.risk_settings.rr_target ?? defaultRrTarget(strategyConfig.strategy_code))}
                      disabled={busy}
                      name="risk:rr_target"
                    >
                      <option value="final">{tKey("settings.finalTarget")}</option>
                      <option value="nearest">{tKey("settings.nearestTarget")}</option>
                    </select>
                  </label>
                  <label>
                    <span title={t(EXECUTION_PROFILE_HELP.rrGuard)}>{tKey("settings.rrGuard")}</span>
                    <select
                      defaultValue={normalizeRRGuardMode(strategyConfig.risk_settings.rr_guard_mode, riskManagement.discovery_rr_guard_mode)}
                      disabled={busy}
                      name="risk:rr_guard_mode"
                    >
                      {RR_GUARD_MODES.map((mode) => (
                        <option key={mode.value} value={mode.value}>{tKey(mode.labelKey)}</option>
                      ))}
                    </select>
                  </label>
                  <label className="strategy-risk-toggle">
                    <span>{tKey("settings.hideLowRrCards")}</span>
                    <input
                      defaultChecked={Boolean(strategyConfig.risk_settings.hide_failed_rr_signals)}
                      disabled={busy}
                      name="risk:hide_failed_rr_signals"
                      type="checkbox"
                    />
                  </label>
                </div>

                    {strategySaveErrors[strategyConfig.id] ? (
                      <div className="strategy-error-message" role="alert">
                        {strategySaveErrors[strategyConfig.id]}
                      </div>
                    ) : null}

                    <div className="strategy-apply-row">
                      <Badge tone="purple">{pairSummary}</Badge>
                      <button className="primary-action compact-action" disabled={busy} type="submit">
                        <Save size={15} />
                        {tKey("settings.apply")}
                      </button>
                    </div>
                  </div>
                ) : null}
                </form>
              );
            })}
          </div>
        </SettingsAccordionSection>

        <SettingsAccordionSection
          className="risk-management-section"
          id="risk"
          icon={<Shield size={18} />}
          onToggle={() => toggleSettingsSection("risk")}
          open={openSettingsSections.has("risk")}
          summary={riskManagement.risk_profile}
          title={tKey("settings.riskManagement")}
        >
          <div className="risk-settings-tabs" role="tablist" aria-label={tKey("settings.riskManagementSections")}>
            {RISK_SETTINGS_TABS.map((tab) => (
              <button
                aria-selected={riskTab === tab.value}
                className={riskTab === tab.value ? "active" : ""}
                key={tab.value}
                onClick={() => setRiskTab(tab.value)}
                role="tab"
                type="button"
              >
                {t(tab.label)}
              </button>
            ))}
          </div>
          {riskState ? (
            <div className="risk-state-strip">
              <Badge tone={riskProtectionTone(riskState.protection_state)}>
                {tKey("settings.protectionLabel")} {riskState.protection_state}
              </Badge>
              {riskState.close_only ? <Badge tone="yellow">{tKey("settings.closeOnly")}</Badge> : null}
              <span>{tKey("settings.daily")} {formatRiskUsageValue(riskState.daily_loss_percent, riskDraft.max_daily_loss_percent, tKey)}</span>
              <span>{tKey("settings.weekly")} {formatRiskUsageValue(riskState.weekly_loss_percent, riskDraft.max_weekly_loss_percent, tKey)}</span>
              <span>{tKey("settings.drawdown")} {formatRiskUsageValue(riskState.account_drawdown_percent, riskState.max_account_drawdown_percent, tKey)}</span>
              <span>{tKey("settings.openRiskShort")} {formatRiskUsageValue(riskState.open_risk_percent, riskState.max_open_risk_percent, tKey)}</span>
              <span>{tKey("settings.correlated")} {formatRiskUsageValue(riskState.correlated_risk_percent, riskState.max_correlated_risk_percent, tKey)}</span>
              <span>{tKey("settings.rules")} {riskState.exchange_rule_status}</span>
              <span>{tKey("settings.adaptiveMultiplier")}{riskState.adaptive_multiplier.toFixed(2)}</span>
            </div>
          ) : null}

          {riskTab === "profile" ? (
            <>
              <div className="segmented">
                {RISK_PROFILES.map((profile) => {
                  const preset = profile.value === "custom"
                    ? null
                    : RISK_PROFILE_PRESETS[profile.value as RiskProfilePresetName];
                  const presetSummary = preset
                    ? `${formatPercentValue(preset.risk_per_trade_percent)} risk / ${preset.min_rr_ratio.toFixed(2)}R`
                    : profile.caption;

                  return (
                    <button
                      className={riskManagement.risk_profile === profile.value ? "active" : ""}
                      disabled={busy}
                      key={profile.value}
                      onClick={() => handleSelectRiskProfile(profile.value)}
                      title={t(profile.caption)}
                      type="button"
                    >
                      <span>{t(profile.label)}</span>
                      <small>{presetSummary}</small>
                    </button>
                  );
                })}
              </div>
              <div className="risk-plan-block">
                <div className="risk-plan-heading">
                  <strong>{tKey("settings.executionProfile")}</strong>
                  <HelpTooltip text={t(EXECUTION_PROFILE_HELP.virtualVsReal)} />
                </div>
                <p className="risk-help-note">{t(EXECUTION_PROFILE_HELP.virtualVsReal)}</p>
                <div className="risk-mode-grid two-option-grid">
                  {RISK_AMOUNT_MODES.map((mode) => (
                    <button
                      className={riskDraft.risk_mode === mode.value ? "active" : ""}
                      disabled={busy || !customRiskEnabled}
                      key={mode.value}
                      onClick={() => updateRiskDraft({ risk_mode: mode.value })}
                      title={t(mode.value === "percent" ? EXECUTION_PROFILE_HELP.percentRisk : EXECUTION_PROFILE_HELP.fixedRisk)}
                      type="button"
                    >
                      {t(mode.label)}
                    </button>
                  ))}
                </div>
                <div className="risk-settings-grid compact-risk-grid">
                  <label className="risk-setting-field">
                    <FieldLabel help={t(EXECUTION_PROFILE_HELP.fixedRisk)} label={tKey("settings.fixedRisk")} />
                    <div>
                      <input
                        aria-describedby="fixed-risk-help fixed-risk-error"
                        aria-label={tKey("settings.fixedRisk")}
                        aria-invalid={Boolean(riskValidationErrors.fixed_risk_amount)}
                        aria-required={riskDraft.risk_mode === "fixed"}
                        disabled={busy || !customRiskEnabled || riskDraft.risk_mode !== "fixed"}
                        inputMode="decimal"
                        min={RISK_MANAGEMENT_SCHEMA_LIMITS.fixed_risk_amount.min}
                        onChange={(event) => updateRiskDraft({
                          fixed_risk_amount: event.target.value === "" ? null : Number(event.target.value)
                        })}
                        required={riskDraft.risk_mode === "fixed"}
                        step="1"
                        type="number"
                        value={riskDraft.fixed_risk_amount ?? ""}
                      />
                      <small>{riskDraft.fixed_risk_currency}</small>
                    </div>
                    <small className="risk-help-text" id="fixed-risk-help">{t(EXECUTION_PROFILE_HELP.fixedRisk)}</small>
                    {riskValidationErrors.fixed_risk_amount ? (
                      <small className="risk-field-error" id="fixed-risk-error">{riskValidationErrors.fixed_risk_amount}</small>
                    ) : null}
                  </label>
                  <label className="risk-setting-field">
                    <span>{tKey("settings.currency")}</span>
                    <div>
                      <input
                        aria-label={tKey("settings.fixedCurrency")}
                        disabled={busy || !customRiskEnabled || riskDraft.risk_mode !== "fixed"}
                        maxLength={16}
                        onChange={(event) => updateRiskDraft({ fixed_risk_currency: event.target.value.toUpperCase() })}
                        value={riskDraft.fixed_risk_currency}
                      />
                    </div>
                  </label>
                  <label className="risk-setting-field">
                    <FieldLabel help={t(EXECUTION_PROFILE_HELP.radarMode)} label={tKey("settings.radarMode")} />
                    <div>
                      <select
                        aria-label={tKey("settings.radarMode")}
                        title={t(EXECUTION_PROFILE_HELP.radarMode)}
                        disabled={busy || !customRiskEnabled}
                        onChange={(event) => updateRiskDraft({ radar_display_mode: event.target.value as RadarDisplayMode })}
                        value={riskDraft.radar_display_mode}
                      >
                        {RADAR_DISPLAY_MODES.map((mode) => (
                          <option key={mode.value} value={mode.value}>{t(mode.label)}</option>
                        ))}
                      </select>
                    </div>
                    <small className="risk-help-text">{t(EXECUTION_PROFILE_HELP.radarMode)}</small>
                  </label>
                </div>
              </div>
              <div className="risk-settings-grid">
                {RISK_PROFILE_FIELD_LABELS.map((field) => {
                  const error = riskValidationErrorForField(riskValidationErrors, field.key);
                  const help = riskNumericFieldHelp(field.key);
                  const limits = riskNumericFieldLimits(field.key);
                  const required = field.key === "risk_per_trade_percent" && riskDraft.risk_mode === "percent";

                  return (
                    <label className="risk-setting-field" key={field.key}>
                      <FieldLabel help={help ? t(help) : undefined} label={t(field.label)} />
                      <div>
                        <input
                          aria-describedby={`${field.key}-help ${field.key}-error`}
                          aria-label={t(field.label)}
                          aria-invalid={Boolean(error)}
                          aria-required={required}
                          disabled={busy || !customRiskEnabled}
                          inputMode="decimal"
                          max={limits?.max}
                          min={limits?.min ?? 0}
                          onChange={(event) => updateRiskDraft({ [field.key]: Number(event.target.value) })}
                          required={required}
                          step={field.step}
                          title={help ? t(help) : undefined}
                          type="number"
                          value={riskDraft[field.key]}
                        />
                        <small>{field.suffix}</small>
                      </div>
                      {help ? <small className="risk-help-text" id={`${field.key}-help`}>{t(help)}</small> : null}
                      {error ? <small className="risk-field-error" id={`${field.key}-error`}>{error}</small> : null}
                    </label>
                  );
                })}
              </div>
              <div className="risk-inclusion-strip">
                <Badge tone="blue">{tKey("settings.feesIncluded")}</Badge>
                <Badge tone="blue">{tKey("settings.slippageIncluded")}</Badge>
                <Badge tone={riskDraft.stop_loss_required ? "green" : "yellow"}>{tKey("settings.stopRequired")}</Badge>
                <Badge tone={riskDraft.take_profit_required ? "green" : "yellow"}>{tKey("settings.tpRequired")}</Badge>
              </div>
              <div className="risk-plan-block">
                <div className="risk-plan-heading">
                  <strong>{tKey("settings.spotRisk")}</strong>
                </div>
                <div className="risk-settings-grid">
                  {SPOT_TRADE_TYPE_FIELD_LABELS.map((field) => (
                    <label className="risk-setting-field" key={field.key}>
                      <span>{t(field.label)}</span>
                      <div>
                        <input
                          aria-label={t(field.label)}
                          disabled={busy || !customRiskEnabled}
                          inputMode="decimal"
                          min="0"
                          onChange={(event) => updateRiskDraft({ [field.key]: Number(event.target.value) })}
                          step={field.step}
                          type="number"
                          value={riskDraft[field.key]}
                        />
                        <small>{field.suffix}</small>
                      </div>
                    </label>
                  ))}
                </div>
                <label className="risk-checkbox-row">
                  <input
                    checked={riskDraft.spot_stop_required}
                    disabled={busy || !customRiskEnabled}
                    onChange={(event) => updateRiskDraft({ spot_stop_required: event.target.checked })}
                    type="checkbox"
                  />
                  <span>{tKey("settings.spotStopRequired")}</span>
                </label>
              </div>
              <div className="risk-plan-block">
                <div className="risk-plan-heading">
                  <strong>{tKey("settings.adaptiveRisk")}</strong>
                </div>
                <label className="risk-checkbox-row">
                  <input
                    checked={riskDraft.auto_reduce_risk_after_losses}
                    disabled={busy || !customRiskEnabled}
                    onChange={(event) => updateRiskDraft({ auto_reduce_risk_after_losses: event.target.checked })}
                    type="checkbox"
                  />
                  <span>{tKey("settings.autoReduceAfterLosses")}</span>
                </label>
                <label className="risk-checkbox-row">
                  <input
                    checked={riskDraft.allow_risk_increase_after_profit}
                    disabled={busy || !customRiskEnabled}
                    onChange={(event) => updateRiskDraft({ allow_risk_increase_after_profit: event.target.checked })}
                    type="checkbox"
                  />
                  <span>{tKey("settings.allowRiskIncrease")}</span>
                </label>
                <div className="risk-settings-grid">
                  <label className="risk-setting-field">
                    <span>{tKey("settings.maxRiskBoost")}</span>
                    <div>
                      <input
                        aria-label={tKey("settings.maxRiskBoost")}
                        disabled={busy || !customRiskEnabled || !riskDraft.allow_risk_increase_after_profit}
                        inputMode="decimal"
                        min="1"
                        onChange={(event) => updateRiskDraft({ max_risk_boost: Number(event.target.value) })}
                        step="0.05"
                        type="number"
                        value={riskDraft.max_risk_boost}
                      />
                      <small>x</small>
                    </div>
                  </label>
                </div>
              </div>
            </>
          ) : null}

          {riskTab === "rules" ? (
            <>
              <div className="risk-plan-block">
                <div className="risk-plan-heading">
                  <strong>{tKey("settings.rrGuardPolicy")}</strong>
                  <HelpTooltip text={t(EXECUTION_PROFILE_HELP.rrGuard)} />
                </div>
                <p className="risk-help-note">{t(EXECUTION_PROFILE_HELP.rrGuard)}</p>
                <div className="risk-settings-grid compact-risk-grid">
                  {RR_GUARD_FIELD_LABELS.map((field) => (
                    <label className="risk-setting-field" key={field.key}>
                      <FieldLabel help={t(EXECUTION_PROFILE_HELP.rrGuard)} label={t(field.label)} />
                      <div>
                        <select
                          aria-label={t(field.label)}
                          disabled={busy || !customRiskEnabled}
                          onChange={(event) => updateRiskDraft({ [field.key]: event.target.value as RRGuardMode })}
                          title={t(EXECUTION_PROFILE_HELP.rrGuard)}
                          value={riskDraft[field.key]}
                        >
                          {RR_GUARD_MODES.map((mode) => (
                            <option key={mode.value} value={mode.value}>{tKey(mode.labelKey)}</option>
                          ))}
                        </select>
                      </div>
                    </label>
                  ))}
                </div>
              </div>
              <div className="risk-settings-grid compact-risk-grid">
                {TRADE_RULE_FIELD_LABELS.map((field) => (
                  <label className="risk-setting-field" key={field.key}>
                    <span>{t(field.label)}</span>
                    <div>
                      <input
                        aria-label={t(field.label)}
                        disabled={busy || !customRiskEnabled}
                        inputMode="decimal"
                        min="0"
                        onChange={(event) => updateRiskDraft({ [field.key]: Number(event.target.value) })}
                        step={field.step}
                        type="number"
                        value={riskDraft[field.key]}
                      />
                      <small>{field.suffix}</small>
                    </div>
                  </label>
                ))}
              </div>
              <div className="risk-plan-block">
                <div className="risk-plan-heading">
                  <strong>{tKey("settings.stopLoss")}</strong>
                </div>
                <div className="risk-mode-grid">
                  {STOP_LOSS_MODES.map((mode) => (
                    <button
                      className={riskDraft.stop_loss_mode === mode.value ? "active" : ""}
                      disabled={busy || !customRiskEnabled}
                      key={mode.value}
                      onClick={() => updateRiskDraft({ stop_loss_mode: mode.value })}
                      title={t(mode.caption)}
                      type="button"
                    >
                      {t(mode.label)}
                    </button>
                  ))}
                </div>
                <div className="risk-settings-grid compact-risk-grid">
                  {STOP_LOSS_FIELD_LABELS.map((field) => {
                    const atrField = field.key === "atr_period" || field.key === "atr_multiplier";
                    return (
                      <label className="risk-setting-field" key={field.key}>
                        <span>{t(field.label)}</span>
                        <div>
                          <input
                            aria-label={t(field.label)}
                            disabled={busy || !customRiskEnabled || (atrField && riskDraft.stop_loss_mode !== "atr")}
                            inputMode="decimal"
                            min="0"
                            onChange={(event) => updateRiskDraft({ [field.key]: Number(event.target.value) })}
                            step={field.step}
                            type="number"
                            value={riskDraft[field.key]}
                          />
                          <small>{field.suffix}</small>
                        </div>
                      </label>
                    );
                  })}
                </div>
              </div>
              <div className="risk-plan-block">
                <div className="risk-plan-heading">
                  <strong>{tKey("settings.takeProfit")}</strong>
                  <Badge tone="purple">{tKey("settings.riskMultiple")}</Badge>
                </div>
                <div className="risk-settings-grid">
                  {TAKE_PROFIT_FIELD_LABELS.map((field) => (
                    <label className="risk-setting-field" key={field.key}>
                      <span>{t(field.label)}</span>
                      <div>
                        <input
                          aria-label={t(field.label)}
                          disabled={busy || !customRiskEnabled}
                          inputMode="decimal"
                          min="0"
                          onChange={(event) => updateRiskDraft({ [field.key]: Number(event.target.value) })}
                          step={field.step}
                          type="number"
                          value={riskDraft[field.key]}
                        />
                        <small>{field.suffix}</small>
                      </div>
                    </label>
                  ))}
                </div>
                <label className="risk-checkbox-row">
                  <input
                    checked={riskDraft.partial_take_profit_enabled}
                    disabled={busy || !customRiskEnabled}
                    onChange={(event) => updateRiskDraft({ partial_take_profit_enabled: event.target.checked })}
                    type="checkbox"
                  />
                  <span>{tKey("settings.partialTakeProfit")}</span>
                </label>
                <div className="risk-settings-grid">
                  {PARTIAL_TAKE_PROFIT_FIELD_LABELS.map((field) => (
                    <label className="risk-setting-field" key={field.key}>
                      <span>{t(field.label)}</span>
                      <div>
                        <input
                          aria-label={t(field.label)}
                          disabled={busy || !customRiskEnabled || !riskDraft.partial_take_profit_enabled}
                          inputMode="decimal"
                          min="0"
                          onChange={(event) => updateRiskDraft({ [field.key]: Number(event.target.value) })}
                          step={field.step}
                          type="number"
                          value={riskDraft[field.key]}
                        />
                        <small>{field.suffix}</small>
                      </div>
                    </label>
                  ))}
                </div>
              </div>
              <div className="risk-plan-block">
                <div className="risk-plan-heading">
                  <strong>{tKey("settings.breakeven")}</strong>
                </div>
                <div className="risk-settings-grid">
                  {BREAKEVEN_FIELD_LABELS.map((field) => (
                    <label className="risk-setting-field" key={field.key}>
                      <span>{t(field.label)}</span>
                      <div>
                        <input
                          aria-label={t(field.label)}
                          disabled={busy || !customRiskEnabled}
                          inputMode="decimal"
                          min="0"
                          onChange={(event) => updateRiskDraft({ [field.key]: Number(event.target.value) })}
                          step={field.step}
                          type="number"
                          value={riskDraft[field.key]}
                        />
                        <small>{field.suffix}</small>
                      </div>
                    </label>
                  ))}
                </div>
              </div>
              <div className="risk-plan-block">
                <div className="risk-plan-heading">
                  <strong>{tKey("settings.trailingStop")}</strong>
                </div>
                <label className="risk-checkbox-row">
                  <input
                    checked={riskDraft.trailing_stop_enabled}
                    disabled={busy || !customRiskEnabled}
                    onChange={(event) => updateRiskDraft({ trailing_stop_enabled: event.target.checked })}
                    type="checkbox"
                  />
                  <span>{tKey("settings.enabled")}</span>
                </label>
                <div className="risk-mode-grid">
                  {TRAILING_MODES.map((mode) => (
                    <button
                      className={riskDraft.trailing_mode === mode.value ? "active" : ""}
                      disabled={busy || !customRiskEnabled || !riskDraft.trailing_stop_enabled}
                      key={mode.value}
                      onClick={() => updateRiskDraft({ trailing_mode: mode.value })}
                      title={t(mode.caption)}
                      type="button"
                    >
                      {t(mode.label)}
                    </button>
                  ))}
                </div>
                <div className="risk-settings-grid">
                  {TRAILING_FIELD_LABELS.map((field) => {
                    const atrField = field.key === "trailing_atr_multiplier";
                    const percentField = field.key === "trailing_stop_percent";
                    return (
                      <label className="risk-setting-field" key={field.key}>
                        <span>{t(field.label)}</span>
                        <div>
                          <input
                            aria-label={t(field.label)}
                            disabled={
                              busy ||
                              !customRiskEnabled ||
                              !riskDraft.trailing_stop_enabled ||
                              (atrField && riskDraft.trailing_mode !== "atr") ||
                              (percentField && riskDraft.trailing_mode === "atr")
                            }
                            inputMode="decimal"
                            min="0"
                            onChange={(event) => updateRiskDraft({ [field.key]: Number(event.target.value) })}
                            step={field.step}
                            type="number"
                            value={riskDraft[field.key]}
                          />
                          <small>{field.suffix}</small>
                        </div>
                      </label>
                    );
                  })}
                </div>
              </div>
              <div className="risk-plan-block">
                <div className="risk-plan-heading">
                  <strong>{tKey("settings.strategyMultipliers")}</strong>
                  <Badge tone="blue">{tKey("settings.riskMultiplier")}</Badge>
                </div>
                <div className="strategy-multiplier-grid">
                  {Object.entries(riskDraft.strategy_risk_multipliers).map(([strategy, multiplier]) => (
                    <label className="strategy-multiplier-field" key={strategy}>
                      <span>{t(STRATEGY_MULTIPLIER_LABELS[strategy] ?? strategy.replaceAll("_", " "))}</span>
                      <input
                        aria-label={`${STRATEGY_MULTIPLIER_LABELS[strategy] ?? strategy} multiplier`}
                        disabled={busy || !customRiskEnabled}
                        inputMode="decimal"
                        min="0"
                        onChange={(event) => updateStrategyRiskMultiplier(strategy, Number(event.target.value))}
                        step="0.05"
                        type="number"
                        value={Number(multiplier)}
                      />
                    </label>
                  ))}
                </div>
              </div>
            </>
          ) : null}

          {riskTab === "futures" ? (
            <>
              <div className="risk-plan-block">
                <div className="risk-plan-heading">
                  <strong>{tKey("settings.futuresProtection")}</strong>
                </div>
                <label className="risk-checkbox-row">
                  <input
                    checked={riskDraft.liquidation_buffer_required}
                    disabled={busy || !customRiskEnabled}
                    onChange={(event) => updateRiskDraft({ liquidation_buffer_required: event.target.checked })}
                    type="checkbox"
                  />
                  <span>{tKey("settings.liquidationBufferRequired")}</span>
                </label>
                <div className="risk-settings-grid">
                  {FUTURES_FIELD_LABELS.map((field) => {
                    const error = riskValidationErrorForField(riskValidationErrors, field.key);
                    const help = riskNumericFieldHelp(field.key);
                    const limits = riskNumericFieldLimits(field.key);

                    return (
                      <label className="risk-setting-field" key={field.key}>
                        <FieldLabel help={help ? t(help) : undefined} label={t(field.label)} />
                        <div>
                          <input
                            aria-describedby={`${field.key}-help ${field.key}-error`}
                            aria-label={t(field.label)}
                            aria-invalid={Boolean(error)}
                            disabled={busy || !customRiskEnabled}
                            inputMode="decimal"
                            max={limits?.max}
                            min={limits?.min ?? 0}
                            onChange={(event) => updateRiskDraft({ [field.key]: Number(event.target.value) })}
                            step={field.step}
                            title={help ? t(help) : undefined}
                            type="number"
                            value={riskDraft[field.key]}
                          />
                          <small>{field.suffix}</small>
                        </div>
                        {help ? <small className="risk-help-text" id={`${field.key}-help`}>{t(help)}</small> : null}
                        {error ? <small className="risk-field-error" id={`${field.key}-error`}>{error}</small> : null}
                      </label>
                    );
                  })}
                </div>
              </div>
              <div className="risk-plan-block">
                <div className="risk-plan-heading">
                  <strong>{tKey("settings.futuresRiskBudget")}</strong>
                </div>
                <div className="risk-settings-grid">
                  {FUTURES_TRADE_TYPE_FIELD_LABELS.map((field) => {
                    const error = riskValidationErrorForField(riskValidationErrors, field.key);
                    const help = riskNumericFieldHelp(field.key);
                    const limits = riskNumericFieldLimits(field.key);

                    return (
                      <label className="risk-setting-field" key={field.key}>
                        <FieldLabel help={help ? t(help) : undefined} label={t(field.label)} />
                        <div>
                          <input
                            aria-describedby={`${field.key}-help ${field.key}-error`}
                            aria-label={t(field.label)}
                            aria-invalid={Boolean(error)}
                            disabled={busy || !customRiskEnabled}
                            inputMode="decimal"
                            max={limits?.max}
                            min={limits?.min ?? 0}
                            onChange={(event) => updateRiskDraft({ [field.key]: Number(event.target.value) })}
                            step={field.step}
                            title={help ? t(help) : undefined}
                            type="number"
                            value={riskDraft[field.key]}
                          />
                          <small>{field.suffix}</small>
                        </div>
                        {help ? <small className="risk-help-text" id={`${field.key}-help`}>{t(help)}</small> : null}
                        {error ? <small className="risk-field-error" id={`${field.key}-error`}>{error}</small> : null}
                      </label>
                    );
                  })}
                </div>
                <label className="risk-checkbox-row">
                  <input
                    checked={riskDraft.futures_liquidation_buffer_required}
                    disabled={busy || !customRiskEnabled}
                    onChange={(event) => updateRiskDraft({ futures_liquidation_buffer_required: event.target.checked })}
                    type="checkbox"
                  />
                  <span>{tKey("settings.futuresLiquidationBufferRequired")}</span>
                </label>
              </div>
            </>
          ) : null}

          {riskTab === "virtual" ? (
            <>
              <div className="risk-plan-block">
                <div className="risk-plan-heading">
                  <strong>{tKey("settings.virtualRiskBudget")}</strong>
                  <HelpTooltip text={t(EXECUTION_PROFILE_HELP.virtualVsReal)} />
                </div>
                <p className="risk-help-note">{t(EXECUTION_PROFILE_HELP.virtualVsReal)}</p>
                <div className="risk-mode-grid two-option-grid">
                  {VIRTUAL_RISK_MODES.map((mode) => (
                    <button
                      className={riskDraft.virtual_risk_mode === mode.value ? "active" : ""}
                      disabled={busy || !customRiskEnabled}
                      key={mode.value}
                      onClick={() => updateRiskDraft({ virtual_risk_mode: mode.value })}
                      type="button"
                    >
                      {t(mode.label)}
                    </button>
                  ))}
                </div>
                <div className="risk-settings-grid">
                  {VIRTUAL_TRADE_TYPE_FIELD_LABELS.map((field) => {
                    const virtualRisk = field.key === "virtual_risk_per_trade_percent";
                    return (
                      <label className="risk-setting-field" key={field.key}>
                        <span>{t(field.label)}</span>
                        <div>
                          <input
                            aria-label={t(field.label)}
                            disabled={busy || !customRiskEnabled || (virtualRisk && riskDraft.virtual_risk_mode !== "custom")}
                            inputMode="decimal"
                            min="0"
                            onChange={(event) => updateRiskDraft({ [field.key]: Number(event.target.value) })}
                            step={field.step}
                            type="number"
                            value={riskDraft[field.key]}
                          />
                          <small>{field.suffix}</small>
                        </div>
                      </label>
                    );
                  })}
                </div>
              </div>
              <div className="risk-plan-block">
                <div className="risk-plan-heading">
                  <strong>{tKey("settings.virtualExecution")}</strong>
                  <HelpTooltip text={t(EXECUTION_PROFILE_HELP.virtualVsReal)} />
                </div>
                <div className="risk-mode-grid">
                  {VIRTUAL_SLIPPAGE_MODELS.map((model) => (
                    <button
                      className={riskDraft.virtual_slippage_model === model.value ? "active" : ""}
                      disabled={busy || !customRiskEnabled}
                      key={model.value}
                      onClick={() => updateRiskDraft({ virtual_slippage_model: model.value })}
                      type="button"
                    >
                      {t(model.label)}
                    </button>
                  ))}
                </div>
                <div className="risk-mode-grid two-option-grid">
                  {VIRTUAL_FEE_MODELS.map((model) => (
                    <button
                      className={riskDraft.virtual_fee_model === model.value ? "active" : ""}
                      disabled={busy || !customRiskEnabled}
                      key={model.value}
                      onClick={() => updateRiskDraft({ virtual_fee_model: model.value })}
                      type="button"
                    >
                      {t(model.label)}
                    </button>
                  ))}
                </div>
                <label className="risk-checkbox-row">
                  <input
                    checked={riskDraft.virtual_trading_uses_realistic_execution}
                    disabled={busy || !customRiskEnabled}
                    onChange={(event) => updateRiskDraft({ virtual_trading_uses_realistic_execution: event.target.checked })}
                    type="checkbox"
                  />
                  <span>{tKey("settings.realisticExecution")}</span>
                </label>
              </div>
            </>
          ) : null}

          {riskTab === "guide" ? (
            <RiskManagementGuide riskDraft={riskDraft} riskState={riskState} />
          ) : null}

          <div className="risk-profile-footer">
            <span>
              {riskDraftValid
                ? tKey("settings.balancedDefaultSafety")
                : Object.values(riskValidationErrors)[0]}
            </span>
            <button
              className="secondary-action"
              disabled={busy || !customRiskEnabled || !riskDraftValid}
              onClick={handleSaveCustomRisk}
              type="button"
            >
              {tKey("settings.saveCustom")}
            </button>
          </div>
        </SettingsAccordionSection>

        <SettingsAccordionSection
          id="simulation"
          icon={<Gauge size={18} />}
          onToggle={() => toggleSettingsSection("simulation")}
          open={openSettingsSections.has("simulation")}
          summary={simulationLevel}
          title={tKey("settings.simulation")}
        >
          <div className="simulation-mode-grid">
            {SIMULATION_LEVELS.map((level) => (
              <button
                className={`simulation-mode-option ${simulationLevel === level.value ? "active" : ""}`}
                disabled={busy}
                key={level.value}
                onClick={() => onSelectSimulationLevel(level.value)}
                type="button"
              >
                <span>
                  <strong>{t(level.label)}</strong>
                  <small>{t(level.caption)}</small>
                </span>
                <Badge tone={level.status === "active" ? "green" : "yellow"}>{t(level.status)}</Badge>
              </button>
            ))}
          </div>
        </SettingsAccordionSection>

        <SettingsAccordionSection
          className="strategy-testing-section"
          id="strategyTesting"
          icon={<FlaskConical size={18} />}
          onToggle={() => toggleSettingsSection("strategyTesting")}
          open={openSettingsSections.has("strategyTesting")}
          summary={tKey("settings.backtestLab")}
          title={tKey("settings.strategyTesting")}
        >
          <StrategyTestingPanel availablePairs={availablePairs} strategyConfigs={strategyConfigs} />
        </SettingsAccordionSection>

        <SettingsAccordionSection
          className="alerts-section"
          id="alerts"
          icon={<Bell size={18} />}
          onToggle={() => toggleSettingsSection("alerts")}
          open={openSettingsSections.has("alerts")}
          summary={tKey("settings.ruleCount", { count: alertRules.length, suffix: alertRules.length === 1 ? "" : "s" })}
          title={tKey("settings.alerts")}
        >
          <div className="inline-form stacked">
            <select
              aria-label={tKey("settings.alertPair")}
              disabled={busy || availablePairs.length === 0}
              onChange={(event) => setPairId(event.target.value)}
              value={pairId}
            >
              <option value="">{availablePairs.length ? tKey("settings.selectPairOption") : tKey("settings.noPairs")}</option>
              {availablePairs.map((pair) => (
                <option key={pair.id} value={pair.id}>{pair.exchange}:{pair.symbol}</option>
              ))}
            </select>
            <select
              aria-label={tKey("settings.alertCondition")}
              disabled={busy}
              onChange={(event) => setConditionType(event.target.value)}
              value={conditionType}
            >
              <option value="price_above">{tKey("settings.priceAbove")}</option>
              <option value="price_below">{tKey("settings.priceBelow")}</option>
              <option value="signal_generated">{tKey("settings.signalGenerated")}</option>
            </select>
            <input
              aria-label={tKey("settings.alertPrice")}
              disabled={busy}
              inputMode="decimal"
              onChange={(event) => setTargetPrice(event.target.value)}
              placeholder={tKey("settings.alertPrice")}
              type="number"
              value={targetPrice}
            />
            <button className="primary-action" disabled={busy || !selectedPair || !targetPrice} onClick={handleCreateAlert} type="button">
              <Bell size={16} />
              {tKey("common.add")}
            </button>
          </div>

          <div className="alert-list">
            {alertRules.length === 0 ? <div className="empty-state compact-empty">{tKey("settings.noAlertRules")}</div> : null}
            {alertRules.map((alert) => (
              <div className="alert-row" key={alert.id}>
                <div>
                  <strong>{alert.pair?.symbol ?? tKey("settings.global")}</strong>
                  <span>{alert.condition_type} {formatCondition(alert.condition_body)}</span>
                </div>
                <label className="toggle-row compact-toggle">
                  <input
                    checked={alert.is_enabled}
                    disabled={busy}
                    onChange={(event) => onToggleAlert(alert.id, event.target.checked)}
                    type="checkbox"
                  />
                  <span>{alert.is_enabled ? tKey("common.on") : tKey("common.off")}</span>
                </label>
                <button className="icon-button compact" disabled={busy} onClick={() => onTestAlert(alert.id)} title={tKey("settings.test")} type="button">
                  <Send size={15} />
                </button>
                <button className="icon-button compact" disabled={busy} onClick={() => onDeleteAlert(alert.id)} title={tKey("common.delete")} type="button">
                  <Trash2 size={15} />
                </button>
              </div>
            ))}
          </div>
        </SettingsAccordionSection>

        <SettingsAccordionSection
          id="timeframes"
          icon={<Gauge size={18} />}
          onToggle={() => toggleSettingsSection("timeframes")}
          open={openSettingsSections.has("timeframes")}
          summary={`${(config?.timeframes ?? ["1m", "5m", "15m", "1h", "4h", "1d"]).length} ${tKey("common.active").toLowerCase()}`}
          title={tKey("settings.timeframes")}
        >
          <div className="chip-cloud">
            {(config?.timeframes ?? ["1m", "5m", "15m", "1h", "4h", "1d"]).map((timeframe) => (
              <Badge tone="purple" key={timeframe}>{timeframe}</Badge>
            ))}
          </div>
        </SettingsAccordionSection>
      </div>
      </section>
      {connectionDeleteCandidate ? (
        <div className="real-trade-modal-backdrop">
          <div aria-labelledby="exchange-delete-title" aria-modal="true" className="real-trade-modal exchange-delete-modal" role="dialog">
            <div className="real-trade-modal-header">
              <div>
                <span className="muted">{tKey("exchange.connection")}</span>
                <h3 id="exchange-delete-title">{tKey("settings.deleteExchangeConnection")}</h3>
              </div>
              <Badge tone="red">{tKey("settings.softDelete")}</Badge>
            </div>
            <div className="real-trade-warning">
              <AlertTriangle size={18} />
              <span>
                {tKey("settings.deleteExchangeConnectionBody", {
                  exchange: connectionDeleteCandidate.exchange_name,
                  label: connectionDeleteCandidate.label
                })}
              </span>
            </div>
            {connectionDeleteError ? (
              <div className="strategy-error-message exchange-delete-error" role="alert">
                {connectionDeleteError}
              </div>
            ) : null}
            <div className="real-trade-modal-actions">
              <button className="secondary-action" disabled={busy} onClick={cancelDeleteExchangeConnection} type="button">
                {tKey("common.cancel")}
              </button>
              <button className="danger-action" disabled={busy} onClick={handleDeleteExchangeConnection} type="button">
                <Trash2 size={17} /> {tKey("settings.deleteExchangeConnection")}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}

interface StrategyPairSelectorProps {
  busy: boolean;
  onChange: (pairs: StrategyPairScope[]) => void;
  selectedPairs: StrategyPairScope[];
  strategyId: string;
}

function StrategyPairSelector({
  busy,
  onChange,
  selectedPairs,
  strategyId
}: StrategyPairSelectorProps) {
  const { t, tKey } = useI18n();
  const [exchange, setExchange] = useState(DEFAULT_MARKET_UNIVERSE_FILTERS.exchange);
  const [category, setCategory] = useState(DEFAULT_MARKET_UNIVERSE_FILTERS.category);
  const [limit, setLimit] = useState<MarketUniverseLimit>(DEFAULT_MARKET_UNIVERSE_FILTERS.limit);
  const [search, setSearch] = useState(DEFAULT_MARKET_UNIVERSE_FILTERS.search);
  const [liquidityTier, setLiquidityTier] = useState(DEFAULT_MARKET_UNIVERSE_FILTERS.liquidity_tier);
  const [sort, setSort] = useState(DEFAULT_MARKET_UNIVERSE_FILTERS.sort);
  const queryParams = useMemo(
    () => ({
      category,
      exchange,
      limit,
      liquidity_tier: liquidityTier || undefined,
      quote: DEFAULT_MARKET_UNIVERSE_FILTERS.quote,
      search: search.trim() || undefined,
      sort,
      status: DEFAULT_MARKET_UNIVERSE_FILTERS.status
    }),
    [category, exchange, limit, liquidityTier, search, sort]
  );
  const pairsQuery = useMarketUniversePairsQuery(queryParams);
  const syncUniverseMutation = useSyncMarketUniverseMutation();
  const universePairs = pairsQuery.data ?? EMPTY_MARKET_UNIVERSE_PAIRS;
  const selectedPairKeys = useMemo(
    () => new Set(selectedPairs.map(pairKey)),
    [selectedPairs]
  );
  const lowLiquidityPairs = useMemo(
    () =>
      universePairs.filter(
        (pair) => selectedPairKeys.has(pairKey(pair)) && pair.liquidity_tier?.toLowerCase() === "low"
      ),
    [selectedPairKeys, universePairs]
  );
  const visibleLimitLabel = MARKET_UNIVERSE_LIMITS.find((option) => option.value === limit)?.label ?? "Top N";
  const lastSyncAt = syncUniverseMutation.data?.synced_at ?? latestSyncedAt(universePairs);
  const selectedSummary = selectedPairs.length
    ? tKey("settings.selectedPairsCount", { count: selectedPairs.length })
    : tKey("settings.allPairsFromScannerUniverse");
  const selectorTitleId = `strategy-pair-selector-${strategyId}`;

  function togglePair(pair: MarketUniversePair, checked: boolean) {
    const scope = pairScope(pair);
    if (checked) {
      onChange(dedupeStrategyPairs([...selectedPairs, scope]));
      return;
    }
    onChange(selectedPairs.filter((selectedPair) => pairKey(selectedPair) !== pairKey(scope)));
  }

  function selectVisiblePairs() {
    onChange(dedupeStrategyPairs([...selectedPairs, ...universePairs.map(pairScope)]));
  }

  function replaceWithVisibleTop() {
    onChange(dedupeStrategyPairs(universePairs.map(pairScope)));
  }

  function clearSelectedPairs() {
    onChange([]);
  }

  async function syncUniverse() {
    try {
      await syncUniverseMutation.mutateAsync({
        category,
        exchange,
        limit,
        persist: true,
        quote: DEFAULT_MARKET_UNIVERSE_FILTERS.quote,
        sort
      });
    } catch {
      // Mutation state renders the error message in this block.
    }
  }

  return (
    <section className="strategy-pair-selector" aria-labelledby={selectorTitleId}>
      <div className="strategy-pair-selector-head">
        <div>
          <span id={selectorTitleId}>{tKey("settings.strategyPairs")}</span>
          <strong>{selectedSummary}</strong>
        </div>
        <div className="strategy-pair-sync">
          <span>{tKey("settings.lastSync", { value: lastSyncAt ? formatDateTime(lastSyncAt) : tKey("settings.noData") })}</span>
          <button
            className="secondary-action compact-action"
            disabled={busy || syncUniverseMutation.isPending}
            onClick={syncUniverse}
            type="button"
          >
            <RefreshCw size={15} />
            {tKey("settings.syncPairsFromExchange")}
          </button>
        </div>
      </div>

      <div className="strategy-pair-filter-grid">
        <label>
          <span>{tKey("common.exchange")}</span>
          <select
            aria-label={tKey("common.exchange")}
            disabled={busy}
            onChange={(event) => setExchange(event.target.value)}
            value={exchange}
          >
            <option value="bybit">{MARKET_UNIVERSE_EXCHANGE_LABELS.bybit}</option>
          </select>
        </label>
        <label>
          <span>{tKey("common.market")}</span>
          <select
            aria-label="Market category universe"
            disabled={busy}
            onChange={(event) => setCategory(event.target.value)}
            value={category}
          >
            {MARKET_UNIVERSE_CATEGORIES.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
        <label>
          <span>{tKey("settings.universeSize")}</span>
          <select
            aria-label={tKey("settings.universeSize")}
            disabled={busy}
            onChange={(event) => setLimit(event.target.value as MarketUniverseLimit)}
            value={limit}
          >
            {MARKET_UNIVERSE_LIMITS.map((option) => (
              <option key={option.value} value={option.value}>{t(option.label)}</option>
            ))}
          </select>
        </label>
        <label>
          <span>{tKey("common.search")}</span>
          <input
            aria-label="Search pair symbol"
            disabled={busy}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="BTCUSDT"
            value={search}
          />
        </label>
        <label>
          <span>{tKey("settings.liquidityTier")}</span>
          <select
            aria-label={tKey("settings.liquidityTier")}
            disabled={busy}
            onChange={(event) => setLiquidityTier(event.target.value)}
            value={liquidityTier}
          >
            {MARKET_UNIVERSE_TIERS.map((option) => (
              <option key={option.value || "all"} value={option.value}>{t(option.label)}</option>
            ))}
          </select>
        </label>
        <label>
          <span>{tKey("common.sort")}</span>
          <select
            aria-label="Sort market universe"
            disabled={busy}
            onChange={(event) => setSort(event.target.value)}
            value={sort}
          >
            {MARKET_UNIVERSE_SORTS.map((option) => (
              <option key={option.value} value={option.value}>{t(option.label)}</option>
            ))}
          </select>
        </label>
      </div>

      <div className="strategy-pair-actions">
        <button
          className="secondary-action compact-action"
          disabled={busy || universePairs.length === 0}
          onClick={selectVisiblePairs}
          type="button"
        >
          <CheckSquare size={15} />
          {tKey("settings.selectVisible")}
        </button>
        <button
          className="secondary-action compact-action"
          disabled={busy || universePairs.length === 0}
          onClick={replaceWithVisibleTop}
          type="button"
        >
          <ListChecks size={15} />
          {tKey("settings.selectVisibleLimit", { limit: visibleLimitLabel })}
        </button>
        <button
          className="secondary-action compact-action"
          disabled={busy || selectedPairs.length === 0}
          onClick={clearSelectedPairs}
          type="button"
        >
          <Trash2 size={15} />
          {tKey("settings.clear")}
        </button>
        <Badge tone={selectedPairs.length ? "blue" : "purple"}>{selectedSummary}</Badge>
      </div>

      {lowLiquidityPairs.length ? (
        <div className="strategy-liquidity-warning" role="alert">
          <AlertTriangle size={16} />
          <span>{tKey("settings.selectedLowLiquidityPairs", { pairs: lowLiquidityPairs.map((pair) => pair.symbol).join(", ") })}</span>
        </div>
      ) : null}

      {pairsQuery.error || syncUniverseMutation.error ? (
        <div className="strategy-error-message" role="alert">
          {pairsQuery.error
            ? tKey("settings.universeLoadFailed", { error: errorMessage(pairsQuery.error) })
            : tKey("settings.universeSyncFailed", { error: errorMessage(syncUniverseMutation.error) })}
        </div>
      ) : null}

      <div className="strategy-pair-table-wrap">
        <table className="strategy-pair-table">
          <thead>
            <tr>
              <th aria-label={tKey("settings.selectPair", { symbol: "" })} />
              <th>{tKey("settings.symbol")}</th>
              <th>{tKey("settings.turnover24h")}</th>
              <th>{tKey("settings.spreadBps")}</th>
              <th>{tKey("settings.liquidityTier")}</th>
              <th>{tKey("settings.funding")}</th>
              <th>{tKey("common.status")}</th>
              <th>{tKey("settings.rank")}</th>
            </tr>
          </thead>
          <tbody>
            {universePairs.map((pair) => {
              const checked = selectedPairKeys.has(pairKey(pair));
              return (
                <tr key={pair.id || pairKey(pair)}>
                  <td>
                    <input
                      aria-label={tKey("settings.selectPair", { symbol: pair.symbol })}
                      checked={checked}
                      disabled={busy}
                      onChange={(event) => togglePair(pair, event.target.checked)}
                      type="checkbox"
                    />
                  </td>
                  <td>
                    <strong>{pair.symbol}</strong>
                    <span>{pair.base_asset}/{pair.quote_asset}</span>
                  </td>
                  <td>{formatCompactUsd(pair.turnover_24h)}</td>
                  <td>{formatBps(pair.spread_bps)}</td>
                  <td>
                    <Badge tone={liquidityTierTone(pair.liquidity_tier)}>{pair.liquidity_tier ?? "unknown"}</Badge>
                  </td>
                  <td>{formatFunding(pair.funding_rate)}</td>
                  <td>{formatUniverseStatus(pair.status)}</td>
                  <td>{pair.liquidity_rank ?? "-"}</td>
                </tr>
              );
            })}
            {pairsQuery.isLoading ? (
              <tr>
                <td colSpan={8}>{tKey("settings.universeLoading")}</td>
              </tr>
            ) : null}
            {!pairsQuery.isLoading && universePairs.length === 0 ? (
              <tr>
                <td colSpan={8}>{tKey("settings.universeEmpty")}</td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function HelpTooltip({ text }: { text: string }) {
  return (
    <span aria-label={text} className="risk-help-tooltip" role="img" title={text}>
      <Info aria-hidden="true" size={14} />
    </span>
  );
}

function FieldLabel({ help, label }: { help?: string; label: string }) {
  return (
    <span className="risk-field-label">
      <span>{label}</span>
      {help ? <HelpTooltip text={help} /> : null}
    </span>
  );
}

function SettingsAccordionSection({
  children,
  className,
  icon,
  id,
  onToggle,
  open,
  summary,
  title
}: {
  children: ReactNode;
  className?: string;
  icon: ReactNode;
  id: SettingsSectionId;
  onToggle: () => void;
  open: boolean;
  summary?: string;
  title: string;
}) {
  return (
    <section className={`settings-section settings-accordion-section ${open ? "open" : ""} ${className ?? ""}`}>
      <button
        aria-controls={`settings-section-${id}`}
        aria-expanded={open}
        className="settings-accordion-trigger"
        onClick={onToggle}
        type="button"
      >
        <div className="section-title">{icon}<h3>{title}</h3></div>
        {summary ? <span className="settings-section-summary">{summary}</span> : null}
        <ChevronDown className="settings-chevron" size={18} />
      </button>
      {open ? (
        <div className="settings-accordion-content" id={`settings-section-${id}`}>
          {children}
        </div>
      ) : null}
    </section>
  );
}

function RiskManagementGuide({
  riskDraft,
  riskState
}: {
  riskDraft: RiskManagementSettings;
  riskState: RiskStateResponse | null;
}) {
  const { tKey } = useI18n();
  return (
    <div className="risk-guide">
      <div className="risk-guide-intro">
        <div className="risk-guide-title">
          <BookOpen size={18} />
          <div>
            <strong>{tKey("settings.riskGuideTitle")}</strong>
            <span>{tKey("settings.riskGuideIntro")}</span>
          </div>
        </div>
      </div>

      <div className="risk-guide-snapshot">
        <div>
          <span>{tKey("settings.currentProfile")}</span>
          <strong>{riskDraft.risk_profile}</strong>
        </div>
        <div>
          <span>{tKey("settings.riskPerTrade")}</span>
          <strong>{formatPercentValue(riskDraft.risk_per_trade_percent)}</strong>
        </div>
        <div>
          <span>{tKey("settings.openRiskShort")}</span>
          <strong>
            {riskState
              ? formatRiskUsageValue(riskState.open_risk_percent, riskState.max_open_risk_percent, tKey)
              : "-"}
          </strong>
        </div>
        <div>
          <span>{tKey("settings.correlated")}</span>
          <strong>
            {riskState
              ? formatRiskUsageValue(riskState.correlated_risk_percent, riskState.max_correlated_risk_percent, tKey)
              : "-"}
          </strong>
        </div>
        <div>
          <span>{tKey("settings.drawdown")}</span>
          <strong>
            {riskState
              ? formatRiskUsageValue(riskState.account_drawdown_percent, riskState.max_account_drawdown_percent, tKey)
              : "-"}
          </strong>
        </div>
        <div>
          <span>{tKey("risk.protection")}</span>
          <strong>{riskState?.protection_state ?? "-"}</strong>
        </div>
      </div>

      <div className="risk-guide-playbook">
        <div className="risk-guide-block">
          <h4>{tKey("settings.riskGuideBlockedTitle")}</h4>
          <ol>
            <li>{tKey("settings.riskGuideBlocked1")}</li>
            <li>{tKey("settings.riskGuideBlocked2")}</li>
            <li>{tKey("settings.riskGuideBlocked3")}</li>
            <li>{tKey("settings.riskGuideBlocked4")}</li>
            <li>{tKey("settings.riskGuideBlocked5")}</li>
            <li>{tKey("settings.riskGuideBlocked6")}</li>
          </ol>
        </div>
        <div className="risk-guide-block">
          <h4>{tKey("settings.riskGuideRelaxTitle")}</h4>
          <ul>
            <li>{tKey("settings.riskGuideRelax1")}</li>
            <li>{tKey("settings.riskGuideRelax2")}</li>
            <li>{tKey("settings.riskGuideRelax3")}</li>
            <li>{tKey("settings.riskGuideRelax4")}</li>
          </ul>
        </div>
      </div>

      <div className="risk-guide-blocker-grid">
        {RISK_BLOCKER_GUIDE.map((item) => (
          <article className="risk-guide-mini" key={item.title}>
            <h4>{item.title}</h4>
            <p>{item.body}</p>
            {item.tip ? <small>{item.tip}</small> : null}
          </article>
        ))}
      </div>

      <div className="risk-guide-sections">
        {RISK_GUIDE_SECTIONS.map((section) => (
          <section className="risk-guide-section" key={section.title}>
            <h4>{section.title}</h4>
            <p>{section.intro}</p>
            <div className="risk-guide-item-list">
              {section.items.map((item) => (
                <article className="risk-guide-item" key={item.title}>
                  <strong>{item.title}</strong>
                  <span>{item.body}</span>
                  {item.tip ? <small>{item.tip}</small> : null}
                </article>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

function formatCondition(condition: Record<string, unknown>): string {
  const price = condition.price;
  if (typeof price === "number" || typeof price === "string") return String(price);
  return "";
}

function shortKeyRef(keyRef: string): string {
  const parts = keyRef.split("/");
  const suffix = parts[parts.length - 1] ?? keyRef;
  return `key_ref:${suffix.slice(0, 8)}`;
}

function formatBalanceAmount(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "-";
  return value.toLocaleString("en-US", {
    currency: "USD",
    maximumFractionDigits: value >= 1000 ? 2 : 6,
    minimumFractionDigits: value >= 1000 ? 2 : 0,
    style: "currency"
  });
}

function formatSnapshotAge(value: string | null | undefined): string {
  if (!value) return "missing";
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return "unknown";
  const diffSeconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
  if (diffSeconds < 60) return "just now";
  const diffMinutes = Math.floor(diffSeconds / 60);
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  return `${Math.floor(diffMinutes / 60)}h ago`;
}

function snapshotStatusTone(status: AccountRiskSnapshot["status"]): "green" | "red" | "yellow" | "blue" {
  if (status === "fresh") return "green";
  if (status === "stale") return "yellow";
  return "red";
}

function uniqueStrings(values: string[]): string[] {
  return Array.from(new Set(values.map((value) => value.trim()).filter(Boolean)));
}

function dedupeStrings(values: string[]): string[] {
  return Array.from(new Set(values.map((value) => value.trim().toLowerCase()).filter(Boolean)));
}

function pairKey(pair: Pick<StrategyPairScope, "exchange" | "symbol">): string {
  return `${pair.exchange.trim().toLowerCase()}:${pair.symbol.trim().toUpperCase()}`;
}

function pairScope(pair: Pick<MarketUniversePair, "exchange" | "symbol">): StrategyPairScope {
  return {
    exchange: pair.exchange.trim().toLowerCase(),
    symbol: pair.symbol.trim().toUpperCase()
  };
}

function dedupeStrategyPairs(pairs: StrategyPairScope[]): StrategyPairScope[] {
  const seen = new Set<string>();
  const deduped: StrategyPairScope[] = [];
  for (const pair of pairs) {
    const scope = {
      exchange: pair.exchange.trim().toLowerCase(),
      symbol: pair.symbol.trim().toUpperCase()
    };
    const key = pairKey(scope);
    if (!scope.exchange || !scope.symbol || seen.has(key)) continue;
    seen.add(key);
    deduped.push(scope);
  }
  return deduped;
}

function pairScopeListKey(pairs: StrategyPairScope[]): string {
  return dedupeStrategyPairs(pairs).map(pairKey).join(",");
}

function latestSyncedAt(pairs: MarketUniversePair[]): string | null {
  let latestTimestamp = 0;
  let latestValue: string | null = null;
  for (const pair of pairs) {
    if (!pair.synced_at) continue;
    const timestamp = Date.parse(pair.synced_at);
    if (Number.isFinite(timestamp) && timestamp > latestTimestamp) {
      latestTimestamp = timestamp;
      latestValue = pair.synced_at;
    }
  }
  return latestValue;
}

function formatDateTime(value: string): string {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return value;
  return new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "short",
    timeStyle: "short"
  }).format(new Date(timestamp));
}

function formatCompactUsd(value: string | null): string {
  const numericValue = decimalStringToNumber(value);
  if (numericValue == null) return "-";
  return new Intl.NumberFormat("en-US", {
    currency: "USD",
    maximumFractionDigits: 2,
    notation: Math.abs(numericValue) >= 1_000_000 ? "compact" : "standard",
    style: "currency"
  }).format(numericValue);
}

function formatBps(value: string | null): string {
  const numericValue = decimalStringToNumber(value);
  return numericValue == null ? "-" : numericValue.toFixed(2);
}

function formatFunding(value: string | null): string {
  const numericValue = decimalStringToNumber(value);
  return numericValue == null ? "-" : `${(numericValue * 100).toFixed(4)}%`;
}

function decimalStringToNumber(value: string | null): number | null {
  if (value == null || value === "") return null;
  const numericValue = Number(value);
  return Number.isFinite(numericValue) ? numericValue : null;
}

function liquidityTierTone(tier: string | null): "green" | "red" | "yellow" | "blue" | "purple" | "neutral" {
  const normalized = tier?.toLowerCase();
  if (normalized === "high") return "green";
  if (normalized === "medium") return "yellow";
  if (normalized === "low") return "red";
  return "neutral";
}

function formatUniverseStatus(status: string): string {
  return status.replaceAll("_", " ");
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "unknown error";
}

function strategyUpdateErrorMessage(error: unknown, tKey: TKey): string {
  const message = errorMessage(error);
  if (/not found in market_pairs|market pair .* is not found/i.test(message)) {
    return tKey("commonErrors.marketPairNotFoundInUniverse");
  }
  return message;
}

function exchangeConnectionDeleteErrorMessage(error: unknown, tKey: TKey): string {
  const message = errorMessage(error);
  if (/not found|не найден/i.test(message)) {
    return tKey("commonErrors.exchangeConnectionNotFound");
  }
  if (/external history|historical|истор/i.test(message)) {
    return tKey("commonErrors.exchangeConnectionHasHistory");
  }
  if (/hard delete|admin|администратор/i.test(message)) {
    return tKey("commonErrors.hardDeleteRequiresAdmin");
  }
  return message;
}

function isVisibleExchangeConnection(connection: ExchangeConnection): boolean {
  return connection.status !== "deleted" && connection.status !== "revoked";
}

function normalizeOrderPlacementMode(value: string): ExchangeConnection["order_placement_mode"] {
  if (
    value === "disabled" ||
    value === "dry_run_orders" ||
    value === "testnet_real_orders" ||
    value === "mainnet_small_size" ||
    value === "mainnet_scaled" ||
    value === "live"
  ) {
    return value;
  }
  return "dry_run";
}

function orderPlacementModeKey(mode: ExchangeConnection["order_placement_mode"]): I18nKey {
  if (mode === "disabled") return "exchange.orderPlacementDisabled";
  if (mode === "dry_run_orders") return "exchange.orderPlacementDryRunOrders";
  if (mode === "testnet_real_orders") return "exchange.orderPlacementTestnetRealOrders";
  if (mode === "mainnet_small_size") return "exchange.orderPlacementMainnetSmallSize";
  if (mode === "mainnet_scaled") return "exchange.orderPlacementMainnetScaled";
  if (mode === "live") return "exchange.orderPlacementLive";
  return "exchange.orderPlacementDryRun";
}

function isRealOrderMode(mode: ExchangeConnection["order_placement_mode"]): boolean {
  return mode === "live" || mode === "testnet_real_orders" || isMainnetOrderMode(mode);
}

function isMainnetOrderMode(mode: ExchangeConnection["order_placement_mode"]): boolean {
  return mode === "live" || mode === "mainnet_small_size" || mode === "mainnet_scaled";
}

function isDryRunOrderMode(mode: ExchangeConnection["order_placement_mode"]): boolean {
  return mode === "dry_run" || mode === "dry_run_orders";
}

function exchangeConnectionExecutionBadge(connection: ExchangeConnection): { labelKey: I18nKey; tone: "blue" | "green" | "red" | "yellow" } {
  if (connection.environment === "testnet") {
    if (isRealOrderMode(connection.order_placement_mode) && connection.can_place_orders) {
      return { labelKey: "exchange.testnetLive", tone: "green" };
    }
    return { labelKey: "exchange.testnetDryRun", tone: "blue" };
  }
  if (connection.can_place_orders) {
    return { labelKey: "exchange.mainnetLiveEnabled", tone: "green" };
  }
  return { labelKey: "exchange.mainnetBlocked", tone: "red" };
}

function safetyBlockerSummary(connection: ExchangeConnection): string {
  if (isDryRunOrderMode(connection.order_placement_mode)) return "order_placement_dry_run";
  if (connection.order_placement_mode === "disabled") return "order_placement_disabled";
  if (connection.safety_blockers.length === 0) return "live_safety_pending";
  return connection.safety_blockers.slice(0, 2).join(", ");
}

function omitRecordKey<T>(record: Record<string, T>, key: string): Record<string, T> {
  if (!(key in record)) return record;
  const next = { ...record };
  delete next[key];
  return next;
}

function getContextTimeframeMap(params: Record<string, unknown>): Record<string, string> {
  const rawMap = params.context_timeframe_map;
  if (!rawMap || typeof rawMap !== "object" || Array.isArray(rawMap)) return {};
  return Object.fromEntries(
    Object.entries(rawMap)
      .map(([signalTimeframe, contextTimeframe]) => [
        signalTimeframe.trim().toLowerCase(),
        String(contextTimeframe).trim().toLowerCase()
      ])
      .filter(([signalTimeframe, contextTimeframe]) => signalTimeframe && contextTimeframe && contextTimeframe !== "default")
  );
}

function contextTimeframeOptions(signalTimeframe: string): string[] {
  const index = STRATEGY_TIMEFRAMES.indexOf(signalTimeframe);
  if (index < 0) return STRATEGY_TIMEFRAMES;
  return STRATEGY_TIMEFRAMES.slice(index + 1);
}

function defaultMaxBodyAtr(strategyCode: string): number {
  return MAX_BODY_ATR_DEFAULTS[strategyCode] ?? 2.5;
}

function defaultMaxRangeAtr(strategyCode: string): number {
  return MAX_RANGE_ATR_DEFAULTS[strategyCode] ?? 3.5;
}

function defaultRrTarget(strategyCode: string): "final" | "nearest" {
  return RR_TARGET_DEFAULTS[strategyCode] ?? "final";
}

function normalizeRRGuardMode(value: FormDataEntryValue | unknown, fallback: RRGuardMode): RRGuardMode {
  return value === "off" || value === "soft" || value === "hard" ? value : fallback;
}

function normalizeRadarDisplayMode(value: FormDataEntryValue | unknown): RadarDisplayMode {
  return RADAR_DISPLAY_MODES.some((mode) => mode.value === value)
    ? value as RadarDisplayMode
    : "all_market_opportunities";
}

function riskProtectionTone(mode: RiskProtectionMode): "green" | "red" | "yellow" | "blue" {
  if (mode === "blocked") return "red";
  if (mode === "virtual_only" || mode === "reduced") return "yellow";
  return "green";
}

function formatPercentValue(value: number): string {
  return `${value.toFixed(2)}%`;
}

function formatRiskUsageValue(used: number, limit: number, tKey: TKey): string {
  return `${formatPercentValue(used)} / ${limit <= 0 ? tKey("common.off") : formatPercentValue(limit)}`;
}

function validateRiskDraft(settings: RiskManagementSettings): RiskValidationErrors {
  const errors: RiskValidationErrors = {};

  if (settings.risk_mode === "percent" && !isPositiveNumber(settings.risk_per_trade_percent)) {
    errors.risk_per_trade_percent = "Risk percent is required when risk mode is Percent.";
  }

  if (settings.risk_mode === "fixed" && !isPositiveNumber(settings.fixed_risk_amount)) {
    errors.fixed_risk_amount = "Fixed amount is required when risk mode is Fixed.";
  }

  validateLeverageValue(errors, "max_leverage", settings.max_leverage, "Max leverage");
  validateLeverageValue(errors, "futures_max_leverage", settings.futures_max_leverage, "Futures max leverage");

  return errors;
}

function validateLeverageValue(
  errors: RiskValidationErrors,
  field: "futures_max_leverage" | "max_leverage",
  value: number,
  label: string
) {
  const limits = RISK_MANAGEMENT_SCHEMA_LIMITS[field];
  if (!Number.isFinite(value) || value < limits.min || (limits.max != null && value > limits.max)) {
    errors[field] = `${label} must be between ${limits.min} and ${limits.max}.`;
  }
}

function riskNumericFieldHelp(field: RiskNumericField): string | undefined {
  if (field === "risk_per_trade_percent") return EXECUTION_PROFILE_HELP.percentRisk;
  if (field === "max_leverage" || field === "futures_max_leverage") return EXECUTION_PROFILE_HELP.leverage;
  return undefined;
}

function riskNumericFieldLimits(field: RiskNumericField): NumericInputLimits | undefined {
  if (field === "risk_per_trade_percent") return RISK_MANAGEMENT_SCHEMA_LIMITS.risk_per_trade_percent;
  if (field === "max_leverage") return RISK_MANAGEMENT_SCHEMA_LIMITS.max_leverage;
  if (field === "futures_max_leverage") return RISK_MANAGEMENT_SCHEMA_LIMITS.futures_max_leverage;
  return undefined;
}

function riskValidationErrorForField(
  errors: RiskValidationErrors,
  field: RiskNumericField
): string | undefined {
  if (field === "risk_per_trade_percent") return errors.risk_per_trade_percent;
  if (field === "max_leverage") return errors.max_leverage;
  if (field === "futures_max_leverage") return errors.futures_max_leverage;
  return undefined;
}

function isPositiveNumber(value: number | null): boolean {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}
