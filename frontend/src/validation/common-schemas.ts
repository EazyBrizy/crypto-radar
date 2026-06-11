import { z } from "zod";
import { SIGNAL_STATUSES } from "@/domain/signal-status";
import { TRADE_STATUSES } from "@/domain/trade-status";

export const TimeframeSchema = z.enum(["1m", "5m", "15m", "1h", "4h", "1d"]);
export const SignalDirectionSchema = z.enum(["long", "short"]);
export const SignalSideSchema = z.enum(["LONG", "SHORT"]);
export const SignalStatusSchema = z.enum(SIGNAL_STATUSES);
export const TradeModeSchema = z.enum(["virtual", "real"]);
export const PendingEntryIntentStatusSchema = z.enum([
  "pending",
  "triggered",
  "filling",
  "filled",
  "failed",
  "cancelled",
  "expired",
  "requires_reconfirmation"
]);
export const TradeSourceSchema = z.enum(["virtual", "real", "backtest"]);
export const TradeStatusSchema = z.enum(TRADE_STATUSES);
export const TradeCloseReasonSchema = z.enum([
  "take_profit",
  "stop_loss",
  "manual_close",
  "invalidation",
  "cancelled",
  "partial_take_profit",
  "breakeven_stop",
  "trailing_stop",
  "time_stop"
]);
export const VirtualSimulationModeSchema = z.enum(["passive", "impact_aware"]);
export const VirtualSimulationTierSchema = z.enum(["mvp", "advanced", "pro"]);
export const VirtualExecutionProfileSchema = z.enum(["realistic", "relaxed_paper", "deterministic_test"]);
export const VirtualFillPolicySchema = z.enum(["strict_orderbook", "relaxed_market_fallback", "deterministic_market_fill"]);
export const VirtualExecutionStatusSchema = z.enum(["filled", "partially_filled", "rejected_virtual_execution"]);
export const VirtualFillStatusSchema = z.enum(["filled", "partial_filled", "blocked", "rejected"]);
export const ImpactRiskSchema = z.enum(["low", "medium", "high"]);
export const ExecutionGateStatusSchema = z.enum(["passed", "warning", "blocked"]);
export const RadarRiskRewardStatusSchema = z.enum(["passed", "warning", "failed", "skipped", "unknown"]);
export const RiskCheckStatusSchema = z.enum(["passed", "warning", "failed"]);
export const ViewToneSchema = z.enum(["green", "red", "yellow", "blue", "purple", "neutral"]);
export const MarketRegimeTypeSchema = z.enum([
  "trend_up",
  "trend_down",
  "range",
  "chop",
  "volatility_compression",
  "volatility_expansion",
  "post_impulse",
  "liquidity_sweep_zone",
  "unknown"
]);
export const MarketRegimeVolatilityStateSchema = z.enum(["compression", "normal", "expansion", "unknown"]);
export const MarketRegimeStructureStateSchema = z.enum(["trend", "range", "chop", "unknown"]);

const DEFAULT_LIQUIDITY_METRICS = {
  spread_percent: 0,
  orderbook_depth_0_1_percent_usd: 0,
  orderbook_depth_0_5_percent_usd: 0,
  orderbook_depth_1_percent_usd: 0,
  volume_1m_usd: 0,
  volume_5m_usd: 0,
  volume_15m_usd: 0,
  average_trade_size_usd: 0,
  volatility_1m_percent: 0,
  liquidity_score: 0,
  impact_score: 0,
  impact_risk: "low" as const
};

const DEFAULT_EXECUTION_QUALITY_GATE = {
  status: "passed" as const,
  warnings: [],
  high_impact_reasons: [],
  blockers: [],
  suggested_max_size_usd: null,
  message: null
};

export const SignalScoreBreakdownSchema = z.object({
  trend_score: z.number(),
  volume_score: z.number(),
  liquidity_score: z.number(),
  orderbook_score: z.number(),
  risk_reward_score: z.number(),
  volatility_score: z.number(),
  overheat_penalty: z.number(),
  news_event_risk_penalty: z.number(),
  total: z.number()
});

