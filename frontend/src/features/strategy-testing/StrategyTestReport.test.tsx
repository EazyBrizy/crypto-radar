import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StrategyTestReport } from "./StrategyTestReport";
import type { StrategyTestReport as StrategyTestReportData } from "./types";

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

  it("renders signal funnel stages and no-entry signals", () => {
    render(<StrategyTestReport report={report()} run={null} />);

    expect(screen.getByText("Signal funnel")).toBeInTheDocument();
    expect(screen.getByText("No entry")).toBeInTheDocument();
    expect(screen.getByText("signal-1")).toBeInTheDocument();
    expect(screen.getByText("not_selected")).toBeInTheDocument();
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
        summary: {
          entry_touch_rate: 0.5,
          expectancy_r: -0.2,
          mode: "research_virtual",
          no_entry_rate: 0.5,
          scenario_count: 1,
          signals_count: 2,
          winrate: 0.58
        },
        warnings: []
      },
      {
        code: "signal_funnel",
        metadata: { stages: [{ count: 1, rate: 0.5, stage: "no_entry" }] },
        metrics: [
          { code: "signals_count", label: "Signals Count", sample_size: 2, value: 2, warnings: [] },
          { code: "entry_touch_rate", label: "Entry Touch Rate", sample_size: 2, value: 0.5, warnings: [] }
        ],
        name: "Signal funnel",
        rows: [
          {
            blocked_reason_code: "not_selected",
            direction: "long",
            funnel_stage: "no_entry",
            signal_score: 82,
            strategy_code: "trend_pullback_continuation",
            symbol: "BTCUSDT",
            synthetic_signal_id: "signal-1",
            timeframe: "1h"
          }
        ],
        summary: {
          closed: 1,
          entry_touched: 1,
          execution_candidates: 2,
          filled: 1,
          losses: 0,
          no_entry: 1,
          signals_count: 2,
          stages: [{ count: 1, rate: 0.5, stage: "no_entry" }],
          wins: 1
        },
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
    summary: { entry_touch_rate: 0.5, expectancy_r: -0.2, no_entry_rate: 0.5, scenario_count: 1, signals_count: 2, trades_count: 1, winrate: 0.58 },
    summary_metrics: [{ code: "winrate", label: "Winrate", sample_size: 12, value: 0.58, warnings: [] }],
    trades_count: 1,
    warnings: []
  };
  return { ...base, ...overrides };
}
