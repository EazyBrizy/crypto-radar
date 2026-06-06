import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StrategyTestSignalList } from "./StrategyTestSignalList";

describe("StrategyTestSignalList", () => {
  it("renders signal and no-entry rows", () => {
    render(
      <StrategyTestSignalList
        signals={[
          {
            direction: "long",
            entry_touched: true,
            filled: true,
            no_entry: false,
            outcome: "win",
            signal_id: "signal-1",
            strategy_code: "trend_pullback_continuation",
            symbol: "BTCUSDT"
          },
          {
            direction: "long",
            entry_touched: false,
            filled: false,
            no_entry: true,
            outcome: "no_entry",
            outcome_reason: "entry_not_touched",
            signal_id: "signal-2",
            strategy_code: "trend_pullback_continuation",
            symbol: "BTCUSDT"
          }
        ]}
      />
    );

    expect(screen.getByText("signal-1")).toBeInTheDocument();
    expect(screen.getByText("signal-2")).toBeInTheDocument();
    expect(screen.getByText("no_entry / entry_not_touched")).toBeInTheDocument();
  });
});
