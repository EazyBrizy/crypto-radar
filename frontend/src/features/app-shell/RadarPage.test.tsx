import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { PendingEntryIntent } from "@/types";
import { RadarPage } from "./RadarPage";

vi.mock("next/dynamic", () => ({
  default: () => () => null
}));

afterEach(() => {
  window.localStorage.clear();
});

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
        onSelectLatestSignal={vi.fn()}
        onSelectPendingEntrySignal={vi.fn()}
        onSelectSignal={vi.fn()}
        radarStatus={null}
        selectedSignal={null}
        selectedSignalId={null}
        pendingEntries={[]}
        pendingEntryHistory={[]}
        signalIds={[]}
        signals={[]}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "Hot" }));

    expect(onRadarDisplayModeChange).toHaveBeenCalledWith("execution_ready");
  });

  it("renders distinct feed-kind filters", () => {
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
        onSelectLatestSignal={vi.fn()}
        onSelectPendingEntrySignal={vi.fn()}
        onSelectSignal={vi.fn()}
        radarStatus={null}
        selectedSignal={null}
        selectedSignalId={null}
        pendingEntries={[]}
        pendingEntryHistory={[]}
        signalIds={[]}
        signals={[]}
      />
    );

    expect(screen.getByRole("button", { name: "Hot" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Watchlist" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Diagnostics" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Blocked" })).toBeInTheDocument();
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
        onSelectLatestSignal={vi.fn()}
        onSelectPendingEntrySignal={vi.fn()}
        onSelectSignal={vi.fn()}
        radarStatus={{
          status: "ok",
          scanner_enabled: true,
          scanner_running: true,
          scanner_stopping: false,
          stage: "warming_up",
          market_data_status: "waiting",
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
          warmup_total: 4,
          warmup_completed: 2,
          warmup_failed: 1,
          warmup_started_at: Date.parse("2026-06-05T10:00:00.000Z"),
          warmup_finished_at: null,
          last_tick_at: null,
          last_tick_age_seconds: null,
          last_signal_at: null,
          last_exchange: null,
          last_symbol: null,
          last_price: null,
          last_error: "timeout BTCUSDT 1m",
          market_stream_connected: false,
          ws_connected: false,
          candle_history: {}
        }}
        selectedSignal={null}
        selectedSignalId={null}
        pendingEntries={[]}
        pendingEntryHistory={[]}
        signalIds={[]}
        signals={[]}
      />
    );

    expect(screen.getByText("Pairs: 2")).toBeInTheDocument();
    expect(screen.getByText("Universe: explicit pairs + default")).toBeInTheDocument();
    expect(screen.getByText("Estimated evaluations: 12")).toBeInTheDocument();
    expect(screen.getAllByText("Connecting").length).toBeGreaterThan(0);
    expect(screen.getByText("Warmup: 2/4, failed 1")).toBeInTheDocument();
    expect(screen.getByText("Last tick: no ticks yet")).toBeInTheDocument();
    expect(screen.getByText("Last error: timeout BTCUSDT 1m")).toBeInTheDocument();
    expect(screen.queryByText("Online")).not.toBeInTheDocument();
  });

  it("shows terminal pending-entry reason codes in the queue history", () => {
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
        onSelectLatestSignal={vi.fn()}
        onSelectPendingEntrySignal={vi.fn()}
        onSelectSignal={vi.fn()}
        radarStatus={null}
        selectedSignal={null}
        selectedSignalId={null}
        pendingEntries={[]}
        pendingEntryHistory={[
          pendingIntent({
            status: "expired",
            reason_code: "pending_entry_expired_before_touch",
            failure_reason: "Pending entry intent expired before entry touch.",
            view: {
              status_label: "Expired",
              status_tone: "red",
              reason_code: "pending_entry_expired_before_touch",
              reason: "Pending entry intent expired before entry touch.",
              entry_zone: "2100 - 2105",
              current_price: 2_120
            }
          })
        ]}
        signalIds={[]}
        signals={[]}
      />
    );

    expect(screen.getByText("pending_entry_expired_before_touch")).toBeInTheDocument();
    expect(screen.getByText("Pending entry expired before entry touch")).toBeInTheDocument();
  });

  it("enables cancel for an active pending entry without action state", () => {
    const onCancelPendingEntry = vi.fn();
    const intent = pendingIntent({ status: "pending" });

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
        onCancelPendingEntry={onCancelPendingEntry}
        onReconfirmPendingEntry={vi.fn()}
        onRadarDisplayModeChange={vi.fn()}
        onSignalViewChange={vi.fn()}
        onStatusFilterChange={vi.fn()}
        onConfirmRealTrade={vi.fn()}
        onPaperTrade={vi.fn()}
        onRefresh={vi.fn()}
        onReject={vi.fn()}
        onSelectLatestSignal={vi.fn()}
        onSelectPendingEntrySignal={vi.fn()}
        onSelectSignal={vi.fn()}
        radarStatus={null}
        selectedSignal={null}
        selectedSignalId={null}
        pendingEntries={[intent]}
        pendingEntryHistory={[]}
        signalIds={[]}
        signals={[]}
      />
    );

    const cancel = screen.getByRole("button", { name: "Cancel" });

    expect(cancel).toBeEnabled();
    fireEvent.click(cancel);
    expect(onCancelPendingEntry).toHaveBeenCalledWith(intent);
  });

  it("shows active real pending entries separately as unsupported diagnostics", () => {
    const realIntent = pendingIntent({
      id: "real_pending_1",
      mode: "real",
      status: "requires_reconfirmation",
      reason_code: "real_pending_not_implemented",
      view: {
        status_label: "Requires reconfirmation",
        status_tone: "yellow",
        reason_code: "real_pending_not_implemented",
        reason: "Real pending entry is not implemented yet. Use virtual waiting entry or manual real execution.",
        entry_zone: "2100 - 2105",
        current_price: 2_101
      }
    });

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
        onSelectLatestSignal={vi.fn()}
        onSelectPendingEntrySignal={vi.fn()}
        onSelectSignal={vi.fn()}
        radarStatus={null}
        selectedSignal={null}
        selectedSignalId={null}
        pendingEntries={[realIntent]}
        pendingEntryHistory={[]}
        signalIds={[]}
        signals={[]}
      />
    );

    expect(screen.getByText("Unsupported real pending")).toBeInTheDocument();
    expect(screen.getAllByText("Diagnostic only").length).toBeGreaterThan(0);
    expect(screen.getByText(/Real pending entry is not implemented yet/u)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reconfirm" })).not.toBeInTheDocument();
  });

  it("selects a pending entry from the whole card", () => {
    const onSelectPendingEntrySignal = vi.fn();
    const intent = pendingIntent({
      id: "intent_card",
      status: "pending",
      symbol: "ETHUSDT"
    });

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
        onSelectLatestSignal={vi.fn()}
        onSelectPendingEntrySignal={onSelectPendingEntrySignal}
        onSelectSignal={vi.fn()}
        radarStatus={null}
        selectedSignal={null}
        selectedSignalId={null}
        pendingEntries={[intent]}
        pendingEntryHistory={[]}
        signalIds={[]}
        signals={[]}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /open pending entry ETHUSDT/i }));

    expect(onSelectPendingEntrySignal).toHaveBeenCalledWith(intent);
  });

  it("collapses the pending-entry queue block", () => {
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
        onSelectLatestSignal={vi.fn()}
        onSelectPendingEntrySignal={vi.fn()}
        onSelectSignal={vi.fn()}
        radarStatus={null}
        selectedSignal={null}
        selectedSignalId={null}
        pendingEntries={[pendingIntent({ status: "pending" })]}
        pendingEntryHistory={[]}
        signalIds={[]}
        signals={[]}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "Collapse pending entries queue" }));

    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
  });

  it("hides terminal pending-entry history locally", () => {
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
        onSelectLatestSignal={vi.fn()}
        onSelectPendingEntrySignal={vi.fn()}
        onSelectSignal={vi.fn()}
        radarStatus={null}
        selectedSignal={null}
        selectedSignalId={null}
        pendingEntries={[]}
        pendingEntryHistory={[pendingIntent({
          id: "terminal_1",
          status: "expired",
          reason_code: "pending_entry_expired_before_touch",
          view: {
            status_label: "Expired",
            status_tone: "red",
            reason_code: "pending_entry_expired_before_touch",
            reason: "Pending entry intent expired before entry touch.",
            entry_zone: "2100 - 2105",
            current_price: 2_120
          }
        })]}
        signalIds={[]}
        signals={[]}
      />
    );

    expect(screen.getByText("pending_entry_expired_before_touch")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Hide pending entry terminal_1" }));

    expect(screen.queryByText("pending_entry_expired_before_touch")).not.toBeInTheDocument();
  });
});

function pendingIntent(overrides: Partial<PendingEntryIntent> = {}): PendingEntryIntent {
  return {
    id: "intent_1",
    user_id: "user_1",
    signal_id: "sig_1",
    strategy_id: null,
    mode: "virtual",
    status: "expired",
    exchange: "bybit",
    symbol: "ETHUSDT",
    side: "long",
    entry_min: 2_100,
    entry_max: 2_105,
    entry_price_policy: "accepted_entry_zone",
    stop_loss: 2_060,
    targets_snapshot: [{ label: "TP1", price: "2150" }],
    accepted_trade_plan_snapshot: {},
    accepted_trade_plan_hash: "sha256:test",
    accepted_signal_status: "ready",
    accepted_signal_version: null,
    accepted_signal_fingerprint: null,
    execution_profile_snapshot: {},
    request_snapshot: {},
    idempotency_key: "pending-entry:test",
    expires_at: null,
    created_at: "2026-05-31T07:00:00.000Z",
    updated_at: "2026-05-31T07:00:00.000Z",
    triggered_at: null,
    filled_at: null,
    filled_trade_id: null,
    failure_reason: null,
    current_price: null,
    reason_code: null,
    localized_reason: null,
    view: null,
    ...overrides
  };
}