export const SignalLayerCheckSchema = z.object({
  name: z.string(),
  status: z.enum(["passed", "warning", "failed", "skipped"]).default("passed"),
  score: z.number().nullable().optional(),
  reason: z.string().nullable().optional(),
  metadata: z.record(z.string(), z.unknown()).default({})
});

export const TradePlanSchema = z.object({
  version: z.literal("v1").default("v1"),
  entry: z.object({
    price: z.number().nullable().optional(),
    min_price: z.number().nullable().optional(),
    max_price: z.number().nullable().optional(),
    source: z.string().default("legacy_fields"),
    metadata: z.record(z.string(), z.unknown()).default({})
  }).default({ source: "legacy_fields", metadata: {} }),
  stop_loss: z.number().nullable().optional(),
  targets: z.array(z.object({
    label: z.string(),
    price: z.number().nullable().optional(),
    r_multiple: z.number().nullable().optional(),
    action: z.string().nullable().optional(),
    close_percent: z.union([z.number(), z.string()]).nullable().optional(),
    source: z.string().nullable().optional(),
    metadata: z.record(z.string(), z.unknown()).default({})
  })).default([]),
  invalidation: z.object({
    price: z.number().nullable().optional(),
    hard_stop: z.number().nullable().optional(),
    conditions: z.array(z.string()).default([]),
    metadata: z.record(z.string(), z.unknown()).default({})
  }).nullable().optional(),
  risk_rules: z.object({
    risk_reward: z.number().nullable().optional(),
    first_target_rr: z.number().nullable().optional(),
    final_target_rr: z.number().nullable().optional(),
    selected_rr: z.number().nullable().optional(),
    selected_rr_target: z.string().nullable().optional(),
    min_rr_ratio: z.number().nullable().optional(),
    metadata: z.record(z.string(), z.unknown()).default({})
  }).default({ metadata: {} }),
  metadata: z.record(z.string(), z.unknown()).default({})
});

export const SignalEdgeSnapshotSchema = z.object({
  status: z.enum(["unknown", "positive", "negative", "insufficient_sample"]).default("unknown"),
  sample_size: z.number().default(0),
  min_sample_size: z.number().default(0),
  winrate: z.number().nullable().optional(),
  avg_win_r: z.number().nullable().optional(),
  avg_loss_r: z.number().nullable().optional(),
  expectancy_r: z.number().nullable().optional(),
  expectancy_after_costs_r: z.number().nullable().optional(),
  profit_factor: z.number().nullable().optional(),
  confidence_score: z.number().default(0),
  source: z.enum(["outcome", "backtest", "mixed", "none"]).default("none"),
  score_bucket: z.string().nullable().optional(),
  metadata: z.record(z.string(), z.unknown()).default({})
});

export const NoTradeFilterResultSchema = z.object({
  enabled: z.boolean().default(true),
  blocked: z.boolean().default(false),
  hard_block: z.boolean().default(false),
  blockers: z.array(z.string()).default([]),
  warnings: z.array(z.string()).default([]),
  checks: z.array(SignalLayerCheckSchema).default([]),
  metadata: z.record(z.string(), z.unknown()).default({})
});

export const DecisionReasonSchema = z.object({
  code: z.string(),
  message: z.string(),
  source: z.enum(["setup", "market_quality", "rr", "no_trade", "risk", "execution", "data"]),
  severity: z.enum(["info", "warning", "blocker"]),
  scope: z.enum(["discovery", "virtual", "real", "backtest"]),
  metadata: z.record(z.string(), z.unknown()).default({})
});

export const SignalDecisionSnapshotSchema = z.object({
  setup_valid: z.boolean(),
  trade_plan_valid: z.boolean(),
  market_context_score: z.number(),
  signal_actionable: z.boolean(),
  execution_allowed_virtual: z.boolean().nullable().optional(),
  execution_allowed_real: z.boolean().nullable().optional(),
  blockers: z.array(DecisionReasonSchema).default([]),
  warnings: z.array(DecisionReasonSchema).default([])
});

export const SignalBadgeViewSchema = z.object({
  code: z.string().min(1),
  label: z.string(),
  tone: ViewToneSchema
}).passthrough();

