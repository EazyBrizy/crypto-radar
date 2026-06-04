import { describe, expect, it } from "vitest";

import { isActivePendingEntryStatus, isTerminalPendingEntryStatus } from "./pending-entry-status";

describe("pending entry status helpers", () => {
  it("separates active and terminal pending-entry states", () => {
    expect(isActivePendingEntryStatus("pending")).toBe(true);
    expect(isActivePendingEntryStatus("requires_reconfirmation")).toBe(true);
    expect(isActivePendingEntryStatus("cancelled")).toBe(false);

    expect(isTerminalPendingEntryStatus("cancelled")).toBe(true);
    expect(isTerminalPendingEntryStatus("expired")).toBe(true);
    expect(isTerminalPendingEntryStatus("pending")).toBe(false);
  });
});
