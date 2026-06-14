import type {
  AccountRiskSnapshot,
  AlertRule,
  BillingPlan,
  ExchangeCatalog,
  ExchangeConnection,
  ExchangeConnectionStatus,
  ExchangeFeeRate,
  ExchangeWalletBalance,
  ExchangeWalletCoinBalance,
  MarketPairOption,
  MarketUniversePair,
  NotificationDelivery,
  PositionRiskSummary,
  PersistedNotification,
  RadarDisplayMode,
  RRGuardMode,
  RiskAmountMode,
  StrategyConfig,
  SubscriptionState,
  SubscriptionStatus,
  SubscriptionTier,
  UserProfile,
  Watchlist
} from "@/features/server-state/types";
import type {
  CandleResponse,
  DecisionReason,
  DecisionReasonScope,
  DecisionReasonSeverity,
  DecisionReasonSource,
  ExecutionGateStatus,
  ExecutionQualityGate,
  HealthStatus,
  ImpactRisk,
  LifecycleTrace,
  LiquidityMetrics,
  MarketDataStatus,
  NoTradeFilterResult,
  OhlcvCandle,
  PendingEntryIntent,
  RadarConfig,
  RadarSignal,
  RadarSummary,
  RadarStatus,
  SignalEdgeSnapshot,
  SignalDecisionSnapshot,
  SignalLayerCheck,
  TradeJournalEntry,
  TradeJournalResponse,
  VirtualAccount,
  VirtualExecutionReport,
  VirtualExecutionProfile,
  VirtualExecutionStatus,
  VirtualFillPolicy,
  VirtualFillStatus,
  BreakevenPlan,
  FuturesRiskPlan,
  PositionSizingResult,
  RiskAdjustmentPlan,
  RiskCheckResult,
  RiskCheckStatus,
  RiskDecision,
  RadarRiskRewardStatus,
  SignalActionState,
  SignalExecutionGateSnapshot,
  RiskPreviewResponse,
  RiskStateResponse,
  SignalStatus,
  StopLossPlan,
  TakeProfitPlan,
  TradeCloseReason,
  TradeMode,
  TradeOrigin,
  TradePlan,
  TradeSource,
  TrailingStopPlan,
  VirtualTradeLifecycleEvent,
  VirtualTradeTargetState,
  VirtualSimulationMode,
  VirtualSimulationTier,
  VirtualSimulatedPositionPath
} from "@/types";
import { z } from "zod";
import { DEV_FALLBACK_USER_ID } from "@/auth/current-user";
import { SIGNAL_STATUSES } from "@/domain/signal-status";
import { isActiveTradeStatus, isTerminalTradeStatus } from "@/domain/trade-status";
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
  | "pending_entry_intent_id"
  | "accepted_trade_plan_hash"
  | "trigger_source"
  | "origin"
  | "lifecycle_trace"
  | "source"
  | "view"
  | "tags"
  | "run_id"
  | "initial_quantity"
  | "remaining_quantity"
  | "closed_quantity"
  | "initial_size_usd"
  | "remaining_size_usd"
  | "current_stop_loss"
  | "stop_moved_to_breakeven"
  | "trailing_active"
  | "trailing_distance"
  | "highest_price_after_trailing"
  | "lowest_price_after_trailing"
  | "realized_pnl"
  | "unrealized_pnl"
  | "exit_fees"
  | "target_states"
  | "lifecycle_events"
>>;

type VirtualAccountDto = Partial<VirtualAccount>;

export class ApiContractError extends Error {
  constructor(contractName: string, details: string) {
    super(`API contract error: ${contractName} ${details}`);
    this.name = "ApiContractError";
  }
}

const metadataSchema = z.record(z.string(), z.unknown());
const viewToneSchema = z.enum(["green", "red", "yellow", "blue", "purple", "neutral"]);
const signalActionKindSchema = z.enum([
  "enter_now",
  "arm_pending_entry",
  "cancel_pending_entry",
  "reconfirm_pending_entry"
]);
const signalActionBlockerSchema = z.object({
  code: z.string().min(1),
  reason_code: z.string().nullable().optional(),
  severity: z.enum(["blocker", "warning", "info"]),
  message: z.string().nullable(),
  display_label: z.string().nullable(),
  metadata: metadataSchema
}).passthrough();
const signalActionStateSchema = z.object({
  can_enter_now: z.boolean(),
  can_arm_pending: z.boolean(),
  can_reconfirm: z.boolean(),
  can_cancel: z.boolean(),
  mode: z.enum(["virtual", "real"]),
  environment: z.string().min(1),
  primary_action: signalActionKindSchema.nullable(),
  disabled_reason_code: z.string().nullable(),
  blockers: z.array(signalActionBlockerSchema),
  warnings: z.array(signalActionBlockerSchema),
  accepted_trade_plan_snapshot: metadataSchema.nullable(),
  display_labels: z.record(z.string(), z.string())
}).passthrough();

const pendingEntryIntentSchema = z.object({
  id: z.string().min(1),
  user_id: z.string().min(1),
  signal_id: z.string().min(1),
  strategy_id: z.string().nullable().optional(),
  mode: z.enum(["virtual", "real"]),
  status: z.enum(["pending", "triggered", "filling", "filled", "failed", "cancelled", "expired", "requires_reconfirmation"]),
  exchange: z.string().min(1),
  symbol: z.string().min(1),
  side: z.enum(["long", "short"]),
  entry_min: z.coerce.number(),
  entry_max: z.coerce.number(),
  entry_price_policy: z.string().min(1),
  stop_loss: z.coerce.number(),
  targets_snapshot: z.union([metadataSchema, z.array(z.unknown())]),
  accepted_trade_plan_snapshot: metadataSchema,
  accepted_trade_plan_hash: z.string().min(1),
  accepted_signal_status: z.string().min(1),
  accepted_signal_version: z.string().nullable().optional(),
  accepted_signal_fingerprint: z.string().nullable().optional(),
  execution_profile_snapshot: metadataSchema,
  request_snapshot: metadataSchema,
  idempotency_key: z.string().min(1),
  expires_at: z.string().nullable().optional(),
  created_at: z.string().min(1),
  updated_at: z.string().min(1),
  triggered_at: z.string().nullable().optional(),
  filled_at: z.string().nullable().optional(),
  filled_trade_id: z.string().nullable().optional(),
  failure_reason: z.string().nullable().optional(),
  technical_message: z.string().nullable().optional(),
  current_price: z.coerce.number().nullable().optional(),
  reason_code: z.string().nullable().optional(),
  localized_reason: z.string().nullable().optional(),
  view: z.object({
    status_label: z.string(),
    status_tone: z.enum(["green", "red", "yellow", "blue", "purple", "neutral"]),
    reason_code: z.string().nullable(),
    reason: z.string(),
    technical_message: z.string().nullable().optional(),
    entry_zone: z.string(),
    current_price: z.coerce.number().nullable()
  }).nullable().optional()
}).passthrough();

const radarSummarySchema = z.object({
  total_signals: z.number(),
  hot_signals: z.number().default(0),
  armable_signals: z.number().default(0),
  execution_ready_signals: z.number(),
  watchlist_signals: z.number().optional(),
  market_ideas: z.number().optional(),
  high_confidence_signals: z.number(),
  positive_edge_signals: z.number(),
  blocked_diagnostics: z.number().default(0),
  blocked_ideas: z.number()
}).passthrough();

const signalBadgeViewSchema = z.object({
  code: z.string().min(1),
  label: z.string(),
  tone: viewToneSchema
}).passthrough();

const signalTargetViewSchema = z.object({
  label: z.string().min(1),
  price: z.number().nullable(),
  r_multiple: z.number().nullable(),
  action: z.string().nullable()
}).passthrough();

const signalTradePlanViewSchema = z.object({
  has_trade_plan: z.boolean(),
  entry_type: z.string(),
  entry_zone: z.string(),
  entry_price: z.number().nullable(),
  stop_loss: z.number().nullable(),
  targets: z.array(signalTargetViewSchema),
  selected_rr: z.number().nullable(),
  selected_rr_target: z.string().nullable(),
  min_rr: z.number().nullable(),
  trade_plan_complete: z.boolean().nullable(),
  fallback_used: z.boolean(),
  missing: z.array(z.string()),
  invalidation: z.string()
}).passthrough();

