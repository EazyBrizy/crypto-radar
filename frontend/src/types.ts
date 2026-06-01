export type SignalDirection = "long" | "short";
export type SignalStatus =
  | "new"
  | "active"
  | "watchlist"
  | "ready"
  | "actionable"
  | "wait_for_pullback"
  | "confirmed"
  | "rejected"
  | "expired"
  | "invalidated"
  | "closed"
  | "entry_touched";
export type TradeMode = "virtual" | "real";
export type TradeStatus = "open" | "closed" | "cancelled";
export type TradeCloseReason =
  | "take_profit"
  | "stop_loss"
  | "manual_close"
  | "invalidation"
  | "cancelled"
  | "partial_take_profit"
  | "breakeven_stop"
  | "trailing_stop"
  | "time_stop";
export type CloseMarketTradeStatus = "closed" | "not_implemented";
export type TradeInvalidationStatus = "valid" | "invalidated" | "unavailable";
export type TradeInvalidationAction = "none" | "close_market_or_wait_stop";
export type TradeInvalidationUserAction = "close_market" | "keep_stop_loss" | "dismissed";
export type VirtualSimulationMode = "passive" | "impact_aware";
export type VirtualSimulationTier = "mvp" | "advanced" | "pro";
export type VirtualExecutionStatus = "filled" | "partially_filled" | "rejected_virtual_execution";
export type ImpactRisk = "low" | "medium" | "high";
export type ExecutionGateStatus = "passed" | "warning" | "blocked";
export type Timeframe = "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
export type StopLossMode = "fixed_percent" | "atr" | "structure";
export type TakeProfitMode = "risk_multiple";
export type TakeProfitTargetAction = "move_stop_to_breakeven" | "trailing_stop" | "full_close" | "observe";
export type TrailingMode = "atr" | "percent" | "structure";
export type FuturesRiskStatus = "passed" | "blocked" | "unknown";
export type TradeInstrumentType = "spot" | "futures" | "virtual";
export type RiskCheckStatus = "passed" | "warning" | "failed";
export type RRGuardMode = "off" | "soft" | "hard";
export type RiskProtectionMode = "normal" | "reduced" | "virtual_only" | "blocked";
export type ExchangeRuleStatus = "fresh" | "missing" | "stale" | "unknown";
export type MarketDataStatus = "fresh" | "partial" | "missing" | "unknown";

export interface OhlcvCandle {
  exchange: string;
  symbol: string;
  timeframe: Timeframe;
  open_time: number;
  close_time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  trades: number;
  is_closed: boolean;
}

export interface CandleResponse {
  candles: OhlcvCandle[];
}

export interface SignalScoreBreakdown {
  trend_score: number;
  volume_score: number;
  liquidity_score: number;
  orderbook_score: number;
  risk_reward_score: number;
  volatility_score: number;
  overheat_penalty: number;
  news_event_risk_penalty: number;
  total: number;
}

export type LayerCheckStatus = "passed" | "warning" | "failed" | "skipped";

export interface SignalLayerCheck {
  name: string;
  status: LayerCheckStatus;
  score: number | null;
  reason: string | null;
  metadata: Record<string, unknown>;
}

export interface TradePlanEntry {
  price: number | null;
  min_price: number | null;
  max_price: number | null;
  source: string;
  metadata: Record<string, unknown>;
}

export interface TradePlanTarget {
  label: string;
  price: number | null;
  r_multiple: number | null;
  action: string | null;
  close_percent: number | string | null;
  source: string | null;
  metadata: Record<string, unknown>;
}

export interface TradePlanInvalidation {
  price: number | null;
  hard_stop: number | null;
  conditions: string[];
  metadata: Record<string, unknown>;
}

export interface TradePlanRiskRules {
  risk_reward: number | null;
  first_target_rr: number | null;
  final_target_rr: number | null;
  selected_rr: number | null;
  selected_rr_target: string | null;
  min_rr_ratio: number | null;
  metadata: Record<string, unknown>;
}

