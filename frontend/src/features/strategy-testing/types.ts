import type { components } from "@/api/generated/openapi-types";

type StrategyTestRunRequestDto = components["schemas"]["StrategyTestRunRequest"];
type StrategyTestRunResponseDto = components["schemas"]["StrategyTestRunResponse"];
type StrategyTestActiveRunResponseDto = components["schemas"]["StrategyTestActiveRunResponse"];
type StrategyTestEstimateResponseDto = components["schemas"]["StrategyTestEstimateResponse"];
type StrategyTestSignalEventDto = components["schemas"]["StrategyTestSignalEvent"];
type StrategyTestFunnelResponseDto = components["schemas"]["StrategyTestFunnelResponse"];
type StrategyTestCalibrationResponseDto = components["schemas"]["StrategyTestCalibrationResponse"];
type StrategyTestRuntimeCountersDto = components["schemas"]["StrategyTestRuntimeCounters"];
type StrategyTestRuntimeStateDto = components["schemas"]["StrategyTestRuntimeState"];
type StrategyTestReportDto = components["schemas"]["StrategyTestReport"];

export type StrategyTestMode = StrategyTestRunRequestDto["mode"];
export type StrategyTestType = StrategyTestRunResponseDto["test_type"];
export type StrategyTestRunStatus = StrategyTestRunResponseDto["status"];
export type StrategyTestDataCompleteness = StrategyTestReportDto["data_completeness"];
export type StrategyTestCalibrationDecision = StrategyTestCalibrationResponseDto["decision"];
export type StrategyTestSameCandlePolicy = StrategyTestRunRequestDto["same_candle_policy"];

export const STRATEGY_TEST_MODES: StrategyTestMode[] = ["discovery", "research_virtual", "production_like"];
export const STRATEGY_TEST_SAME_CANDLE_POLICIES: StrategyTestSameCandlePolicy[] = [
  "conservative_stop_first",
  "intrabar_unknown",
  "stop_first",
  "target_first",
  "ignore_ambiguous"
];

export type StrategyTestPair = components["schemas"]["StrategyTestPair"];

export interface StrategyTestRunRequest {
  user_id?: string;
  test_type?: StrategyTestType;
  strategies: string[];
  pairs: StrategyTestPair[];
  timeframes: string[];
  start_at: string;
  end_at: string;
  mode: StrategyTestMode;
  initial_capital: StrategyTestRunRequestDto["initial_capital"];
  fee_rate: StrategyTestRunRequestDto["fee_rate"];
  slippage_bps: StrategyTestRunRequestDto["slippage_bps"];
  same_candle_policy: StrategyTestSameCandlePolicy;
  params?: Record<string, unknown>;
  metric_set?: string[];
  tags?: string[];
}

export interface StrategyTestRequestedMatrix {
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
  skipped_scenarios?: number;
  scenarios_total?: number;
  scenarios_completed?: number;
  scenarios_failed?: number;
  scenarios_skipped?: number;
  pairs_processed?: number;
  strategies_processed?: number;
  timeframes_processed?: number;
  errors_count?: number;
  warnings_count?: number;
  scenario_summaries?: StrategyTestScenarioSummary[];
  scenarios?: StrategyTestScenarioSummary[];
  trades_count?: number;
  signals_seen?: number;
  signals_count?: number;
  execution_candidates?: number;
  entry_touched?: number;
  filled?: number;
  closed?: number;
  wins?: number;
  losses?: number;
  no_entry?: number;
  entry_touch_rate?: number | null;
  no_entry_rate?: number | null;
  false_signal_rate?: number | null;
  risk_rejections?: number;
  execution_rejections?: number;
  signal_funnel?: StrategyTestFunnelResponseDto;
  [key: string]: unknown;
}

export interface StrategyTestScenarioSummary {
  strategy?: string;
  exchange?: string;
  symbol?: string;
  timeframe?: string;
  status?: "completed" | "failed" | "skipped" | string;
  error?: string;
  bars_total?: number;
  signals_count?: number;
  signals_seen?: number;
  execution_candidates?: number;
  entry_touched?: number;
  filled?: number;
  closed?: number;
  trades_count?: number;
  wins?: number;
  losses?: number;
  no_entry?: number;
  risk_rejections?: number;
  execution_rejections?: number;
  winrate?: number | null;
  expectancy_r?: number | null;
  [key: string]: unknown;
}

export type StrategyTestRuntimeCounters = Partial<StrategyTestRuntimeCountersDto> & Record<string, unknown>;
export type StrategyTestRuntimeState = Partial<Omit<StrategyTestRuntimeStateDto, "counters">> & {
  counters?: StrategyTestRuntimeCounters;
} & Record<string, unknown>;

export interface StrategyTestRunResponse {
  run_id: string;
  status: StrategyTestRunStatus;
  test_type: StrategyTestType;
  requested_matrix: StrategyTestRequestedMatrix;
  summary: StrategyTestRunSummary;
  runtime_state: StrategyTestRuntimeState;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  last_heartbeat_at: string | null;
  error: string | null;
  worker_id?: StrategyTestRunResponseDto["worker_id"];
  worker_attempt?: StrategyTestRunResponseDto["worker_attempt"];
  claimed_at?: StrategyTestRunResponseDto["claimed_at"];
  lease_expires_at?: StrategyTestRunResponseDto["lease_expires_at"];
}

export interface StrategyTestActiveRunResponse {
  active_run: StrategyTestRunResponse | null;
  can_run: StrategyTestActiveRunResponseDto["can_run"];
  disabled_reason_code: StrategyTestActiveRunResponseDto["disabled_reason_code"];
  disabled_reason: StrategyTestActiveRunResponseDto["disabled_reason"];
  is_stale: StrategyTestActiveRunResponseDto["is_stale"];
  stale_threshold_seconds: StrategyTestActiveRunResponseDto["stale_threshold_seconds"];
  allowed_actions: NonNullable<StrategyTestActiveRunResponseDto["allowed_actions"]>;
}

export type StrategyTestEstimateResponse = StrategyTestEstimateResponseDto;

export interface StrategyTestRunDetailResponse {
  run: StrategyTestRunResponse;
  trades_count: number;
  warnings: string[];
  rejections: string[];
}

export type StrategyTestCalibrationProfile = components["schemas"]["StrategyTestCalibrationProfile"];
export type StrategyTestCalibrationResponse = StrategyTestCalibrationResponseDto;

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

export type StrategyTestSignalEvent = StrategyTestSignalEventDto;
export type StrategyTestFunnelResponse = StrategyTestFunnelResponseDto;

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
  is_partial: boolean;
  data_completeness: StrategyTestDataCompleteness;
  can_publish_calibration?: StrategyTestReportDto["can_publish_calibration"];
  calibration_disabled_reason_code?: StrategyTestReportDto["calibration_disabled_reason_code"];
  calibration_disabled_reason?: StrategyTestReportDto["calibration_disabled_reason"];
  requested_matrix: StrategyTestRequestedMatrix;
  assumptions: Record<string, unknown>;
  summary: StrategyTestRunSummary;
  sections: StrategyTestReportSection[];
  scenario_summaries?: StrategyTestScenarioSummary[];
  metrics: StrategyTestMetric[];
  candidate_adjustments: StrategyTestCandidateAdjustment[];
  generated_at: string;
  summary_metrics: StrategyTestMetric[];
  grouped_metrics: StrategyTestMetric[];
  trades_count: number;
  warnings: string[];
  rejections: string[];
}