export const SignalTargetViewSchema = z.object({
  label: z.string().min(1),
  price: z.number().nullable().optional(),
  r_multiple: z.number().nullable().optional(),
  action: z.string().nullable().optional()
}).passthrough();

export const SignalTradePlanViewSchema = z.object({
  has_trade_plan: z.boolean(),
  entry_type: z.string(),
  entry_zone: z.string(),
  entry_price: z.number().nullable().optional(),
  stop_loss: z.number().nullable().optional(),
  targets: z.array(SignalTargetViewSchema).default([]),
  selected_rr: z.number().nullable().optional(),
  selected_rr_target: z.string().nullable().optional(),
  min_rr: z.number().nullable().optional(),
  trade_plan_complete: z.boolean().nullable().optional(),
  fallback_used: z.boolean().default(false),
  missing: z.array(z.string()).default([]),
  invalidation: z.string()
}).passthrough();

export const SignalCardViewSchema = z.object({
  status_label: z.string(),
  status_tone: ViewToneSchema,
  opportunity_label: z.string(),
  opportunity_tone: ViewToneSchema,
  risk_label: z.string(),
  risk_meta: z.string(),
  badges: z.array(SignalBadgeViewSchema).default([]),
  entry_label: z.string(),
  entry_value: z.string(),
  stop_loss: z.number().nullable().optional(),
  targets: z.array(SignalTargetViewSchema).default([]),
  selected_rr: z.number().nullable().optional(),
  reason: z.string()
}).passthrough();

export const SignalExecutionGateReasonSchema = z.object({
  code: z.string(),
  severity: z.enum(["blocker", "warning", "info"]),
  source: z.string(),
  message: z.string(),
  metadata: z.record(z.string(), z.unknown()).default({})
}).passthrough();

export const SignalExecutionGateSnapshotSchema = z.object({
  status: z.enum(["passed", "warning", "blocked"]),
  feed_kind: z.enum(["market_idea", "watchlist", "execution_signal", "blocked"]),
  can_notify: z.boolean(),
  can_enter_now: z.boolean(),
  can_arm_pending: z.boolean(),
  can_show_in_execution_feed: z.boolean(),
  reasons: z.array(SignalExecutionGateReasonSchema).default([]),
  warnings: z.array(SignalExecutionGateReasonSchema).default([]),
  metadata: z.record(z.string(), z.unknown()).default({})
}).passthrough();

export const SignalDetailsPrimaryStatusSchema = z.enum([
  "execution_ready",
  "waiting_entry",
  "requires_reconfirmation",
  "blocked",
  "watchlist",
  "cancelled",
  "expired",
  "unknown"
]);

export const SignalDetailsBlockerViewSchema = z.object({
  code: z.string().min(1),
  severity: z.enum(["blocker", "warning", "info"]),
  category: z.enum(["entry", "risk", "market_data", "liquidity", "execution", "technical"]),
  user_message: z.string(),
  debug_messages: z.array(z.string()).default([])
}).passthrough();

export const SignalDetailsRiskSummaryViewSchema = z.object({
  label: z.string(),
  risk_failed: z.boolean().default(false),
  risk_reward_blocked: z.boolean().default(false),
  risk_reward_warning: z.string().nullable().optional(),
  forming_candle: z.boolean().default(false),
  open_candle_allowed: z.boolean().default(false),
  forming_reason: z.string().nullable().optional(),
  status_allows_trade: z.boolean().default(false),
  trade_plan_complete: z.boolean().default(false),
  risk_reward_ok: z.boolean().default(false),
  is_market_opportunity: z.boolean().default(false)
}).passthrough();

export const SignalDetailsExecutionSummaryViewSchema = z.object({
  preview_available: z.boolean().default(false),
  risk_check_status: z.string().nullable().optional(),
  risk_decision_status: z.string().nullable().optional(),
  can_enter: z.boolean().nullable().optional(),
  quality_gate_status: z.string().nullable().optional(),
  impact_risk: z.string().nullable().optional(),
  status_allows_trade: z.boolean().default(false)
}).passthrough();

