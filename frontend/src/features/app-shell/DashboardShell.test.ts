import { describe, expect, it } from "vitest";

import { scannerTopbarStatus } from "./DashboardShell";

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
