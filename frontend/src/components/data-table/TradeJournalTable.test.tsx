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
  source: "virtual",
  tags: [],
  run_id: null,
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

  it("shows backtest source and disables market close", async () => {
    const user = userEvent.setup();
    const onCloseMarket = vi.fn();
    const backtestTrade: TradeJournalEntry = {
      ...baseTrade,
      id: "backtest_trade_1",
      source: "backtest",
      tags: ["backtest", "research"],
      run_id: "11111111-1111-4111-8111-111111111111"
    };

    render(<TradeJournalTable onCloseMarket={onCloseMarket} trades={[backtestTrade]} />);

    expect(screen.getByText("backtest")).toBeInTheDocument();
    expect(screen.getByText("run 11111111")).toBeInTheDocument();

    const closeButton = screen.getByLabelText("Close ETHUSDT at market");
    expect(closeButton).toBeDisabled();

    await user.click(closeButton);

    expect(onCloseMarket).not.toHaveBeenCalled();
  });

  it("shows virtual lifecycle target and PnL state", () => {
    const lifecycleTrade: TradeJournalEntry = {
      ...baseTrade,
      current_stop_loss: 2_100,
      remaining_quantity: 0.025,
      stop_moved_to_breakeven: true,
      trailing_active: true,
      realized_pnl: 3.25,
      unrealized_pnl: 1.75,
      target_states: [
        {
          label: "TP1",
          price: 2_150,
          close_percent: 40,
          action: "partial_close",
          hit: true,
          hit_at: "2026-05-28T10:30:00.000Z",
          closed_quantity: 0.0188,
          closed_size_usd: 40,
          realized_pnl: 3.25,
          exit_fee: 0.05
        },
        {
          label: "TP2",
          price: 2_200,
          close_percent: 30,
          action: "reduce_runner",
          hit: false,
          hit_at: null,
          closed_quantity: 0,
          closed_size_usd: 0,
          realized_pnl: 0,
          exit_fee: 0
        }
      ]
    };

    render(<TradeJournalTable trades={[lifecycleTrade]} />);

    expect(screen.getByText("TP1 hit")).toBeInTheDocument();
    expect(screen.getByText("BE")).toBeInTheDocument();
    expect(screen.getByText("Trail")).toBeInTheDocument();
    expect(screen.getByText(/Remain/u)).toBeInTheDocument();
    expect(screen.getByText(/R \+\$3\.25 \/ U \+\$1\.75/u)).toBeInTheDocument();
  });
});