export const SignalDetailsViewSchema = z.object({
  title: z.string(),
  side: SignalDirectionSchema,
  primary_status: SignalDetailsPrimaryStatusSchema,
  primary_status_label: z.string(),
  primary_status_tone: ViewToneSchema,
  primary_action_label: z.string(),
  recommended_action_text: z.string(),
  can_enter_now: z.boolean().nullable().optional(),
  trade_plan: SignalTradePlanViewSchema,
  risk_summary: SignalDetailsRiskSummaryViewSchema,
  execution_summary: SignalDetailsExecutionSummaryViewSchema,
  top_reasons: z.array(z.string()).default([]),
  top_blockers: z.array(SignalDetailsBlockerViewSchema).default([]),
  warnings: z.array(SignalDetailsBlockerViewSchema).default([])
}).passthrough();

export const RadarSignalSchema = z.object({
  id: z.string(),
  symbol: z.string(),
  exchange: z.string(),
  strategy: z.string(),
  direction: SignalDirectionSchema,
  confidence: z.number(),
  risk_reward: z.number().nullable().optional(),
  first_target_rr: z.number().nullable().optional(),
  final_target_rr: z.number().nullable().optional(),
  selected_rr: z.number().nullable().optional(),
  selected_rr_target: z.string().nullable().optional(),
  min_rr_ratio: z.number().nullable().optional(),
  urgency: z.enum(["low", "medium", "high"]).default("medium"),
  status: SignalStatusSchema.default("active"),
  score: z.number().default(0),
  timeframe: z.string().default("stream"),
  candle_state: z.enum(["open", "closed"]).default("closed").optional(),
  entry_min: z.number().nullable().optional(),
  entry_max: z.number().nullable().optional(),
  stop_loss: z.number().nullable().optional(),
  take_profit_1: z.number().nullable().optional(),
  take_profit_2: z.number().nullable().optional(),
  explanation: z.array(z.string()).default([]),
  risks: z.array(z.string()).default([]),
  score_breakdown: SignalScoreBreakdownSchema.optional(),
  status_reason: z.string().nullable().optional(),
  quality: z.object({
    passed: z.boolean(),
    tier: z.enum(["major", "mid_alt", "low_liquidity", "unknown"]),
    score: z.number(),
    volume_24h_quote: z.number().nullable().optional(),
    spread_bps: z.number().nullable().optional(),
    history_ok: z.boolean(),
    rough_chart_score: z.number().nullable().optional(),
    checks: z.array(SignalLayerCheckSchema).default([]),
    warnings: z.array(z.string()).default([])
  }).nullable().optional(),
  regime: z.object({
    signal_timeframe: z.string(),
    context_timeframe: z.string().nullable().optional(),
    direction: z.enum(["bullish", "bearish", "range", "unknown"]),
    strength: z.enum(["weak", "normal", "strong", "unknown"]),
    alignment: z.enum(["aligned", "mixed", "against", "unknown"]),
    regime_type: MarketRegimeTypeSchema.default("unknown"),
    volatility_state: MarketRegimeVolatilityStateSchema.default("unknown"),
    structure_state: MarketRegimeStructureStateSchema.default("unknown"),
    compatibility: z.record(z.string(), z.unknown()).default({}),
    score_adjustment: z.number(),
    checks: z.array(SignalLayerCheckSchema).default([])
  }).nullable().optional(),
  setup: z.object({
    name: z.string(),
    stage: z.enum(["forming", "ready", "confirmed"]),
    checks: z.array(SignalLayerCheckSchema).default([])
  }).nullable().optional(),
  confirmation: z.object({
    passed: z.boolean(),
    checks: z.array(SignalLayerCheckSchema).default([])
  }).nullable().optional(),
  invalidation: z.object({
    price: z.number().nullable().optional(),
    hard_stop: z.number().nullable().optional(),
    conditions: z.array(z.string()).default([]),
    metadata: z.record(z.string(), z.unknown()).default({})
  }).nullable().optional(),
  exit_plan: z.object({
    targets: z.array(z.record(z.string(), z.unknown())).default([]),
    breakeven: z.record(z.string(), z.unknown()).default({}),
    trailing: z.record(z.string(), z.unknown()).default({})
  }).nullable().optional(),
  trade_plan: TradePlanSchema.nullable().optional(),
  auto_entry: z.object({
    enabled: z.boolean(),
    status: PendingEntryIntentStatusSchema,
    mode: z.enum(["virtual", "real"]),
    user_id: z.string(),
    armed_at: z.string().nullable().optional(),
    triggered_at: z.string().nullable().optional(),
    message: z.string().nullable().optional(),
    request: z.record(z.string(), z.unknown()).default({}),
    trade_id: z.string().nullable().optional(),
    real_execution: z.record(z.string(), z.unknown()).nullable().optional()
  }).nullable().optional(),
  edge: SignalEdgeSnapshotSchema.nullable().optional(),
  no_trade_filter: NoTradeFilterResultSchema.nullable().optional(),
  decision: SignalDecisionSnapshotSchema.nullable().optional(),
  execution_gate: SignalExecutionGateSnapshotSchema.nullable().optional(),
  rr_status: RadarRiskRewardStatusSchema.nullable().optional(),
  risk_gate_status: RiskCheckStatusSchema.nullable().optional(),
  can_enter: z.boolean().nullable().optional(),
  display_reason: z.string().nullable().optional(),
  card_view: SignalCardViewSchema.nullable().optional(),
  details_view: SignalDetailsViewSchema.nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
  expires_at: z.string().nullable().optional(),
  confirmed_trade_id: z.string().nullable().optional()
}).passthrough();

