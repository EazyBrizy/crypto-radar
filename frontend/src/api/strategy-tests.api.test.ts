import { afterEach, describe, expect, it, vi } from "vitest";

import { strategyTestsApi } from "./strategy-tests.api";
import { currentUserId } from "./user-identity";

vi.mock("./user-identity", () => ({
  currentUserId: vi.fn(async () => {
    throw new Error("strategy tests API must not resolve frontend user ids implicitly");
  })
}));

describe("strategyTestsApi identity contract", () => {
  afterEach(() => {
    vi.clearAllMocks();
    vi.unstubAllGlobals();
  });

  it("sends run intent without frontend user_id", async () => {
    const fetchSpy = vi.fn(async () => jsonResponse(strategyTestRun()));
    vi.stubGlobal("fetch", fetchSpy);

    await strategyTestsApi.run(strategyTestRunRequest());

    const [, init] = fetchSpy.mock.calls[0];
    const body = JSON.parse(String(init?.body));
    expect(body).not.toHaveProperty("user_id");
    expect(body).toMatchObject({
      test_type: "historical_backtest",
      strategies: ["trend_pullback_continuation"]
    });
    expect(currentUserId).not.toHaveBeenCalled();
  });

  it("uses backend request identity for active/list/report routes by default", async () => {
    const fetchSpy = vi.fn(async () => jsonResponse([]));
    vi.stubGlobal("fetch", fetchSpy);

    await strategyTestsApi.listRuns();
    await strategyTestsApi.listReports();

    expect(String(fetchSpy.mock.calls[0][0])).toContain("/api/v1/strategy-tests/runs");
    expect(String(fetchSpy.mock.calls[0][0])).not.toContain("user_id=");
    expect(String(fetchSpy.mock.calls[1][0])).toContain("/api/v1/strategy-tests/reports");
    expect(String(fetchSpy.mock.calls[1][0])).not.toContain("user_id=");
    expect(currentUserId).not.toHaveBeenCalled();
  });

  it("keeps explicit user_id query override for dev compatibility", async () => {
    const fetchSpy = vi.fn(async () => jsonResponse(activeRunState()));
    vi.stubGlobal("fetch", fetchSpy);

    await strategyTestsApi.activeRun("usr_debug");

    expect(String(fetchSpy.mock.calls[0][0])).toContain("/api/v1/strategy-tests/runs/active?user_id=usr_debug");
    expect(currentUserId).not.toHaveBeenCalled();
  });
});

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    headers: { "Content-Type": "application/json" },
    status: 200
  });
}

function strategyTestRunRequest() {
  return {
    end_at: "2026-06-02T00:00:00.000Z",
    fee_rate: 0.001,
    initial_capital: 1000,
    mode: "research_virtual" as const,
    pairs: [{ exchange: "bybit", symbol: "BTCUSDT" }],
    same_candle_policy: "stop_first" as const,
    slippage_bps: 0,
    start_at: "2026-06-01T00:00:00.000Z",
    strategies: ["trend_pullback_continuation"],
    test_type: "historical_backtest" as const,
    timeframes: ["1h"]
  };
}

function strategyTestRun() {
  return {
    created_at: "2026-06-02T00:00:00.000Z",
    error: null,
    finished_at: null,
    last_heartbeat_at: null,
    requested_matrix: {},
    run_id: "11111111-1111-4111-8111-111111111111",
    runtime_state: {},
    started_at: null,
    status: "queued",
    summary: {},
    test_type: "historical_backtest"
  };
}

function activeRunState() {
  return {
    active_run: null,
    allowed_actions: ["refresh"],
    can_run: true,
    disabled_reason: null,
    disabled_reason_code: null,
    is_stale: false,
    stale_threshold_seconds: 900
  };
}
