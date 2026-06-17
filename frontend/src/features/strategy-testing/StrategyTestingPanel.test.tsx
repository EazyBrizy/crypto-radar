import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { MarketPairOption, StrategyConfig } from "@/features/server-state/types";
import { I18nProvider } from "@/i18n";
import { StrategyTestingPanel } from "./StrategyTestingPanel";

const STRATEGY_TEST_FORM_STORAGE_KEY = "crypto-radar:strategy-testing-panel:v1:demo_user";
const STRATEGY_TEST_FORM_BASE_STORAGE_KEY = "crypto-radar:strategy-testing-panel:v1";

const mocks = vi.hoisted(() => ({
  activeRun: null as unknown,
  cancelStrategyTest: vi.fn(),
  estimate: {
    average_bars_per_scenario: 200,
    scenario_count: 3,
    scenarios: [],
    size_level: "small",
    total_bars: 600,
    warnings: []
  } as unknown,
  estimateQueries: [] as Array<{
    options?: { enabled?: boolean };
    request: unknown;
  }>,
  publishCalibration: vi.fn(),
  report: null as unknown,
  reportQueries: [] as Array<{
    options?: { enabled?: boolean; refetchInterval?: number | false };
    runId: string | null;
  }>,
  reportError: null as Error | null,
  runDetail: null as unknown,
  runDetailQueries: [] as Array<{
    options?: { enabled?: boolean; refetchInterval?: number | false };
    runId: string | null;
  }>,
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
  useStrategyTestEstimate: (
    request: unknown,
    options?: { enabled?: boolean }
  ) => {
    mocks.estimateQueries.push({ request, options });
    return {
      data: mocks.estimate,
      error: null,
      isFetching: false,
      isLoading: false
    };
  },
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
  useStrategyTestRun: (
    runId: string | null,
    options?: { enabled?: boolean; refetchInterval?: number | false }
  ) => {
    mocks.runDetailQueries.push({ runId, options });
    return {
      data: mocks.runDetail,
      error: null,
      isFetching: false,
      isLoading: false,
      refetch: vi.fn()
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
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 70,
    getVirtualItems: () => Array.from({ length: count }, (_value, index) => ({
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
    mocks.activeRun = null;
    mocks.cancelStrategyTest.mockReset();
    mocks.estimate = strategyTestEstimate();
    mocks.estimateQueries = [];
    mocks.publishCalibration.mockReset();
    mocks.report = null;
    mocks.reportQueries = [];
    mocks.reportError = null;
    mocks.runDetail = null;
    mocks.runDetailQueries = [];
    mocks.runStrategyTest.mockReset();
    mocks.runs = [];
    window.localStorage.removeItem("crypto-radar:locale");
    window.localStorage.removeItem(STRATEGY_TEST_FORM_STORAGE_KEY);
    window.localStorage.removeItem(STRATEGY_TEST_FORM_BASE_STORAGE_KEY);
  });

  it("renders the mode selector", () => {
    renderPanel();

    expect(screen.getByRole("button", { name: "Research virtual" })).toHaveClass("active");
    expect(screen.getByRole("button", { name: "Research virtual" })).toHaveAttribute(
      "title",
      expect.stringContaining("virtual execution")
    );
    expect(screen.getByRole("button", { name: "Production-like" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Forward virtual" })).toBeInTheDocument();
  });

  it("renders scanner/market data hint when forward_virtual is selected", async () => {
    const user = userEvent.setup();
    renderPanel();

    expect(screen.queryByText("Forward virtual needs scanner market data; with scanner disabled it will wait for ticks.")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Forward virtual" }));

    expect(screen.getByText("Forward virtual needs scanner market data; with scanner disabled it will wait for ticks.")).toBeInTheDocument();
  });

  it("shows a large run warning before starting a heavy matrix", async () => {
    const user = userEvent.setup();
    const availablePairs = [
      marketPair("BTCUSDT", "BTC"),
      marketPair("ETHUSDT", "ETH"),
      marketPair("SOLUSDT", "SOL"),
      marketPair("XRPUSDT", "XRP"),
      marketPair("DOGEUSDT", "DOGE"),
      marketPair("ADAUSDT", "ADA"),
      marketPair("BNBUSDT", "BNB"),
      marketPair("LINKUSDT", "LINK")
    ];
    mocks.estimate = strategyTestEstimate({
      average_bars_per_scenario: 25_920,
      scenario_count: 16,
      size_level: "large",
      total_bars: 414_720
    });

    renderPanel({
      availablePairs,
      strategyConfigs: [strategyConfig({ timeframes: ["1m", "5m"] })]
    });

    for (const pair of availablePairs.slice(3)) {
      await user.click(screen.getByRole("checkbox", { name: new RegExp(pair.symbol, "u") }));
    }

    const estimate = screen.getByLabelText("Strategy test run estimate");
    expect(within(estimate).getByText("16")).toBeInTheDocument();
    expect(within(estimate).getByText("414,720 bars total")).toBeInTheDocument();
    expect(within(estimate).getByText(/Large run/u)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Run strategy test/u }));

    expect(mocks.runStrategyTest).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Large run confirmation")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Confirm large run/u })).toBeInTheDocument();
  });

  it("renders duplicate market data estimate warnings as non-critical warnings without blocking the run", async () => {
    const user = userEvent.setup();
    const candlesCount = expectedCandles(30, 15);
    const rawRows = candlesCount * 30 + 197;
    const barsTotal = candlesCount - 200;
    const warningMessage = `bybit:BTCUSDT:15m has ${rawRows} raw candle rows for ${candlesCount} deduped candles.`;
    mocks.runStrategyTest.mockResolvedValue(strategyTestRun({
      status: "queued",
      test_type: "historical_backtest"
    }));
    mocks.estimate = strategyTestEstimate({
      scenario_count: 1,
      scenarios: [
        {
          bars_total: barsTotal,
          candles_count: candlesCount,
          duplicate_rows: rawRows - candlesCount,
          exchange: "bybit",
          raw_rows: rawRows,
          strategy: "trend_pullback_continuation",
          symbol: "BTCUSDT",
          timeframe: "15m",
          warmup_bars: 200,
          warning_codes: ["market_data_duplicates"]
        }
      ],
      size_level: "small",
      total_bars: barsTotal,
      warnings: [
        {
          code: "market_data_duplicates",
          deduped_candles: candlesCount,
          duplicate_ratio: 30.0684,
          exchange: "bybit",
          message: warningMessage,
          raw_rows: rawRows,
          symbol: "BTCUSDT",
          timeframe: "15m"
        }
      ]
    });

    renderPanel();

    const estimate = screen.getByLabelText("Strategy test run estimate");
    const warningRow = within(estimate).getByText(warningMessage).closest("div");
    if (!warningRow) throw new Error("Duplicate warning row was not rendered.");
    expect(warningRow).toHaveClass("strategy-test-estimate-warning-yellow");
    expect(warningRow).not.toHaveClass("strategy-test-large-confirmation");
    expect(within(estimate).getByText("15m")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Run strategy test/u }));

    expect(mocks.runStrategyTest).toHaveBeenCalledTimes(1);
    expect(screen.queryByLabelText("Large run confirmation")).not.toBeInTheDocument();
  });

  it("renders missing market data estimate warnings as severe", () => {
    const warningMessage = "bybit:ETHUSDT:1m is missing market data.";
    mocks.estimate = strategyTestEstimate({
      scenario_count: 1,
      scenarios: [
        {
          bars_total: 0,
          candles_count: 0,
          duplicate_rows: 0,
          exchange: "bybit",
          raw_rows: 0,
          strategy: "trend_pullback_continuation",
          symbol: "ETHUSDT",
          timeframe: "1m",
          warmup_bars: 200,
          warning_codes: ["market_data_missing"]
        }
      ],
      size_level: "small",
      total_bars: 0,
      warnings: [
        {
          code: "market_data_missing",
          exchange: "bybit",
          message: warningMessage,
          symbol: "ETHUSDT",
          timeframe: "1m"
        }
      ]
    });

    renderPanel({
      availablePairs: [marketPair("ETHUSDT", "ETH")]
    });

    const estimate = screen.getByLabelText("Strategy test run estimate");
    const warningRow = within(estimate).getByText(warningMessage).closest("div");
    if (!warningRow) throw new Error("Missing-data warning row was not rendered.");
    expect(warningRow).toHaveClass("strategy-test-estimate-warning-red");
  });

  it("builds the smoke preset request with one pair, one timeframe, three days, and production-like mode", async () => {
    const user = userEvent.setup();
    mocks.runStrategyTest.mockResolvedValue(strategyTestRun({
      status: "queued",
      test_type: "historical_backtest"
    }));

    renderPanel({
      availablePairs: [marketPair("BTCUSDT", "BTC"), marketPair("ETHUSDT", "ETH")],
      strategyConfigs: [strategyConfig({ timeframes: ["1m", "5m"] })]
    });

    await user.click(screen.getByRole("button", { name: /Smoke/u }));
    const runButton = screen.getByRole("button", { name: /Run strategy test/u });
    await waitFor(() => expect(runButton).toBeEnabled());
    await user.click(runButton);

    await waitFor(() => expect(mocks.runStrategyTest).toHaveBeenCalledTimes(1));
    const request = mocks.runStrategyTest.mock.calls[0][0];
    expect(request).toEqual(expect.objectContaining({
      mode: "production_like",
      pairs: [{ exchange: "bybit", symbol: "BTCUSDT" }],
      tags: ["backtest"],
      test_type: "historical_backtest",
      timeframes: ["1m"]
    }));
    expect(new Date(request.end_at).getTime() - new Date(request.start_at).getTime()).toBe(3 * 24 * 60 * 60 * 1000);
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

  it("shows all available pairs instead of only the first fifty", () => {
    renderPanel({ availablePairs: marketPairs(60) });

    expect(screen.getByRole("checkbox", { name: /TOKEN001USDT/u })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /TOKEN060USDT/u })).toBeInTheDocument();
  });

  it("selects all available pairs", async () => {
    const user = userEvent.setup();
    const availablePairs = marketPairs(200);

    renderPanel({ availablePairs });

    await user.click(screen.getByRole("button", { name: "Select all pairs" }));

    const pairGroup = screen.getByRole("region", { name: "Pairs" });
    const checkedPairs = within(pairGroup)
      .getAllByRole("checkbox")
      .filter((checkbox) => (checkbox as HTMLInputElement).checked);
    expect(checkedPairs).toHaveLength(200);
    expect(within(pairGroup).getByText("200 / 200 selected")).toBeInTheDocument();
  });

  it("filters pairs and selects only visible filtered pairs", async () => {
    const user = userEvent.setup();
    const availablePairs = [
      marketPair("BTCUSDT", "BTC"),
      marketPair("ETHUSDT", "ETH"),
      marketPair("SOLUSDT", "SOL"),
      marketPair("SOLUSDC", "SOL", { quote_asset: "USDC" }),
      marketPair("AVAXUSDT", "AVAX", { exchange: "okx" })
    ];

    renderPanel({ availablePairs });

    await user.click(screen.getByRole("button", { name: "Clear pairs" }));
    await user.type(screen.getByLabelText("Filter pairs"), "sol");

    expect(screen.getByRole("checkbox", { name: /SOLUSDT/u })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /SOLUSDC/u })).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: /BTCUSDT/u })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Select visible pairs" }));
    await user.clear(screen.getByLabelText("Filter pairs"));

    expect(screen.getByRole("checkbox", { name: /BTCUSDT/u })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: /ETHUSDT/u })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: /SOLUSDT/u })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /SOLUSDC/u })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /AVAXUSDT/u })).not.toBeChecked();
  });

  it("disables Run with a clear message when any matrix dimension is cleared", async () => {
    const user = userEvent.setup();
    renderPanel({
      availablePairs: [marketPair("BTCUSDT", "BTC"), marketPair("ETHUSDT", "ETH")],
      strategyConfigs: [strategyConfig({ timeframes: ["1m", "5m"] })]
    });

    await user.click(screen.getByRole("button", { name: "Clear strategies" }));
    expect(screen.getByRole("button", { name: /Run strategy test/u })).toBeDisabled();
    expect(screen.getByText("Select at least one strategy, pair, and timeframe.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Select all strategies" }));
    await user.click(screen.getByRole("button", { name: "Clear pairs" }));
    expect(screen.getByRole("button", { name: /Run strategy test/u })).toBeDisabled();
    expect(screen.getByText("Select at least one strategy, pair, and timeframe.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Select all pairs" }));
    await user.click(screen.getByRole("button", { name: "Clear timeframes" }));
    expect(screen.getByRole("button", { name: /Run strategy test/u })).toBeDisabled();
    expect(screen.getByText("Select at least one strategy, pair, and timeframe.")).toBeInTheDocument();
  });

  it("shows a local scenario count and large matrix warning", async () => {
    const user = userEvent.setup();
    renderPanel({
      availablePairs: marketPairs(200),
      strategyConfigs: [
        strategyConfig({ timeframes: ["1m", "5m", "15m", "1h"] }),
        strategyConfig({
          id: "strategy_config_2",
          name: "Mean reversion",
          strategy_code: "mean_reversion",
          strategy_name: "Mean Reversion",
          strategy_version_id: "strategy_version_2",
          timeframes: ["1m", "5m", "15m", "1h"]
        })
      ]
    });

    await user.click(screen.getByRole("button", { name: "Select all strategies" }));
    await user.click(screen.getByRole("button", { name: "Select all pairs" }));
    await user.click(screen.getByRole("button", { name: "Select all timeframes" }));

    expect(screen.getByText("1,600 scenarios selected")).toBeInTheDocument();
    expect(screen.getByText("Large matrix will run in worker. It may take a long time. Cached candles will be reused on later runs.")).toBeInTheDocument();
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
    expect(screen.getByRole("button", { name: /Run strategy test/u })).toBeEnabled();
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
      params: {
        historical_pending_entries_enabled: true,
        pending_entry_max_wait_bars: 12
      },
      same_candle_policy: "stop_first",
      slippage_bps: 0,
      strategies: ["trend_pullback_continuation"],
      tags: ["backtest"],
      timeframes: ["1m", "5m", "15m"]
    }));
  });

  it("runs with advanced historical pending settings", async () => {
    const user = userEvent.setup();
    mocks.runStrategyTest.mockResolvedValue(strategyTestRun({
      status: "queued",
      test_type: "historical_backtest"
    }));

    renderPanel();

    await user.click(screen.getByRole("checkbox", { name: /Historical pending entries/u }));
    await user.clear(screen.getByLabelText("Pending max wait bars"));
    await user.type(screen.getByLabelText("Pending max wait bars"), "4");
    const runButton = screen.getByRole("button", { name: /Run strategy test/u });
    await waitFor(() => expect(runButton).toBeEnabled());
    await user.click(runButton);

    await waitFor(() => expect(mocks.runStrategyTest).toHaveBeenCalledTimes(1));
    expect(mocks.runStrategyTest).toHaveBeenCalledWith(expect.objectContaining({
      params: {
        historical_pending_entries_enabled: false,
        pending_entry_max_wait_bars: 4
      }
    }));
  });

  it("disables historical pending params for discovery mode", async () => {
    const user = userEvent.setup();
    mocks.runStrategyTest.mockResolvedValue(strategyTestRun({
      status: "queued",
      test_type: "historical_backtest"
    }));

    renderPanel();

    await user.click(screen.getByRole("button", { name: "Discovery" }));
    const runButton = screen.getByRole("button", { name: /Run strategy test/u });
    await waitFor(() => expect(runButton).toBeEnabled());
    await user.click(runButton);

    await waitFor(() => expect(mocks.runStrategyTest).toHaveBeenCalledTimes(1));
    expect(mocks.runStrategyTest).toHaveBeenCalledWith(expect.objectContaining({
      mode: "discovery",
      params: {
        historical_pending_entries_enabled: false,
        pending_entry_max_wait_bars: 12
      }
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

  it("persists selected strategies, pairs, and timeframes in localStorage", async () => {
    const user = userEvent.setup();
    const availablePairs = [
      marketPair("BTCUSDT", "BTC"),
      marketPair("ETHUSDT", "ETH"),
      marketPair("SOLUSDT", "SOL"),
      marketPair("XRPUSDT", "XRP")
    ];
    const strategyConfigs = [
      strategyConfig({ timeframes: ["1m", "5m", "15m", "1h"] }),
      strategyConfig({
        id: "strategy_config_2",
        name: "Mean reversion",
        strategy_code: "mean_reversion",
        strategy_name: "Mean Reversion",
        strategy_version_id: "strategy_version_2",
        timeframes: ["1m", "5m", "15m", "1h"]
      })
    ];

    renderPanel({ availablePairs, strategyConfigs });

    await user.click(screen.getByRole("checkbox", { name: /Mean Reversion/u }));
    await user.click(screen.getByRole("checkbox", { name: /XRPUSDT/u }));
    await user.click(screen.getByRole("checkbox", { name: "1h" }));

    await waitFor(() => expect(storedStrategyTestForm()).toEqual(expect.objectContaining({
      selectedPairIds: ["bybit:BTCUSDT", "bybit:ETHUSDT", "bybit:SOLUSDT", "bybit:XRPUSDT"],
      selectedStrategyCodes: ["trend_pullback_continuation", "mean_reversion"],
      selectedTimeframes: ["1m", "5m", "15m", "1h"]
    })));
  });

  it("restores persisted selected strategies, pairs, and timeframes after remount", async () => {
    const user = userEvent.setup();
    const availablePairs = [
      marketPair("BTCUSDT", "BTC"),
      marketPair("ETHUSDT", "ETH"),
      marketPair("SOLUSDT", "SOL"),
      marketPair("XRPUSDT", "XRP")
    ];
    const strategyConfigs = [
      strategyConfig({ timeframes: ["1m", "5m", "15m", "1h"] }),
      strategyConfig({
        id: "strategy_config_2",
        name: "Mean reversion",
        strategy_code: "mean_reversion",
        strategy_name: "Mean Reversion",
        strategy_version_id: "strategy_version_2",
        timeframes: ["1m", "5m", "15m", "1h"]
      })
    ];
    const view = renderPanel({ availablePairs, strategyConfigs });

    await user.click(screen.getByRole("checkbox", { name: /Mean Reversion/u }));
    await user.click(screen.getByRole("checkbox", { name: /XRPUSDT/u }));
    await user.click(screen.getByRole("checkbox", { name: "1h" }));
    await waitFor(() => expect(storedStrategyTestForm()).toEqual(expect.objectContaining({
      selectedPairIds: expect.arrayContaining(["bybit:XRPUSDT"]),
      selectedStrategyCodes: expect.arrayContaining(["mean_reversion"]),
      selectedTimeframes: expect.arrayContaining(["1h"])
    })));

    view.unmount();
    renderPanel({ availablePairs, strategyConfigs });

    await waitFor(() => expect(screen.getByRole("checkbox", { name: /Mean Reversion/u })).toBeChecked());
    expect(screen.getByRole("checkbox", { name: /XRPUSDT/u })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "1h" })).toBeChecked();
  });

  it("filters persisted pairs that are no longer available", async () => {
    window.localStorage.setItem(STRATEGY_TEST_FORM_STORAGE_KEY, JSON.stringify({
      selectedPairIds: ["bybit:DELISTEDUSDT", "bybit:ETHUSDT"],
      selectedStrategyCodes: ["trend_pullback_continuation"],
      selectedTimeframes: ["1m"]
    }));

    renderPanel({
      availablePairs: [
        marketPair("BTCUSDT", "BTC"),
        marketPair("ETHUSDT", "ETH"),
        marketPair("SOLUSDT", "SOL")
      ]
    });

    await waitFor(() => expect(screen.getByRole("checkbox", { name: /BTCUSDT/u })).not.toBeChecked());
    expect(screen.getByRole("checkbox", { name: /ETHUSDT/u })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /SOLUSDT/u })).not.toBeChecked();
    expect(screen.queryByRole("checkbox", { name: /DELISTEDUSDT/u })).not.toBeInTheDocument();
  });

  it("renders and recovers persistence when localStorage contains broken JSON", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(STRATEGY_TEST_FORM_STORAGE_KEY, "{broken json");

    expect(() => renderPanel()).not.toThrow();
    expect(screen.getByRole("checkbox", { name: /Trend Pullback/u })).toBeChecked();

    await user.click(screen.getByRole("button", { name: "Forward virtual" }));

    await waitFor(() => expect(storedStrategyTestForm()).toEqual(expect.objectContaining({
      testType: "forward_virtual"
    })));
  });

  it("resets the form to defaults and clears persisted selection", async () => {
    const user = userEvent.setup();
    const availablePairs = [
      marketPair("BTCUSDT", "BTC"),
      marketPair("ETHUSDT", "ETH"),
      marketPair("SOLUSDT", "SOL"),
      marketPair("XRPUSDT", "XRP")
    ];
    const strategyConfigs = [
      strategyConfig({ timeframes: ["1m", "5m", "15m", "1h"] }),
      strategyConfig({
        id: "strategy_config_2",
        name: "Mean reversion",
        strategy_code: "mean_reversion",
        strategy_name: "Mean Reversion",
        strategy_version_id: "strategy_version_2",
        timeframes: ["1m", "5m", "15m", "1h"]
      })
    ];

    renderPanel({ availablePairs, strategyConfigs });

    await user.click(screen.getByRole("checkbox", { name: /Mean Reversion/u }));
    await user.click(screen.getByRole("checkbox", { name: /XRPUSDT/u }));
    await user.click(screen.getByRole("checkbox", { name: "1h" }));
    await waitFor(() => expect(window.localStorage.getItem(STRATEGY_TEST_FORM_STORAGE_KEY)).not.toBeNull());

    await user.click(screen.getByRole("button", { name: /Reset form/u }));

    expect(screen.getByRole("checkbox", { name: /Mean Reversion/u })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: /XRPUSDT/u })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "1h" })).not.toBeChecked();
    expect(window.localStorage.getItem(STRATEGY_TEST_FORM_STORAGE_KEY)).toBeNull();
  });

  it("runs a forward virtual strategy test when pending max wait bars is invalid", async () => {
    const user = userEvent.setup();
    mocks.runStrategyTest.mockResolvedValue(strategyTestRun({
      status: "queued",
      test_type: "forward_virtual"
    }));

    renderPanel();

    await user.clear(screen.getByLabelText("Pending max wait bars"));
    await user.type(screen.getByLabelText("Pending max wait bars"), "0");
    await user.click(screen.getByRole("button", { name: "Forward virtual" }));
    const runButton = screen.getByRole("button", { name: /Run strategy test/u });
    await waitFor(() => expect(runButton).toBeEnabled());
    await user.click(runButton);

    await waitFor(() => expect(mocks.runStrategyTest).toHaveBeenCalledTimes(1));
    expect(mocks.runStrategyTest).toHaveBeenCalledWith(expect.objectContaining({
      params: {},
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

  it("explains that an active historical scenario can take a while", () => {
    mocks.activeRun = activeRunState({
      active_run: strategyTestRun({
        last_heartbeat_at: "2026-06-02T00:01:00.000Z",
        run_id: "67676767-6767-4767-8767-676767676767",
        status: "running",
        test_type: "historical_backtest"
      }),
      can_run: false,
      is_stale: false
    });

    renderPanel();

    const notice = screen.getByLabelText("Active strategy test run");
    expect(within(notice).getByText("Run is receiving heartbeats. Large historical scenarios can stay on the same scenario for a while.")).toBeInTheDocument();
  });

  it("renders active progress bars, ETA, and funnel counters in the active run notice", () => {
    const activeRun = strategyTestRun({
      run_id: "68686868-6868-4868-8868-686868686868",
      runtime_state: {
        bars_per_second: 40,
        bars_pct: 38.74,
        counters: {
          closed: 1,
          execution_candidates: 8,
          execution_rejections: 1,
          filled: 2,
          no_entry: 4,
          pending_armed: 1,
          pending_entries: 2,
          risk_rejections: 2,
          signals: 6542
        },
        current_scenario_bars_processed: 49750,
        current_scenario_bars_total: 86597,
        current_scenario_index: 3,
        current_scenario_key: "trend_pullback_continuation::bybit::BTCUSDT::15m",
        eta_seconds: 12,
        matrix_bars_processed: 149750,
        matrix_bars_total: 386597,
        phase: "running_scenario",
        scenarios_completed: 2,
        scenarios_total: 16
      },
      status: "running",
      test_type: "historical_backtest"
    });
    mocks.activeRun = activeRunState({
      active_run: activeRun,
      can_run: false,
      is_stale: false
    });
    mocks.runDetail = activeRun;

    renderPanel();

    const notice = screen.getByLabelText("Active strategy test run");
    const progress = within(notice).getByLabelText("Active run progress summary");
    expect(within(progress).getByText("2 / 16")).toBeInTheDocument();
    expect(within(progress).getByText("3 / 16")).toBeInTheDocument();
    expect(within(progress).getByText("149750 / 386597 (38.74%)")).toBeInTheDocument();
    expect(within(progress).getByText("49750 / 86597")).toBeInTheDocument();
    expect(within(progress).getByText("trend_pullback_continuation::bybit::BTCUSDT::15m")).toBeInTheDocument();
    expect(within(progress).getByText("40 bars/s")).toBeInTheDocument();
    expect(within(progress).getByText("12s")).toBeInTheDocument();
    expect(within(progress).getByText("6542")).toBeInTheDocument();
    expect(within(progress).getByText("Phase")).toBeInTheDocument();
    expect(within(progress).getByText("Pending armed")).toBeInTheDocument();
    expect(within(progress).getByText("No entry")).toBeInTheDocument();
    expect(within(progress).getByText("Filled")).toBeInTheDocument();
  });

  it("renders queued active run as waiting for worker lease", () => {
    mocks.activeRun = activeRunState({
      active_run: strategyTestRun({
        claimed_at: null,
        last_heartbeat_at: null,
        lease_expires_at: null,
        run_id: "69696969-6969-4969-8969-696969696969",
        runtime_state: {
          phase: "queued",
          status: "queued"
        },
        status: "queued",
        test_type: "historical_backtest",
        worker_attempt: 0,
        worker_id: null
      }),
      allowed_actions: ["refresh", "cancel"],
      can_run: false,
      is_stale: false
    });

    renderPanel();

    const notice = screen.getByLabelText("Active strategy test run");
    expect(within(notice).getByText("queued")).toBeInTheDocument();
    expect(within(notice).queryByText("Run is receiving heartbeats. Large historical scenarios can stay on the same scenario for a while.")).not.toBeInTheDocument();
    expect(within(notice).getByText("Queued; waiting for strategy-test worker to claim this run.")).toBeInTheDocument();
    expect(within(notice).getByText("If this does not change, start strategy-test-worker.")).toBeInTheDocument();
    expect(within(notice).getByText("Waiting for worker")).toBeInTheDocument();
    expect(within(notice).getByText("Worker lease")).toBeInTheDocument();
    expect(within(notice).getByRole("button", { name: /Cancel run/u })).toBeInTheDocument();
  });

  it("renders forward waiting_for_market_data state from backend runtime", () => {
    mocks.activeRun = activeRunState({
      active_run: strategyTestRun({
        run_id: "70707070-7070-4070-8070-707070707070",
        runtime_state: {
          last_heartbeat_reason: "no_matching_market_data",
          processed_signals: 0,
          processed_ticks: 0,
          status: "waiting_for_market_data"
        },
        status: "running",
        test_type: "forward_virtual",
        worker_id: "strategy-worker-a"
      }),
      can_run: false,
      is_stale: false
    });

    renderPanel();

    const notice = screen.getByLabelText("Active strategy test run");
    expect(within(notice).getByText("Waiting for market data")).toBeInTheDocument();
    expect(within(notice).getByText("no_matching_market_data")).toBeInTheDocument();
    expect(within(notice).getByText("strategy-worker-a")).toBeInTheDocument();
  });

  it("renders selected active run progress instead of an empty report state", async () => {
    const user = userEvent.setup();
    const activeRun = strategyTestRun({
      run_id: "77777777-7777-4777-8777-777777777777",
      runtime_state: {
        bars_per_second: 40,
        bars_pct: 50,
        bars_processed: 500,
        bars_total: 1000,
        current_exchange: "bybit",
        current_strategy: "trend_pullback_continuation",
        current_symbol: "BTCUSDT",
        current_timeframe: "15m",
        entry_touched: 3,
        eta_seconds: 12,
        execution_candidates: 8,
        execution_rejections: 1,
        filled: 2,
        last_progress_at: "2026-06-02T00:01:30.000Z",
        no_entry: 4,
        not_selected: 3,
        pending_armed: 1,
        pending_entries_count: 2,
        phase: "running_scenario",
        risk_rejections: 2,
        scenario_completed: 2,
        scenario_total: 6,
        signals_seen: 11,
        trades_count: 0
      },
      status: "running",
      test_type: "historical_backtest"
    });
    mocks.activeRun = activeRunState({
      active_run: activeRun,
      can_run: false,
      is_stale: false
    });
    mocks.runDetail = activeRun;

    renderPanel();

    await user.click(within(screen.getByLabelText("Active strategy test run")).getByRole("button", { name: "Open report" }));

    const progress = screen.getByLabelText("Active run progress");
    expect(progress).toBeInTheDocument();
    expect(within(progress).getByText("running_scenario")).toBeInTheDocument();
    expect(within(progress).getByText("2 / 6")).toBeInTheDocument();
    expect(within(progress).getByText("trend_pullback_continuation")).toBeInTheDocument();
    expect(within(progress).getByText("bybit:BTCUSDT")).toBeInTheDocument();
    expect(within(progress).getByText("15m")).toBeInTheDocument();
    expect(within(progress).getByText("500 / 1000 (50%)")).toBeInTheDocument();
    expect(within(progress).getByText("40 bars/s")).toBeInTheDocument();
    expect(within(progress).getByText("12s")).toBeInTheDocument();
    expect(within(progress).getByText("Not selected")).toBeInTheDocument();
    expect(within(progress).getByText("Pending entries")).toBeInTheDocument();
    expect(screen.queryByText("No report selected")).not.toBeInTheDocument();
    expect(screen.queryByText("No summary metrics")).not.toBeInTheDocument();
  });

  it("renders selected completed zero-trade run instead of an empty report state", async () => {
    const user = userEvent.setup();
    const completedRun = strategyTestRun({
      run_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      status: "completed",
      summary: {
        completed_scenarios: 1,
        execution_candidates: 0,
        failed_scenarios: 0,
        filled: 0,
        no_entry: 0,
        scenario_count: 1,
        signals_count: 0,
        signals_seen: 0,
        trades_count: 0
      },
      test_type: "historical_backtest"
    });
    mocks.runs = [completedRun];
    mocks.report = null;

    renderPanel();

    await user.click(screen.getByRole("button", { name: `Open report for run ${completedRun.run_id}` }));

    expect(screen.getByText("No trades, but test completed")).toBeInTheDocument();
    expect(screen.queryByText("No report selected")).not.toBeInTheDocument();
    const selectedReportQuery = mocks.reportQueries.find((query) => query.runId === completedRun.run_id);
    expect(selectedReportQuery?.options).toEqual({
      enabled: true,
      refetchInterval: false
    });
  });

  it("renders selected failed run error instead of an empty report state", async () => {
    const user = userEvent.setup();
    const failedRun = strategyTestRun({
      error: "ClickHouse write failed",
      run_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      runtime_state: {
        partial_summary: {
          completed_scenarios: 1,
          failed_scenarios: 1,
          scenario_count: 2,
          signals_seen: 5,
          trades_count: 0
        }
      },
      status: "failed",
      summary: {},
      test_type: "historical_backtest"
    });
    mocks.runs = [failedRun];
    mocks.report = null;

    renderPanel();

    await user.click(screen.getByRole("button", { name: `Open report for run ${failedRun.run_id}` }));

    expect(screen.getByText("Report failed")).toBeInTheDocument();
    expect(screen.getAllByText("ClickHouse write failed").length).toBeGreaterThan(0);
    expect(screen.queryByText("No report selected")).not.toBeInTheDocument();
  });

  it("polls active run detail while a historical run is active", () => {
    const activeRun = strategyTestRun({
      run_id: "88888888-8888-4888-8888-888888888888",
      status: "running",
      test_type: "historical_backtest"
    });
    mocks.activeRun = activeRunState({
      active_run: activeRun,
      can_run: false,
      is_stale: false
    });

    renderPanel();

    const activeRunDetailQuery = mocks.runDetailQueries.find((query) => query.runId === activeRun.run_id);
    expect(activeRunDetailQuery?.options).toEqual({
      enabled: true,
      refetchInterval: 2500
    });
  });

  it("labels cancel as stopping for a stopping active run", () => {
    mocks.activeRun = activeRunState({
      active_run: strategyTestRun({
        run_id: "99999999-9999-4999-8999-999999999999",
        status: "stopping"
      }),
      allowed_actions: ["refresh", "cancel"],
      can_run: false,
      is_stale: false
    });

    renderPanel();

    expect(screen.getByRole("button", { name: /Stopping/u })).toBeDisabled();
  });

  it("allows cancelling a stale stopping active run", async () => {
    const user = userEvent.setup();
    mocks.activeRun = activeRunState({
      active_run: strategyTestRun({
        run_id: "abababab-abab-4bab-8bab-abababababab",
        status: "stopping"
      }),
      allowed_actions: ["refresh", "cancel"],
      can_run: true,
      is_stale: true
    });
    mocks.cancelStrategyTest.mockResolvedValue(strategyTestRun({
      run_id: "abababab-abab-4bab-8bab-abababababab",
      status: "cancelled"
    }));

    renderPanel();

    const cancelButton = screen.getByRole("button", { name: /Cancel run/u });
    expect(cancelButton).toBeEnabled();
    await user.click(cancelButton);

    expect(mocks.cancelStrategyTest).toHaveBeenCalledWith("abababab-abab-4bab-8bab-abababababab");
  });
});

function renderPanel({
  availablePairs = [marketPair()],
  strategyConfigs = [strategyConfig()]
}: {
  availablePairs?: MarketPairOption[];
  strategyConfigs?: StrategyConfig[];
} = {}) {
  return render(<StrategyTestingPanel availablePairs={availablePairs} strategyConfigs={strategyConfigs} />);
}

function storedStrategyTestForm(): Record<string, unknown> {
  const raw = window.localStorage.getItem(STRATEGY_TEST_FORM_STORAGE_KEY);
  if (!raw) throw new Error("Strategy test form storage was not written.");
  return JSON.parse(raw) as Record<string, unknown>;
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

function strategyTestEstimate(overrides: Record<string, unknown> = {}) {
  return {
    average_bars_per_scenario: 200,
    scenario_count: 3,
    scenarios: [
      {
        bars_total: 200,
        candles_count: 400,
        duplicate_rows: 0,
        exchange: "bybit",
        raw_rows: 400,
        strategy: "trend_pullback_continuation",
        symbol: "BTCUSDT",
        timeframe: "1m",
        warmup_bars: 200,
        warning_codes: []
      }
    ],
    size_level: "small",
    total_bars: 600,
    warnings: [],
    ...overrides
  };
}

function expectedCandles(days: number, timeframeMinutes: number): number {
  return days * 24 * 60 / timeframeMinutes;
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

function marketPairs(count: number): MarketPairOption[] {
  return Array.from({ length: count }, (_value, index) => {
    const tokenNumber = String(index + 1).padStart(3, "0");
    return marketPair(`TOKEN${tokenNumber}USDT`, `TOKEN${tokenNumber}`);
  });
}

function marketPair(
  symbol = "BTCUSDT",
  baseAsset = "BTC",
  overrides: Partial<MarketPairOption> = {}
): MarketPairOption {
  const exchange = overrides.exchange ?? "bybit";
  return {
    base_asset: baseAsset,
    exchange,
    id: `pair_${exchange}_${symbol.toLowerCase()}`,
    quote_asset: "USDT",
    status: "active",
    symbol,
    ...overrides
  };
}

function strategyConfig(overrides: Partial<StrategyConfig> = {}): StrategyConfig {
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
    user_id: "demo_user",
    ...overrides
  };
}
