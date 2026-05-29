import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { TradeJournalEntry } from "@/types";
import { TradeJournalTable } from "./TradeJournalTable";

vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: () => ({
    getTotalSize: () => 128,
    getVirtualItems: () => [
      { index: 0, start: 0 },
      { index: 1, start: 64 }
    ],
    measureElement: vi.fn()
  })
}));

const baseTrade: TradeJournalEntry = {
  id: "trade_1",
  user_id: "demo_user",
  signal_id: "sig_1",
  mode: "virtual",
  exchange: "bybit",
  symbol: "ETHUSDT",
  strategy: "EMA_PULLBACK",
  timeframe: "15m",
  side: "long",
  entry_price: 2_100,
  current_price: 2_125,
  exit_price: null,
  size_usd: 100,
  quantity: 0.047,
  leverage: 2,
  risk_percent: 1,
  risk_amount: 10,
  risk_reward: 3,
  stop_loss: 2_060,
  take_profit: [2_180],
  fees: 0,
  slippage_bps: 2,
  simulation_mode: "passive",
  execution_status: "filled",
  requested_size_usd: 100,
  filled_size_usd: 100,
  unfilled_size_usd: 0,
  execution: null,
  status: "open",
  result: null,
  close_reason: null,
  pnl: 1.2,
  pnl_percent: 1.2,
  mfe: 1.4,
  mae: 0,
  screenshots: [],
  ai_review: null,
  opened_at: "2026-05-28T10:00:00.000Z",
  updated_at: "2026-05-28T10:01:00.000Z",
  closed_at: null
};

describe("TradeJournalTable", () => {
  it("selects a trade when the row is clicked", async () => {
    const user = userEvent.setup();
    const onSelectTrade = vi.fn();
    const secondTrade = { ...baseTrade, id: "trade_2", symbol: "BTCUSDT" };

    render(
      <TradeJournalTable
        onSelectTrade={onSelectTrade}
        selectedTradeId="trade_2"
        trades={[baseTrade, secondTrade]}
      />
    );

    await user.click(screen.getByText("ETHUSDT"));

    expect(onSelectTrade).toHaveBeenCalledWith(baseTrade);
    expect(screen.getByText("BTCUSDT").closest('[role="row"]')).toHaveClass("selected");
  });

  it("runs market close action without selecting the row", async () => {
    const user = userEvent.setup();
    const onCloseMarket = vi.fn();
    const onSelectTrade = vi.fn();

    render(
      <TradeJournalTable
        onCloseMarket={onCloseMarket}
        onSelectTrade={onSelectTrade}
        trades={[baseTrade]}
      />
    );

    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();

    await user.click(screen.getByLabelText("Close ETHUSDT at market"));

    expect(onCloseMarket).toHaveBeenCalledWith(baseTrade);
    expect(onSelectTrade).not.toHaveBeenCalled();
  });
});
