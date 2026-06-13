import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { MarketPairOption, StrategyConfig } from "@/features/server-state/types";
import { I18nProvider } from "@/i18n";
import { StrategyTestingPanel } from "./StrategyTestingPanel";

const mocks = vi.hoisted(() => ({
  activeRun: null as unknown,
  cancelStrategyTest: vi.fn(),
  publishCalibration: vi.fn(),
  report: null as unknown,
  reportQueries: [] as Array<{
    options?: { enabled?: boolean; refetchInterval?: number | false };
    runId: string | null;
  }>,
  reportError: null as Error | null,
  runStrategyTest: vi.fn(),
  runs: [] as unknown[]
}));

vi.mock("@/hooks/use-radar-queries", () => ({
  useCancelStrategyTestRun: () => ({
    error: null,
    isPending: false,
    mutateAsync: mocks.cancelStrategyTest
  }),
  usePublishStrategyTestCalibration: () => ({
    data: null,
    error: null,
    isPending: false,
    mutateAsync: mocks.publishCalibration
  }),
  useRunStrategyTest: () => ({
    error: null,
    isPending: false,
    mutateAsync: mocks.runStrategyTest
  }),
  useStrategyTestReport: (
    runId: string | null,
    options?: { enabled?: boolean; refetchInterval?: number | false }
  ) => {
    mocks.reportQueries.push({ runId, options });
    return {
      data: mocks.report,
      error: mocks.reportError,
      isLoading: false
    };
  },
  useStrategyTestActiveRun: () => ({
    data: mocks.activeRun,
    error: null,
    isFetching: false,
    isLoading: false,
    refetch: vi.fn()
  }),
  useStrategyTestRuns: () => ({
    data: mocks.runs,
    error: null,
    isLoading: false
  })
}));

vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: () => ({
    getTotalSize: () => 128,
    getVirtualItems: () => [],
    measureElement: vi.fn()
  })
}));