export const LiquidityMetricsSchema = z.object({
  spread_percent: z.number().default(0),
  orderbook_depth_0_1_percent_usd: z.number().default(0),
  orderbook_depth_0_5_percent_usd: z.number().default(0),
  orderbook_depth_1_percent_usd: z.number().default(0),
  volume_1m_usd: z.number().default(0),
  volume_5m_usd: z.number().default(0),
  volume_15m_usd: z.number().default(0),
  average_trade_size_usd: z.number().default(0),
  volatility_1m_percent: z.number().default(0),
  liquidity_score: z.number().default(0),
  impact_score: z.number().default(0),
  impact_risk: ImpactRiskSchema.default("low")
});

export const VirtualExecutionReportSchema = z.object({
  mode: VirtualSimulationModeSchema.default("passive"),
  simulation_tier: VirtualSimulationTierSchema.default("mvp"),
  active_capabilities: z.array(z.string()).default([]),
  planned_capabilities: z.array(z.string()).default([]),
  execution_profile: VirtualExecutionProfileSchema.default("realistic"),
  fill_policy: VirtualFillPolicySchema.default("strict_orderbook"),
  status: VirtualExecutionStatusSchema.default("filled"),
  requested_size_usd: z.number().default(0),
  filled_size_usd: z.number().default(0),
  unfilled_size_usd: z.number().default(0),
  fill_ratio: z.number().default(1),
  reference_price: z.number().default(0),
  average_price: z.number().nullable().optional(),
  estimated_fill_price: z.number().nullable().optional(),
  entry_slippage_bps: z.number().default(0),
  exit_slippage_bps: z.number().default(0),
  market_impact_percent: z.number().default(0),
  best_bid_before: z.number().nullable().optional(),
  best_ask_before: z.number().nullable().optional(),
  book_price_after: z.number().nullable().optional(),
  liquidity: LiquidityMetricsSchema.default(DEFAULT_LIQUIDITY_METRICS),
  quality_gate: z.object({
    status: ExecutionGateStatusSchema.default("passed"),
    warnings: z.array(z.string()).default([]),
    high_impact_reasons: z.array(z.string()).default([]),
    blockers: z.array(z.string()).default([]),
    suggested_max_size_usd: z.number().nullable().optional(),
    message: z.string().nullable().optional()
  }).default(DEFAULT_EXECUTION_QUALITY_GATE),
  simulated_path: z.object({
    model: z.literal("exponential_decay").default("exponential_decay"),
    reference_price: z.number(),
    entry_price: z.number(),
    post_trade_price: z.number(),
    initial_impact_delta: z.number(),
    decay_lambda: z.number(),
    decay_horizon_seconds: z.number().default(60),
    points: z.array(z.object({
      offset_seconds: z.number(),
      real_price: z.number(),
      impact_delta: z.number(),
      effective_price: z.number(),
      impact_remaining_percent: z.number()
    })).default([]),
    simulated_candle: z.object({
      start_offset_seconds: z.number().default(0),
      end_offset_seconds: z.number().default(60),
      open: z.number(),
      high: z.number(),
      low: z.number(),
      close: z.number()
    })
  }).nullable().optional(),
  fill_result: z.object({
    status: VirtualFillStatusSchema,
    requested_notional: z.number().default(0),
    filled_notional: z.number().default(0),
    avg_fill_price: z.number().nullable().optional(),
    estimated_slippage_bps: z.number().default(0),
    spread_bps: z.number().default(0),
    market_impact_bps: z.number().default(0),
    reason: z.string().nullable().optional(),
    warnings: z.array(z.string()).default([]),
    raw_inputs_snapshot: z.record(z.string(), z.unknown()).default({})
  }).nullable().optional(),
  raw_inputs_snapshot: z.record(z.string(), z.unknown()).default({}),
  rejected_reason: z.string().nullable().optional(),
  warnings: z.array(z.string()).default([]),
  blockers: z.array(z.string()).default([]),
  reason_code: z.string().nullable().optional(),
  reason_codes: z.array(z.string()).default([]),
  notes: z.array(z.string()).default([])
});

