import { describe, expect, it } from "vitest";

import {
  isActiveTradeStatus,
  isTerminalTradeStatus,
  TRADE_STATUSES
} from "./trade-status";

describe("trade status domain", () => {
  it("classifies active and terminal virtual position statuses", () => {
    expect(TRADE_STATUSES).toEqual([
      "open",
      "partially_closed",
      "closed",
      "stopped",
      "invalidated",
      "expired",
      "cancelled"
    ]);
    expect(isActiveTradeStatus("partially_closed")).toBe(true);
    expect(isTerminalTradeStatus("stopped")).toBe(true);
    expect(isTerminalTradeStatus("partially_closed")).toBe(false);
  });
});
