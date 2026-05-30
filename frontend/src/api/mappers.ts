import type {
  AlertRule,
  BillingPlan,
  ExchangeCatalog,
  ExchangeConnection,
  ExchangeConnectionStatus,
  ExchangeFeeRate,
  MarketPairOption,
  NotificationDelivery,
  PersistedNotification,
  StrategyConfig,
  SubscriptionState,
  SubscriptionStatus,
  SubscriptionTier,
  UserProfile,
  Watchlist
} from "@/features/server-state/types";
import type {
  CandleResponse,
  ExecutionGateStatus,
  ExecutionQualityGate,
  HealthStatus,
  ImpactRisk,
  LiquidityMetrics,
  MarketDataStatus,
  OhlcvCandle,
  RadarConfig,
  RadarSignal,
  RadarStatus,
  TradeJournalEntry,
  TradeJournalResponse,
  VirtualAccount,
  VirtualExecutionReport,
  VirtualExecutionStatus,
  BreakevenPlan,
  FuturesRiskPlan,
  PositionSizingResult,
  RiskAdjustmentPlan,
  RiskCheckResult,
  RiskDecision,
  RiskPreviewResponse,
  RiskStateResponse,
  SignalStatus,
  StopLossPlan,
  TakeProfitPlan,
  TrailingStopPlan,
  VirtualSimulationMode,
  VirtualSimulationTier,
  VirtualSimulatedPositionPath
} from "@/types";
import type { OhlcvCandleDto, RadarConfigDto, RadarSignalDto, TradeJournalEntryDto } from "./generated/schemas";

type TradeJournalEntryExtra = TradeJournalEntryDto & Partial<Pick<
  TradeJournalEntry,
  | "risk_amount"
  | "risk_reward"
  | "slippage_bps"
  | "close_reason"
  | "simulation_mode"
  | "execution_status"
  | "requested_size_usd"
  | "filled_size_usd"
  | "unfilled_size_usd"
  | "execution"
>>;

type VirtualAccountDto = Partial<VirtualAccount>;

export function normalizeSignal(signal: RadarSignalDto): RadarSignal {
  const enriched = signal as RadarSignalDto & Partial<RadarSignal>;
  return {
    id: signal.id,
    symbol: signal.symbol,
    exchange: signal.exchange,
    strategy: signal.strategy,
    direction: signal.direction,
    confidence: signal.confidence,
    risk_reward: signal.risk_reward ?? null,
    urgency: signal.urgency ?? "medium",
    status: normalizeSignalStatus(signal.status),
    score: signal.score ?? 0,
    timeframe: signal.timeframe ?? "stream",
    entry_min: signal.entry_min ?? null,
    entry_max: signal.entry_max ?? null,
    stop_loss: signal.stop_loss ?? null,
    take_profit_1: signal.take_profit_1 ?? null,
    take_profit_2: signal.take_profit_2 ?? null,
    explanation: signal.explanation ?? [],
    risks: signal.risks ?? [],
    score_breakdown: signal.score_breakdown ?? {
      trend_score: 0,
      volume_score: 0,
      liquidity_score: 0,
      orderbook_score: 0,
      risk_reward_score: 0,
      volatility_score: 0,
      overheat_penalty: 0,
      news_event_risk_penalty: 0,
      total: 0
    },
    created_at: signal.created_at,
    updated_at: signal.updated_at,
    expires_at: signal.expires_at ?? null,
    status_reason: enriched.status_reason ?? null,
    quality: enriched.quality ?? null,
    regime: enriched.regime ?? null,
    setup: enriched.setup ?? null,
    confirmation: enriched.confirmation ?? null,
    invalidation: enriched.invalidation ?? null,
    exit_plan: enriched.exit_plan ?? null,
    confirmed_trade_id: signal.confirmed_trade_id ?? null
  };
}

export function normalizeTrade(trade: TradeJournalEntryDto): TradeJournalEntry {
  const enriched = trade as TradeJournalEntryExtra;
  return {
    id: trade.id,
    user_id: trade.user_id,
    signal_id: trade.signal_id ?? null,
    mode: trade.mode,
    exchange: trade.exchange,
    symbol: trade.symbol,
    strategy: trade.strategy,
    timeframe: trade.timeframe,
    side: trade.side,
    entry_price: trade.entry_price,
    current_price: trade.current_price,
    exit_price: trade.exit_price ?? null,
    size_usd: trade.size_usd,
    quantity: trade.quantity,
    leverage: trade.leverage,
    risk_percent: trade.risk_percent,
    risk_amount: enriched.risk_amount ?? 0,
    risk_reward: enriched.risk_reward ?? 3,
    stop_loss: trade.stop_loss,
    take_profit: trade.take_profit ?? [],
    fees: trade.fees,
    slippage_bps: enriched.slippage_bps ?? 0,
    simulation_mode: normalizeSimulationMode(enriched.simulation_mode),
    execution_status: normalizeExecutionStatus(enriched.execution_status),
    requested_size_usd: enriched.requested_size_usd ?? null,
    filled_size_usd: enriched.filled_size_usd ?? null,
    unfilled_size_usd: enriched.unfilled_size_usd ?? 0,
    execution: normalizeExecutionReport(enriched.execution),
    status: trade.status,
    result: trade.result ?? null,
    close_reason: enriched.close_reason ?? null,
    pnl: trade.pnl ?? null,
    pnl_percent: trade.pnl_percent ?? null,
    mfe: trade.mfe,
    mae: trade.mae,
    screenshots: trade.screenshots ?? [],
    ai_review: trade.ai_review ?? null,
    opened_at: trade.opened_at,
    updated_at: trade.updated_at,
    closed_at: trade.closed_at ?? null
  };
}