const signalCardViewSchema = z.object({
  status_label: z.string(),
  status_tone: viewToneSchema,
  opportunity_label: z.string(),
  opportunity_tone: viewToneSchema,
  risk_label: z.string(),
  risk_meta: z.string(),
  badges: z.array(signalBadgeViewSchema),
  entry_label: z.string(),
  entry_value: z.string(),
  stop_loss: z.number().nullable(),
  targets: z.array(signalTargetViewSchema),
  selected_rr: z.number().nullable(),
  reason: z.string()
}).passthrough();

const signalExecutionGateReasonSchema = z.object({
  code: z.string(),
  severity: z.enum(["blocker", "warning", "info"]),
  source: z.string(),
  message: z.string(),
  metadata: z.record(z.string(), z.unknown()).default({})
}).passthrough();

const signalExecutionGateSchema = z.object({
  status: z.enum(["passed", "warning", "blocked"]),
  feed_kind: z.enum(["market_idea", "watchlist", "execution_signal", "blocked"]),
  can_notify: z.boolean(),
  can_enter_now: z.boolean(),
  can_arm_pending: z.boolean(),
  can_arm_virtual_pending: z.boolean().optional(),
  can_arm_real_pending: z.boolean().optional(),
  can_show_in_execution_feed: z.boolean(),
  reasons: z.array(signalExecutionGateReasonSchema).default([]),
  warnings: z.array(signalExecutionGateReasonSchema).default([]),
  metadata: z.record(z.string(), z.unknown()).default({})
}).passthrough();

const signalDetailsPrimaryStatusSchema = z.enum([
  "execution_ready",
  "waiting_entry",
  "requires_reconfirmation",
  "blocked",
  "watchlist",
  "cancelled",
  "expired",
  "unknown"
]);

const signalDetailsBlockerSchema = z.object({
  code: z.string().min(1),
  severity: z.enum(["blocker", "warning", "info"]),
  category: z.enum(["entry", "risk", "market_data", "liquidity", "execution", "technical"]),
  user_message: z.string(),
  debug_messages: z.array(z.string())
}).passthrough();

const signalDetailsRiskSummarySchema = z.object({
  label: z.string(),
  risk_failed: z.boolean(),
  risk_reward_blocked: z.boolean(),
  risk_reward_warning: z.string().nullable(),
  forming_candle: z.boolean(),
  open_candle_allowed: z.boolean(),
  forming_reason: z.string().nullable(),
  status_allows_trade: z.boolean(),
  trade_plan_complete: z.boolean(),
  risk_reward_ok: z.boolean(),
  is_market_opportunity: z.boolean()
}).passthrough();

const signalDetailsExecutionSummarySchema = z.object({
  preview_available: z.boolean(),
  risk_check_status: z.string().nullable(),
  risk_decision_status: z.string().nullable(),
  can_enter: z.boolean().nullable(),
  quality_gate_status: z.string().nullable(),
  impact_risk: z.string().nullable(),
  status_allows_trade: z.boolean()
}).passthrough();

const signalDetailsViewSchema = z.object({
  title: z.string(),
  side: z.enum(["long", "short"]),
  primary_status: signalDetailsPrimaryStatusSchema,
  primary_status_label: z.string(),
  primary_status_tone: viewToneSchema,
  primary_action_label: z.string(),
  recommended_action_text: z.string(),
  can_enter_now: z.boolean().nullable(),
  trade_plan: signalTradePlanViewSchema,
  risk_summary: signalDetailsRiskSummarySchema,
  execution_summary: signalDetailsExecutionSummarySchema,
  top_reasons: z.array(z.string()),
  top_blockers: z.array(signalDetailsBlockerSchema),
  warnings: z.array(signalDetailsBlockerSchema)
}).passthrough();

const tradeViewSchema = z.object({
  status_label: z.string(),
  status_tone: viewToneSchema,
  source_label: z.string(),
  pnl: z.object({
    realized_pnl: z.number(),
    unrealized_pnl: z.number(),
    total_pnl: z.number().nullable(),
    pnl_percent: z.number().nullable(),
    tone: viewToneSchema
  }).passthrough()
}).passthrough();

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
    first_target_rr: enriched.first_target_rr ?? null,
    final_target_rr: enriched.final_target_rr ?? null,
    selected_rr: enriched.selected_rr ?? null,
    selected_rr_target: enriched.selected_rr_target ?? null,
    min_rr_ratio: enriched.min_rr_ratio ?? null,
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
    trade_plan: normalizeTradePlan(enriched.trade_plan),
    auto_entry: null,
    edge: normalizeSignalEdge(enriched.edge),
    no_trade_filter: normalizeNoTradeFilter(enriched.no_trade_filter),
    decision: normalizeDecisionSnapshot(enriched.decision),
    execution_gate: normalizeSignalExecutionGate(enriched.execution_gate),
    rr_status: normalizeRadarRiskRewardStatus(enriched.rr_status),
    risk_gate_status: normalizeOptionalRiskCheckStatus(enriched.risk_gate_status),
    can_enter: optionalBoolean(enriched.can_enter),
    display_reason: optionalString(enriched.display_reason),
    card_view: normalizeSignalCardView(enriched.card_view),
    details_view: normalizeSignalDetailsView(enriched.details_view),
    confirmed_trade_id: signal.confirmed_trade_id ?? null
  };
}

export function normalizePendingEntryIntent(value: unknown): PendingEntryIntent {
  const intent = parseContract(pendingEntryIntentSchema, value, "PendingEntryIntent");
  return {
    id: intent.id,
    user_id: intent.user_id,
    signal_id: intent.signal_id,
    strategy_id: optionalString(intent.strategy_id),
    mode: intent.mode,
    status: intent.status,
    exchange: intent.exchange,
    symbol: intent.symbol,
    side: intent.side,
    entry_min: intent.entry_min,
    entry_max: intent.entry_max,
    entry_price_policy: intent.entry_price_policy,
    stop_loss: intent.stop_loss,
    targets_snapshot: normalizeTargetsSnapshot(intent.targets_snapshot),
    accepted_trade_plan_snapshot: normalizeMetadata(intent.accepted_trade_plan_snapshot),
    accepted_trade_plan_hash: intent.accepted_trade_plan_hash,
    accepted_signal_status: normalizeSignalStatus(intent.accepted_signal_status),
    accepted_signal_version: optionalString(intent.accepted_signal_version),
    accepted_signal_fingerprint: optionalString(intent.accepted_signal_fingerprint),
    execution_profile_snapshot: normalizeMetadata(intent.execution_profile_snapshot),
    request_snapshot: normalizeMetadata(intent.request_snapshot),
    idempotency_key: intent.idempotency_key,
    expires_at: optionalString(intent.expires_at),
    created_at: intent.created_at,
    updated_at: intent.updated_at,
    triggered_at: optionalString(intent.triggered_at),
    filled_at: optionalString(intent.filled_at),
    filled_trade_id: optionalString(intent.filled_trade_id),
    failure_reason: optionalString(intent.failure_reason),
    technical_message: optionalString(intent.technical_message),
    current_price: optionalNumber(intent.current_price),
    reason_code: optionalString(intent.reason_code),
    localized_reason: optionalString(intent.localized_reason),
    view: intent.view
      ? {
          status_label: intent.view.status_label,
          status_tone: intent.view.status_tone,
          reason_code: intent.view.reason_code,
          reason: intent.view.reason,
          technical_message: optionalString(intent.view.technical_message),
          entry_zone: intent.view.entry_zone,
          current_price: optionalNumber(intent.view.current_price)
        }
      : null
  };
}

