import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { StrategyTestRunsTable } from "./StrategyTestRunsTable";
import type { StrategyTestRunResponse } from "./types";

vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => 128,
    getVirtualItems: () => Array.from({ length: count }, (_, index) => ({
      index,
      key: index,
      size: 70,
      start: index * 70
    })),
    measureElement: vi.fn()
  })
}));

describe("StrategyTestRunsTable", () => {
  it("shows forward test type and running counters", () => {
    render(<StrategyTestRunsTable runs={[forwardRun()]} />);

    expect(screen.getByText("forward_virtual")).toBeInTheDocument();
    expect(screen.getByText("3 signals")).toBeInTheDocument();
    expect(screen.getByText("1 open")).toBeInTheDocument();
    expect(screen.getByText("PnL 12.5")).toBeInTheDocument();
  });

  it("shows cancel action for running forward tests", async () => {
    const user = userEvent.setup();
    const cancelRun = vi.fn();

    render(<StrategyTestRunsTable onCancelRun={cancelRun} runs={[forwardRun()]} />);

    await user.click(screen.getByRole("button", { name: /Cancel forward run/u }));

    expect(cancelRun).toHaveBeenCalledWith(forwardRun().run_id);
  });
});

function forwardRun(): StrategyTestRunResponse {
  return {
    created_at: "2026-06-06T10:00:00.000Z",
    error: null,
    finished_at: null,
    requested_matrix: {
      pairs: [{ exchange: "bybit", symbol: "BTCUSDT" }],
      scenario_count: 1,
      strategies: ["trend_pullback_continuation"],
      test_type: "forward_virtual",
      timeframes: ["1m"]
    },
    run_id: "11111111-1111-4111-8111-111111111111",
    started_at: "2026-06-06T10:00:00.000Z",
    status: "running",
    summary: {
      current_equity: 1012.5,
      filled_trades: 1,
      open_positions: 1,
      realized_pnl: 12.5,
      signals_seen: 3
    }
  };
}