export function normalizeExecutionReport(value: unknown): VirtualExecutionReport | null {
  if (!isRecord(value)) return null;
  const liquidity = isRecord(value.liquidity) ? value.liquidity : {};
  return {
    mode: normalizeSimulationMode(value.mode),
    simulation_tier: normalizeSimulationTier(value.simulation_tier),
    active_capabilities: Array.isArray(value.active_capabilities) ? value.active_capabilities.map(String) : [],
    planned_capabilities: Array.isArray(value.planned_capabilities) ? value.planned_capabilities.map(String) : [],
    status: normalizeExecutionStatus(value.status),
    requested_size_usd: Number(value.requested_size_usd ?? 0),
    filled_size_usd: Number(value.filled_size_usd ?? 0),
    unfilled_size_usd: Number(value.unfilled_size_usd ?? 0),
    fill_ratio: Number(value.fill_ratio ?? 1),
    reference_price: Number(value.reference_price ?? 0),
    average_price: value.average_price == null ? null : Number(value.average_price),
    entry_slippage_bps: Number(value.entry_slippage_bps ?? 0),
    exit_slippage_bps: Number(value.exit_slippage_bps ?? 0),
    market_impact_percent: Number(value.market_impact_percent ?? 0),
    best_bid_before: value.best_bid_before == null ? null : Number(value.best_bid_before),
    best_ask_before: value.best_ask_before == null ? null : Number(value.best_ask_before),
    book_price_after: value.book_price_after == null ? null : Number(value.book_price_after),
    liquidity: normalizeLiquidityMetrics(liquidity),
    quality_gate: normalizeQualityGate(value.quality_gate),
    risk_adjustment_plan: normalizeRiskAdjustmentPlan(value.risk_adjustment_plan),
    risk_check: normalizeRiskCheckResult(value.risk_check),
    risk_decision: normalizeRiskDecision(value.risk_decision),
    position_sizing: normalizePositionSizing(value.position_sizing),
    stop_loss_plan: normalizeStopLossPlan(value.stop_loss_plan),
    take_profit_plan: normalizeTakeProfitPlan(value.take_profit_plan),
    breakeven_plan: normalizeBreakevenPlan(value.breakeven_plan),
    trailing_stop_plan: normalizeTrailingStopPlan(value.trailing_stop_plan),
    futures_risk_plan: normalizeFuturesRiskPlan(value.futures_risk_plan),
    simulated_path: normalizeSimulatedPath(value.simulated_path),
    rejected_reason: value.rejected_reason == null ? null : String(value.rejected_reason),
    notes: Array.isArray(value.notes) ? value.notes.map(String) : []
  };
}

function normalizePositionSizing(value: unknown): PositionSizingResult | null {
  if (!isRecord(value)) return null;
  return {
    side: value.side === "short" ? "short" : "long",
    account_equity: Number(value.account_equity ?? 0),
    risk_per_trade_percent: Number(value.risk_per_trade_percent ?? 0),
    risk_amount: Number(value.risk_amount ?? 0),
    entry_price: Number(value.entry_price ?? 0),
    stop_loss_price: Number(value.stop_loss_price ?? 0),
    stop_distance_per_unit: Number(value.stop_distance_per_unit ?? 0),
    estimated_entry_fee_per_unit: Number(value.estimated_entry_fee_per_unit ?? 0),
    estimated_exit_fee_per_unit: Number(value.estimated_exit_fee_per_unit ?? 0),
    slippage_buffer_per_unit: Number(value.slippage_buffer_per_unit ?? 0),
    funding_buffer_per_unit: Number(value.funding_buffer_per_unit ?? 0),
    effective_risk_per_unit: Number(value.effective_risk_per_unit ?? 0),
    position_size_base: Number(value.position_size_base ?? 0),
    notional: Number(value.notional ?? 0),
    leverage: Number(value.leverage ?? 1),
    required_margin: Number(value.required_margin ?? 0),
    fee_rate: Number(value.fee_rate ?? 0),
    slippage_bps: Number(value.slippage_bps ?? 0),
    include_fees_in_risk: Boolean(value.include_fees_in_risk ?? true),
    include_slippage_in_risk: Boolean(value.include_slippage_in_risk ?? true)
  };
}

function normalizeRiskAdjustmentPlan(value: unknown): RiskAdjustmentPlan | null {
  if (!isRecord(value)) return null;
  return {
    instrument_type: normalizeTradeInstrumentType(value.instrument_type),
    strategy: String(value.strategy ?? "unknown"),
    signal_score: Number(value.signal_score ?? 0),
    account_equity: Number(value.account_equity ?? 0),
    base_risk_percent: Number(value.base_risk_percent ?? 0),
    base_risk_amount: Number(value.base_risk_amount ?? 0),
    strategy_risk_multiplier: Number(value.strategy_risk_multiplier ?? 1),
    signal_score_multiplier: Number(value.signal_score_multiplier ?? 1),
    volatility_multiplier: Number(value.volatility_multiplier ?? 1),
    user_mode_multiplier: Number(value.user_mode_multiplier ?? 1),
    adjusted_risk_percent: Number(value.adjusted_risk_percent ?? 0),
    adjusted_risk_amount: Number(value.adjusted_risk_amount ?? 0),
    signal_trade_allowed: Boolean(value.signal_trade_allowed ?? true),
    signal_virtual_only: Boolean(value.signal_virtual_only ?? false),
    warnings: Array.isArray(value.warnings) ? value.warnings.map(String) : []
  };
}

function normalizeRiskCheckResult(value: unknown): RiskCheckResult | null {
  if (!isRecord(value)) return null;
  return {
    status: normalizeRiskCheckStatus(value.status),
    blockers: Array.isArray(value.blockers) ? value.blockers.map(String) : [],
    warnings: Array.isArray(value.warnings) ? value.warnings.map(String) : [],
    rr: value.rr == null ? null : Number(value.rr),
    min_rr_ratio: Number(value.min_rr_ratio ?? 0),
    account_equity: Number(value.account_equity ?? 0),
    adjusted_risk_amount: Number(value.adjusted_risk_amount ?? 0),
    adjusted_risk_percent: Number(value.adjusted_risk_percent ?? 0),
    effective_risk_amount: Number(value.effective_risk_amount ?? 0),
    position_notional: Number(value.position_notional ?? 0),
    position_size_base: Number(value.position_size_base ?? 0),
    required_margin: Number(value.required_margin ?? 0),
    available_balance: value.available_balance == null ? null : Number(value.available_balance),
    close_only: Boolean(value.close_only ?? false),
    real_entries_allowed: Boolean(value.real_entries_allowed ?? true),
    virtual_entries_allowed: Boolean(value.virtual_entries_allowed ?? true),
    reduce_only_allowed: Boolean(value.reduce_only_allowed ?? true),
    protective_orders_allowed: Boolean(value.protective_orders_allowed ?? true),
    daily_risk_used_percent: value.daily_risk_used_percent == null ? null : Number(value.daily_risk_used_percent),
    max_daily_loss_percent: Number(value.max_daily_loss_percent ?? 0),
    account_drawdown_percent: value.account_drawdown_percent == null ? null : Number(value.account_drawdown_percent),
    max_account_drawdown_percent: Number(value.max_account_drawdown_percent ?? 0),
    open_risk_used_percent: value.open_risk_used_percent == null ? null : Number(value.open_risk_used_percent),
    max_open_risk_percent: Number(value.max_open_risk_percent ?? 0),
    correlated_risk_used_percent: value.correlated_risk_used_percent == null ? null : Number(value.correlated_risk_used_percent),
    max_correlated_risk_percent: Number(value.max_correlated_risk_percent ?? 0),
    protection_state: normalizeRiskProtectionMode(value.protection_state),
    exchange_rule_status: normalizeExchangeRuleStatus(value.exchange_rule_status),
    exchange_rule_age_seconds: value.exchange_rule_age_seconds == null ? null : Number(value.exchange_rule_age_seconds),
    exchange_rule_ttl_seconds: value.exchange_rule_ttl_seconds == null ? null : Number(value.exchange_rule_ttl_seconds),
    market_data_status: normalizeMarketDataStatus(value.market_data_status),
    best_bid: value.best_bid == null ? null : Number(value.best_bid),
    best_ask: value.best_ask == null ? null : Number(value.best_ask),
    mark_price: value.mark_price == null ? null : Number(value.mark_price),
    funding_rate: value.funding_rate == null ? null : Number(value.funding_rate),
    funding_buffer_amount: Number(value.funding_buffer_amount ?? 0),
    fee_rate_source: value.fee_rate_source == null ? null : String(value.fee_rate_source),
    maker_fee_rate: value.maker_fee_rate == null ? null : Number(value.maker_fee_rate),
    taker_fee_rate: value.taker_fee_rate == null ? null : Number(value.taker_fee_rate),
    spread_percent: value.spread_percent == null ? null : Number(value.spread_percent),
    spread_bps: value.spread_bps == null ? null : Number(value.spread_bps),
    max_spread_bps: Number(value.max_spread_bps ?? 0),
    slippage_bps: Number(value.slippage_bps ?? 0),
    max_slippage_bps: Number(value.max_slippage_bps ?? 0),
    price_deviation_bps: value.price_deviation_bps == null ? null : Number(value.price_deviation_bps),
    max_price_deviation_bps: Number(value.max_price_deviation_bps ?? 0),
    orderbook_depth_usd: value.orderbook_depth_usd == null ? null : Number(value.orderbook_depth_usd),
    orderbook_can_fill: value.orderbook_can_fill == null ? null : Boolean(value.orderbook_can_fill),
    orderbook_liquidity_ratio: value.orderbook_liquidity_ratio == null ? null : Number(value.orderbook_liquidity_ratio),
    max_orderbook_liquidity_ratio: Number(value.max_orderbook_liquidity_ratio ?? 1)
  };
}