export const TradeJournalEntrySchema = z.object({
  id: z.string(),
  user_id: z.string(),
  signal_id: z.string().nullable().optional(),
  mode: TradeModeSchema,
  source: TradeSourceSchema.default("virtual"),
  tags: z.array(z.string()).default([]),
  run_id: z.string().nullable().optional(),
  exchange: z.string(),
  symbol: z.string(),
  strategy: z.string(),
  timeframe: z.string(),
  side: SignalDirectionSchema,
  entry_price: z.number(),
  current_price: z.number(),
  exit_price: z.number().nullable().optional(),
  size_usd: z.number(),
  quantity: z.number(),
  initial_quantity: z.number().nullable().optional(),
  remaining_quantity: z.number().nullable().optional(),
  closed_quantity: z.number().default(0),
  initial_size_usd: z.number().nullable().optional(),
  remaining_size_usd: z.number().nullable().optional(),
  leverage: z.number(),
  risk_percent: z.number(),
  risk_amount: z.number().default(0),
  risk_reward: z.number().default(3),
  stop_loss: z.number(),
  current_stop_loss: z.number().nullable().optional(),
  stop_moved_to_breakeven: z.boolean().default(false),
  trailing_active: z.boolean().default(false),
  trailing_distance: z.number().nullable().optional(),
  highest_price_after_trailing: z.number().nullable().optional(),
  lowest_price_after_trailing: z.number().nullable().optional(),
  take_profit: z.array(z.number()).default([]),
  fees: z.number().default(0),
  realized_pnl: z.number().default(0),
  unrealized_pnl: z.number().default(0),
  exit_fees: z.number().default(0),
  slippage_bps: z.number().default(0),
  simulation_mode: VirtualSimulationModeSchema.default("passive"),
  execution_status: VirtualExecutionStatusSchema.default("filled"),
  requested_size_usd: z.number().nullable().optional(),
  filled_size_usd: z.number().nullable().optional(),
  unfilled_size_usd: z.number().default(0),
  execution: VirtualExecutionReportSchema.nullable().optional(),
  status: TradeStatusSchema,
  result: z.enum(["win", "loss", "breakeven"]).nullable().optional(),
  close_reason: TradeCloseReasonSchema.nullable().optional(),
  pnl: z.number().nullable().optional(),
  pnl_percent: z.number().nullable().optional(),
  mfe: z.number().default(0),
  mae: z.number().default(0),
  screenshots: z.array(z.string()).default([]),
  ai_review: z.string().nullable().optional(),
  opened_at: z.string(),
  updated_at: z.string(),
  closed_at: z.string().nullable().optional(),
  target_states: z.array(z.object({
    label: z.string(),
    price: z.number(),
    close_percent: z.number().default(0),
    action: z.string().nullable().optional(),
    hit: z.boolean().default(false),
    hit_at: z.string().nullable().optional(),
    closed_quantity: z.number().default(0),
    closed_size_usd: z.number().default(0),
    realized_pnl: z.number().default(0),
    exit_fee: z.number().default(0)
  })).default([]),
  lifecycle_events: z.array(z.object({
    event_type: z.string(),
    reason: TradeCloseReasonSchema.nullable().optional(),
    target_label: z.string().nullable().optional(),
    price: z.number().nullable().optional(),
    quantity: z.number().nullable().optional(),
    size_usd: z.number().nullable().optional(),
    realized_pnl: z.number().nullable().optional(),
    exit_fee: z.number().nullable().optional(),
    stop_loss: z.number().nullable().optional(),
    created_at: z.string(),
    metadata: z.record(z.string(), z.unknown()).default({})
  })).default([])
});

