import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { StrategyTestReport } from "./StrategyTestReport";
import type { StrategyTestReport as StrategyTestReportData, StrategyTestRunResponse } from "./types";

describe("StrategyTestReport", () => {
  it("renders Strategy Test Report", () => {
    render(<StrategyTestReport report={report()} run={null} />);

    expect(screen.getByText("Strategy Test Report")).toBeInTheDocument();
    expect(screen.getByText("Strategy comparison")).toBeInTheDocument();
  });

  it("renders candidate adjustments", () => {
    render(<StrategyTestReport report={report()} run={null} />);

    expect(screen.getByText("Raise minimum score threshold toward 80 for trend_pullback_continuation.")).toBeInTheDocument();
    expect(screen.getByText("negative expectancy")).toBeInTheDocument();
  });

  it("handles empty insufficient-data report", () => {
    render(<StrategyTestReport report={report({ candidate_adjustments: [], trades_count: 0, warnings: ["insufficient_data"] })} run={null} />);

    expect(screen.getByText("No candidate adjustments")).toBeInTheDocument();
    expect(screen.getByText("1 warnings")).toBeInTheDocument();
  });

  it("renders conversion funnel", () => {
    render(<StrategyTestReport report={report()} run={null} />);

    expect(screen.getByText("Conversion funnel")).toBeInTheDocument();
    expect(screen.getByText("entry_touched")).toBeInTheDocument();
    expect(screen.getByText("Signal list")).toBeInTheDocument();
    expect(screen.getByText("signal-2")).toBeInTheDocument();
    expect(screen.getAllByText("no_entry").length).toBeGreaterThan(0);
  });

  it("renders live forward dashboard for running forward tests", () => {
    render(<StrategyTestReport report={null} run={forwardRun()} />);

    expect(screen.getByText("Live forward test")).toBeInTheDocument();
    expect(screen.getByText("Signals found")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("Open positions")).toBeInTheDocument();
    expect(screen.getByText("Current equity")).toBeInTheDocument();
    expect(screen.getByText("1012.5")).toBeInTheDocument();
  });

  it("publishes completed run for calibration", async () => {
    const user = userEvent.setup();
    const onPublishCalibration = vi.fn().mockResolvedValue({
      blocked_count: 1,
      eligible_count: 2,
      profiles_updated: 3,
      run_id: "11111111-1111-4111-8111-111111111111",
      source: "historical_backtest"
    });
    render(<StrategyTestReport onPublishCalibration={onPublishCalibration} report={report()} run={null} />);

    await user.click(screen.getByRole("button", { name: "Use this run for calibration" }));

    expect(onPublishCalibration).toHaveBeenCalledWith("11111111-1111-4111-8111-111111111111");
    expect(await screen.findByText("Calibration profiles updated: 2 eligible, 1 blocked")).toBeInTheDocument();
  });
});

function report(overrides: Partial<StrategyTestReportData> = {}): StrategyTestReportData {
  const base: StrategyTestReportData = {
    assumptions: { same_candle_policy: "stop_first" },
    candidate_adjustments: [
      {
        confidence: "medium",
        evidence: { expectancy_r: -0.2, sample_size: 12 },
        reason: "negative expectancy",
        scope: "score_bucket=70-79",
        strategy_code: "trend_pullback_continuation",
        suggested_change: "Raise minimum score threshold toward 80 for trend_pullback_continuation."
      }
    ],
    generated_at: "2026-06-02T00:00:00.000Z",
    grouped_metrics: [],
    metrics: [],
    mode: "research_virtual",
    rejections: [],
    requested_matrix: {
      pairs: [{ exchange: "bybit", symbol: "BTCUSDT" }],
      scenario_count: 1,
      strategies: ["trend_pullback_continuation"],
      timeframes: ["1h"]
    },
    run_id: "11111111-1111-4111-8111-111111111111",
    sections: [
      {
        code: "summary",
        metadata: {},
        metrics: [{ code: "winrate", label: "Winrate", sample_size: 12, value: 0.58, warnings: [] }],
        name: "Summary",
        rows: [],
        summary: { expectancy_r: -0.2, mode: "research_virtual", scenario_count: 1, winrate: 0.58 },
        warnings: []
      },
      {
        code: "strategy_comparison",
        metadata: {},
        metrics: [],
        name: "Strategy comparison",
        rows: [{ expectancy_r: -0.2, sample_size: 12, strategy: "trend_pullback_continuation", winrate: 0.58 }],
        summary: {},
        warnings: []
      },
      {
        code: "conversion_funnel",
        metadata: {},
        metrics: [],
        name: "Conversion funnel",
        rows: [
          { count: 2, rate: 1, stage: "signals" },
          { count: 1, rate: 0.5, stage: "entry_touched" },
          { count: 1, rate: 0.5, stage: "filled" },
          { count: 1, rate: 0.5, stage: "no_entry" }
        ],
        summary: {
          entry_touched_count: 1,
          filled_count: 1,
          no_entry_count: 1,
          signals_count: 2
        },
        warnings: []
      },
      {
        code: "signal_list",
        metadata: { rows_returned: 2 },
        metrics: [],
        name: "Signal list",
        rows: [
          { direction: "long", filled: true, outcome: "win", signal_id: "signal-1", strategy_code: "trend_pullback_continuation", symbol: "BTCUSDT" },
          { direction: "long", no_entry: true, outcome: "no_entry", signal_id: "signal-2", strategy_code: "trend_pullback_continuation", symbol: "BTCUSDT" }
        ],
        summary: {},
        warnings: []
      },
      {
        code: "trade_list",
        metadata: {},
        metrics: [],
        name: "Trade list",
        rows: [{ direction: "long", realized_r: -1, strategy_code: "trend_pullback_continuation", symbol: "BTCUSDT", trade_id: "trade-1" }],
        summary: {},
        warnings: []
      }
    ],
    status: "completed",
    summary: { expectancy_r: -0.2, scenario_count: 1, trades_count: 1, winrate: 0.58 },
    summary_metrics: [{ code: "winrate", label: "Winrate", sample_size: 12, value: 0.58, warnings: [] }],
    trades_count: 1,
    warnings: []
  };
  return { ...base, ...overrides };
}

function forwardRun(): StrategyTestRunResponse {
  return {
    created_at: "2026-06-06T10:00:00.000Z",
    error: null,
    finished_at: null,
    requested_matrix: {
      pairs: [{ exchange: "bybit", symbol: "BTCUSDT" }],
      scenario_count: 1,
      strategies: ["trend_pullback_continuation"],
      test_type: "forward_virtual" as const,
      timeframes: ["1m"]
    },
    run_id: "11111111-1111-4111-8111-111111111111",
    started_at: "2026-06-06T10:00:00.000Z",
    status: "running" as const,
    summary: {
      blocked_signals: 1,
      current_equity: 1012.5,
      execution_candidates: 2,
      filled_trades: 1,
      last_tick_at: "2026-06-06T10:02:00.000Z",
      open_positions: 1,
      realized_pnl: 12.5,
      signals_seen: 3,
      unrealized_pnl: 2.5
    }
  };
}