export function normalizeRiskDecision(value: unknown): RiskDecision | null {
  if (!isRecord(value)) return null;
  const riskAdjustmentPlan = normalizeRiskAdjustmentPlan(value.risk_adjustment_plan);
  const positionSizing = normalizePositionSizing(value.position_sizing);
  const checkedPositionSizing = normalizePositionSizing(value.checked_position_sizing);
  const riskCheck = normalizeRiskCheckResult(value.risk_check);
  const stopLossPlan = normalizeStopLossPlan(value.stop_loss_plan);
  const takeProfitPlan = normalizeTakeProfitPlan(value.take_profit_plan);
  const breakevenPlan = normalizeBreakevenPlan(value.breakeven_plan);
  const trailingStopPlan = normalizeTrailingStopPlan(value.trailing_stop_plan);
  if (
    !riskAdjustmentPlan ||
    !positionSizing ||
    !checkedPositionSizing ||
    !riskCheck ||
    !stopLossPlan ||
    !takeProfitPlan ||
    !breakevenPlan ||
    !trailingStopPlan
  ) {
    return null;
  }
  const stage = String(value.stage ?? "preview");
  return {
    mode: value.mode === "real" ? "real" : "virtual",
    stage: stage === "pre_execution" || stage === "post_execution" || stage === "confirm" ? stage : "preview",
    status: normalizeRiskCheckStatus(value.status),
    can_enter: Boolean(value.can_enter ?? false),
    blockers: Array.isArray(value.blockers) ? value.blockers.map(String) : [],
    warnings: Array.isArray(value.warnings) ? value.warnings.map(String) : [],
    exchange: String(value.exchange ?? ""),
    symbol: String(value.symbol ?? ""),
    instrument_type: normalizeTradeInstrumentType(value.instrument_type),
    requested_notional: value.requested_notional == null ? null : Number(value.requested_notional),
    risk_adjustment_plan: riskAdjustmentPlan,
    position_sizing: positionSizing,
    checked_position_sizing: checkedPositionSizing,
    risk_check: riskCheck,
    stop_loss_plan: stopLossPlan,
    take_profit_plan: takeProfitPlan,
    breakeven_plan: breakevenPlan,
    trailing_stop_plan: trailingStopPlan,
    futures_risk_plan: normalizeFuturesRiskPlan(value.futures_risk_plan),
    notes: Array.isArray(value.notes) ? value.notes.map(String) : []
  };
}

export function normalizeRiskState(value: unknown): RiskStateResponse | null {
  if (!isRecord(value)) return null;
  return {
    user_id: String(value.user_id ?? "demo_user"),
    mode: value.mode === "real" ? "real" : value.mode === "virtual" ? "virtual" : null,
    protection_state: normalizeRiskProtectionMode(value.protection_state),
    protection_reason: value.protection_reason == null ? null : String(value.protection_reason),
    close_only: Boolean(value.close_only ?? false),
    real_entries_allowed: Boolean(value.real_entries_allowed ?? true),
    virtual_entries_allowed: Boolean(value.virtual_entries_allowed ?? true),
    reduce_only_allowed: Boolean(value.reduce_only_allowed ?? true),
    protective_orders_allowed: Boolean(value.protective_orders_allowed ?? true),
    loss_streak: Number(value.loss_streak ?? 0),
    daily_loss_amount: Number(value.daily_loss_amount ?? 0),
    weekly_loss_amount: Number(value.weekly_loss_amount ?? 0),
    daily_window_start: value.daily_window_start == null ? null : String(value.daily_window_start),
    weekly_window_start: value.weekly_window_start == null ? null : String(value.weekly_window_start),
    window_timezone: String(value.window_timezone ?? "UTC"),
    peak_equity: Number(value.peak_equity ?? 0),
    current_equity: Number(value.current_equity ?? 0),
    adaptive_multiplier: Number(value.adaptive_multiplier ?? 1),
    daily_loss_percent: Number(value.daily_loss_percent ?? 0),
    weekly_loss_percent: Number(value.weekly_loss_percent ?? 0),
    account_drawdown_percent: Number(value.account_drawdown_percent ?? 0),
    max_account_drawdown_percent: Number(value.max_account_drawdown_percent ?? 0),
    open_risk_amount: Number(value.open_risk_amount ?? 0),
    open_risk_percent: Number(value.open_risk_percent ?? 0),
    max_open_risk_percent: Number(value.max_open_risk_percent ?? 0),
    correlated_risk_amount: Number(value.correlated_risk_amount ?? 0),
    correlated_risk_percent: Number(value.correlated_risk_percent ?? 0),
    max_correlated_risk_percent: Number(value.max_correlated_risk_percent ?? 0),
    correlation_group: value.correlation_group == null ? null : String(value.correlation_group),
    exchange_rule_status: normalizeExchangeRuleStatus(value.exchange_rule_status),
    exchange_rule_age_seconds: value.exchange_rule_age_seconds == null ? null : Number(value.exchange_rule_age_seconds),
    exchange_rule_ttl_seconds: value.exchange_rule_ttl_seconds == null ? null : Number(value.exchange_rule_ttl_seconds)
  };
}