export const TradeInvalidationAlertSchema = z.object({
  trade_id: z.string(),
  signal_id: z.string().nullable().optional(),
  exchange: z.string(),
  symbol: z.string(),
  strategy: z.string(),
  timeframe: z.string(),
  side: SignalDirectionSchema,
  status: z.enum(["valid", "invalidated", "unavailable"]),
  invalidated: z.boolean().default(false),
  reason: z.string().nullable().optional(),
  triggered_conditions: z.array(z.string()).default([]),
  watched_conditions: z.array(z.string()).default([]),
  suggested_action: z.enum(["none", "close_market_or_wait_stop"]).default("none"),
  current_price: z.number(),
  stop_loss: z.number(),
  invalidation_price: z.number().nullable().optional(),
  detected_at: z.string(),
  fingerprint: z.string().nullable().optional(),
  user_action: z.enum(["close_market", "keep_stop_loss", "dismissed"]).nullable().optional(),
  user_action_at: z.string().nullable().optional(),
  action_dismissed: z.boolean().default(false),
  metadata: z.record(z.string(), z.unknown()).default({})
});

export const RadarStatusSchema = z.object({
  status: z.string(),
  scanner_enabled: z.boolean(),
  scanner_running: z.boolean(),
  scanner_stopping: z.boolean().default(false),
  stage: z.enum(["idle", "starting", "warming_up", "listening", "stale", "degraded", "stopped", "error"]).default("stopped"),
  market_data_status: z.enum(["online", "waiting", "stale", "offline", "error"]).default("offline"),
  processed_signals: z.number(),
  exchanges: z.array(z.string()).default([]),
  symbols: z.array(z.string()).default([]),
  scan_pairs: z.array(z.string()).default([]),
  scanner_pairs_count: z.number().default(0),
  scanner_universe_source: z.string().default("default"),
  scanner_universe_warning: z.string().nullable().optional(),
  estimated_strategy_checks: z.number().default(0),
  max_scanner_pairs: z.number().nullable().optional(),
  timeframes: z.array(z.string()).default([]),
  strategies: z.array(z.string()).default([]),
  ticks_processed: z.number().default(0),
  candles_updated: z.number().default(0),
  features_built: z.number().default(0),
  strategy_evaluations: z.number().default(0),
  signals_found: z.number().default(0),
  candles_seeded: z.number().default(0),
  warmup_total: z.number().default(0),
  warmup_completed: z.number().default(0),
  warmup_failed: z.number().default(0),
  warmup_started_at: z.number().nullable().optional(),
  warmup_finished_at: z.number().nullable().optional(),
  last_tick_at: z.number().nullable().optional(),
  last_tick_age_seconds: z.number().nullable().optional(),
  last_signal_at: z.number().nullable().optional(),
  last_exchange: z.string().nullable().optional(),
  last_symbol: z.string().nullable().optional(),
  last_price: z.number().nullable().optional(),
  last_error: z.string().nullable().optional(),
  market_stream_connected: z.boolean().default(false),
  ws_connected: z.boolean().default(false),
  candle_history: z.record(z.string(), z.number()).default({})
});
