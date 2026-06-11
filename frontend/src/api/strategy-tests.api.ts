import { requestJson } from "./client";
import { currentUserId } from "./user-identity";
import type {
  StrategyTestActiveRunResponse,
  StrategyTestReport,
  StrategyTestRunDetailResponse,
  StrategyTestRunRequest,
  StrategyTestRunResponse,
  StrategyTestRunStatus,
  StrategyTestTrade
} from "@/features/strategy-testing/types";

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
    const userId = request.user_id ?? await currentUserId();
    return rawJson<StrategyTestRunResponse>("/api/v1/strategy-tests/runs", {
      body: JSON.stringify({
        user_id: userId,
        test_type: request.test_type ?? "historical_backtest",
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
    const userId = params.userId ?? await currentUserId();
    return rawJson<StrategyTestRunResponse[]>(strategyTestRunsPath({ ...params, userId }));
  },
  async activeRun(userId?: string): Promise<StrategyTestActiveRunResponse> {
    const resolvedUserId = userId ?? await currentUserId();
    const query = new URLSearchParams({ user_id: resolvedUserId });
    return rawJson<StrategyTestActiveRunResponse>(`/api/v1/strategy-tests/runs/active?${query.toString()}`);
  },
  async cancelRun(runId: string): Promise<StrategyTestRunResponse> {
    return rawJson<StrategyTestRunResponse>(`/api/v1/strategy-tests/runs/${encodeURIComponent(runId)}/cancel`, {
      method: "POST"
    });
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
  if (params.userId) query.set("user_id", params.userId);
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
  return requestJson<T>(path, init);
}
