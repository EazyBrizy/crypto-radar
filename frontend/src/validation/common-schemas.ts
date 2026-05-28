import { z } from "zod";

export const TimeframeSchema = z.enum(["1m", "5m", "15m", "1h", "4h", "1d"]);
export const SignalDirectionSchema = z.enum(["long", "short"]);
export const SignalSideSchema = z.enum(["LONG", "SHORT"]);
export const SignalStatusSchema = z.enum([
  "new",
  "active",
  "watchlist",
  "confirmed",
  "rejected",
  "expired",
  "invalidated",
  "closed",
  "entry_touched"
]);
export const TradeModeSchema = z.enum(["virtual", "real"]);
export const TradeStatusSchema = z.enum(["open", "closed", "cancelled"]);
export const VirtualSimulationModeSchema = z.enum(["passive", "impact_aware"]);
export const VirtualExecutionStatusSchema = z.enum(["filled", "partially_filled", "rejected_virtual_execution"]);
export const ImpactRiskSchema = z.enum(["low", "medium", "high"]);
export const ExecutionGateStatusSchema = z.enum(["passed", "warning", "blocked"]);

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

export const RadarSignalSchema = z.object({
  id: z.string(),
  symbol: z.string(),
  exchange: z.string(),
  strategy: z.string(),
  direction: SignalDirectionSchema,
  confidence: z.number(),
  risk_reward: z.number().nullable().optional(),
  urgency: z.enum(["low", "medium", "high"]).default("medium"),
  status: SignalStatusSchema.default("active"),
  score: z.number().default(0),
  timeframe: z.string().default("stream"),
  entry_min: z.number().nullable().optional(),
  entry_max: z.number().nullable().optional(),
  stop_loss: z.number().nullable().optional(),
  take_profit_1: z.number().nullable().optional(),
  take_profit_2: z.number().nullable().optional(),
  explanation: z.array(z.string()).default([]),
  risks: z.array(z.string()).default([]),
  score_breakdown: SignalScoreBreakdownSchema.optional(),
  created_at: z.string(),
  updated_at: z.string(),
  confirmed_trade_id: z.string().nullable().optional()
});

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
  status: VirtualExecutionStatusSchema.default("filled"),
  requested_size_usd: z.number().default(0),
  filled_size_usd: z.number().default(0),
  unfilled_size_usd: z.number().default(0),
  fill_ratio: z.number().default(1),
  reference_price: z.number().default(0),
  average_price: z.number().nullable().optional(),
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
  rejected_reason: z.string().nullable().optional(),
  notes: z.array(z.string()).default([])
});

export const TradeJournalEntrySchema = z.object({
  id: z.string(),
  user_id: z.string(),
  signal_id: z.string().nullable().optional(),
  mode: TradeModeSchema,
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
  leverage: z.number(),
  risk_percent: z.number(),
  risk_amount: z.number().default(0),
  risk_reward: z.number().default(3),
  stop_loss: z.number(),
  take_profit: z.array(z.number()).default([]),
  fees: z.number().default(0),
  slippage_bps: z.number().default(0),
  simulation_mode: VirtualSimulationModeSchema.default("passive"),
  execution_status: VirtualExecutionStatusSchema.default("filled"),
  requested_size_usd: z.number().nullable().optional(),
  filled_size_usd: z.number().nullable().optional(),
  unfilled_size_usd: z.number().default(0),
  execution: VirtualExecutionReportSchema.nullable().optional(),
  status: TradeStatusSchema,
  result: z.enum(["win", "loss", "breakeven"]).nullable().optional(),
  close_reason: z.enum(["take_profit", "stop_loss", "manual_close", "cancelled"]).nullable().optional(),
  pnl: z.number().nullable().optional(),
  pnl_percent: z.number().nullable().optional(),
  mfe: z.number().default(0),
  mae: z.number().default(0),
  screenshots: z.array(z.string()).default([]),
  ai_review: z.string().nullable().optional(),
  opened_at: z.string(),
  updated_at: z.string(),
  closed_at: z.string().nullable().optional()
});

export const RadarStatusSchema = z.object({
  status: z.string(),
  scanner_enabled: z.boolean(),
  scanner_running: z.boolean(),
  scanner_stopping: z.boolean().default(false),
  processed_signals: z.number(),
  exchanges: z.array(z.string()).default([]),
  symbols: z.array(z.string()).default([]),
  timeframes: z.array(z.string()).default([]),
  strategies: z.array(z.string()).default([]),
  ticks_processed: z.number().default(0),
  candles_updated: z.number().default(0),
  features_built: z.number().default(0),
  strategy_evaluations: z.number().default(0),
  signals_found: z.number().default(0),
  candles_seeded: z.number().default(0),
  last_tick_at: z.number().nullable().optional(),
  last_signal_at: z.number().nullable().optional(),
  last_exchange: z.string().nullable().optional(),
  last_symbol: z.string().nullable().optional(),
  last_price: z.number().nullable().optional(),
  candle_history: z.record(z.string(), z.number()).default({})
});