export function normalizeRiskPreviewResponse(value: unknown): RiskPreviewResponse | null {
  if (!isRecord(value)) return null;
  const decision = normalizeRiskDecision(value.decision);
  const state = normalizeRiskState(value.state);
  if (!decision || !state) return null;
  return {
    decision,
    state,
    risk_decision_id: value.risk_decision_id == null ? null : String(value.risk_decision_id)
  };
}

export function riskPreviewToExecutionReport(preview: RiskPreviewResponse): VirtualExecutionReport {
  const decision = preview.decision;
  const status = decision.status === "failed" ? "blocked" : decision.status;
  const sizing = decision.checked_position_sizing;
  return {
    mode: "passive",
    simulation_tier: "mvp",
    active_capabilities: ["backend_risk_gate", "risk_decision_audit"],
    planned_capabilities: [],
    status: "filled",
    requested_size_usd: decision.requested_notional ?? sizing.notional,
    filled_size_usd: sizing.notional,
    unfilled_size_usd: 0,
    fill_ratio: 1,
    reference_price: sizing.entry_price,
    average_price: sizing.entry_price,
    entry_slippage_bps: sizing.slippage_bps,
    exit_slippage_bps: sizing.slippage_bps,
    market_impact_percent: 0,
    best_bid_before: decision.risk_check.best_bid,
    best_ask_before: decision.risk_check.best_ask,
    book_price_after: null,
    liquidity: {
      spread_percent: decision.risk_check.spread_percent ?? 0,
      orderbook_depth_0_1_percent_usd: 0,
      orderbook_depth_0_5_percent_usd: decision.risk_check.orderbook_depth_usd ?? 0,
      orderbook_depth_1_percent_usd: decision.risk_check.orderbook_depth_usd ?? 0,
      volume_1m_usd: 0,
      volume_5m_usd: 0,
      volume_15m_usd: 0,
      average_trade_size_usd: 0,
      volatility_1m_percent: 0,
      liquidity_score: 0,
      impact_score: 0,
      impact_risk: decision.status === "failed" ? "high" : decision.status === "warning" ? "medium" : "low"
    },
    quality_gate: {
      status,
      warnings: decision.warnings,
      high_impact_reasons: [],
      blockers: decision.blockers,
      suggested_max_size_usd: decision.status === "failed" ? decision.position_sizing.notional : null,
      message: decision.blockers[0] ?? decision.warnings[0] ?? null
    },
    risk_adjustment_plan: decision.risk_adjustment_plan,
    risk_check: decision.risk_check,
    risk_decision: decision,
    position_sizing: decision.checked_position_sizing,
    stop_loss_plan: decision.stop_loss_plan,
    take_profit_plan: decision.take_profit_plan,
    breakeven_plan: decision.breakeven_plan,
    trailing_stop_plan: decision.trailing_stop_plan,
    futures_risk_plan: decision.futures_risk_plan,
    simulated_path: null,
    rejected_reason: decision.status === "failed" ? decision.blockers.join("; ") : null,
    notes: [
      ...decision.notes,
      `Protection: ${preview.state.protection_state}`,
      `Exchange rules: ${preview.state.exchange_rule_status}`,
      `Market data: ${decision.risk_check.market_data_status}`,
      preview.state.correlation_group ? `Correlation: ${preview.state.correlation_group}` : ""
    ].filter(Boolean)
  };
}

function normalizeStopLossPlan(value: unknown): StopLossPlan | null {
  if (!isRecord(value)) return null;
  return {
    side: value.side === "short" ? "short" : "long",
    mode: normalizeStopLossMode(value.mode),
    entry_price: Number(value.entry_price ?? 0),
    stop_loss_price: Number(value.stop_loss_price ?? 0),
    risk_per_unit: Number(value.risk_per_unit ?? 0),
    source: String(value.source ?? "unknown"),
    default_stop_loss_percent: Number(value.default_stop_loss_percent ?? 1.5),
    atr_period: Number(value.atr_period ?? 14),
    atr_multiplier: Number(value.atr_multiplier ?? 2),
    atr_value: value.atr_value == null ? null : Number(value.atr_value),
    warnings: Array.isArray(value.warnings) ? value.warnings.map(String) : []
  };
}

function normalizeTakeProfitPlan(value: unknown): TakeProfitPlan | null {
  if (!isRecord(value)) return null;
  return {
    mode: "risk_multiple",
    side: value.side === "short" ? "short" : "long",
    entry_price: Number(value.entry_price ?? 0),
    stop_loss_price: Number(value.stop_loss_price ?? 0),
    risk_per_unit: Number(value.risk_per_unit ?? 0),
    partial_take_profit_enabled: Boolean(value.partial_take_profit_enabled ?? true),
    targets: Array.isArray(value.targets)
      ? value.targets.filter(isRecord).map((target) => ({
          label: normalizeTakeProfitLabel(target.label),
          r_multiple: Number(target.r_multiple ?? 0),
          price: Number(target.price ?? 0),
          close_percent: Number(target.close_percent ?? 0),
          action: normalizeTakeProfitAction(target.action)
        }))
      : []
  };
}

function normalizeBreakevenPlan(value: unknown): BreakevenPlan | null {
  if (!isRecord(value)) return null;
  return {
    side: value.side === "short" ? "short" : "long",
    entry_price: Number(value.entry_price ?? 0),
    stop_loss_price: Number(value.stop_loss_price ?? 0),
    risk_per_unit: Number(value.risk_per_unit ?? 0),
    move_after_r: Number(value.move_after_r ?? 1),
    trigger_price: Number(value.trigger_price ?? 0),
    breakeven_stop_price: Number(value.breakeven_stop_price ?? 0),
    offset_percent: Number(value.offset_percent ?? 0)
  };
}

function normalizeTrailingStopPlan(value: unknown): TrailingStopPlan | null {
  if (!isRecord(value)) return null;
  return {
    side: value.side === "short" ? "short" : "long",
    enabled: Boolean(value.enabled ?? false),
    mode: normalizeTrailingMode(value.mode),
    entry_price: Number(value.entry_price ?? 0),
    current_price: Number(value.current_price ?? 0),
    trailing_distance: value.trailing_distance == null ? null : Number(value.trailing_distance),
    trailing_stop_price: value.trailing_stop_price == null ? null : Number(value.trailing_stop_price),
    trailing_percent: Number(value.trailing_percent ?? 0),
    atr_multiplier: Number(value.atr_multiplier ?? 1.5),
    atr_value: value.atr_value == null ? null : Number(value.atr_value),
    structure_stop_price: value.structure_stop_price == null ? null : Number(value.structure_stop_price),
    source: String(value.source ?? "unknown"),
    warnings: Array.isArray(value.warnings) ? value.warnings.map(String) : []
  };
}

