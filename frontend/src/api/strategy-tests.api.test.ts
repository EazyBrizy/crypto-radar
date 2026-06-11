import { afterEach, describe, expect, it, vi } from "vitest";

import * as client from "./client";
import { strategyTestsApi } from "./strategy-tests.api";
import type { StrategyTestRunRequest } from "@/features/strategy-testing/types";

describe("strategyTestsApi", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("sends forward test_type in run request body", async () => {
    const requestSpy = vi.spyOn(client, "requestJson").mockResolvedValue({
      created_at: null,
      error: null,
      finished_at: null,
      requested_matrix: {},
      run_id: "run-1",
      started_at: null,
      status: "queued",
      summary: {}
    } as never);

    await strategyTestsApi.run(forwardRequest());

    const [, init] = requestSpy.mock.calls[0];
    const body = JSON.parse(String(init?.body));
    expect(body.test_type).toBe("forward_virtual");
    expect(body.tags).toEqual(["forward_test"]);
  });

  it("builds getStatus path", async () => {
    const requestSpy = vi.spyOn(client, "requestJson").mockResolvedValue({ run_id: "run-1" } as never);

    await strategyTestsApi.getStatus("run-1");

    expect(requestSpy).toHaveBeenCalledWith("/api/v1/strategy-tests/runs/run-1/status");
  });

  it("builds cancelRun path", async () => {
    const requestSpy = vi.spyOn(client, "requestJson").mockResolvedValue({ run_id: "run-1" } as never);

    await strategyTestsApi.cancelRun("run-1");

    expect(requestSpy).toHaveBeenCalledWith("/api/v1/strategy-tests/runs/run-1/cancel", { method: "POST" });
  });

  it("builds publishCalibration path", async () => {
    const requestSpy = vi.spyOn(client, "requestJson").mockResolvedValue({ run_id: "run-1", profiles_updated: 1 } as never);

    await strategyTestsApi.publishCalibration("run-1");

    expect(requestSpy).toHaveBeenCalledWith("/api/v1/strategy-tests/runs/run-1/calibration", { method: "POST" });
  });
});

function forwardRequest(): StrategyTestRunRequest {
  return {
    end_at: "2026-06-06T14:00:00.000Z",
    fee_rate: 0.001,
    initial_capital: 1000,
    mode: "research_virtual",
    pairs: [{ exchange: "bybit", symbol: "BTCUSDT" }],
    same_candle_policy: "stop_first",
    slippage_bps: 0,
    start_at: "2026-06-06T10:00:00.000Z",
    strategies: ["trend_pullback_continuation"],
    tags: ["forward_test"],
    test_type: "forward_virtual",
    timeframes: ["1m"]
  } as StrategyTestRunRequest;
}