export interface TradePlan {
  version: "v1";
  entry: TradePlanEntry;
  stop_loss: number | null;
  targets: TradePlanTarget[];
  invalidation: TradePlanInvalidation | null;
  risk_rules: TradePlanRiskRules;
  metadata: Record<string, unknown>;
}

export type SignalEdgeStatus = "unknown" | "positive" | "negative" | "insufficient_sample";

export interface SignalEdgeSnapshot {
  status: SignalEdgeStatus;
  sample_size: number;
  min_sample_size: number;
  winrate: number | null;
  avg_win_r: number | null;
  avg_loss_r: number | null;
  expectancy_r: number | null;
  expectancy_after_costs_r: number | null;
  profit_factor: number | null;
  confidence_score: number;
  source: "outcome" | "backtest" | "mixed" | "none";
  score_bucket: string | null;
  metadata: Record<string, unknown>;
}

export interface MarketQualitySnapshot {
  passed: boolean;
  tier: "major" | "mid_alt" | "low_liquidity" | "unknown";
  score: number;
  volume_24h_quote: number | null;
  spread_bps: number | null;
  history_ok: boolean;
  rough_chart_score: number | null;
  checks: SignalLayerCheck[];
  warnings: string[];
}

export interface NoTradeFilterResult {
  enabled: boolean;
  blocked: boolean;
  hard_block: boolean;
  blockers: string[];
  warnings: string[];
  checks: SignalLayerCheck[];
  metadata: Record<string, unknown>;
}

export interface MarketRegimeSnapshot {
  signal_timeframe: string;
  context_timeframe: string | null;
  direction: "bullish" | "bearish" | "range" | "unknown";
  strength: "weak" | "normal" | "strong" | "unknown";
  alignment: "aligned" | "mixed" | "against" | "unknown";
  score_adjustment: number;
  checks: SignalLayerCheck[];
}

export interface StrategySetupSnapshot {
  name: string;
  stage: "forming" | "ready" | "confirmed";
  checks: SignalLayerCheck[];
}

export interface SignalConfirmationSnapshot {
  passed: boolean;
  checks: SignalLayerCheck[];
}

export interface SignalInvalidationSnapshot {
  price: number | null;
  hard_stop: number | null;
  conditions: string[];
  metadata: Record<string, unknown>;
}

export interface SignalExitPlanSnapshot {
  targets: Array<Record<string, unknown>>;
  breakeven: Record<string, unknown>;
  trailing: Record<string, unknown>;
}

export interface SignalAutoEntrySnapshot {
  enabled: boolean;
  status: "pending" | "triggered" | "failed" | "cancelled";
  mode: TradeMode;
  user_id: string;
  armed_at: string | null;
  triggered_at: string | null;
  message: string | null;
  request: Record<string, unknown>;
  trade_id: string | null;
  real_execution: Record<string, unknown> | null;
}

export interface RadarSignal {
  id: string;
  symbol: string;
  exchange: string;
  strategy: string;
  direction: SignalDirection;
  confidence: number;
  risk_reward: number | null;
  first_target_rr: number | null;
  final_target_rr: number | null;
  selected_rr: number | null;
  selected_rr_target: string | null;
  min_rr_ratio: number | null;
  urgency: "low" | "medium" | "high";
  status: SignalStatus;
  score: number;
  timeframe: string;
  entry_min: number | null;
  entry_max: number | null;
  stop_loss: number | null;
  take_profit_1: number | null;
  take_profit_2: number | null;
  explanation: string[];
  risks: string[];
  score_breakdown: SignalScoreBreakdown;
  status_reason: string | null;
  quality: MarketQualitySnapshot | null;
  regime: MarketRegimeSnapshot | null;
  setup: StrategySetupSnapshot | null;
  confirmation: SignalConfirmationSnapshot | null;
  invalidation: SignalInvalidationSnapshot | null;
  exit_plan: SignalExitPlanSnapshot | null;
  trade_plan?: TradePlan | null;
  auto_entry: SignalAutoEntrySnapshot | null;
  edge?: SignalEdgeSnapshot | null;
  no_trade_filter?: NoTradeFilterResult | null;
  created_at: string;
  updated_at: string;
  expires_at: string | null;
  confirmed_trade_id?: string | null;
}