function normalizeFuturesRiskPlan(value: unknown): FuturesRiskPlan | null {
  if (!isRecord(value)) return null;
  return {
    side: value.side === "short" ? "short" : "long",
    status: normalizeFuturesRiskStatus(value.status),
    entry_price: Number(value.entry_price ?? 0),
    stop_loss_price: Number(value.stop_loss_price ?? 0),
    leverage: Number(value.leverage ?? 1),
    max_leverage: Number(value.max_leverage ?? 1),
    leverage_allowed: Boolean(value.leverage_allowed ?? true),
    liquidation_price: value.liquidation_price == null ? null : Number(value.liquidation_price),
    liquidation_buffer_percent: value.liquidation_buffer_percent == null ? null : Number(value.liquidation_buffer_percent),
    min_liquidation_buffer_percent: Number(value.min_liquidation_buffer_percent ?? 0),
    liquidation_before_stop: value.liquidation_before_stop == null ? null : Boolean(value.liquidation_before_stop),
    message: String(value.message ?? ""),
    warnings: Array.isArray(value.warnings) ? value.warnings.map(String) : []
  };
}

function normalizeSimulatedPath(value: unknown): VirtualSimulatedPositionPath | null {
  if (!isRecord(value)) return null;
  const candle = isRecord(value.simulated_candle) ? value.simulated_candle : null;
  if (candle === null) return null;
  return {
    model: "exponential_decay",
    reference_price: Number(value.reference_price ?? 0),
    entry_price: Number(value.entry_price ?? 0),
    post_trade_price: Number(value.post_trade_price ?? 0),
    initial_impact_delta: Number(value.initial_impact_delta ?? 0),
    decay_lambda: Number(value.decay_lambda ?? 0),
    decay_horizon_seconds: Number(value.decay_horizon_seconds ?? 60),
    points: Array.isArray(value.points)
      ? value.points.filter(isRecord).map((point) => ({
          offset_seconds: Number(point.offset_seconds ?? 0),
          real_price: Number(point.real_price ?? 0),
          impact_delta: Number(point.impact_delta ?? 0),
          effective_price: Number(point.effective_price ?? 0),
          impact_remaining_percent: Number(point.impact_remaining_percent ?? 0)
        }))
      : [],
    simulated_candle: {
      start_offset_seconds: Number(candle.start_offset_seconds ?? 0),
      end_offset_seconds: Number(candle.end_offset_seconds ?? 60),
      open: Number(candle.open ?? 0),
      high: Number(candle.high ?? 0),
      low: Number(candle.low ?? 0),
      close: Number(candle.close ?? 0)
    }
  };
}

function normalizeLiquidityMetrics(value: Record<string, unknown>): LiquidityMetrics {
  return {
    spread_percent: Number(value.spread_percent ?? 0),
    orderbook_depth_0_1_percent_usd: Number(value.orderbook_depth_0_1_percent_usd ?? 0),
    orderbook_depth_0_5_percent_usd: Number(value.orderbook_depth_0_5_percent_usd ?? 0),
    orderbook_depth_1_percent_usd: Number(value.orderbook_depth_1_percent_usd ?? 0),
    volume_1m_usd: Number(value.volume_1m_usd ?? 0),
    volume_5m_usd: Number(value.volume_5m_usd ?? 0),
    volume_15m_usd: Number(value.volume_15m_usd ?? 0),
    average_trade_size_usd: Number(value.average_trade_size_usd ?? 0),
    volatility_1m_percent: Number(value.volatility_1m_percent ?? 0),
    liquidity_score: Number(value.liquidity_score ?? 0),
    impact_score: Number(value.impact_score ?? 0),
    impact_risk: normalizeImpactRisk(value.impact_risk)
  };
}

function normalizeQualityGate(value: unknown): ExecutionQualityGate {
  const gate = isRecord(value) ? value : {};
  return {
    status: normalizeGateStatus(gate.status),
    warnings: Array.isArray(gate.warnings) ? gate.warnings.map(String) : [],
    high_impact_reasons: Array.isArray(gate.high_impact_reasons) ? gate.high_impact_reasons.map(String) : [],
    blockers: Array.isArray(gate.blockers) ? gate.blockers.map(String) : [],
    suggested_max_size_usd: gate.suggested_max_size_usd == null ? null : Number(gate.suggested_max_size_usd),
    message: gate.message == null ? null : String(gate.message)
  };
}

function normalizeSimulationMode(value: unknown): VirtualSimulationMode {
  return value === "impact_aware" ? "impact_aware" : "passive";
}

function normalizeSimulationTier(value: unknown): VirtualSimulationTier {
  if (value === "advanced" || value === "pro") return value;
  return "mvp";
}

function normalizeExecutionStatus(value: unknown): VirtualExecutionStatus {
  if (value === "partially_filled" || value === "rejected_virtual_execution") return value;
  return "filled";
}

function normalizeSignalStatus(value: unknown): SignalStatus {
  if (
    value === "new" ||
    value === "active" ||
    value === "watchlist" ||
    value === "ready" ||
    value === "actionable" ||
    value === "wait_for_pullback" ||
    value === "confirmed" ||
    value === "rejected" ||
    value === "expired" ||
    value === "invalidated" ||
    value === "closed" ||
    value === "entry_touched"
  ) return value;
  return "active";
}

function normalizeImpactRisk(value: unknown): ImpactRisk {
  if (value === "medium" || value === "high") return value;
  return "low";
}

function normalizeGateStatus(value: unknown): ExecutionGateStatus {
  if (value === "warning" || value === "blocked") return value;
  return "passed";
}

export function normalizeCandle(candle: OhlcvCandleDto): OhlcvCandle {
  return {
    exchange: candle.exchange,
    symbol: candle.symbol,
    timeframe: candle.timeframe,
    open_time: candle.open_time,
    close_time: candle.close_time,
    open: candle.open,
    high: candle.high,
    low: candle.low,
    close: candle.close,
    volume: candle.volume,
    trades: candle.trades ?? 0,
    is_closed: candle.is_closed ?? false
  };
}

export function normalizeConfig(config: RadarConfigDto): RadarConfig {
  return {
    exchanges: config.exchanges ?? ["bybit"],
    symbols: config.symbols ?? [],
    use_all_symbols: config.use_all_symbols ?? false,
    timeframes: config.timeframes ?? ["1m", "5m", "15m", "1h", "4h", "1d"]
  };
}

export function normalizeCandleResponse(candles: OhlcvCandleDto[]): CandleResponse {
  return { candles: candles.map(normalizeCandle) };
}

export function normalizeVirtualAccount(account?: unknown): VirtualAccount | null {
  if (!account) return null;
  const value = account as VirtualAccountDto;
  return {
    user_id: value.user_id ?? "demo_user",
    starting_balance: value.starting_balance ?? 100,
    balance: value.balance ?? 100,
    equity: value.equity ?? value.balance ?? 100,
    realized_pnl: value.realized_pnl ?? 0,
    unrealized_pnl: value.unrealized_pnl ?? 0,
    risk_per_trade: value.risk_per_trade ?? 10,
    risk_reward: value.risk_reward ?? 3,
    open_positions: value.open_positions ?? 0,
    closed_trades: value.closed_trades ?? 0,
    wins: value.wins ?? 0,
    losses: value.losses ?? 0,
    breakeven: value.breakeven ?? 0,
    updated_at: value.updated_at ?? new Date().toISOString()
  };
}