export function normalizeTrade(trade: TradeJournalEntryDto): TradeJournalEntry {
  const enriched = trade as TradeJournalEntryExtra;
  const takeProfit = trade.take_profit ?? [];
  const initialQuantity = enriched.initial_quantity ?? trade.quantity;
  const terminal = isTerminalTradeStatus(trade.status);
  const active = isActiveTradeStatus(trade.status);
  const remainingQuantity = enriched.remaining_quantity ?? (terminal ? 0 : trade.quantity);
  const closedQuantity = enriched.closed_quantity ?? Math.max(initialQuantity - remainingQuantity, 0);
  const initialSizeUsd = enriched.initial_size_usd ?? trade.size_usd;
  const remainingSizeUsd = enriched.remaining_size_usd ?? (terminal ? 0 : trade.size_usd);
  const realizedPnl = enriched.realized_pnl ?? (terminal ? trade.pnl ?? 0 : 0);
  const unrealizedPnl = enriched.unrealized_pnl ?? (active ? trade.pnl ?? 0 : 0);
  const origin = normalizeTradeOrigin(enriched.origin);
  return {
    id: trade.id,
    user_id: trade.user_id,
    signal_id: trade.signal_id ?? null,
    pending_entry_intent_id: optionalString(enriched.pending_entry_intent_id) ?? origin?.pending_entry_intent_id ?? null,
    accepted_trade_plan_hash: optionalString(enriched.accepted_trade_plan_hash) ?? origin?.accepted_trade_plan_hash ?? null,
    trigger_source: optionalString(enriched.trigger_source) ?? origin?.trigger_source ?? null,
    origin,
    mode: trade.mode,
    source: normalizeTradeSource(enriched.source, trade.mode),
    tags: normalizeStringList(enriched.tags),
    run_id: enriched.run_id ?? null,
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
    initial_quantity: initialQuantity,
    remaining_quantity: remainingQuantity,
    closed_quantity: closedQuantity,
    initial_size_usd: initialSizeUsd,
    remaining_size_usd: remainingSizeUsd,
    leverage: trade.leverage,
    risk_percent: trade.risk_percent,
    risk_amount: enriched.risk_amount ?? 0,
    risk_reward: enriched.risk_reward ?? 3,
    stop_loss: trade.stop_loss,
    current_stop_loss: enriched.current_stop_loss ?? trade.stop_loss,
    stop_moved_to_breakeven: enriched.stop_moved_to_breakeven ?? false,
    trailing_active: enriched.trailing_active ?? false,
    trailing_distance: enriched.trailing_distance ?? null,
    highest_price_after_trailing: enriched.highest_price_after_trailing ?? null,
    lowest_price_after_trailing: enriched.lowest_price_after_trailing ?? null,
    take_profit: takeProfit,
    fees: trade.fees,
    realized_pnl: realizedPnl,
    unrealized_pnl: unrealizedPnl,
    exit_fees: enriched.exit_fees ?? 0,
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
    closed_at: trade.closed_at ?? null,
    target_states: normalizeTargetStates(enriched.target_states, takeProfit, trade),
    lifecycle_events: normalizeLifecycleEvents(enriched.lifecycle_events),
    lifecycle_trace: normalizeLifecycleTrace(enriched.lifecycle_trace),
    view: normalizeTradeView(enriched.view)
  };
}

export function normalizeSignalActionState(value: unknown): SignalActionState {
  const state = parseContract(signalActionStateSchema, value, "SignalActionState");
  return {
    can_enter_now: state.can_enter_now,
    can_arm_pending: state.can_arm_pending,
    can_reconfirm: state.can_reconfirm,
    can_cancel: state.can_cancel,
    mode: state.mode,
    environment: state.environment,
    primary_action: state.primary_action,
    disabled_reason_code: state.disabled_reason_code,
    blockers: state.blockers.map((item) => ({
      code: item.code,
      reason_code: item.reason_code ?? item.code,
      severity: item.severity,
      message: item.message,
      display_label: item.display_label,
      metadata: { ...item.metadata }
    })),
    warnings: state.warnings.map((item) => ({
      code: item.code,
      reason_code: item.reason_code ?? item.code,
      severity: item.severity,
      message: item.message,
      display_label: item.display_label,
      metadata: { ...item.metadata }
    })),
    accepted_trade_plan_snapshot: state.accepted_trade_plan_snapshot ? { ...state.accepted_trade_plan_snapshot } : null,
    display_labels: { ...state.display_labels }
  };
}

export function normalizeRadarSummary(value: unknown): RadarSummary {
  return parseContract(radarSummarySchema, value, "RadarSummary");
}

function normalizeSignalCardView(value: unknown): RadarSignal["card_view"] {
  if (!isRecord(value)) return null;
  return parseContract(signalCardViewSchema, value, "SignalCardView");
}

function normalizeSignalDetailsView(value: unknown): RadarSignal["details_view"] {
  if (!isRecord(value)) return null;
  return parseContract(signalDetailsViewSchema, value, "SignalDetailsView");
}

function normalizeSignalTradePlanView(value: unknown): NonNullable<RadarSignal["details_view"]>["trade_plan"] {
  return parseContract(signalTradePlanViewSchema, value, "SignalTradePlanView");
}

function normalizeSignalTargetViews(value: unknown): NonNullable<RadarSignal["card_view"]>["targets"] {
  return parseContract(z.array(signalTargetViewSchema), value, "SignalTargetView[]");
}

function normalizeDetailsRiskSummary(value: unknown): NonNullable<RadarSignal["details_view"]>["risk_summary"] {
  return parseContract(signalDetailsRiskSummarySchema, value, "SignalDetailsRiskSummary");
}

function normalizeDetailsExecutionSummary(value: unknown): NonNullable<RadarSignal["details_view"]>["execution_summary"] {
  return parseContract(signalDetailsExecutionSummarySchema, value, "SignalDetailsExecutionSummary");
}

function normalizeDetailsBlockers(value: unknown): NonNullable<RadarSignal["details_view"]>["top_blockers"] {
  return parseContract(z.array(signalDetailsBlockerSchema), value, "SignalDetailsBlocker[]");
}

function normalizeTradeView(value: unknown): TradeJournalEntry["view"] {
  if (!isRecord(value)) return null;
  return parseContract(tradeViewSchema, value, "TradeView");
}

function normalizeTradePlan(value: unknown): TradePlan | null {
  if (!isRecord(value)) return null;
  const entry = isRecord(value.entry) ? value.entry : {};
  const invalidation = isRecord(value.invalidation) ? value.invalidation : null;
  const riskRules = isRecord(value.risk_rules) ? value.risk_rules : {};
  return {
    version: "v1",
    entry: {
      price: optionalNumber(entry.price),
      min_price: optionalNumber(entry.min_price),
      max_price: optionalNumber(entry.max_price),
      source: String(entry.source ?? "legacy_fields"),
      metadata: normalizeMetadata(entry.metadata)
    },
    stop_loss: optionalNumber(value.stop_loss),
    targets: Array.isArray(value.targets)
      ? value.targets.filter(isRecord).map((target) => ({
          label: String(target.label ?? "TP"),
          price: optionalNumber(target.price),
          r_multiple: optionalNumber(target.r_multiple),
          action: optionalString(target.action),
          close_percent: normalizeClosePercent(target.close_percent),
          source: optionalString(target.source),
          metadata: normalizeMetadata(target.metadata)
        }))
      : [],
    invalidation: invalidation
      ? {
          price: optionalNumber(invalidation.price),
          hard_stop: optionalNumber(invalidation.hard_stop),
          conditions: Array.isArray(invalidation.conditions) ? invalidation.conditions.map(String) : [],
          metadata: normalizeMetadata(invalidation.metadata)
        }
      : null,
    risk_rules: {
      risk_reward: optionalNumber(riskRules.risk_reward),
      first_target_rr: optionalNumber(riskRules.first_target_rr),
      final_target_rr: optionalNumber(riskRules.final_target_rr),
      selected_rr: optionalNumber(riskRules.selected_rr),
      selected_rr_target: optionalString(riskRules.selected_rr_target),
      min_rr_ratio: optionalNumber(riskRules.min_rr_ratio),
      metadata: normalizeMetadata(riskRules.metadata)
    },
    metadata: normalizeMetadata(value.metadata)
  };
}

function normalizeSignalEdge(value: unknown): SignalEdgeSnapshot | null {
  if (!isRecord(value)) return null;
  return {
    status: normalizeEdgeStatus(value.status),
    sample_size: Number(value.sample_size ?? 0),
    min_sample_size: Number(value.min_sample_size ?? 0),
    winrate: optionalNumber(value.winrate),
    avg_win_r: optionalNumber(value.avg_win_r),
    avg_loss_r: optionalNumber(value.avg_loss_r),
    expectancy_r: optionalNumber(value.expectancy_r),
    expectancy_after_costs_r: optionalNumber(value.expectancy_after_costs_r),
    profit_factor: optionalNumber(value.profit_factor),
    confidence_score: Number(value.confidence_score ?? 0),
    source: normalizeEdgeSource(value.source),
    score_bucket: optionalString(value.score_bucket),
    metadata: normalizeMetadata(value.metadata)
  };
}