export interface RadarResponse {
  signals: RadarSignal[];
}

export interface LiquidityMetrics {
  spread_percent: number;
  orderbook_depth_0_1_percent_usd: number;
  orderbook_depth_0_5_percent_usd: number;
  orderbook_depth_1_percent_usd: number;
  volume_1m_usd: number;
  volume_5m_usd: number;
  volume_15m_usd: number;
  average_trade_size_usd: number;
  volatility_1m_percent: number;
  liquidity_score: number;
  impact_score: number;
  impact_risk: ImpactRisk;
}

export interface ExecutionQualityGate {
  status: ExecutionGateStatus;
  warnings: string[];
  high_impact_reasons: string[];
  blockers: string[];
  suggested_max_size_usd: number | null;
  message: string | null;
}

export interface VirtualImpactPathPoint {
  offset_seconds: number;
  real_price: number;
  impact_delta: number;
  effective_price: number;
  impact_remaining_percent: number;
}

export interface VirtualImpactCandle {
  start_offset_seconds: number;
  end_offset_seconds: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface VirtualSimulatedPositionPath {
  model: "exponential_decay";
  reference_price: number;
  entry_price: number;
  post_trade_price: number;
  initial_impact_delta: number;
  decay_lambda: number;
  decay_horizon_seconds: number;
  points: VirtualImpactPathPoint[];
  simulated_candle: VirtualImpactCandle;
}

export interface PositionSizingResult {
  side: SignalDirection;
  account_equity: number;
  risk_per_trade_percent: number;
  risk_amount: number;
  entry_price: number;
  stop_loss_price: number;
  stop_distance_per_unit: number;
  estimated_entry_fee_per_unit: number;
  estimated_exit_fee_per_unit: number;
  slippage_buffer_per_unit: number;
  funding_buffer_per_unit: number;
  effective_risk_per_unit: number;
  position_size_base: number;
  notional: number;
  leverage: number;
  required_margin: number;
  fee_rate: number;
  slippage_bps: number;
  include_fees_in_risk: boolean;
  include_slippage_in_risk: boolean;
}

export interface RiskAdjustmentPlan {
  instrument_type: TradeInstrumentType;
  strategy: string;
  signal_score: number;
  account_equity: number;
  base_risk_percent: number;
  base_risk_amount: number;
  strategy_risk_multiplier: number;
  signal_score_multiplier: number;
  volatility_multiplier: number;
  user_mode_multiplier: number;
  adjusted_risk_percent: number;
  adjusted_risk_amount: number;
  signal_trade_allowed: boolean;
  signal_virtual_only: boolean;
  warnings: string[];
}

export interface RiskCheckResult {
  status: RiskCheckStatus;
  blockers: string[];
  warnings: string[];
  rr: number | null;
  min_rr_ratio: number;
  risk_reward_guard_mode: RRGuardMode;
  risk_reward_warning: boolean;
  risk_reward_warning_reason: string | null;
  risk_reward_blocked: boolean;
  risk_reward_block_reason: string | null;
  account_equity: number;
  adjusted_risk_amount: number;
  adjusted_risk_percent: number;
  effective_risk_amount: number;
  position_notional: number;
  position_size_base: number;
  required_margin: number;
  available_balance: number | null;
  close_only: boolean;
  real_entries_allowed: boolean;
  virtual_entries_allowed: boolean;
  reduce_only_allowed: boolean;
  protective_orders_allowed: boolean;
  daily_risk_used_percent: number | null;
  max_daily_loss_percent: number;
  account_drawdown_percent: number | null;
  max_account_drawdown_percent: number;
  open_risk_used_percent: number | null;
  max_open_risk_percent: number;
  correlated_risk_used_percent: number | null;
  max_correlated_risk_percent: number;
  protection_state: RiskProtectionMode;
  exchange_rule_status: ExchangeRuleStatus;
  exchange_rule_age_seconds: number | null;
  exchange_rule_ttl_seconds: number | null;
  market_data_status: MarketDataStatus;
  best_bid: number | null;
  best_ask: number | null;
  mark_price: number | null;
  funding_rate: number | null;
  funding_buffer_amount: number;
  fee_rate_source: string | null;
  maker_fee_rate: number | null;
  taker_fee_rate: number | null;
  spread_percent: number | null;
  spread_bps: number | null;
  max_spread_bps: number;
  slippage_bps: number;
  max_slippage_bps: number;
  price_deviation_bps: number | null;
  max_price_deviation_bps: number;
  orderbook_depth_usd: number | null;
  orderbook_can_fill: boolean | null;
  orderbook_liquidity_ratio: number | null;
  max_orderbook_liquidity_ratio: number;
}

export interface RiskDecision {
  mode: TradeMode;
  stage: "preview" | "pre_execution" | "post_execution" | "confirm";
  status: RiskCheckStatus;
  can_enter: boolean;
  blockers: string[];
  warnings: string[];
  exchange: string;
  symbol: string;
  instrument_type: TradeInstrumentType;
  requested_notional: number | null;
  risk_adjustment_plan: RiskAdjustmentPlan;
  position_sizing: PositionSizingResult;
  checked_position_sizing: PositionSizingResult;
  risk_check: RiskCheckResult;
  stop_loss_plan: StopLossPlan;
  take_profit_plan: TakeProfitPlan;
  breakeven_plan: BreakevenPlan;
  trailing_stop_plan: TrailingStopPlan;
  futures_risk_plan: FuturesRiskPlan | null;
  notes: string[];
}

export interface RiskStateResponse {
  user_id: string;
  mode: TradeMode | null;
  protection_state: RiskProtectionMode;
  protection_reason: string | null;
  close_only: boolean;
  real_entries_allowed: boolean;
  virtual_entries_allowed: boolean;
  reduce_only_allowed: boolean;
  protective_orders_allowed: boolean;
  loss_streak: number;
  daily_loss_amount: number;
  weekly_loss_amount: number;
  daily_window_start: string | null;
  weekly_window_start: string | null;
  window_timezone: string;
  peak_equity: number;
  current_equity: number;
  adaptive_multiplier: number;
  daily_loss_percent: number;
  weekly_loss_percent: number;
  account_drawdown_percent: number;
  max_account_drawdown_percent: number;
  open_risk_amount: number;
  open_risk_percent: number;
  max_open_risk_percent: number;
  correlated_risk_amount: number;
  correlated_risk_percent: number;
  max_correlated_risk_percent: number;
  correlation_group: string | null;
  exchange_rule_status: ExchangeRuleStatus;
  exchange_rule_age_seconds: number | null;
  exchange_rule_ttl_seconds: number | null;
}

export interface RiskPreviewResponse {
  decision: RiskDecision;
  state: RiskStateResponse;
  risk_decision_id: string | null;
}

export interface StopLossPlan {
  side: SignalDirection;
  mode: StopLossMode;
  entry_price: number;
  stop_loss_price: number;
  risk_per_unit: number;
  source: string;
  default_stop_loss_percent: number;
  atr_period: number;
  atr_multiplier: number;
  atr_value: number | null;
  warnings: string[];
}

export interface TakeProfitTarget {
  label: "TP1" | "TP2" | "TP3";
  r_multiple: number;
  price: number;
  close_percent: number;
  action: TakeProfitTargetAction;
}

export interface TakeProfitPlan {
  mode: TakeProfitMode;
  side: SignalDirection;
  entry_price: number;
  stop_loss_price: number;
  risk_per_unit: number;
  partial_take_profit_enabled: boolean;
  targets: TakeProfitTarget[];
  source?: string;
  selected_rr?: number | null;
  selected_rr_target?: string | null;
  notes?: string[];
}

export interface BreakevenPlan {
  side: SignalDirection;
  entry_price: number;
  stop_loss_price: number;
  risk_per_unit: number;
  move_after_r: number;
  trigger_price: number;
  breakeven_stop_price: number;
  offset_percent: number;
}

export interface TrailingStopPlan {
  side: SignalDirection;
  enabled: boolean;
  mode: TrailingMode;
  entry_price: number;
  current_price: number;
  trailing_distance: number | null;
  trailing_stop_price: number | null;
  trailing_percent: number;
  atr_multiplier: number;
  atr_value: number | null;
  structure_stop_price: number | null;
  source: string;
  warnings: string[];
}

export interface FuturesRiskPlan {
  side: SignalDirection;
  status: FuturesRiskStatus;
  entry_price: number;
  stop_loss_price: number;
  leverage: number;
  max_leverage: number;
  leverage_allowed: boolean;
  liquidation_price: number | null;
  liquidation_buffer_percent: number | null;
  min_liquidation_buffer_percent: number;
  liquidation_before_stop: boolean | null;
  message: string;
  warnings: string[];
}

export interface VirtualExecutionReport {
  mode: VirtualSimulationMode;
  simulation_tier: VirtualSimulationTier;
  active_capabilities: string[];
  planned_capabilities: string[];
  status: VirtualExecutionStatus;
  requested_size_usd: number;
  filled_size_usd: number;
  unfilled_size_usd: number;
  fill_ratio: number;
  reference_price: number;
  average_price: number | null;
  entry_slippage_bps: number;
  exit_slippage_bps: number;
  market_impact_percent: number;
  best_bid_before: number | null;
  best_ask_before: number | null;
  book_price_after: number | null;
  liquidity: LiquidityMetrics;
  quality_gate: ExecutionQualityGate;
  risk_adjustment_plan: RiskAdjustmentPlan | null;
  risk_check: RiskCheckResult | null;
  risk_decision: RiskDecision | null;
  position_sizing: PositionSizingResult | null;
  stop_loss_plan: StopLossPlan | null;
  take_profit_plan: TakeProfitPlan | null;
  breakeven_plan: BreakevenPlan | null;
  trailing_stop_plan: TrailingStopPlan | null;
  futures_risk_plan: FuturesRiskPlan | null;
  simulated_path: VirtualSimulatedPositionPath | null;
  rejected_reason: string | null;
  notes: string[];
}

export interface VirtualTradeTargetState {
  label: string;
  price: number;
  close_percent: number;
  action: string | null;
  hit: boolean;
  hit_at: string | null;
  closed_quantity: number;
  closed_size_usd: number;
  realized_pnl: number;
  exit_fee: number;
}

export interface VirtualTradeLifecycleEvent {
  event_type: string;
  reason: TradeCloseReason | null;
  target_label: string | null;
  price: number | null;
  quantity: number | null;
  size_usd: number | null;
  realized_pnl: number | null;
  exit_fee: number | null;
  stop_loss: number | null;
  created_at: string;
  metadata: Record<string, unknown>;
}

export interface TradeJournalEntry {
  id: string;
  user_id: string;
  signal_id: string | null;
  mode: TradeMode;
  exchange: string;
  symbol: string;
  strategy: string;
  timeframe: string;
  side: SignalDirection;
  entry_price: number;
  current_price: number;
  exit_price: number | null;
  size_usd: number;
  quantity: number;
  initial_quantity?: number | null;
  remaining_quantity?: number | null;
  closed_quantity?: number;
  initial_size_usd?: number | null;
  remaining_size_usd?: number | null;
  leverage: number;
  risk_percent: number;
  risk_amount: number;
  risk_reward: number;
  stop_loss: number;
  current_stop_loss?: number | null;
  stop_moved_to_breakeven?: boolean;
  trailing_active?: boolean;
  take_profit: number[];
  fees: number;
  realized_pnl?: number;
  unrealized_pnl?: number;
  exit_fees?: number;
  slippage_bps: number;
  simulation_mode: VirtualSimulationMode;
  execution_status: VirtualExecutionStatus;
  requested_size_usd: number | null;
  filled_size_usd: number | null;
  unfilled_size_usd: number;
  execution: VirtualExecutionReport | null;
  status: TradeStatus;
  result: "win" | "loss" | "breakeven" | null;
  close_reason: TradeCloseReason | null;
  pnl: number | null;
  pnl_percent: number | null;
  mfe: number;
  mae: number;
  screenshots: string[];
  ai_review: string | null;
  opened_at: string;
  updated_at: string;
  closed_at: string | null;
  target_states?: VirtualTradeTargetState[];
  lifecycle_events?: VirtualTradeLifecycleEvent[];
}

export interface TradeInvalidationAlert {
  trade_id: string;
  signal_id: string | null;
  exchange: string;
  symbol: string;
  strategy: string;
  timeframe: string;
  side: SignalDirection;
  status: TradeInvalidationStatus;
  invalidated: boolean;
  reason: string | null;
  triggered_conditions: string[];
  watched_conditions: string[];
  suggested_action: TradeInvalidationAction;
  current_price: number;
  stop_loss: number;
  invalidation_price: number | null;
  detected_at: string;
  fingerprint: string | null;
  user_action: TradeInvalidationUserAction | null;
  user_action_at: string | null;
  action_dismissed: boolean;
  metadata: Record<string, unknown>;
}

export interface TradeInvalidationActionResponse {
  action: TradeInvalidationUserAction;
  alert: TradeInvalidationAlert;
  message: string;
}

export interface VirtualAccount {
  user_id: string;
  starting_balance: number;
  balance: number;
  equity: number;
  realized_pnl: number;
  unrealized_pnl: number;
  risk_per_trade: number;
  risk_reward: number;
  open_positions: number;
  closed_trades: number;
  wins: number;
  losses: number;
  breakeven: number;
  updated_at: string;
}

export interface TradeJournalResponse {
  trades: TradeJournalEntry[];
  account?: VirtualAccount | null;
}

export interface CloseMarketTradeResponse {
  mode: TradeMode;
  status: CloseMarketTradeStatus;
  message: string;
  trade: TradeJournalEntry | null;
}

export interface RadarConfig {
  exchanges: string[];
  symbols: string[];
  use_all_symbols: boolean;
  timeframes: string[];
}

export interface HealthStatus {
  status: string;
  scanner_enabled: boolean;
  scanner_running: boolean;
  scanner_stopping?: boolean;
  processed_signals: number;
  ticks_processed?: number;
  features_built?: number;
  strategy_evaluations?: number;
  signals_found?: number;
  candles_seeded?: number;
  last_symbol?: string | null;
  last_price?: number | null;
}

export interface RadarStatus extends HealthStatus {
  exchanges: string[];
  symbols: string[];
  timeframes: string[];
  strategies: string[];
  scanner_subscription_hash: string | null;
  strategy_config_hash: string | null;
  ticks_processed: number;
  candles_updated: number;
  features_built: number;
  strategy_evaluations: number;
  signals_found: number;
  candles_seeded: number;
  last_tick_at: number | null;
  last_signal_at: number | null;
  last_exchange: string | null;
  last_symbol: string | null;
  last_price: number | null;
  candle_history: Record<string, number>;
}