export function normalizeTradeResponse(trades: TradeJournalEntryDto[], account?: unknown): TradeJournalResponse {
  return { trades: trades.map(normalizeTrade), account: normalizeVirtualAccount(account) };
}

export function normalizeWatchlist(config: RadarConfig): Watchlist {
  return {
    id: "config-derived",
    user_id: "demo_user",
    name: "Default",
    is_default: true,
    pairs: config.symbols.map((symbol) => ({
      id: symbol,
      exchange: config.exchanges[0] ?? "bybit",
      symbol,
      base_asset: symbol.replace(/USDT$/, ""),
      quote_asset: "USDT",
      status: "active",
      added_at: new Date(0).toISOString()
    })),
    symbols: config.symbols,
    use_all_symbols: config.use_all_symbols,
    created_at: new Date(0).toISOString(),
    updated_at: null
  };
}

export function normalizeMarketPair(value: unknown): MarketPairOption {
  const pair = value as Partial<MarketPairOption>;
  return {
    id: String(pair.id ?? ""),
    exchange: String(pair.exchange ?? "bybit"),
    symbol: String(pair.symbol ?? ""),
    base_asset: String(pair.base_asset ?? ""),
    quote_asset: String(pair.quote_asset ?? ""),
    status: String(pair.status ?? "active")
  };
}

export function normalizeWatchlistResponse(value: unknown): Watchlist {
  const watchlist = value as Partial<Watchlist>;
  const pairs = Array.isArray(watchlist.pairs)
    ? watchlist.pairs.map((pair) => ({
        ...normalizeMarketPair(pair),
        added_at: String((pair as { added_at?: unknown }).added_at ?? watchlist.created_at ?? new Date().toISOString())
      }))
    : [];
  return {
    id: String(watchlist.id ?? ""),
    user_id: String(watchlist.user_id ?? "demo_user"),
    name: String(watchlist.name ?? "Default"),
    is_default: Boolean(watchlist.is_default ?? true),
    pairs,
    symbols: pairs.map((pair) => pair.symbol),
    use_all_symbols: false,
    created_at: String(watchlist.created_at ?? new Date().toISOString()),
    updated_at: watchlist.updated_at ?? null
  };
}

export function normalizeStrategyConfig(value: unknown): StrategyConfig {
  const config = isRecord(value) ? value : {};
  const pairs = Array.isArray(config.pairs)
    ? config.pairs
        .filter(isRecord)
        .map((pair) => ({
          exchange: String(pair.exchange ?? "bybit").toLowerCase(),
          symbol: String(pair.symbol ?? "").toUpperCase()
        }))
        .filter((pair) => pair.symbol.length > 0)
    : [];
  return {
    id: String(config.id ?? ""),
    user_id: String(config.user_id ?? "demo_user"),
    strategy_version_id: String(config.strategy_version_id ?? ""),
    strategy_code: String(config.strategy_code ?? ""),
    strategy_name: String(config.strategy_name ?? config.name ?? "Strategy"),
    strategy_version: String(config.strategy_version ?? "1.0"),
    name: String(config.name ?? config.strategy_name ?? "Strategy"),
    exchanges: Array.isArray(config.exchanges) ? config.exchanges.map(String) : ["bybit"],
    pairs,
    timeframes: Array.isArray(config.timeframes) ? config.timeframes.map(String) : ["1m", "5m", "15m", "1h", "4h", "1d"],
    params: isRecord(config.params) ? config.params : {},
    risk_settings: isRecord(config.risk_settings) ? config.risk_settings : {},
    is_enabled: Boolean(config.is_enabled ?? true),
    created_at: String(config.created_at ?? new Date().toISOString()),
    updated_at: String(config.updated_at ?? new Date().toISOString())
  };
}

export function normalizeAlertRule(value: unknown): AlertRule {
  const alert = value as Partial<AlertRule>;
  return {
    id: String(alert.id ?? ""),
    user_id: String(alert.user_id ?? "demo_user"),
    pair: alert.pair ? normalizeMarketPair(alert.pair) : null,
    strategy_version_id: alert.strategy_version_id ?? null,
    condition_type: String(alert.condition_type ?? "price_above"),
    condition_body: alert.condition_body ?? {},
    channels: Array.isArray(alert.channels) ? alert.channels.map(String) : ["websocket"],
    is_enabled: Boolean(alert.is_enabled ?? true),
    created_at: String(alert.created_at ?? new Date().toISOString())
  };
}

export function normalizeNotification(value: unknown): PersistedNotification {
  const notification = value as Partial<PersistedNotification>;
  return {
    id: String(notification.id ?? ""),
    user_id: String(notification.user_id ?? "demo_user"),
    type: String(notification.type ?? "system"),
    title: String(notification.title ?? "Notification"),
    body: notification.body == null ? null : String(notification.body),
    payload: isRecord(notification.payload) ? notification.payload : {},
    is_read: Boolean(notification.is_read),
    created_at: String(notification.created_at ?? new Date().toISOString()),
    deliveries: Array.isArray(notification.deliveries)
      ? notification.deliveries.map(normalizeNotificationDelivery)
      : []
  };
}

export function normalizeBillingPlan(value: unknown): BillingPlan {
  const plan = value as Partial<BillingPlan>;
  return {
    id: String(plan.id ?? ""),
    code: String(plan.code ?? "free"),
    name: String(plan.name ?? plan.code ?? "Free"),
    price_monthly: Number(plan.price_monthly ?? 0),
    currency: String(plan.currency ?? "USD"),
    limits: isRecord(plan.limits) ? plan.limits : {},
    features: isRecord(plan.features) ? plan.features : {},
    is_active: Boolean(plan.is_active ?? true),
    created_at: String(plan.created_at ?? new Date().toISOString())
  };
}

export function normalizeSubscriptionStatus(value: unknown): SubscriptionStatus {
  const subscription = value as Partial<SubscriptionStatus>;
  const tier = normalizeSubscriptionTier(subscription.tier ?? subscription.plan_code ?? "free");
  return {
    state: normalizeSubscriptionState(subscription.state ?? "none"),
    tier,
    plan_id: subscription.plan_id == null ? null : String(subscription.plan_id),
    plan_code: subscription.plan_code == null ? null : String(subscription.plan_code),
    plan_name: subscription.plan_name == null ? null : String(subscription.plan_name),
    current_period_start: subscription.current_period_start == null ? null : String(subscription.current_period_start),
    current_period_end: subscription.current_period_end == null ? null : String(subscription.current_period_end),
    external_provider: subscription.external_provider == null ? null : String(subscription.external_provider),
    external_id: subscription.external_id == null ? null : String(subscription.external_id),
    limits: isRecord(subscription.limits) ? subscription.limits : {},
    features: isRecord(subscription.features) ? subscription.features : {}
  };
}

