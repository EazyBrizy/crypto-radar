import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { MarketPairOption, StrategyConfig } from "@/features/server-state/types";
import { StrategyTestingPanel } from "./StrategyTestingPanel";

const mocks = vi.hoisted(() => ({
  report: null as unknown,
  reportError: null as Error | null,
  runStrategyTest: vi.fn(),
  runs: [] as unknown[],
  useStrategyTestStatus: vi.fn(() => ({
    data: null,
    error: null,
    isLoading: false
  }))
}));

vi.mock("@/hooks/use-radar-queries", () => ({
  useCancelStrategyTestRun: () => ({
    error: null,
    isPending: false,
    mutateAsync: vi.fn()
  }),
  usePublishStrategyTestCalibration: () => ({
    error: null,
    isPending: false,
    mutateAsync: vi.fn()
  }),
  useRunStrategyTest: () => ({
    error: null,
    isPending: false,
    mutateAsync: mocks.runStrategyTest
  }),
  useStrategyTestReport: () => ({
    data: mocks.report,
    error: mocks.reportError,
    isLoading: false
  }),
  useStrategyTestRuns: () => ({
    data: mocks.runs,
    error: null,
    isLoading: false
  }),
  useStrategyTestStatus: mocks.useStrategyTestStatus
}));

vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => 128,
    getVirtualItems: () => Array.from({ length: count }, (_, index) => ({
      index,
      key: index,
      size: 70,
      start: index * 70
    })),
    measureElement: vi.fn()
  })
}));

describe("StrategyTestingPanel", () => {
  afterEach(() => {
    mocks.report = null;
    mocks.reportError = null;
    mocks.runStrategyTest.mockReset();
    mocks.runs = [];
    mocks.useStrategyTestStatus.mockReset();
    mocks.useStrategyTestStatus.mockReturnValue({
      data: null,
      error: null,
      isLoading: false
    });
  });

  it("renders the mode selector", () => {
    renderPanel();

    expect(screen.getByRole("button", { name: "Исторический virtual backtest" })).toHaveClass("active");
    expect(screen.getByRole("button", { name: "Production-like backtest" })).toBeInTheDocument();
    expect(screen.getByTitle("Historical backtest uses closed candles and does not affect live radar/trades.")).toBeInTheDocument();
  });

  it("renders Backtest and Forward test tabs", () => {
    renderPanel();

    expect(screen.getByRole("tab", { name: "Backtest" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Forward test" })).toBeInTheDocument();
  });

  it("shows forward-specific settings", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getByRole("tab", { name: "Forward test" }));

    expect(screen.getByText("Forward test runs in background with isolated virtual account.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "4h" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "12h" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "24h" })).toBeInTheDocument();
    expect(screen.getByLabelText("Same candle policy")).toBeInTheDocument();
  });

  it("disables Run when the matrix is missing", () => {
    renderPanel({ availablePairs: [], strategyConfigs: [] });

    expect(screen.getByText("No enabled strategies")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run strategy test/u })).toBeDisabled();
  });

  it("disables Run while another strategy test is active", () => {
    mocks.runs = [{
      created_at: "2026-06-02T00:00:00.000Z",
      error: null,
      finished_at: null,
      requested_matrix: { scenario_count: 3 },
      run_id: "22222222-2222-4222-8222-222222222222",
      started_at: null,
      status: "queued",
      summary: {}
    }];

    renderPanel();

    expect(screen.getByText("Run in progress")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run strategy test/u })).toBeDisabled();
  });

  it("runs with selected strategies, pairs, and timeframes", async () => {
    const user = userEvent.setup();
    mocks.runStrategyTest.mockResolvedValue({
      created_at: "2026-06-02T00:00:00.000Z",
      error: null,
      finished_at: null,
      requested_matrix: { pairs: [{ exchange: "bybit", symbol: "BTCUSDT" }], scenario_count: 3, strategies: ["trend_pullback_continuation"], timeframes: ["1m", "5m", "15m"] },
      run_id: "11111111-1111-4111-8111-111111111111",
      started_at: null,
      status: "queued",
      summary: {}
    });

    renderPanel();

    const runButton = screen.getByRole("button", { name: /Run strategy test/u });
    await waitFor(() => expect(runButton).toBeEnabled());

    await user.click(runButton);

    await waitFor(() => expect(mocks.runStrategyTest).toHaveBeenCalledTimes(1));
    expect(mocks.runStrategyTest).toHaveBeenCalledWith(expect.objectContaining({
      fee_rate: 0.001,
      initial_capital: 1000,
      mode: "research_virtual",
      pairs: [{ exchange: "bybit", symbol: "BTCUSDT" }],
      same_candle_policy: "stop_first",
      slippage_bps: 0,
      strategies: ["trend_pullback_continuation"],
      tags: ["backtest"],
      test_type: "historical_backtest",
      timeframes: ["1m", "5m", "15m"]
    }));
  });

  it("starts forward test request with forward_virtual test type", async () => {
    const user = userEvent.setup();
    mocks.runStrategyTest.mockResolvedValue({
      created_at: "2026-06-02T00:00:00.000Z",
      error: null,
      finished_at: null,
      requested_matrix: { scenario_count: 3, test_type: "forward_virtual" },
      run_id: "11111111-1111-4111-8111-111111111111",
      started_at: null,
      status: "queued",
      summary: {}
    });

    renderPanel();

    await user.click(screen.getByRole("tab", { name: "Forward test" }));
    await user.click(screen.getByRole("button", { name: /Start forward test/u }));

    await waitFor(() => expect(mocks.runStrategyTest).toHaveBeenCalledTimes(1));
    expect(mocks.runStrategyTest).toHaveBeenCalledWith(expect.objectContaining({
      mode: "research_virtual",
      tags: ["forward_test"],
      test_type: "forward_virtual"
    }));
  });

  it("polls selected active forward status every 2.5s", async () => {
    const user = userEvent.setup();
    mocks.runStrategyTest.mockResolvedValue(forwardRunResponse());

    renderPanel();

    await user.click(screen.getByRole("tab", { name: "Forward test" }));
    await user.click(screen.getByRole("button", { name: /Start forward test/u }));

    await waitFor(() => expect(mocks.useStrategyTestStatus).toHaveBeenCalledWith(
      "11111111-1111-4111-8111-111111111111",
      expect.objectContaining({ enabled: true, refetchInterval: 2500 })
    ));
  });

  it("includes new advanced params", async () => {
    const user = userEvent.setup();
    mocks.runStrategyTest.mockResolvedValue({
      created_at: "2026-06-02T00:00:00.000Z",
      error: null,
      finished_at: null,
      requested_matrix: { scenario_count: 3 },
      run_id: "11111111-1111-4111-8111-111111111111",
      started_at: null,
      status: "queued",
      summary: {}
    });

    renderPanel();

    await user.selectOptions(screen.getByLabelText("Signal selection"), "highest_score");
    await replaceNumber(user, screen.getByLabelText("Max concurrent positions"), "4");
    await replaceNumber(user, screen.getByLabelText("Max positions per symbol"), "2");
    await replaceNumber(user, screen.getByLabelText("Cooldown bars after close"), "3");
    await user.click(screen.getByLabelText("Allow opposite signal flip"));
    await replaceNumber(user, screen.getByLabelText("Max bars in trade"), "12");
    await user.click(screen.getByRole("button", { name: /Run strategy test/u }));

    await waitFor(() => expect(mocks.runStrategyTest).toHaveBeenCalledTimes(1));
    expect(mocks.runStrategyTest).toHaveBeenCalledWith(expect.objectContaining({
      params: {
        allow_opposite_signal_flip: true,
        cooldown_bars_after_close: 3,
        max_bars_in_trade: 12,
        max_concurrent_positions: 4,
        max_positions_per_symbol: 2,
        signal_selection_policy: "highest_score"
      }
    }));
  });
});

