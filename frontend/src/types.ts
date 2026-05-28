export type SignalDirection = "long" | "short";
export type SignalStatus =
  | "new"
  | "active"
  | "watchlist"
  | "confirmed"
  | "rejected"
  | "expired"
  | "invalidated"
  | "closed"
  | "entry_touched";
export type TradeMode = "virtual" | "real";
export type TradeStatus = "open" | "closed" | "cancelled";
export type VirtualSimulationMode = "passive" | "impact_aware";
export type VirtualExecutionStatus = "filled" | "partially_filled" | "rejected_virtual_execution";
export type ImpactRisk = "low" | "medium" | "high";
export type ExecutionGateStatus = "passed" | "warning" | "blocked";
export type Timeframe = "1m" | "5m" | "15m" | "1h" | "4h" | "1d";

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

export interface RadarSignal {
  id: string;
  symbol: string;
  exchange: string;
  strategy: string;
  direction: SignalDirection;
  confidence: number;
  risk_reward: number | null;
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
  created_at: string;
  updated_at: string;
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

export interface VirtualExecutionReport {
  mode: VirtualSimulationMode;
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
  rejected_reason: string | null;
  notes: string[];
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
  leverage: number;
  risk_percent: number;
  risk_amount: number;
  risk_reward: number;
  stop_loss: number;
  take_profit: number[];
  fees: number;
  slippage_bps: number;
  simulation_mode: VirtualSimulationMode;
  execution_status: VirtualExecutionStatus;
  requested_size_usd: number | null;
  filled_size_usd: number | null;
  unfilled_size_usd: number;
  execution: VirtualExecutionReport | null;
  status: TradeStatus;
  result: "win" | "loss" | "breakeven" | null;
  close_reason: "take_profit" | "stop_loss" | "manual_close" | "cancelled" | null;
  pnl: number | null;
  pnl_percent: number | null;
  mfe: number;
  mae: number;
  screenshots: string[];
  ai_review: string | null;
  opened_at: string;
  updated_at: string;
  closed_at: string | null;
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