export function normalizeUserProfile(value: unknown): UserProfile {
  const profile = isRecord(value) ? value : {};
  const riskProfile = normalizeRiskProfile(profile.risk_profile);
  return {
    id: String(profile.id ?? ""),
    email: String(profile.email ?? ""),
    name: profile.name == null ? null : String(profile.name),
    risk_profile: riskProfile,
    settings: normalizeProfileSettings(profile.settings, riskProfile),
    created_at: String(profile.created_at ?? new Date().toISOString())
  };
}

function normalizeProfileSettings(value: unknown, profileFallback: UserProfile["risk_profile"]): UserProfile["settings"] {
  const settings = isRecord(value) ? { ...value } : {};
  const virtualTrading = isRecord(settings.virtual_trading) ? settings.virtual_trading : {};
  const simulationLevel = normalizeVirtualSimulationLevel(virtualTrading.simulation_level);
  const riskManagement = normalizeRiskManagementSettings(settings.risk_management, profileFallback);
  return {
    ...settings,
    virtual_trading: {
      simulation_level: simulationLevel,
      simulation_level_status: simulationLevel === "mvp" ? "active" : "stub",
      effective_simulation_level: simulationLevel === "mvp" ? "mvp" : "mvp"
    },
    risk_management: riskManagement
  };
}

function normalizeRiskManagementSettings(
  value: unknown,
  profileFallback: UserProfile["risk_profile"]
): UserProfile["settings"]["risk_management"] {
  const settings = isRecord(value) ? value : {};
  return {
    risk_profile: normalizeRiskProfile(settings.risk_profile ?? profileFallback),
    risk_per_trade_percent: Number(settings.risk_per_trade_percent ?? 1),
    min_rr_ratio: Number(settings.min_rr_ratio ?? 2),
    max_daily_loss_percent: Number(settings.max_daily_loss_percent ?? 3),
    max_weekly_loss_percent: Number(settings.max_weekly_loss_percent ?? 7),
    max_account_drawdown_percent: Number(settings.max_account_drawdown_percent ?? 10),
    max_open_risk_percent: Number(settings.max_open_risk_percent ?? 5),
    max_correlated_risk_percent: Number(settings.max_correlated_risk_percent ?? 3),
    max_spread_bps: Number(settings.max_spread_bps ?? 50),
    max_slippage_bps: Number(settings.max_slippage_bps ?? 150),
    max_price_deviation_bps: Number(settings.max_price_deviation_bps ?? 100),
    max_orderbook_liquidity_ratio: Number(settings.max_orderbook_liquidity_ratio ?? 1),
    include_fees_in_risk: Boolean(settings.include_fees_in_risk ?? true),
    include_slippage_in_risk: Boolean(settings.include_slippage_in_risk ?? true),
    stop_loss_required: Boolean(settings.stop_loss_required ?? true),
    take_profit_required: Boolean(settings.take_profit_required ?? true),
    stop_loss_mode: normalizeStopLossMode(settings.stop_loss_mode),
    default_stop_loss_percent: Number(settings.default_stop_loss_percent ?? 1.5),
    atr_period: Number(settings.atr_period ?? 14),
    atr_multiplier: Number(settings.atr_multiplier ?? 2),
    take_profit_mode: "risk_multiple",
    tp1_r_multiple: Number(settings.tp1_r_multiple ?? 1),
    tp2_r_multiple: Number(settings.tp2_r_multiple ?? 2),
    tp3_r_multiple: Number(settings.tp3_r_multiple ?? 3),
    partial_take_profit_enabled: Boolean(settings.partial_take_profit_enabled ?? true),
    tp1_close_percent: Number(settings.tp1_close_percent ?? 30),
    tp2_close_percent: Number(settings.tp2_close_percent ?? 40),
    tp3_close_percent: Number(settings.tp3_close_percent ?? 30),
    move_sl_to_breakeven_after_r: Number(settings.move_sl_to_breakeven_after_r ?? 1),
    breakeven_offset_percent: Number(settings.breakeven_offset_percent ?? 0.05),
    trailing_stop_enabled: Boolean(settings.trailing_stop_enabled ?? true),
    trailing_mode: normalizeTrailingMode(settings.trailing_mode),
    trailing_atr_multiplier: Number(settings.trailing_atr_multiplier ?? 1.5),
    trailing_stop_percent: Number(settings.trailing_stop_percent ?? 0.5),
    max_leverage: Number(settings.max_leverage ?? 3),
    min_liquidation_buffer_percent: Number(settings.min_liquidation_buffer_percent ?? 2),
    liquidation_buffer_required: Boolean(settings.liquidation_buffer_required ?? true),
    spot_risk_per_trade_percent: Number(settings.spot_risk_per_trade_percent ?? 1),
    spot_max_position_size_percent: Number(settings.spot_max_position_size_percent ?? 20),
    spot_stop_required: Boolean(settings.spot_stop_required ?? true),
    futures_risk_per_trade_percent: Number(settings.futures_risk_per_trade_percent ?? 0.5),
    futures_max_leverage: Number(settings.futures_max_leverage ?? 3),
    futures_max_open_risk_percent: Number(settings.futures_max_open_risk_percent ?? 3),
    futures_liquidation_buffer_required: Boolean(settings.futures_liquidation_buffer_required ?? true),
    virtual_risk_mode: settings.virtual_risk_mode === "custom" ? "custom" : "same_as_real",
    virtual_risk_per_trade_percent: Number(settings.virtual_risk_per_trade_percent ?? 1),
    virtual_starting_balance: Number(settings.virtual_starting_balance ?? 10000),
    virtual_slippage_model: normalizeVirtualSlippageModel(settings.virtual_slippage_model),
    virtual_fee_model: settings.virtual_fee_model === "manual" ? "manual" : "exchange_based",
    virtual_trading_uses_realistic_execution: Boolean(settings.virtual_trading_uses_realistic_execution ?? true),
    strategy_risk_multipliers: isRecord(settings.strategy_risk_multipliers)
      ? Object.fromEntries(Object.entries(settings.strategy_risk_multipliers).map(([key, value]) => [key, Number(value)]))
      : defaultStrategyRiskMultipliers(),
    auto_reduce_risk_after_losses: Boolean(settings.auto_reduce_risk_after_losses ?? true),
    allow_risk_increase_after_profit: Boolean(settings.allow_risk_increase_after_profit ?? false),
    increase_risk_after_profit_streak: Boolean(settings.increase_risk_after_profit_streak ?? false),
    max_risk_boost: Number(settings.max_risk_boost ?? 1.25)
  };
}

function normalizeRiskProfile(value: unknown) {
  if (value === "conservative" || value === "aggressive" || value === "custom") return value;
  return "balanced";
}

function normalizeStopLossMode(value: unknown) {
  if (value === "atr" || value === "structure") return value;
  return "fixed_percent";
}

