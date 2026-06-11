export type StrategyTestMode = "discovery" | "research_virtual" | "production_like";
export type StrategyTestType = "historical_backtest" | "forward_virtual";
export type StrategyTestRunStatus = "queued" | "running" | "completed" | "failed" | "cancelled" | "stopping";
export type StrategyTestSameCandlePolicy = "stop_first" | "target_first" | "ignore_ambiguous";
export type StrategyTestSignalSelectionPolicy =
  | "first_actionable"
  | "highest_score"
  | "all_non_overlapping"
  | "all_signals";

export const STRATEGY_TEST_MODES: StrategyTestMode[] = ["discovery", "research_virtual", "production_like"];
export const STRATEGY_TEST_SAME_CANDLE_POLICIES: StrategyTestSameCandlePolicy[] = [
  "stop_first",
  "target_first",
  "ignore_ambiguous"
];
export const STRATEGY_TEST_SIGNAL_SELECTION_POLICIES: StrategyTestSignalSelectionPolicy[] = [
  "first_actionable",
  "highest_score",
  "all_non_overlapping",
  "all_signals"
];

export interface StrategyTestPair {
  exchange: string;
  symbol: string;
}

export interface StrategyTestRunRequest {
  user_id?: string;
  test_type?: StrategyTestType;
  strategies: string[];
  pairs: StrategyTestPair[];
  timeframes: string[];
  start_at: string;
  end_at: string;
  mode: StrategyTestMode;
  initial_capital: number;
  fee_rate: number;
  slippage_bps: number;
  same_candle_policy: StrategyTestSameCandlePolicy;
  params?: Record<string, unknown>;
  metric_set?: string[];
  tags?: string[];
}

export interface StrategyTestRequestedMatrix {
  test_type?: StrategyTestType;
  strategies?: string[];
  pairs?: StrategyTestPair[];
  timeframes?: string[];
  parameter_sets?: Array<Record<string, unknown>>;
  assumption_sets?: Array<Record<string, unknown>>;
  scenario_count?: number;
  [key: string]: unknown;
}

export interface StrategyTestRunSummary {
  scenario_count?: number;
  completed_scenarios?: number;
  failed_scenarios?: number;
  signals_count?: number;
  trades_count?: number;
  signals_seen?: number;
  entry_touch_count?: number;
  filled_count?: number;
  no_entry_count?: number;
  risk_rejections?: number;
  execution_rejections?: number;
  execution_candidates?: number;
  blocked_signals?: number;
  pending_entries?: number;
  entry_touched?: number;
  filled_trades?: number;
  open_positions?: number;
  closed_trades?: number;
  no_entry?: number;
  current_equity?: number;
  realized_pnl?: number;
  unrealized_pnl?: number;
  last_tick_at?: string | null;
  last_signal_at?: string | null;
  [key: string]: unknown;
}

export interface StrategyTestRunResponse {
  run_id: string;
  status: StrategyTestRunStatus;
  requested_matrix: StrategyTestRequestedMatrix;
  summary: StrategyTestRunSummary;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
}

export interface StrategyTestRunDetailResponse {
  run: StrategyTestRunResponse;
  trades_count: number;
  warnings: string[];
  rejections: string[];
}

export interface StrategyTestCalibrationPublishResponse {
  run_id: string;
  source: "historical_backtest" | "forward_virtual" | "mixed";
  profiles_updated: number;
  eligible_count: number;
  blocked_count: number;
}

type DecimalJson = number | string;

export interface StrategyTestTrade {
  run_id: string;
  trade_id: string;
  exchange: string;
  symbol: string;
  timeframe: string;
  strategy_code: string;
  metadata?: Record<string, unknown>;
  user_id?: string;
  mode?: StrategyTestMode;
  strategy_version?: string;
  direction?: string;
  signal_score?: number | null;
  market_regime?: string;
  score_bucket?: string;
  entry_time?: string;
  exit_time?: string | null;
  entry_price?: DecimalJson;
  exit_price?: DecimalJson | null;
  stop_loss?: DecimalJson | null;
  targets?: Array<Record<string, unknown>>;
  selected_rr?: number | null;
  realized_r?: number | null;
  pnl?: DecimalJson;
  pnl_pct?: number;
  fees?: DecimalJson;
  slippage?: DecimalJson;
  mfe_r?: number | null;
  mae_r?: number | null;
  bars_to_entry?: number | null;
  bars_in_trade?: number | null;
  close_reason?: string;
  outcome?: string;
  risk_rejected?: boolean;
  execution_rejected?: boolean;
  warnings?: string[];
  features_snapshot?: Record<string, unknown>;
  trade_plan?: Record<string, unknown>;
  tags?: string[];
  created_at?: string;
}

export interface StrategyTestSignal {
  run_id: string;
  user_id?: string;
  mode?: StrategyTestMode;
  scenario_id?: string;
  strategy_code: string;
  strategy_version?: string;
  exchange?: string;
  symbol: string;
  timeframe?: string;
  direction?: string;
  signal_id: string;
  signal_time?: string;
  signal_score?: number | null;
  feed_kind?: string;
  gate_status?: string;
  status?: string;
  trigger_passed?: boolean;
  edge_status?: string;
  selected_rr?: number | null;
  entry_min?: DecimalJson | null;
  entry_max?: DecimalJson | null;
  stop_loss?: DecimalJson | null;
  target_1?: DecimalJson | null;
  outcome?: string;
  outcome_reason?: string;
  entry_touched?: boolean;
  filled?: boolean;
  risk_rejected?: boolean;
  execution_rejected?: boolean;
  no_entry?: boolean;
  bars_to_entry?: number | null;
  bars_to_outcome?: number | null;
  metadata?: Record<string, unknown>;
  created_at?: string;
}

export type StrategyTestMetricValue = number | string | boolean | null;
export type StrategyTestMetricConfidence = "high" | "medium" | "low" | "insufficient_sample";

export interface StrategyTestMetric {
  run_id?: string;
  scenario_id?: string | null;
  name?: string;
  code?: string;
  label?: string;
  value: StrategyTestMetricValue;
  sample_size?: number;
  unit?: string | null;
  group?: Record<string, unknown>;
  confidence?: StrategyTestMetricConfidence;
  warnings?: string[];
  metadata?: Record<string, unknown>;
}

export interface StrategyTestReportSection {
  code: string;
  name: string;
  summary: Record<string, unknown>;
  metrics: StrategyTestMetric[];
  rows: Array<Record<string, unknown>>;
  warnings: string[];
  metadata: Record<string, unknown>;
}

export interface StrategyTestCandidateAdjustment {
  strategy_code: string;
  scope: string;
  reason: string;
  evidence: Record<string, unknown>;
  suggested_change: string;
  confidence: "low" | "medium" | "high";
}

export interface StrategyTestReport {
  run_id: string;
  status: StrategyTestRunStatus;
  mode: StrategyTestMode;
  requested_matrix: StrategyTestRequestedMatrix;
  assumptions: Record<string, unknown>;
  summary: StrategyTestRunSummary;
  sections: StrategyTestReportSection[];
  metrics: StrategyTestMetric[];
  candidate_adjustments: StrategyTestCandidateAdjustment[];
  generated_at: string;
  summary_metrics: StrategyTestMetric[];
  grouped_metrics: StrategyTestMetric[];
  trades_count: number;
  warnings: string[];
  rejections: string[];
}
