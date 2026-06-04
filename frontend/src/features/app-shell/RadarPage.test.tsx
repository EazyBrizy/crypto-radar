import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RadarPage } from "./RadarPage";

vi.mock("next/dynamic", () => ({
  default: () => () => null
}));

describe("RadarPage", () => {
  it("emits Radar display mode changes from the mode switch", () => {
    const onRadarDisplayModeChange = vi.fn();

    render(
      <RadarPage
        busy={false}
        filter="all"
        radarDisplayMode="all_market_opportunities"
        signalView="open"
        statusFilter="all"
        health={null}
        loading={false}
        onFilterChange={vi.fn()}
        onAcceptPendingEntry={vi.fn()}
        onCancelPendingEntry={vi.fn()}
        onReconfirmPendingEntry={vi.fn()}
        onRadarDisplayModeChange={onRadarDisplayModeChange}
        onSignalViewChange={vi.fn()}
        onStatusFilterChange={vi.fn()}
        onConfirmRealTrade={vi.fn()}
        onPaperTrade={vi.fn()}
        onRefresh={vi.fn()}
        onReject={vi.fn()}
        onSelectSignal={vi.fn()}
        radarStatus={null}
        selectedSignal={null}
        selectedSignalId={null}
        signalIds={[]}
        signals={[]}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "execution ready" }));

    expect(onRadarDisplayModeChange).toHaveBeenCalledWith("execution_ready");
  });

  it("renders scanner universe activity metrics", () => {
    render(
      <RadarPage
        busy={false}
        filter="all"
        radarDisplayMode="all_market_opportunities"
        signalView="open"
        statusFilter="all"
        health={null}
        loading={false}
        onFilterChange={vi.fn()}
        onAcceptPendingEntry={vi.fn()}
        onCancelPendingEntry={vi.fn()}
        onReconfirmPendingEntry={vi.fn()}
        onRadarDisplayModeChange={vi.fn()}
        onSignalViewChange={vi.fn()}
        onStatusFilterChange={vi.fn()}
        onConfirmRealTrade={vi.fn()}
        onPaperTrade={vi.fn()}
        onRefresh={vi.fn()}
        onReject={vi.fn()}
        onSelectSignal={vi.fn()}
        radarStatus={{
          status: "ok",
          scanner_enabled: true,
          scanner_running: true,
          scanner_stopping: false,
          processed_signals: 0,
          exchanges: ["bybit"],
          symbols: ["BTCUSDT"],
          scan_pairs: ["bybit:XRPUSDT", "bybit:BTCUSDT"],
          scanner_pairs_count: 2,
          scanner_universe_source: "explicit pairs + default",
          scanner_universe_warning: null,
          estimated_strategy_checks: 12,
          max_scanner_pairs: 200,
          timeframes: ["15m", "1h"],
          strategies: ["trend_pullback_continuation"],
          scanner_subscription_hash: "hash",
          strategy_config_hash: "hash",
          ticks_processed: 0,
          candles_updated: 0,
          features_built: 0,
          strategy_evaluations: 0,
          signals_found: 1,
          candles_seeded: 10,
          last_tick_at: null,
          last_signal_at: null,
          last_exchange: null,
          last_symbol: null,
          last_price: null,
          candle_history: {}
        }}
        selectedSignal={null}
        selectedSignalId={null}
        signalIds={[]}
        signals={[]}
      />
    );

    expect(screen.getByText("Pairs: 2")).toBeInTheDocument();
    expect(screen.getByText("Universe: explicit pairs + default")).toBeInTheDocument();
    expect(screen.getByText("Estimated evaluations: 12")).toBeInTheDocument();
  });
});