function normalizeNoTradeFilter(value: unknown): NoTradeFilterResult | null {
  if (!isRecord(value)) return null;
  return {
    enabled: Boolean(value.enabled ?? true),
    blocked: Boolean(value.blocked ?? false),
    hard_block: Boolean(value.hard_block ?? false),
    blockers: Array.isArray(value.blockers) ? value.blockers.map(String) : [],
    warnings: Array.isArray(value.warnings) ? value.warnings.map(String) : [],
    checks: normalizeLayerChecks(value.checks),
    metadata: normalizeMetadata(value.metadata)
  };
}

function normalizeSignalExecutionGate(value: unknown): SignalExecutionGateSnapshot | null {
  if (value == null) return null;
  return parseContract(signalExecutionGateSchema, value, "SignalExecutionGateSnapshot");
}

function normalizeDecisionSnapshot(value: unknown): SignalDecisionSnapshot | null {
  if (!isRecord(value)) return null;
  return {
    setup_valid: Boolean(value.setup_valid ?? false),
    trade_plan_valid: Boolean(value.trade_plan_valid ?? false),
    market_context_score: Number(value.market_context_score ?? 0),
    signal_actionable: Boolean(value.signal_actionable ?? false),
    execution_allowed_virtual: optionalBoolean(value.execution_allowed_virtual),
    execution_allowed_real: optionalBoolean(value.execution_allowed_real),
    blockers: normalizeDecisionReasons(value.blockers),
    warnings: normalizeDecisionReasons(value.warnings)
  };
}

function normalizeDecisionReasons(value: unknown): DecisionReason[] {
  if (!Array.isArray(value)) return [];
  return value.filter(isRecord).map((reason) => ({
    code: String(reason.code ?? "decision_reason"),
    message: String(reason.message ?? reason.code ?? "Decision reason"),
    source: normalizeDecisionReasonSource(reason.source),
    severity: normalizeDecisionReasonSeverity(reason.severity),
    scope: normalizeDecisionReasonScope(reason.scope),
    metadata: normalizeMetadata(reason.metadata)
  }));
}

function normalizeLayerChecks(value: unknown): SignalLayerCheck[] {
  if (!Array.isArray(value)) return [];
  return value.filter(isRecord).map((check) => ({
    name: String(check.name ?? "check"),
    status: check.status === "warning" || check.status === "failed" || check.status === "skipped" ? check.status : "passed",
    score: optionalNumber(check.score),
    reason: optionalString(check.reason),
    metadata: normalizeMetadata(check.metadata)
  }));
}

function normalizeTargetStates(
  value: unknown,
  takeProfit: number[],
  trade: TradeJournalEntryDto
): VirtualTradeTargetState[] {
  if (Array.isArray(value) && value.length) {
    return value.filter(isRecord).map((target) => ({
      label: String(target.label ?? "TP"),
      price: Number(target.price ?? 0),
      close_percent: Number(target.close_percent ?? 0),
      action: optionalString(target.action),
      hit: Boolean(target.hit ?? false),
      hit_at: optionalString(target.hit_at),
      closed_quantity: Number(target.closed_quantity ?? 0),
      closed_size_usd: Number(target.closed_size_usd ?? 0),
      realized_pnl: Number(target.realized_pnl ?? 0),
      exit_fee: Number(target.exit_fee ?? 0)
    }));
  }
  if (!takeProfit.length) return [];
  const finalPrice = takeProfit[takeProfit.length - 1];
  const terminal = isTerminalTradeStatus(trade.status);
  const takeProfitClosed = trade.status === "closed" && trade.close_reason === "take_profit";
  return [
    {
      label: "Final",
      price: finalPrice,
      close_percent: 100,
      action: "full_close",
      hit: takeProfitClosed,
      hit_at: takeProfitClosed ? trade.closed_at ?? null : null,
      closed_quantity: terminal ? trade.quantity : 0,
      closed_size_usd: terminal ? trade.size_usd : 0,
      realized_pnl: terminal ? trade.pnl ?? 0 : 0,
      exit_fee: 0
    }
  ];
}

function normalizeTradeOrigin(value: unknown): TradeOrigin | null {
  if (!isRecord(value)) return null;
  return {
    signal_id: optionalString(value.signal_id),
    pending_entry_intent_id: optionalString(value.pending_entry_intent_id),
    strategy: optionalString(value.strategy),
    mode: normalizeTradeMode(value.mode),
    accepted_trade_plan_hash: optionalString(value.accepted_trade_plan_hash),
    trigger_source: optionalString(value.trigger_source),
    virtual_order_id: optionalString(value.virtual_order_id),
    virtual_trade_id: optionalString(value.virtual_trade_id),
    position_id: optionalString(value.position_id)
  };
}

function normalizeLifecycleTrace(value: unknown): LifecycleTrace {
  const trace = isRecord(value) ? value : {};
  return {
    signal_id: optionalString(trace.signal_id),
    pending_entry_intent_id: optionalString(trace.pending_entry_intent_id),
    risk_decision_id: optionalString(trace.risk_decision_id),
    audit_id: optionalString(trace.audit_id),
    virtual_trade_id: optionalString(trace.virtual_trade_id),
    real_order_id: optionalString(trace.real_order_id),
    exit_event_id: optionalString(trace.exit_event_id)
  };
}

function normalizeLifecycleEvents(value: unknown): VirtualTradeLifecycleEvent[] {
  if (!Array.isArray(value)) return [];
  return value.filter(isRecord).map((event) => ({
    signal_id: optionalString(event.signal_id),
    pending_entry_intent_id: optionalString(event.pending_entry_intent_id),
    risk_decision_id: optionalString(event.risk_decision_id),
    virtual_trade_id: optionalString(event.virtual_trade_id),
    real_order_id: optionalString(event.real_order_id),
    exit_event_id: optionalString(event.exit_event_id),
    event_type: String(event.event_type ?? "event"),
    reason: normalizeTradeCloseReason(event.reason),
    target_label: optionalString(event.target_label),
    price: optionalNumber(event.price),
    quantity: optionalNumber(event.quantity),
    size_usd: optionalNumber(event.size_usd),
    realized_pnl: optionalNumber(event.realized_pnl),
    exit_fee: optionalNumber(event.exit_fee),
    stop_loss: optionalNumber(event.stop_loss),
    created_at: String(event.created_at ?? new Date().toISOString()),
    lifecycle_trace: normalizeLifecycleTrace(event.lifecycle_trace),
    metadata: normalizeMetadata(event.metadata)
  }));
}

export function normalizeExecutionReport(value: unknown): VirtualExecutionReport | null {
  if (!isRecord(value)) return null;
  const liquidity = isRecord(value.liquidity) ? value.liquidity : {};
  return {
    mode: normalizeSimulationMode(value.mode),
    simulation_tier: normalizeSimulationTier(value.simulation_tier),
    active_capabilities: Array.isArray(value.active_capabilities) ? value.active_capabilities.map(String) : [],
    planned_capabilities: Array.isArray(value.planned_capabilities) ? value.planned_capabilities.map(String) : [],
    execution_profile: normalizeVirtualExecutionProfile(value.execution_profile),
    fill_policy: normalizeVirtualFillPolicy(value.fill_policy),
    status: normalizeExecutionStatus(value.status),
    requested_size_usd: Number(value.requested_size_usd ?? 0),
    filled_size_usd: Number(value.filled_size_usd ?? 0),
    unfilled_size_usd: Number(value.unfilled_size_usd ?? 0),
    fill_ratio: Number(value.fill_ratio ?? 1),
    reference_price: Number(value.reference_price ?? 0),
    average_price: value.average_price == null ? null : Number(value.average_price),
    estimated_fill_price: value.estimated_fill_price == null ? null : Number(value.estimated_fill_price),
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
    fill_result: normalizeFillResult(value.fill_result),
    raw_inputs_snapshot: normalizeMetadata(value.raw_inputs_snapshot),
    rejected_reason: value.rejected_reason == null ? null : String(value.rejected_reason),
    technical_message: value.technical_message == null ? null : String(value.technical_message),
    technical_messages: normalizeStringList(value.technical_messages),
    warnings: normalizeStringList(value.warnings),
    blockers: normalizeStringList(value.blockers),
    reason_code: value.reason_code == null ? null : String(value.reason_code),
    reason_codes: normalizeStringList(value.reason_codes),
    notes: Array.isArray(value.notes) ? value.notes.map(String) : []
  };
}

