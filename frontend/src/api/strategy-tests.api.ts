import { API_BASE, API_TIMEOUT_MS } from "./client";
import type {
  StrategyTestReport,
  StrategyTestRunDetailResponse,
  StrategyTestRunRequest,
  StrategyTestRunResponse,
  StrategyTestRunStatus,
  StrategyTestTrade
} from "@/features/strategy-testing/types";

const DEFAULT_USER_ID = "demo_user";

export interface StrategyTestRunListParams {
  userId?: string;
  limit?: number;
  status?: StrategyTestRunStatus;
}

export interface StrategyTestReportListParams {
  userId?: string;
  limit?: number;
}

export const strategyTestsApi = {
  async run(request: StrategyTestRunRequest): Promise<StrategyTestRunResponse> {
    return rawJson<StrategyTestRunResponse>("/api/v1/strategy-tests/runs", {
      body: JSON.stringify({
        user_id: request.user_id ?? DEFAULT_USER_ID,
        strategies: request.strategies,
        pairs: request.pairs,
        timeframes: request.timeframes,
        start_at: request.start_at,
        end_at: request.end_at,
        mode: request.mode,
        initial_capital: request.initial_capital,
        fee_rate: request.fee_rate,
        slippage_bps: request.slippage_bps,
        same_candle_policy: request.same_candle_policy,
        params: request.params ?? {},
        metric_set: request.metric_set ?? [],
        tags: request.tags ?? ["backtest"]
      }),
      headers: { "content-type": "application/json" },
      method: "POST"
    });
  },
  async listRuns(params: StrategyTestRunListParams = {}): Promise<StrategyTestRunResponse[]> {
    return rawJson<StrategyTestRunResponse[]>(strategyTestRunsPath(params));
  },
  async getRun(runId: string): Promise<StrategyTestRunResponse> {
    const detail = await rawJson<StrategyTestRunDetailResponse>(`/api/v1/strategy-tests/runs/${encodeURIComponent(runId)}`);
    return detail.run;
  },
  async getTrades(runId: string): Promise<StrategyTestTrade[]> {
    return rawJson<StrategyTestTrade[]>(`/api/v1/strategy-tests/runs/${encodeURIComponent(runId)}/trades`);
  },
  async listReports(params: StrategyTestReportListParams = {}): Promise<StrategyTestReport[]> {
    return rawJson<StrategyTestReport[]>(strategyTestReportsPath(params));
  },
  async getReport(runId: string): Promise<StrategyTestReport> {
    return rawJson<StrategyTestReport>(`/api/v1/strategy-tests/reports/${encodeURIComponent(runId)}`);
  }
};

function strategyTestRunsPath(params: StrategyTestRunListParams): string {
  const query = new URLSearchParams();
  query.set("user_id", params.userId ?? DEFAULT_USER_ID);
  if (params.limit != null) query.set("limit", String(params.limit));
  if (params.status) query.set("status", params.status);
  return `/api/v1/strategy-tests/runs?${query.toString()}`;
}

function strategyTestReportsPath(params: StrategyTestReportListParams): string {
  const query = new URLSearchParams();
  if (params.userId) query.set("user_id", params.userId);
  if (params.limit != null) query.set("limit", String(params.limit));
  const queryString = query.toString();
  return queryString ? `/api/v1/strategy-tests/reports?${queryString}` : "/api/v1/strategy-tests/reports";
}

async function rawJson<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeout = globalThis.setTimeout(() => controller.abort(), API_TIMEOUT_MS);
  try {
    const response = await fetch(`${API_BASE}${path}`, { ...init, signal: controller.signal });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(apiErrorMessage(data) ?? `API error ${response.status}`);
    }
    return data as T;
  } finally {
    globalThis.clearTimeout(timeout);
  }
}

function apiErrorMessage(value: unknown): string | null {
  if (!value || typeof value !== "object" || !("detail" in value)) return null;
  const detail = (value as { detail?: unknown }).detail;
  return typeof detail === "string" ? detail : null;
}