async function replaceNumber(user: ReturnType<typeof userEvent.setup>, input: HTMLElement, value: string) {
  await user.clear(input);
  await user.type(input, value);
}

function renderPanel({
  availablePairs = [marketPair()],
  strategyConfigs = [strategyConfig()]
}: {
  availablePairs?: MarketPairOption[];
  strategyConfigs?: StrategyConfig[];
} = {}) {
  render(<StrategyTestingPanel availablePairs={availablePairs} strategyConfigs={strategyConfigs} />);
}

function forwardRunResponse() {
  return {
    created_at: "2026-06-02T00:00:00.000Z",
    error: null,
    finished_at: null,
    requested_matrix: { scenario_count: 3, test_type: "forward_virtual" as const },
    run_id: "11111111-1111-4111-8111-111111111111",
    started_at: "2026-06-02T00:00:00.000Z",
    status: "running" as const,
    summary: { signals_seen: 3 }
  };
}

function marketPair(): MarketPairOption {
  return {
    base_asset: "BTC",
    exchange: "bybit",
    id: "pair_btc",
    quote_asset: "USDT",
    status: "active",
    symbol: "BTCUSDT"
  };
}

function strategyConfig(): StrategyConfig {
  return {
    created_at: "2026-06-02T00:00:00.000Z",
    exchanges: ["bybit"],
    id: "strategy_config_1",
    is_enabled: true,
    name: "Trend pullback",
    pairs: [{ exchange: "bybit", symbol: "BTCUSDT" }],
    params: {},
    risk_settings: {},
    strategy_code: "trend_pullback_continuation",
    strategy_name: "Trend Pullback",
    strategy_version: "1.0.0",
    strategy_version_id: "strategy_version_1",
    timeframes: ["1m", "5m", "15m"],
    updated_at: "2026-06-02T00:00:00.000Z",
    user_id: "demo_user"
  };
}