function normalizeFillResult(value: unknown): VirtualExecutionReport["fill_result"] {
  if (!isRecord(value)) return null;
  return {
    status: normalizeFillStatus(value.status),
    requested_notional: Number(value.requested_notional ?? 0),
    filled_notional: Number(value.filled_notional ?? 0),
    avg_fill_price: value.avg_fill_price == null ? null : Number(value.avg_fill_price),
    estimated_slippage_bps: Number(value.estimated_slippage_bps ?? 0),
    spread_bps: Number(value.spread_bps ?? 0),
    market_impact_bps: Number(value.market_impact_bps ?? 0),
    reason: value.reason == null ? null : String(value.reason),
    reason_code: value.reason_code == null ? null : String(value.reason_code),
    technical_message: value.technical_message == null ? null : String(value.technical_message),
    warnings: Array.isArray(value.warnings) ? value.warnings.map(String) : [],
    raw_inputs_snapshot: normalizeMetadata(value.raw_inputs_snapshot)
  };
}

function normalizePositionSizing(value: unknown): PositionSizingResult | null {
  if (!isRecord(value)) return null;
  return {
    side: value.side === "short" ? "short" : "long",
    account_equity: Number(value.account_equity ?? 0),
    risk_mode: normalizeRiskAmountMode(value.risk_mode),
    fixed_risk_amount: value.fixed_risk_amount == null ? null : Number(value.fixed_risk_amount),
    requested_risk_amount: value.requested_risk_amount == null ? null : Number(value.requested_risk_amount),
    effective_risk_amount: value.effective_risk_amount == null ? null : Number(value.effective_risk_amount),
    risk_amount_capped: Boolean(value.risk_amount_capped ?? false),
    risk_cap_amount: value.risk_cap_amount == null ? null : Number(value.risk_cap_amount),
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
    risk_mode: normalizeRiskAmountMode(value.risk_mode),
    fixed_risk_amount: value.fixed_risk_amount == null ? null : Number(value.fixed_risk_amount),
    requested_risk_amount: Number(value.requested_risk_amount ?? value.base_risk_amount ?? 0),
    effective_risk_amount: Number(value.effective_risk_amount ?? value.adjusted_risk_amount ?? 0),
    risk_amount_capped: Boolean(value.risk_amount_capped ?? false),
    risk_cap_amount: value.risk_cap_amount == null ? null : Number(value.risk_cap_amount),
    risk_cap_percent: value.risk_cap_percent == null ? null : Number(value.risk_cap_percent),
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
    reason_code: value.reason_code == null ? null : String(value.reason_code),
    reason_codes: normalizeStringList(value.reason_codes),
    technical_message: value.technical_message == null ? null : String(value.technical_message),
    technical_messages: normalizeStringList(value.technical_messages),
    rr: value.rr == null ? null : Number(value.rr),
    min_rr_ratio: Number(value.min_rr_ratio ?? 0),
    risk_reward_guard_mode: normalizeRRGuardMode(value.risk_reward_guard_mode, "soft"),
    risk_reward_warning: Boolean(value.risk_reward_warning ?? false),
    risk_reward_warning_reason: value.risk_reward_warning_reason == null ? null : String(value.risk_reward_warning_reason),
    risk_reward_blocked: Boolean(value.risk_reward_blocked ?? false),
    risk_reward_block_reason: value.risk_reward_block_reason == null ? null : String(value.risk_reward_block_reason),
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
    max_orderbook_liquidity_ratio: Number(value.max_orderbook_liquidity_ratio ?? 1),
    orderbook_source: value.orderbook_source == null ? null : String(value.orderbook_source),
    orderbook_freshness_status: normalizeMarketDataStatus(value.orderbook_freshness_status),
    orderbook_fetched_at: value.orderbook_fetched_at == null ? null : String(value.orderbook_fetched_at),
    orderbook_age_seconds: value.orderbook_age_seconds == null ? null : Number(value.orderbook_age_seconds),
    orderbook_depth_levels: Number(value.orderbook_depth_levels ?? 0),
    orderbook_vwap_price: value.orderbook_vwap_price == null ? null : Number(value.orderbook_vwap_price),
    orderbook_vwap_impact_bps: value.orderbook_vwap_impact_bps == null ? null : Number(value.orderbook_vwap_impact_bps),
    orderbook_slippage_bps: value.orderbook_slippage_bps == null ? null : Number(value.orderbook_slippage_bps),
    orderbook_fillable_notional_usd:
      value.orderbook_fillable_notional_usd == null ? null : Number(value.orderbook_fillable_notional_usd)
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
    risk_profile_source: String(value.risk_profile_source ?? "unknown"),
    execution_profile_sources: normalizeStringRecord(value.execution_profile_sources),
    blockers: Array.isArray(value.blockers) ? value.blockers.map(String) : [],
    warnings: Array.isArray(value.warnings) ? value.warnings.map(String) : [],
    reason_code: value.reason_code == null ? null : String(value.reason_code),
    reason_codes: normalizeStringList(value.reason_codes),
    technical_message: value.technical_message == null ? null : String(value.technical_message),
    technical_messages: normalizeStringList(value.technical_messages),
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
    user_id: String(value.user_id ?? DEV_FALLBACK_USER_ID),
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
    execution_profile: "realistic",
    fill_policy: "strict_orderbook",
    status: "filled",
    requested_size_usd: decision.requested_notional ?? sizing.notional,
    filled_size_usd: sizing.notional,
    unfilled_size_usd: 0,
    fill_ratio: 1,
    reference_price: sizing.entry_price,
    average_price: sizing.entry_price,
    estimated_fill_price: sizing.entry_price,
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
    fill_result: {
      status: status === "blocked" ? "blocked" : "filled",
      requested_notional: decision.requested_notional ?? sizing.notional,
      filled_notional: status === "blocked" ? 0 : sizing.notional,
      avg_fill_price: status === "blocked" ? null : sizing.entry_price,
      estimated_slippage_bps: sizing.slippage_bps,
      spread_bps: decision.risk_check.spread_bps ?? 0,
      market_impact_bps: decision.risk_check.orderbook_vwap_impact_bps ?? 0,
      reason: decision.status === "failed" ? decision.blockers.join("; ") : null,
      warnings: decision.warnings,
      raw_inputs_snapshot: {
        side: sizing.side,
        symbol: decision.symbol,
        exchange: decision.exchange,
        requested_notional: decision.requested_notional ?? sizing.notional,
        market_data_status: decision.risk_check.market_data_status,
        spread_bps: decision.risk_check.spread_bps ?? 0
      }
    },
    raw_inputs_snapshot: {
      side: sizing.side,
      symbol: decision.symbol,
      exchange: decision.exchange,
      requested_notional: decision.requested_notional ?? sizing.notional,
      market_data_status: decision.risk_check.market_data_status,
      spread_bps: decision.risk_check.spread_bps ?? 0
    },
    rejected_reason: decision.status === "failed" ? decision.blockers.join("; ") : null,
    warnings: decision.warnings,
    blockers: decision.blockers,
    reason_code: decision.status === "failed" ? (decision.blockers[0] ?? "risk_gate_blocked") : "filled",
    reason_codes: decision.status === "failed" ? decision.blockers : decision.warnings,
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
      : [],
    source: String(value.source ?? "risk_settings"),
    selected_rr: value.selected_rr == null ? null : Number(value.selected_rr),
    selected_rr_target: value.selected_rr_target == null ? null : String(value.selected_rr_target),
    notes: Array.isArray(value.notes) ? value.notes.map(String) : []
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

function normalizeVirtualExecutionProfile(value: unknown): VirtualExecutionProfile {
  if (value === "relaxed_paper" || value === "deterministic_test") return value;
  return "realistic";
}

function normalizeVirtualFillPolicy(value: unknown): VirtualFillPolicy {
  if (value === "relaxed_market_fallback" || value === "deterministic_market_fill") return value;
  return "strict_orderbook";
}

function normalizeExecutionStatus(value: unknown): VirtualExecutionStatus {
  if (value === "partially_filled" || value === "rejected_virtual_execution") return value;
  return "filled";
}

function normalizeFillStatus(value: unknown): VirtualFillStatus {
  if (value === "partial_filled" || value === "blocked" || value === "rejected") return value;
  return "filled";
}

function normalizeTradeSource(value: unknown, mode: TradeJournalEntry["mode"]): TradeSource {
  if (value === "virtual" || value === "real" || value === "backtest") return value;
  return mode === "real" ? "real" : "virtual";
}

function normalizeTradeMode(value: unknown): TradeMode {
  return value === "real" ? "real" : "virtual";
}

function normalizeStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}

function normalizeSignalStatus(value: unknown): SignalStatus {
  if (typeof value === "string" && (SIGNAL_STATUSES as readonly string[]).includes(value)) return value as SignalStatus;
  return "active";
}

function normalizePendingEntryStatus(value: unknown): PendingEntryIntent["status"] {
  if (
    value === "triggered" ||
    value === "filling" ||
    value === "filled" ||
    value === "failed" ||
    value === "cancelled" ||
    value === "expired" ||
    value === "requires_reconfirmation"
  ) {
    return value;
  }
  return "pending";
}

function normalizeTargetsSnapshot(value: unknown): PendingEntryIntent["targets_snapshot"] {
  if (Array.isArray(value)) {
    return value.filter(isRecord).map((target) => ({ ...target }));
  }
  return normalizeMetadata(value);
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
    user_id: value.user_id ?? DEV_FALLBACK_USER_ID,
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
    user_id: DEV_FALLBACK_USER_ID,
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

export function normalizeMarketUniversePair(value: unknown): MarketUniversePair {
  const pair = isRecord(value) ? value : {};
  return {
    ...normalizeMarketPair(value),
    category: nullableString(pair.category),
    market_type: nullableString(pair.market_type),
    turnover_24h: nullableDecimalString(pair.turnover_24h),
    volume_24h: nullableDecimalString(pair.volume_24h),
    last_price: nullableDecimalString(pair.last_price),
    mark_price: nullableDecimalString(pair.mark_price),
    bid_price: nullableDecimalString(pair.bid_price),
    ask_price: nullableDecimalString(pair.ask_price),
    spread_bps: nullableDecimalString(pair.spread_bps),
    funding_rate: nullableDecimalString(pair.funding_rate),
    liquidity_rank: optionalNumber(pair.liquidity_rank),
    liquidity_tier: nullableString(pair.liquidity_tier),
    synced_at: nullableString(pair.synced_at)
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
    user_id: String(watchlist.user_id ?? DEV_FALLBACK_USER_ID),
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
    user_id: String(config.user_id ?? DEV_FALLBACK_USER_ID),
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
    user_id: String(alert.user_id ?? DEV_FALLBACK_USER_ID),
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
    user_id: String(notification.user_id ?? DEV_FALLBACK_USER_ID),
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
    risk_mode: normalizeRiskAmountMode(settings.risk_mode),
    risk_per_trade_percent: Number(settings.risk_per_trade_percent ?? 1),
    fixed_risk_amount: settings.fixed_risk_amount == null ? null : Number(settings.fixed_risk_amount),
    fixed_risk_currency: String(settings.fixed_risk_currency ?? "USDT").trim().toUpperCase() || "USDT",
    radar_display_mode: normalizeRadarDisplayMode(settings.radar_display_mode),
    min_rr_ratio: Number(settings.min_rr_ratio ?? 2),
    rr_guard_mode: normalizeRRGuardMode(settings.rr_guard_mode, "soft"),
    discovery_rr_guard_mode: normalizeRRGuardMode(settings.discovery_rr_guard_mode, "soft"),
    real_rr_guard_mode: normalizeRRGuardMode(settings.real_rr_guard_mode, "hard"),
    virtual_rr_guard_mode: normalizeRRGuardMode(settings.virtual_rr_guard_mode, "soft"),
    backtest_rr_guard_mode: normalizeRRGuardMode(settings.backtest_rr_guard_mode, "soft"),
    strategy_rr_guard_modes: normalizeStrategyRRGuardModes(settings.strategy_rr_guard_modes),
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
    real_execution_enabled: Boolean(settings.real_execution_enabled ?? false),
    real_requires_fresh_market_data: Boolean(settings.real_requires_fresh_market_data ?? true),
    real_requires_positive_edge: Boolean(settings.real_requires_positive_edge ?? true),
    real_fee_rate_ttl_seconds: Number(settings.real_fee_rate_ttl_seconds ?? 86_400),
    no_trade_filters_enabled: Boolean(settings.no_trade_filters_enabled ?? true),
    max_spread_bps_for_entry: Number(settings.max_spread_bps_for_entry ?? 50),
    max_slippage_bps_for_entry: Number(settings.max_slippage_bps_for_entry ?? 150),
    min_depth_usd_for_entry: Number(settings.min_depth_usd_for_entry ?? 0),
    max_obstacle_distance_r: Number(settings.max_obstacle_distance_r ?? 1),
    cooldown_after_stop_minutes: Number(settings.cooldown_after_stop_minutes ?? 0),
    max_strategy_losses_per_day: Number(settings.max_strategy_losses_per_day ?? 0),
    edge_min_sample_size: Number(settings.edge_min_sample_size ?? 50),
    min_expectancy_after_costs_r: Number(settings.min_expectancy_after_costs_r ?? 0.05),
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

function normalizeRiskAmountMode(value: unknown): RiskAmountMode {
  return value === "fixed" ? "fixed" : "percent";
}

function normalizeRadarDisplayMode(value: unknown): RadarDisplayMode {
  if (
    value === "all_market_opportunities" ||
    value === "market_ideas" ||
    value === "watchlist" ||
    value === "execution_ready" ||
    value === "execution_signals" ||
    value === "blocked"
  ) {
    return value;
  }
  return "execution_ready";
}

function normalizeRRGuardMode(value: unknown, fallback: RRGuardMode): RRGuardMode {
  if (value === "off" || value === "soft" || value === "hard") return value;
  return fallback;
}

function normalizeStrategyRRGuardModes(value: unknown): Record<string, RRGuardMode> {
  if (!isRecord(value)) return {};
  return Object.fromEntries(
    Object.entries(value)
      .map(([key, mode]) => [key, normalizeRRGuardMode(mode, "soft")] as const)
      .filter(([key]) => key.length > 0)
  );
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

function normalizeOptionalRiskCheckStatus(value: unknown): RiskCheckStatus | null {
  if (value === "passed" || value === "warning" || value === "failed") return value;
  return null;
}

function normalizeRadarRiskRewardStatus(value: unknown): RadarRiskRewardStatus | null {
  if (
    value === "passed" ||
    value === "warning" ||
    value === "failed" ||
    value === "skipped" ||
    value === "unknown"
  ) {
    return value;
  }
  return null;
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
  if (value === "fresh" || value === "partial" || value === "missing" || value === "stale") return value;
  return "unknown";
}

function normalizeScannerStage(value: unknown, scannerRunning: boolean): HealthStatus["stage"] {
  if (
    value === "idle" ||
    value === "starting" ||
    value === "warming_up" ||
    value === "listening" ||
    value === "stale" ||
    value === "degraded" ||
    value === "stopped" ||
    value === "error"
  ) {
    return value;
  }
  return scannerRunning ? "starting" : "stopped";
}

function normalizeScannerMarketDataStatus(value: unknown, scannerRunning: boolean): HealthStatus["market_data_status"] {
  if (
    value === "online" ||
    value === "waiting" ||
    value === "stale" ||
    value === "offline" ||
    value === "error"
  ) {
    return value;
  }
  return scannerRunning ? "waiting" : "offline";
}

function normalizeKillSwitchStatus(value: unknown): HealthStatus["kill_switch"] {
  if (!value || typeof value !== "object") {
    return null;
  }
  const raw = value as Partial<NonNullable<HealthStatus["kill_switch"]>>;
  const state = normalizeKillSwitchState(raw.state);
  const defaultExecutionAllowed = state === "healthy" || state === "degraded";
  const rawReasons: unknown[] = Array.isArray(raw.reasons) ? raw.reasons : [];
  const reasons = rawReasons
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    .map((item) => ({
      code: String(item.code ?? "kill_switch_unknown"),
      severity: item.severity === "warning" ? "warning" as const : "blocker" as const,
      message: String(item.message ?? "Kill-switch is active."),
      metadata: typeof item.metadata === "object" && item.metadata !== null
        ? item.metadata as Record<string, unknown>
        : {}
    }));
  return {
    state,
    execution_allowed: Boolean(raw.execution_allowed ?? defaultExecutionAllowed),
    manual_unlock_required: Boolean(raw.manual_unlock_required ?? state === "manual_unlock_required"),
    reasons,
    reason_codes: Array.isArray(raw.reason_codes)
      ? raw.reason_codes.map(String)
      : reasons.map((reason) => reason.code),
    metrics: typeof raw.metrics === "object" && raw.metrics !== null
      ? Object.fromEntries(
          Object.entries(raw.metrics).map(([key, metric]) => [key, Number(metric ?? 0)])
        )
      : {}
  };
}

function normalizeKillSwitchState(value: unknown): NonNullable<HealthStatus["kill_switch"]>["state"] {
  if (
    value === "healthy" ||
    value === "degraded" ||
    value === "paused" ||
    value === "killed" ||
    value === "manual_unlock_required"
  ) {
    return value;
  }
  return "healthy";
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
  const metadata = isRecord(connection.metadata) ? connection.metadata : {};
  return {
    id: String(connection.id ?? ""),
    user_id: requiredString(connection.user_id, "ExchangeConnection", "user_id"),
    exchange_id: String(connection.exchange_id ?? ""),
    exchange_code: String(connection.exchange_code ?? ""),
    exchange_name: String(connection.exchange_name ?? connection.exchange_code ?? ""),
    label: String(connection.label ?? ""),
    account_type: String(connection.account_type ?? "spot"),
    key_ref: String(connection.key_ref ?? ""),
    permissions: isRecord(connection.permissions) ? connection.permissions : {},
    status: normalizeExchangeConnectionStatus(connection.status),
    environment: normalizeExchangeConnectionEnvironment(connection.environment),
    order_placement_mode: normalizeExchangeOrderPlacementMode(connection.order_placement_mode),
    can_place_orders: Boolean(connection.can_place_orders),
    safety_blockers: normalizeStringArray(connection.safety_blockers),
    mainnet_explicitly_enabled: Boolean(connection.mainnet_explicitly_enabled),
    last_sync_at: connection.last_sync_at == null ? null : String(connection.last_sync_at),
    last_account_snapshot_at: connection.last_account_snapshot_at == null ? null : String(connection.last_account_snapshot_at),
    account_snapshot_status: normalizeAccountSnapshotStatus(connection.account_snapshot_status),
    revoked_at: connection.revoked_at == null ? null : String(connection.revoked_at),
    deleted_at: connection.deleted_at == null ? null : String(connection.deleted_at),
    deletion_reason: connection.deletion_reason == null ? null : String(connection.deletion_reason),
    metadata,
    created_at: String(connection.created_at ?? new Date().toISOString())
  };
}

function normalizeExchangeConnectionStatus(value: unknown): ExchangeConnection["status"] {
  if (value === "disabled" || value === "revoked" || value === "deleted") return value;
  return "active";
}

function normalizeExchangeConnectionEnvironment(value: unknown): ExchangeConnection["environment"] {
  if (value === "testnet" || value === "mainnet") return value;
  return "testnet";
}

function normalizeExchangeOrderPlacementMode(value: unknown): ExchangeConnection["order_placement_mode"] {
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

export function normalizeHealth(value: unknown): HealthStatus {
  const health = value as Partial<HealthStatus>;
  const scannerRunning = Boolean(health.scanner_running);
  return {
    status: String(health.status ?? "unknown"),
    scanner_enabled: Boolean(health.scanner_enabled),
    scanner_running: scannerRunning,
    scanner_stopping: Boolean(health.scanner_stopping),
    stage: normalizeScannerStage(health.stage, scannerRunning),
    market_data_status: normalizeScannerMarketDataStatus(health.market_data_status, scannerRunning),
    processed_signals: Number(health.processed_signals ?? 0),
    ticks_processed: Number(health.ticks_processed ?? 0),
    warmup_total: Number(health.warmup_total ?? 0),
    warmup_completed: Number(health.warmup_completed ?? 0),
    warmup_failed: Number(health.warmup_failed ?? 0),
    warmup_started_at: optionalNumber(health.warmup_started_at),
    warmup_finished_at: optionalNumber(health.warmup_finished_at),
    last_tick_age_seconds: optionalNumber(health.last_tick_age_seconds),
    last_error: optionalString(health.last_error),
    market_stream_connected: Boolean(health.market_stream_connected),
    ws_connected: Boolean(health.ws_connected ?? health.market_stream_connected),
    features_built: Number(health.features_built ?? 0),
    strategy_evaluations: Number(health.strategy_evaluations ?? 0),
    signals_found: Number(health.signals_found ?? 0),
    candles_seeded: Number(health.candles_seeded ?? 0),
    scanner_pairs_count: Number(health.scanner_pairs_count ?? 0),
    scanner_universe_source: String(health.scanner_universe_source ?? "default"),
    scanner_universe_warning: health.scanner_universe_warning ?? null,
    estimated_strategy_checks: Number(health.estimated_strategy_checks ?? 0),
    max_scanner_pairs: health.max_scanner_pairs == null ? null : Number(health.max_scanner_pairs),
    last_symbol: health.last_symbol ?? null,
    last_price: health.last_price ?? null,
    kill_switch: normalizeKillSwitchStatus(health.kill_switch)
  };
}

export function normalizeRadarStatus(value: unknown): RadarStatus {
  const status = value as Partial<RadarStatus>;
  const scanPairs = status.scan_pairs ?? [];
  return {
    ...normalizeHealth(status),
    exchanges: status.exchanges ?? [],
    symbols: status.symbols ?? [],
    scan_pairs: scanPairs,
    scanner_pairs_count: Number(status.scanner_pairs_count ?? scanPairs.length ?? status.symbols?.length ?? 0),
    scanner_universe_source: String(status.scanner_universe_source ?? "default"),
    scanner_universe_warning: status.scanner_universe_warning ?? null,
    estimated_strategy_checks: Number(status.estimated_strategy_checks ?? 0),
    max_scanner_pairs: status.max_scanner_pairs == null ? null : Number(status.max_scanner_pairs),
    timeframes: status.timeframes ?? [],
    strategies: status.strategies ?? [],
    scanner_subscription_hash: status.scanner_subscription_hash ?? null,
    strategy_config_hash: status.strategy_config_hash ?? null,
    ticks_processed: Number(status.ticks_processed ?? 0),
    candles_updated: Number(status.candles_updated ?? 0),
    features_built: Number(status.features_built ?? 0),
    strategy_evaluations: Number(status.strategy_evaluations ?? 0),
    signals_found: Number(status.signals_found ?? 0),
    candles_seeded: Number(status.candles_seeded ?? 0),
    warmup_total: Number(status.warmup_total ?? 0),
    warmup_completed: Number(status.warmup_completed ?? 0),
    warmup_failed: Number(status.warmup_failed ?? 0),
    warmup_started_at: optionalNumber(status.warmup_started_at),
    warmup_finished_at: optionalNumber(status.warmup_finished_at),
    last_tick_at: status.last_tick_at ?? null,
    last_tick_age_seconds: optionalNumber(status.last_tick_age_seconds),
    last_signal_at: status.last_signal_at ?? null,
    last_exchange: status.last_exchange ?? null,
    last_symbol: status.last_symbol ?? null,
    last_price: status.last_price ?? null,
    last_error: optionalString(status.last_error),
    market_stream_connected: Boolean(status.market_stream_connected),
    ws_connected: Boolean(status.ws_connected ?? status.market_stream_connected),
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

export function normalizeExchangeWalletBalance(value: unknown): ExchangeWalletBalance {
  const wallet = value as Partial<ExchangeWalletBalance>;
  return {
    exchange: String(wallet.exchange ?? ""),
    connection_id: String(wallet.connection_id ?? ""),
    account_type: String(wallet.account_type ?? "unknown"),
    total_equity: optionalNumber(wallet.total_equity),
    total_wallet_balance: optionalNumber(wallet.total_wallet_balance),
    total_available_balance: optionalNumber(wallet.total_available_balance),
    coins: Array.isArray(wallet.coins) ? wallet.coins.map(normalizeExchangeWalletCoinBalance) : [],
    fetched_at: wallet.fetched_at == null ? null : String(wallet.fetched_at),
    status: normalizeAccountSnapshotStatus(wallet.status),
    warnings: Array.isArray(wallet.warnings) ? wallet.warnings.map(String) : []
  };
}

export function normalizeAccountRiskSnapshot(value: unknown): AccountRiskSnapshot {
  const snapshot = value as Partial<AccountRiskSnapshot>;
  return {
    status: normalizeAccountSnapshotStatus(snapshot.status),
    fetched_at: snapshot.fetched_at == null ? null : String(snapshot.fetched_at),
    account_equity: optionalNumber(snapshot.account_equity),
    available_balance: optionalNumber(snapshot.available_balance),
    wallet_balance: optionalNumber(snapshot.wallet_balance),
    margin_mode: snapshot.margin_mode == null ? null : String(snapshot.margin_mode),
    total_initial_margin: optionalNumber(snapshot.total_initial_margin),
    total_maintenance_margin: optionalNumber(snapshot.total_maintenance_margin),
    maintenance_margin_rate: optionalNumber(snapshot.maintenance_margin_rate),
    positions: Array.isArray(snapshot.positions) ? snapshot.positions.map(normalizePositionRiskSummary) : [],
    open_risk_amount: Number(snapshot.open_risk_amount ?? 0),
    source: normalizeAccountSnapshotSource(snapshot.source),
    warnings: Array.isArray(snapshot.warnings) ? snapshot.warnings.map(String) : []
  };
}

function normalizeExchangeWalletCoinBalance(value: unknown): ExchangeWalletCoinBalance {
  const coin = value as Partial<ExchangeWalletCoinBalance>;
  return {
    coin: String(coin.coin ?? ""),
    equity: optionalNumber(coin.equity),
    usd_value: optionalNumber(coin.usd_value),
    wallet_balance: optionalNumber(coin.wallet_balance),
    available_to_withdraw: optionalNumber(coin.available_to_withdraw),
    locked: optionalNumber(coin.locked),
    borrow_amount: optionalNumber(coin.borrow_amount),
    accrued_interest: optionalNumber(coin.accrued_interest),
    total_order_im: optionalNumber(coin.total_order_im),
    total_position_im: optionalNumber(coin.total_position_im),
    total_position_mm: optionalNumber(coin.total_position_mm),
    unrealised_pnl: optionalNumber(coin.unrealised_pnl)
  };
}

function normalizePositionRiskSummary(value: unknown): PositionRiskSummary {
  const position = value as Partial<PositionRiskSummary>;
  const side = position.side === "long" || position.side === "short" ? position.side : "unknown";
  return {
    symbol: position.symbol == null ? null : String(position.symbol),
    side,
    quantity: optionalNumber(position.quantity),
    notional: optionalNumber(position.notional),
    entry_price: optionalNumber(position.entry_price),
    mark_price: optionalNumber(position.mark_price),
    unrealized_pnl: optionalNumber(position.unrealized_pnl),
    risk_amount: optionalNumber(position.risk_amount),
    initial_margin: optionalNumber(position.initial_margin),
    maintenance_margin: optionalNumber(position.maintenance_margin),
    margin_mode: position.margin_mode == null ? null : String(position.margin_mode)
  };
}

function normalizeAccountSnapshotStatus(value: unknown): AccountRiskSnapshot["status"] {
  return value === "fresh" || value === "stale" || value === "missing" ? value : "missing";
}

function normalizeAccountSnapshotSource(value: unknown): AccountRiskSnapshot["source"] {
  if (
    value === "exchange" ||
    value === "request" ||
    value === "virtual" ||
    value === "dry_run" ||
    value === "demo"
  ) {
    return value;
  }
  return "exchange";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function normalizeMetadata(value: unknown): Record<string, unknown> {
  return isRecord(value) ? { ...value } : {};
}

function normalizeStringRecord(value: unknown): Record<string, string> {
  if (!isRecord(value)) return {};
  return Object.fromEntries(Object.entries(value).map(([key, entry]) => [key, String(entry)]));
}

function normalizeStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String).filter(Boolean) : [];
}

function optionalNumber(value: unknown): number | null {
  if (value == null) return null;
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue : null;
}

function optionalString(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

function nullableString(value: unknown): string | null {
  if (value == null || value === "") return null;
  return String(value);
}

function nullableDecimalString(value: unknown): string | null {
  if (value == null || value === "") return null;
  return String(value);
}

function optionalBoolean(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

function normalizeDecisionReasonSource(value: unknown): DecisionReasonSource {
  if (
    value === "setup" ||
    value === "market_quality" ||
    value === "rr" ||
    value === "no_trade" ||
    value === "risk" ||
    value === "execution" ||
    value === "data"
  ) {
    return value;
  }
  return "data";
}

function normalizeDecisionReasonSeverity(value: unknown): DecisionReasonSeverity {
  if (value === "info" || value === "blocker") return value;
  return "warning";
}

function normalizeDecisionReasonScope(value: unknown): DecisionReasonScope {
  if (value === "virtual" || value === "real" || value === "backtest") return value;
  return "discovery";
}

function normalizeClosePercent(value: unknown): number | string | null {
  if (value == null) return null;
  if (typeof value === "string") return value;
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue : null;
}

function normalizeEdgeStatus(value: unknown): SignalEdgeSnapshot["status"] {
  if (value === "positive" || value === "negative" || value === "insufficient_sample") return value;
  return "unknown";
}

function normalizeEdgeSource(value: unknown): SignalEdgeSnapshot["source"] {
  if (value === "outcome" || value === "backtest" || value === "mixed") return value;
  return "none";
}

function normalizeTradeCloseReason(value: unknown): TradeCloseReason | null {
  if (
    value === "take_profit" ||
    value === "stop_loss" ||
    value === "manual_close" ||
    value === "invalidation" ||
    value === "cancelled" ||
    value === "partial_take_profit" ||
    value === "breakeven_stop" ||
    value === "trailing_stop" ||
    value === "time_stop"
  ) {
    return value;
  }
  return null;
}

function normalizeSubscriptionTier(value: unknown): SubscriptionTier {
  return value === "pro" || value === "team" ? value : "free";
}

function normalizeSubscriptionState(value: unknown): SubscriptionState {
  if (value === "active" || value === "trialing" || value === "past_due" || value === "canceled") return value;
  return "none";
}

function normalizeViewTone(value: unknown): "green" | "red" | "yellow" | "blue" | "purple" | "neutral" {
  if (value === "green" || value === "red" || value === "yellow" || value === "blue" || value === "purple") return value;
  return "neutral";
}

function normalizeSignalDetailsPrimaryStatus(value: unknown): NonNullable<RadarSignal["details_view"]>["primary_status"] {
  if (
    value === "execution_ready" ||
    value === "waiting_entry" ||
    value === "requires_reconfirmation" ||
    value === "blocked" ||
    value === "watchlist" ||
    value === "cancelled" ||
    value === "expired"
  ) {
    return value;
  }
  return "unknown";
}

function normalizeDetailsBlockerCategory(value: unknown): NonNullable<RadarSignal["details_view"]>["top_blockers"][number]["category"] {
  if (
    value === "entry" ||
    value === "risk" ||
    value === "market_data" ||
    value === "liquidity" ||
    value === "execution" ||
    value === "technical"
  ) {
    return value;
  }
  return "technical";
}

function requiredString(value: unknown, contractName: string, fieldName: string): string {
  if (typeof value === "string" && value.trim()) return value;
  throw new ApiContractError(contractName, `${fieldName}: Required`);
}

function parseContract<T extends z.ZodType>(
  schema: T,
  value: unknown,
  contractName: string
): z.infer<T> {
  const parsed = schema.safeParse(value);
  if (parsed.success) return parsed.data;
  throw new ApiContractError(contractName, formatZodIssues(parsed.error));
}

function formatZodIssues(error: z.ZodError): string {
  const issue = error.issues[0];
  if (!issue) return "is invalid";
  const path = issue.path.length ? issue.path.join(".") : "payload";
  return `${path}: ${issue.message}`;
}
