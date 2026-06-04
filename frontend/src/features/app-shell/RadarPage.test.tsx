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
});