describe("StrategyTestingPanel", () => {
  afterEach(() => {
    mocks.activeRun = null;
    mocks.cancelStrategyTest.mockReset();
    mocks.publishCalibration.mockReset();
    mocks.report = null;
    mocks.reportQueries = [];
    mocks.reportError = null;
    mocks.runStrategyTest.mockReset();
    mocks.runs = [];
    window.localStorage.removeItem("crypto-radar:locale");
  });

  it("renders the mode selector", () => {
    renderPanel();

    expect(screen.getByRole("button", { name: "Research virtual" })).toHaveClass("active");
    expect(screen.getByRole("button", { name: "Production-like" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Forward virtual" })).toBeInTheDocument();
  });

  it("localizes strategy testing count badges through the DOM localizer", async () => {
    window.localStorage.setItem("crypto-radar:locale", "ru");
    mocks.runs = [
      strategyTestRun({
        run_id: "77777777-7777-4777-8777-777777777777",
        status: "completed"
      })
    ];

    render(
      <I18nProvider>
        <StrategyTestingPanel availablePairs={[marketPair()]} strategyConfigs={[strategyConfig()]} />
      </I18nProvider>
    );

    expect(await screen.findByText("3 сценария")).toBeInTheDocument();
    expect(screen.getByText("1 недавний запуск")).toBeInTheDocument();
    expect(screen.queryByText("3 scenarios")).not.toBeInTheDocument();
    expect(screen.queryByText("1 recent runs")).not.toBeInTheDocument();
  });

  it("disables Run when the matrix is missing", () => {
    renderPanel({ availablePairs: [], strategyConfigs: [] });

    expect(screen.getByText("No enabled strategies")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run strategy test/u })).toBeDisabled();
  });

  it("disables Run and shows backend reason while another strategy test is active", () => {
    mocks.activeRun = activeRunState({
      active_run: strategyTestRun({
        run_id: "22222222-2222-4222-8222-222222222222",
        status: "running"
      }),
      can_run: false,
      disabled_reason: "Backend says another strategy test run is active.",
      disabled_reason_code: "active_strategy_test_run",
      is_stale: false
    });

    renderPanel();

    expect(screen.getByText("Run in progress")).toBeInTheDocument();
    expect(screen.getByText(/Backend says another strategy test run is active/u)).toBeInTheDocument();
    const notice = screen.getByLabelText("Active strategy test run");
    expect(within(notice).getByText("Active run 22222222")).toBeInTheDocument();
    expect(within(notice).getByText("running")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run strategy test/u })).toBeDisabled();
  });

  it("shows cancel action for stale active run from backend state", async () => {
    const user = userEvent.setup();
    mocks.activeRun = activeRunState({
      active_run: strategyTestRun({
        run_id: "33333333-3333-4333-8333-333333333333",
        status: "running"
      }),
      allowed_actions: ["refresh", "cancel"],
      can_run: true,
      is_stale: true
    });
    mocks.cancelStrategyTest.mockResolvedValue(strategyTestRun({
      run_id: "33333333-3333-4333-8333-333333333333",
      status: "cancelled"
    }));

    renderPanel();

    const notice = screen.getByLabelText("Active strategy test run");
    expect(within(notice).getByText("Stale active run")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Cancel run/u }));

    expect(mocks.cancelStrategyTest).toHaveBeenCalledWith("33333333-3333-4333-8333-333333333333");
  });

  it("cancels a blocking active run through the backend action", async () => {
    const user = userEvent.setup();
    mocks.activeRun = activeRunState({
      active_run: strategyTestRun({
        run_id: "44444444-4444-4444-8444-444444444444",
        status: "running"
      }),
      allowed_actions: ["refresh", "cancel"],
      can_run: false,
      disabled_reason: "Backend says the active run must be cancelled before starting another.",
      disabled_reason_code: "active_strategy_test_run",
      is_stale: false
    });
    mocks.cancelStrategyTest.mockResolvedValue(strategyTestRun({
      run_id: "44444444-4444-4444-8444-444444444444",
      status: "cancelled"
    }));

    renderPanel();

    const notice = screen.getByLabelText("Active strategy test run");
    expect(within(notice).getByText(/Backend says the active run/u)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run strategy test/u })).toBeDisabled();
    await user.click(within(notice).getByRole("button", { name: /Cancel run/u }));

    expect(mocks.cancelStrategyTest).toHaveBeenCalledWith("44444444-4444-4444-8444-444444444444");
  });

  it("enables Run when backend reports no active run and form is valid", async () => {
    mocks.activeRun = activeRunState({ active_run: null, can_run: true, is_stale: false });

    renderPanel();

    await waitFor(() => expect(screen.getByRole("button", { name: /Run strategy test/u })).toBeEnabled());
  });

  it("runs with selected strategies, pairs, and timeframes", async () => {
    const user = userEvent.setup();
    mocks.runStrategyTest.mockResolvedValue({
      created_at: "2026-06-02T00:00:00.000Z",
      error: null,
      finished_at: null,
      last_heartbeat_at: null,
      requested_matrix: { pairs: [{ exchange: "bybit", symbol: "BTCUSDT" }], scenario_count: 3, strategies: ["trend_pullback_continuation"], timeframes: ["1m", "5m", "15m"] },
      run_id: "11111111-1111-4111-8111-111111111111",
      runtime_state: {},
      started_at: null,
      status: "queued",
      summary: {},
      test_type: "historical_backtest"
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
      timeframes: ["1m", "5m", "15m"]
    }));
  });

  it("runs a forward virtual strategy test when selected", async () => {
    const user = userEvent.setup();
    mocks.runStrategyTest.mockResolvedValue(strategyTestRun({
      status: "queued",
      test_type: "forward_virtual"
    }));

    renderPanel();

    await user.click(screen.getByRole("button", { name: "Forward virtual" }));
    const runButton = screen.getByRole("button", { name: /Run strategy test/u });
    await waitFor(() => expect(runButton).toBeEnabled());
    await user.click(runButton);

    await waitFor(() => expect(mocks.runStrategyTest).toHaveBeenCalledTimes(1));
    expect(mocks.runStrategyTest).toHaveBeenCalledWith(expect.objectContaining({
      tags: ["forward_virtual"],
      test_type: "forward_virtual"
    }));
  });

  it("shows signal funnel summary for a completed run", () => {
    mocks.runs = [
      strategyTestRun({
        status: "completed",
        summary: {
          closed: 7,
          entry_touched: 8,
          execution_candidates: 9,
          filled: 7,
          no_entry: 2,
          signals_count: 11,
          trades_count: 7
        },
        test_type: "historical_backtest"
      })
    ];

    renderPanel();

    const funnel = screen.getByLabelText("Strategy test funnel summary");
    expect(within(funnel).getByText("11 signals")).toBeInTheDocument();
    expect(within(funnel).getByText("9 candidates")).toBeInTheDocument();
    expect(within(funnel).getByText("8 touched")).toBeInTheDocument();
    expect(within(funnel).getByText("2 no entry")).toBeInTheDocument();
  });

  it("does not request a report while the selected run is still active", async () => {
    const user = userEvent.setup();
    const runningRun = strategyTestRun({
      run_id: "55555555-5555-4555-8555-555555555555",
      status: "running"
    });
    mocks.runs = [runningRun];

    renderPanel();

    const notice = screen.getByLabelText("Active strategy test run");
    await user.click(within(notice).getByRole("button", { name: "Open report" }));

    const selectedReportQuery = mocks.reportQueries.find((query) => query.runId === runningRun.run_id);
    expect(selectedReportQuery?.options).toEqual({
      enabled: false,
      refetchInterval: false
    });
  });

  it("does not request a report for an active run before it appears in the runs list", async () => {
    const user = userEvent.setup();
    const activeRun = strategyTestRun({
      run_id: "66666666-6666-4666-8666-666666666666",
      status: "running"
    });
    mocks.activeRun = activeRunState({
      active_run: activeRun,
      can_run: false,
      is_stale: false
    });

    renderPanel();

    const notice = screen.getByLabelText("Active strategy test run");
    await user.click(within(notice).getByRole("button", { name: "Open report" }));

    const selectedReportQuery = mocks.reportQueries.find((query) => query.runId === activeRun.run_id);
    expect(selectedReportQuery?.options).toEqual({
      enabled: false,
      refetchInterval: false
    });
  });
});

function renderPanel({
  availablePairs = [marketPair()],
  strategyConfigs = [strategyConfig()]
}: {
  availablePairs?: MarketPairOption[];
  strategyConfigs?: StrategyConfig[];
} = {}) {
  render(<StrategyTestingPanel availablePairs={availablePairs} strategyConfigs={strategyConfigs} />);
}

function activeRunState(overrides: Record<string, unknown> = {}) {
  return {
    active_run: null,
    allowed_actions: ["refresh"],
    can_run: true,
    disabled_reason: null,
    disabled_reason_code: null,
    is_stale: false,
    stale_threshold_seconds: 900,
    ...overrides
  };
}

function strategyTestRun(overrides: Record<string, unknown> = {}) {
  return {
    created_at: "2026-06-02T00:00:00.000Z",
    error: null,
    finished_at: null,
    last_heartbeat_at: "2026-06-02T00:01:00.000Z",
    requested_matrix: { scenario_count: 3 },
    run_id: "22222222-2222-4222-8222-222222222222",
    runtime_state: {},
    started_at: "2026-06-02T00:00:00.000Z",
    status: "running",
    summary: {},
    test_type: "forward_virtual",
    ...overrides
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