function normalizeTrailingMode(value: unknown) {
  if (value === "percent" || value === "structure") return value;
  return "atr";
}

function normalizeFuturesRiskStatus(value: unknown) {
  if (value === "passed" || value === "blocked") return value;
  return "unknown";
}

function normalizeRiskCheckStatus(value: unknown) {
  if (value === "passed" || value === "failed") return value;
  return "warning";
}

function normalizeRiskProtectionMode(value: unknown) {
  if (value === "reduced" || value === "virtual_only" || value === "blocked") return value;
  return "normal";
}

function normalizeExchangeRuleStatus(value: unknown) {
  if (value === "fresh" || value === "missing" || value === "stale") return value;
  return "unknown";
}

function normalizeMarketDataStatus(value: unknown): MarketDataStatus {
  if (value === "fresh" || value === "partial" || value === "missing") return value;
  return "unknown";
}

function normalizeTradeInstrumentType(value: unknown) {
  if (value === "spot" || value === "futures") return value;
  return "virtual";
}

function normalizeVirtualSlippageModel(value: unknown) {
  if (value === "none" || value === "fixed_percent" || value === "orderbook_based" || value === "volatility_based") return value;
  return "spread_based";
}

function defaultStrategyRiskMultipliers(): Record<string, number> {
  return {
    trend_following: 1,
    trend_pullback_continuation: 1,
    breakout: 0.75,
    scalping: 0.5,
    mean_reversion: 0.75,
    smart_money_setup: 1,
    news_event_trade: 0.25
  };
}

function normalizeTakeProfitLabel(value: unknown): "TP1" | "TP2" | "TP3" {
  if (value === "TP2" || value === "TP3") return value;
  return "TP1";
}

function normalizeTakeProfitAction(value: unknown) {
  if (value === "trailing_stop" || value === "full_close" || value === "observe") return value;
  return "move_stop_to_breakeven";
}

function normalizeVirtualSimulationLevel(value: unknown) {
  if (value === "advanced" || value === "pro") return value;
  return "mvp";
}

function normalizeNotificationDelivery(value: unknown): NotificationDelivery {
  const delivery = value as Partial<NotificationDelivery>;
  return {
    id: String(delivery.id ?? ""),
    notification_id: String(delivery.notification_id ?? ""),
    channel: String(delivery.channel ?? "websocket"),
    status: String(delivery.status ?? "unknown"),
    provider_msg_id: delivery.provider_msg_id == null ? null : String(delivery.provider_msg_id),
    sent_at: delivery.sent_at == null ? null : String(delivery.sent_at),
    error: delivery.error == null ? null : String(delivery.error)
  };
}

export function normalizeExchangeCatalog(catalog: Record<string, string[]>): ExchangeCatalog {
  return {
    supported_exchanges: catalog.supported_exchanges ?? [],
    supported_symbols: catalog.supported_symbols ?? [],
    supported_timeframes: catalog.supported_timeframes ?? []
  };
}

export function normalizeExchangeConnections(catalog: ExchangeCatalog): ExchangeConnectionStatus[] {
  return catalog.supported_exchanges.map((exchange) => ({
    exchange,
    state: "available",
    account_label: null,
    last_sync_at: null
  }));
}

export function normalizeExchangeConnection(value: unknown): ExchangeConnection {
  const connection = value as Partial<ExchangeConnection>;
  return {
    id: String(connection.id ?? ""),
    user_id: String(connection.user_id ?? "demo_user"),
    exchange_id: String(connection.exchange_id ?? ""),
    exchange_code: String(connection.exchange_code ?? ""),
    exchange_name: String(connection.exchange_name ?? connection.exchange_code ?? ""),
    label: String(connection.label ?? ""),
    account_type: String(connection.account_type ?? "spot"),
    key_ref: String(connection.key_ref ?? ""),
    permissions: isRecord(connection.permissions) ? connection.permissions : {},
    status: String(connection.status ?? "active"),
    last_sync_at: connection.last_sync_at == null ? null : String(connection.last_sync_at),
    metadata: isRecord(connection.metadata) ? connection.metadata : {},
    created_at: String(connection.created_at ?? new Date().toISOString())
  };
}

export function normalizeHealth(value: unknown): HealthStatus {
  const health = value as Partial<HealthStatus>;
  return {
    status: String(health.status ?? "unknown"),
    scanner_enabled: Boolean(health.scanner_enabled),
    scanner_running: Boolean(health.scanner_running),
    scanner_stopping: Boolean(health.scanner_stopping),
    processed_signals: Number(health.processed_signals ?? 0),
    ticks_processed: Number(health.ticks_processed ?? 0),
    features_built: Number(health.features_built ?? 0),
    strategy_evaluations: Number(health.strategy_evaluations ?? 0),
    signals_found: Number(health.signals_found ?? 0),
    candles_seeded: Number(health.candles_seeded ?? 0),
    last_symbol: health.last_symbol ?? null,
    last_price: health.last_price ?? null
  };
}

export function normalizeRadarStatus(value: unknown): RadarStatus {
  const status = value as Partial<RadarStatus>;
  return {
    ...normalizeHealth(status),
    exchanges: status.exchanges ?? [],
    symbols: status.symbols ?? [],
    timeframes: status.timeframes ?? [],
    strategies: status.strategies ?? [],
    ticks_processed: Number(status.ticks_processed ?? 0),
    candles_updated: Number(status.candles_updated ?? 0),
    features_built: Number(status.features_built ?? 0),
    strategy_evaluations: Number(status.strategy_evaluations ?? 0),
    signals_found: Number(status.signals_found ?? 0),
    candles_seeded: Number(status.candles_seeded ?? 0),
    last_tick_at: status.last_tick_at ?? null,
    last_signal_at: status.last_signal_at ?? null,
    last_exchange: status.last_exchange ?? null,
    last_symbol: status.last_symbol ?? null,
    last_price: status.last_price ?? null,
    candle_history: status.candle_history ?? {}
  };
}

export function normalizeExchangeFeeRate(value: unknown): ExchangeFeeRate {
  const fee = value as Partial<ExchangeFeeRate>;
  return {
    connection_id: String(fee.connection_id ?? ""),
    exchange_code: String(fee.exchange_code ?? ""),
    account_type: fee.account_type == null ? null : String(fee.account_type),
    category: String(fee.category ?? "linear"),
    symbol: fee.symbol == null ? null : String(fee.symbol),
    maker_fee_rate: Number(fee.maker_fee_rate ?? 0),
    taker_fee_rate: Number(fee.taker_fee_rate ?? 0),
    source: String(fee.source ?? "unknown"),
    fetched_at: String(fee.fetched_at ?? new Date().toISOString())
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function normalizeSubscriptionTier(value: unknown): SubscriptionTier {
  return value === "pro" || value === "team" ? value : "free";
}

function normalizeSubscriptionState(value: unknown): SubscriptionState {
  if (value === "active" || value === "trialing" || value === "past_due" || value === "canceled") return value;
  return "none";
}
