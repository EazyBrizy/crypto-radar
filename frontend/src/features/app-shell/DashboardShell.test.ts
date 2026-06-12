import { describe, expect, it } from "vitest";

import { killSwitchBannerView, scannerTopbarStatus } from "./DashboardShell";

describe("scannerTopbarStatus", () => {
  it("shows Online only for live market data", () => {
    expect(scannerTopbarStatus({
      market_data_status: "waiting",
      scanner_stopping: false,
      stage: "warming_up"
    })).toEqual({ className: "syncing-dot", text: "Scanner connecting" });

    expect(scannerTopbarStatus({
      market_data_status: "online",
      scanner_stopping: false,
      stage: "listening"
    })).toEqual({ className: "live-dot", text: "Scanner Online" });
  });

  it("maps stale and error states to explicit labels", () => {
    expect(scannerTopbarStatus({
      market_data_status: "stale",
      scanner_stopping: false,
      stage: "stale"
    })).toEqual({ className: "stale-dot", text: "Scanner data stale" });

    expect(scannerTopbarStatus({
      market_data_status: "error",
      scanner_stopping: false,
      stage: "error"
    })).toEqual({ className: "error-dot", text: "Scanner error" });
  });
});

describe("killSwitchBannerView", () => {
  it("shows execution killed and risk paused reasons", () => {
    expect(killSwitchBannerView({
      state: "manual_unlock_required",
      execution_allowed: false,
      manual_unlock_required: true,
      reason_codes: ["kill_switch_daily_loss_exceeded"],
      reasons: [{ code: "kill_switch_daily_loss_exceeded", message: "Daily loss limit exceeded." }]
    })).toEqual({
      className: "error-banner",
      title: "Execution killed",
      message: "Daily loss limit exceeded.",
      action: "Manual unlock required"
    });

    expect(killSwitchBannerView({
      state: "paused",
      execution_allowed: false,
      manual_unlock_required: false,
      reason_codes: ["kill_switch_stale_market_data"],
      reasons: [{ code: "kill_switch_stale_market_data", message: "Market data is stale." }]
    })).toEqual({
      className: "warning-banner",
      title: "Risk paused",
      message: "Market data is stale.",
      action: "Execution is paused"
    });
  });
});
