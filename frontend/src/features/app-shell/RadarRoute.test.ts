import { QueryClient } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PendingEntryIntent, RadarSignal, SignalStatus } from "@/types";
import { createRealtimeEventRouter } from "@/realtime/event-router";
import { useSignalStore } from "@/stores/signal-store";
import { useUiStore } from "@/stores/ui-store";
import {
  canArmPendingEntry,
  canSendPaperTrade,
  RadarRoute,
  selectPendingEntryForDetails,
  selectRealTradeConnection,
  shouldRequestExecutionPreview
} from "./RadarRoute";
import type { ExchangeConnection } from "@/features/server-state/types";

const radarRouteMockState = vi.hoisted(() => ({
  exchangeConnections: [] as ExchangeConnection[],
  pendingEntries: [] as PendingEntryIntent[],
  pendingEntryHistory: [] as PendingEntryIntent[],
  radarDisplayModeCalls: [] as Array<string | null | undefined>,
  radarDataUpdatedAt: 0,
  radarResponse: { signals: [] as unknown[] },
  realPreviewCalls: [] as Array<{ connectionId: string | null; enabled: boolean | undefined; signalId: string | null }>,
  refetch: vi.fn(),
  mutateAsync: vi.fn()
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() })
}));

vi.mock("@/auth/use-auth", () => ({
  useAuthSessionQuery: () => ({ data: { user: { id: "user_1" } } })
}));

vi.mock("@/hooks/use-radar-queries", () => {
  const query = (data: unknown = null) => ({
    data,
    dataUpdatedAt: radarRouteMockState.radarDataUpdatedAt,
    error: null,
    isFetching: false,
    isLoading: false,
    refetch: radarRouteMockState.refetch
  });
  const mutation = () => ({
    isPending: false,
    mutateAsync: radarRouteMockState.mutateAsync
  });

  return {
    useArmPendingEntryMutation: mutation,
    useCancelPendingEntryMutation: mutation,
    useConfirmRealMutation: mutation,
    useConfirmVirtualMutation: mutation,
    useExchangeConnectionAccountSnapshotsQuery: () => ({
      dataByConnectionId: {},
      pendingByConnectionId: {}
    }),
    useExchangeConnectionsQuery: () => query(radarRouteMockState.exchangeConnections),
    useHealthQuery: () => query(null),
    useHistoricalSignalsQuery: () => query([]),
    usePendingEntriesQuery: (_userId: string, scope: "active" | "history") =>
      query(scope === "history" ? radarRouteMockState.pendingEntryHistory : radarRouteMockState.pendingEntries),
    usePendingEntryActionStatesQuery: (entries: PendingEntryIntent[]) => ({
      dataByIntentId: Object.fromEntries(entries.map((entry) => [entry.id, {
        can_enter_now: false,
        can_arm_pending: false,
        can_reconfirm: entry.status === "requires_reconfirmation",
        can_cancel: entry.status === "pending" || entry.status === "requires_reconfirmation",
        mode: entry.mode,
        environment: entry.mode,
        primary_action: null,
        disabled_reason_code: null,
        blockers: [],
        warnings: [],
        accepted_trade_plan_snapshot: null,
        display_labels: {}
      }])),
      pendingByIntentId: {}
    }),
    usePendingEntryHistoryQuery: () => query([]),
    usePendingEntryQuery: () => query(null),
    useRadarQuery: (radarDisplayMode?: string | null) => {
      radarRouteMockState.radarDisplayModeCalls.push(radarDisplayMode);
      return query(radarRouteMockState.radarResponse);
    },
    useRadarStatusQuery: () => query(null),
    useReconfirmPendingEntryMutation: mutation,
    useRejectSignalMutation: mutation,
    useRiskStateQuery: () => query(null),
    useSendSignalActionMutation: mutation,
    useSignalActionStateQuery: () => query({
      can_enter_now: false,
      can_arm_pending: true,
      can_reconfirm: false,
      can_cancel: false,
      mode: "virtual",
      environment: "virtual",
      primary_action: "arm_pending_entry",
      disabled_reason_code: null,
      blockers: [],
      warnings: [],
      accepted_trade_plan_snapshot: null,
      display_labels: { primary_action: "Wait for entry" }
    }),
    useSignalExecutionPreviewQuery: () => query(null),
    useSignalRealExecutionPreviewQuery: (signalId: string | null, connectionId: string | null, options?: { enabled?: boolean }) => {
      radarRouteMockState.realPreviewCalls.push({
        connectionId,
        enabled: options?.enabled,
        signalId
      });
      return query(null);
    },
    useUserProfileQuery: () => query(null)
  };
});

vi.mock("./RadarPage", async () => {
  const React = await vi.importActual<typeof import("react")>("react");

  return {
    RadarPage: (props: {
      filter: "all" | "long" | "short";
      onFilterChange: (filter: "all" | "long" | "short") => void;
      onAcceptPendingEntry: (signal: RadarSignal) => void;
      onSelectLatestSignal: () => void;
      onSelectPendingEntrySignal: (intent: PendingEntryIntent) => void;
      onSelectSignal: (signal: RadarSignal) => void;
      missingSelectedSignalId: string | null;
      radarDisplayMode: string;
      onRadarDisplayModeChange: (mode: "all_market_opportunities" | "market_ideas" | "watchlist" | "execution_ready" | "execution_signals" | "blocked") => void;
      pendingEntries: PendingEntryIntent[];
      selectedPendingEntry?: PendingEntryIntent | null;
      selectedSignal: RadarSignal | null;
      selectedSignalId: string | null;
      signalIds: string[];
      signals: RadarSignal[];
    }) => React.createElement(
      "section",
      { "data-testid": "radar-page" },
      React.createElement("div", { "data-testid": "selected-signal" }, props.selectedSignal?.id ?? "none"),
      React.createElement("div", { "data-testid": "selected-card" }, props.selectedSignalId ?? "none"),
      React.createElement("div", { "data-testid": "selected-pending-entry" }, props.selectedPendingEntry?.id ?? "none"),
      React.createElement("div", { "data-testid": "missing-signal" }, props.missingSelectedSignalId ?? "none"),
      React.createElement("div", { "data-testid": "active-mode" }, props.radarDisplayMode),
      React.createElement("div", { "data-testid": "signal-ids" }, props.signalIds.join(",")),
      React.createElement("div", { "data-testid": "pending-statuses" }, props.pendingEntries.map((intent) => `${intent.id}:${intent.status}`).join(",")),
      React.createElement("div", { "data-testid": "active-filter" }, props.filter),
      props.missingSelectedSignalId
        ? React.createElement("button", { onClick: props.onSelectLatestSignal, type: "button" }, "choose latest")
        : null,
      props.signals[0]
        ? React.createElement("button", { onClick: () => props.onAcceptPendingEntry(props.signals[0]), type: "button" }, `arm virtual pending ${props.signals[0].id}`)
        : null,
      React.createElement("button", { onClick: () => props.onFilterChange("short"), type: "button" }, "filter short"),
      React.createElement("button", { onClick: () => props.onFilterChange("all"), type: "button" }, "filter all"),
      React.createElement("button", { onClick: () => props.onRadarDisplayModeChange("execution_ready"), type: "button" }, "mode execution_ready"),
      React.createElement("button", { onClick: () => props.onRadarDisplayModeChange("blocked"), type: "button" }, "mode blocked"),
      ...props.pendingEntries.map((intent) => React.createElement(
        "button",
        { key: intent.id, onClick: () => props.onSelectPendingEntrySignal(intent), type: "button" },
        `select pending ${intent.id}`
      )),
      ...props.signals.map((signal) => React.createElement(
        "button",
        { key: signal.id, onClick: () => props.onSelectSignal(signal), type: "button" },
        `select ${signal.id}`
      ))
    )
  };
});

const baseSignal: RadarSignal = {
  id: "sig_1",
  symbol: "BTCUSDT",
  exchange: "bybit",
  strategy: "trend_pullback_continuation",
  direction: "long",
  confidence: 0.82,
  risk_reward: 2,
  first_target_rr: 1,
  final_target_rr: 2,
  selected_rr: 2,
  selected_rr_target: "final",
  min_rr_ratio: 1.5,
  urgency: "medium",
  status: "ready",
  score: 82,
  timeframe: "15m",
  entry_min: 100,
  entry_max: 101,
  stop_loss: 98,
  take_profit_1: 104,
  take_profit_2: null,
  explanation: [],
  risks: [],
  score_breakdown: {
    trend_score: 80,
    volume_score: 80,
    liquidity_score: 80,
    orderbook_score: 80,
    risk_reward_score: 80,
    volatility_score: 80,
    overheat_penalty: 0,
    news_event_risk_penalty: 0,
    total: 82
  },
  status_reason: null,
  quality: null,
  regime: null,
  setup: null,
  confirmation: null,
  invalidation: null,
  exit_plan: null,
  auto_entry: null,
  created_at: "2026-05-31T07:00:00.000Z",
  updated_at: "2026-05-31T07:00:00.000Z",
  expires_at: "2026-05-31T08:00:00.000Z",
  execution_gate: {
    status: "warning",
    feed_kind: "watchlist",
    can_notify: false,
    can_enter_now: false,
    can_arm_pending: true,
    can_show_in_execution_feed: false,
    reasons: [],
    warnings: [],
    metadata: {}
  }
};

beforeEach(() => {
  radarRouteMockState.exchangeConnections = [];
  radarRouteMockState.pendingEntries = [];
  radarRouteMockState.pendingEntryHistory = [];
  radarRouteMockState.radarDisplayModeCalls = [];
  radarRouteMockState.radarDataUpdatedAt = Date.parse("2026-06-05T09:59:00.000Z");
  radarRouteMockState.radarResponse = { signals: [] };
  radarRouteMockState.realPreviewCalls = [];
  radarRouteMockState.refetch.mockResolvedValue(null);
  radarRouteMockState.mutateAsync.mockResolvedValue(null);
  useSignalStore.getState().clearSignals();
  useUiStore.setState({ selectedSignalId: null, signalFilter: "all" });
});

afterEach(() => {
  vi.useRealTimers();
});

function signalWithStatus(
  status: SignalStatus,
  detailsOverrides: Partial<NonNullable<RadarSignal["details_view"]>> = {}
): RadarSignal {
  return { ...baseSignal, status, details_view: detailsView(detailsOverrides) };
}

function detailsView(
  overrides: Partial<NonNullable<RadarSignal["details_view"]>> = {}
): NonNullable<RadarSignal["details_view"]> {
  return {
    title: "BTCUSDT backend detail",
    side: "long",
    primary_status: "blocked",
    primary_status_label: "Blocked",
    primary_status_tone: "red",
    primary_action_label: "Locked",
    recommended_action_text: "Backend owns action availability.",
    can_enter_now: false,
    trade_plan: {
      has_trade_plan: true,
      entry_type: "Backend entry",
      entry_zone: "100 - 101",
      entry_price: 100,
      stop_loss: 98,
      targets: [],
      selected_rr: 2,
      selected_rr_target: "final",
      min_rr: 1.5,
      trade_plan_complete: true,
      fallback_used: false,
      missing: [],
      invalidation: "-"
    },
    risk_summary: {
      label: "Risk ok",
      risk_failed: false,
      risk_reward_blocked: false,
      risk_reward_warning: null,
      forming_candle: false,
      open_candle_allowed: false,
      forming_reason: null,
      status_allows_trade: true,
      trade_plan_complete: true,
      risk_reward_ok: true,
      is_market_opportunity: true
    },
    execution_summary: executionSummary(),
    top_reasons: [],
    top_blockers: [],
    warnings: [],
    ...overrides
  };
}

function executionSummary(
  overrides: Partial<NonNullable<RadarSignal["details_view"]>["execution_summary"]> = {}
): NonNullable<RadarSignal["details_view"]>["execution_summary"] {
  return {
    preview_available: true,
    risk_check_status: null,
    risk_decision_status: null,
    can_enter: null,
    quality_gate_status: null,
    impact_risk: null,
    status_allows_trade: true,
    ...overrides
  };
}

function routeSignal(overrides: Partial<RadarSignal> = {}): RadarSignal {
  return {
    ...baseSignal,
    created_at: "2026-06-04T07:00:00.000Z",
    updated_at: "2026-06-04T07:00:00.000Z",
    expires_at: "2026-12-31T08:00:00.000Z",
    ...overrides
  };
}

function blockedGate(): NonNullable<RadarSignal["execution_gate"]> {
  return {
    status: "blocked",
    feed_kind: "blocked",
    can_notify: false,
    can_enter_now: false,
    can_arm_pending: false,
    can_show_in_execution_feed: false,
    reasons: [
      {
        code: "score_below_execution_threshold",
        severity: "info",
        source: "score",
        message: "Score 60 is below execution threshold 70.",
        metadata: { score: 60, execution_score_threshold: 70 }
      }
    ],
    warnings: [],
    metadata: {}
  };
}

describe("RadarRoute selection", () => {
  it("requests the all-market-opportunities radar feed by default", () => {
    render(createElement(RadarRoute));

    expect(radarRouteMockState.radarDisplayModeCalls[0]).toBe("all_market_opportunities");
    expect(screen.getByTestId("active-mode")).toHaveTextContent("all_market_opportunities");
  });

  it("keeps blocked diagnostics visible in the default all-market list", async () => {
    const hotSignal = routeSignal({ id: "sig_hot" });
    const blockedSignal = routeSignal({
      id: "sig_blocked",
      execution_gate: blockedGate(),
      details_view: detailsView({
        primary_status: "blocked",
        can_enter_now: false,
        execution_summary: executionSummary({ preview_available: false })
      })
    });
    radarRouteMockState.radarResponse = { signals: [blockedSignal, hotSignal] };

    render(createElement(RadarRoute));

    await waitFor(() => expect(screen.getByTestId("signal-ids")).toHaveTextContent("sig_hot"));
    expect(screen.getByTestId("signal-ids")).toHaveTextContent("sig_blocked");
  });

  it("narrows blocked diagnostics after selecting the blocked mode", async () => {
    const hotSignal = routeSignal({ id: "sig_hot" });
    const blockedSignal = routeSignal({
      id: "sig_blocked",
      execution_gate: blockedGate(),
      details_view: detailsView({
        primary_status: "blocked",
        can_enter_now: false,
        execution_summary: executionSummary({ preview_available: false })
      })
    });
    radarRouteMockState.radarResponse = { signals: [hotSignal, blockedSignal] };

    render(createElement(RadarRoute));

    expect(screen.getByTestId("signal-ids")).toHaveTextContent("sig_hot");
    expect(screen.getByTestId("signal-ids")).toHaveTextContent("sig_blocked");

    fireEvent.click(screen.getByRole("button", { name: "mode blocked" }));

    await waitFor(() => expect(screen.getByTestId("active-mode")).toHaveTextContent("blocked"));
    expect(screen.getByTestId("signal-ids")).toHaveTextContent("sig_blocked");
    expect(screen.getByTestId("signal-ids")).not.toHaveTextContent("sig_hot");
  });

  it("does not keep stale blocked realtime signals visible in explicit execution-ready mode", async () => {
    useSignalStore.getState().addSignal(routeSignal({
      id: "sig_realtime_blocked",
      execution_gate: blockedGate(),
      details_view: detailsView({
        primary_status: "blocked",
        can_enter_now: false,
        execution_summary: executionSummary({ preview_available: false })
      }),
      updated_at: "2026-06-05T10:00:05.000Z"
    }));
    radarRouteMockState.radarResponse = { signals: [] };

    render(createElement(RadarRoute));

    fireEvent.click(screen.getByRole("button", { name: "mode execution_ready" }));

    await waitFor(() => expect(screen.getByTestId("active-mode")).toHaveTextContent("execution_ready"));
    expect(screen.getByTestId("signal-ids")).toBeEmptyDOMElement();
  });

  it("renders realtime signal.created after an empty REST radar snapshot and shows pending after arming", async () => {
    radarRouteMockState.radarResponse = { signals: [] };
    const queryClient = new QueryClient();
    const router = createRealtimeEventRouter({ queryClient, onRealtimeEvent: () => undefined });
    const realtimeSignal = routeSignal({
      id: "sig_realtime",
      symbol: "BTCUSDT",
      updated_at: "2026-06-05T10:00:05.000Z",
      expires_at: "2099-06-05T11:00:05.000Z"
    });
    radarRouteMockState.mutateAsync.mockImplementation(async (payload) => {
      expect(payload).toEqual({
        signalId: "sig_realtime",
        kind: "arm_pending_entry",
        mode: "virtual"
      });
      radarRouteMockState.pendingEntries = [pendingIntent({
        id: "intent_realtime",
        signal_id: "sig_realtime",
        symbol: realtimeSignal.symbol,
        side: realtimeSignal.direction,
        status: "pending"
      })];
      return null;
    });

    const { rerender } = render(createElement(RadarRoute));

    expect(screen.getByTestId("signal-ids")).toHaveTextContent("");

    await act(async () => {
      router.route({
        id: "evt_realtime_created",
        type: "signal.created",
        version: 1,
        timestamp: "2026-06-05T10:00:05.000Z",
        payload: {
          signal: realtimeSignal,
          signalId: realtimeSignal.id,
          pair: realtimeSignal.symbol,
          exchange: realtimeSignal.exchange,
          side: "LONG",
          strategy: realtimeSignal.strategy,
          confidence: realtimeSignal.score,
          risk: "MEDIUM",
          entryZone: { from: realtimeSignal.entry_min, to: realtimeSignal.entry_max },
          stopLoss: realtimeSignal.stop_loss,
          takeProfit: [realtimeSignal.take_profit_1, realtimeSignal.take_profit_2].filter((price): price is number => typeof price === "number"),
          timeframe: realtimeSignal.timeframe
        }
      });
    });

    expect(screen.getByTestId("signal-ids")).toHaveTextContent("sig_realtime");

    fireEvent.click(screen.getByRole("button", { name: "arm virtual pending sig_realtime" }));

    await waitFor(() => expect(radarRouteMockState.mutateAsync).toHaveBeenCalledTimes(1));
    await act(async () => {
      rerender(createElement(RadarRoute));
    });

    expect(screen.getByTestId("pending-statuses")).toHaveTextContent("intent_realtime:pending");
  });

  it("does not reapply an empty REST snapshot over realtime signals on clock ticks", async () => {
    vi.useFakeTimers({ now: new Date("2026-06-05T10:00:00.000Z") });
    radarRouteMockState.radarResponse = { signals: [] };

    render(createElement(RadarRoute));

    expect(screen.getByTestId("signal-ids")).toHaveTextContent("");

    await act(async () => {
      vi.setSystemTime(new Date("2026-06-05T10:00:05.000Z"));
      useSignalStore.getState().addSignal(routeSignal({
        id: "sig_realtime",
        expires_at: "2026-06-05T11:00:00.000Z",
        updated_at: "2026-06-05T10:00:05.000Z"
      }));
    });

    expect(screen.getByTestId("signal-ids")).toHaveTextContent("sig_realtime");

    await act(async () => {
      vi.advanceTimersByTime(30_000);
    });

    expect(screen.getByTestId("signal-ids")).toHaveTextContent("sig_realtime");
  });

  it("does not change the selected signal when a new signal arrives after manual selection", async () => {
    const signalA = routeSignal({ id: "sig_a", direction: "long", symbol: "AAAUSDT" });
    const signalB = routeSignal({ id: "sig_b", direction: "short", symbol: "BBBUSDT" });
    const signalC = routeSignal({ id: "sig_c", direction: "long", symbol: "CCCUSDT" });
    radarRouteMockState.radarResponse = { signals: [signalA, signalB] };

    const { rerender } = render(createElement(RadarRoute));

    fireEvent.click(await screen.findByRole("button", { name: "select sig_b" }));

    expect(screen.getByTestId("selected-signal")).toHaveTextContent("sig_b");
    expect(screen.getByTestId("selected-card")).toHaveTextContent("sig_b");
    expect(useUiStore.getState().selectedSignalId).toBe("sig_b");

    radarRouteMockState.radarResponse = { signals: [signalC, signalA, signalB] };
    await act(async () => {
      rerender(createElement(RadarRoute));
    });

    await waitFor(() => expect(screen.getByTestId("selected-signal")).toHaveTextContent("sig_b"));
    expect(screen.getByTestId("selected-card")).toHaveTextContent("sig_b");
    expect(screen.getByTestId("signal-ids")).toHaveTextContent("sig_c,sig_a,sig_b");
    expect(useUiStore.getState().selectedSignalId).toBe("sig_b");
  });

  it("shows a stable placeholder when the selected signal is filtered out", async () => {
    const signalA = routeSignal({ id: "sig_a", direction: "long", symbol: "AAAUSDT" });
    const signalB = routeSignal({ id: "sig_b", direction: "short", symbol: "BBBUSDT" });
    radarRouteMockState.radarResponse = { signals: [signalA, signalB] };

    render(createElement(RadarRoute));

    await waitFor(() => expect(screen.getByTestId("selected-signal")).toHaveTextContent("sig_a"));

    fireEvent.click(screen.getByRole("button", { name: "filter short" }));

    await waitFor(() => expect(screen.getByTestId("selected-signal")).toHaveTextContent("none"));
    expect(screen.getByTestId("selected-card")).toHaveTextContent("sig_a");
    expect(screen.getByTestId("missing-signal")).toHaveTextContent("sig_a");
    expect(screen.getByTestId("signal-ids")).toHaveTextContent("sig_b");
    expect(useUiStore.getState().selectedSignalId).toBe("sig_a");

    fireEvent.click(screen.getByRole("button", { name: "choose latest" }));

    await waitFor(() => expect(screen.getByTestId("selected-signal")).toHaveTextContent("sig_b"));
    expect(useUiStore.getState().selectedSignalId).toBe("sig_b");
  });

  it("selects the related signal when a pending entry is clicked", async () => {
    const signalA = routeSignal({ id: "sig_a", direction: "long", symbol: "AAAUSDT" });
    const signalB = routeSignal({ id: "sig_b", direction: "short", symbol: "BBBUSDT" });
    radarRouteMockState.radarResponse = { signals: [signalA, signalB] };
    radarRouteMockState.pendingEntries = [pendingIntent({
      id: "intent_b",
      signal_id: "sig_b",
      symbol: signalB.symbol,
      side: signalB.direction
    })];

    render(createElement(RadarRoute));

    fireEvent.click(await screen.findByRole("button", { name: "select pending intent_b" }));

    await waitFor(() => expect(screen.getByTestId("selected-signal")).toHaveTextContent("sig_b"));
    expect(useUiStore.getState().selectedSignalId).toBe("sig_b");
  });

  it("selects pending-entry details when the related signal is absent from the feed", async () => {
    radarRouteMockState.radarResponse = { signals: [] };
    radarRouteMockState.pendingEntries = [pendingIntent({
      id: "intent_missing_signal",
      signal_id: "sig_missing",
      symbol: "MISSINGUSDT",
      status: "requires_reconfirmation"
    })];

    render(createElement(RadarRoute));

    fireEvent.click(await screen.findByRole("button", { name: "select pending intent_missing_signal" }));

    await waitFor(() => expect(screen.getByTestId("selected-signal")).toHaveTextContent("none"));
    expect(screen.getByTestId("selected-card")).toHaveTextContent("sig_missing");
    expect(screen.getByTestId("missing-signal")).toHaveTextContent("sig_missing");
    expect(screen.getByTestId("selected-pending-entry")).toHaveTextContent("intent_missing_signal");
  });

  it("requests real execution preview for the selected real exchange connection", async () => {
    radarRouteMockState.exchangeConnections = [exchangeConnection({ id: "conn_real" })];
    radarRouteMockState.radarResponse = {
      signals: [
        routeSignal({
          id: "sig_real",
          details_view: detailsView({
            execution_summary: executionSummary({ preview_available: true })
          })
        })
      ]
    };

    render(createElement(RadarRoute));

    await waitFor(() => expect(screen.getByTestId("selected-signal")).toHaveTextContent("sig_real"));
    await waitFor(() => expect(radarRouteMockState.realPreviewCalls).toContainEqual({
      connectionId: "conn_real",
      enabled: true,
      signalId: "sig_real"
    }));
  });
});

describe("shouldRequestExecutionPreview", () => {
  it("requests preview only when backend details view marks it available", () => {
    expect(shouldRequestExecutionPreview(signalWithStatus("new"), "open", false)).toBe(true);
    expect(shouldRequestExecutionPreview(signalWithStatus("watchlist"), "open", false)).toBe(true);
    expect(shouldRequestExecutionPreview(signalWithStatus("ready"), "open", false)).toBe(true);
    expect(shouldRequestExecutionPreview(signalWithStatus("wait_for_pullback"), "open", false)).toBe(true);
  });

  it("does not preview history, blocked UI state, unavailable backend preview, or missing signal", () => {
    expect(shouldRequestExecutionPreview(signalWithStatus("ready"), "history", false)).toBe(false);
    expect(shouldRequestExecutionPreview(signalWithStatus("ready"), "open", true)).toBe(false);
    expect(shouldRequestExecutionPreview(signalWithStatus("expired", {
      execution_summary: executionSummary({ preview_available: false })
    }), "open", false)).toBe(false);
    expect(shouldRequestExecutionPreview(null, "open", false)).toBe(false);
  });
});

describe("paper trade eligibility", () => {
  it("does not allow active market opportunities to enter", () => {
    expect(canSendPaperTrade(signalWithStatus("active"))).toBe(false);
  });

  it("allows paper trade only after backend execution permission", () => {
    expect(canSendPaperTrade(signalWithStatus("actionable"))).toBe(false);
    expect(canSendPaperTrade(signalWithStatus("entry_touched"))).toBe(false);
    expect(canSendPaperTrade(signalWithStatus("actionable", { can_enter_now: true }))).toBe(true);
    expect(canSendPaperTrade(signalWithStatus("entry_touched", { can_enter_now: true }))).toBe(true);
    expect(canSendPaperTrade(signalWithStatus("entry_touched", { can_enter_now: false }))).toBe(false);
  });

  it("does not turn soft or legacy RR warnings into enter permission", () => {
    const lowRrSignal: RadarSignal = {
      ...baseSignal,
      details_view: detailsView({
        can_enter_now: false,
        primary_status: "waiting_entry",
        primary_action_label: "Wait for entry"
      }),
      selected_rr: 0.8,
      confirmation: {
        passed: false,
        checks: [
          {
            name: "risk_reward_guard",
            status: "failed",
            score: 0.8,
            reason: "Risk/reward blocked: nearest target is below minimum",
            metadata: { risk_reward_blocked: true }
          }
        ]
      }
    };

    expect(canArmPendingEntry(lowRrSignal)).toBe(true);
    expect(canSendPaperTrade(lowRrSignal)).toBe(false);
  });

  it("uses backend details view to expose the pending-entry affordance", () => {
    expect(canArmPendingEntry(signalWithStatus("active", {
      primary_status: "waiting_entry",
      primary_action_label: "Wait for entry"
    }))).toBe(true);
    expect(canArmPendingEntry(signalWithStatus("ready", {
      primary_status: "execution_ready",
      primary_action_label: "Enter now"
    }))).toBe(false);
  });
});

describe("pending entry selection", () => {
  it("prefers active pending intent over terminal history", () => {
    const active = pendingIntent({ id: "active", status: "pending" });
    const terminal = pendingIntent({ id: "terminal", status: "cancelled" });

    expect(selectPendingEntryForDetails(active, [terminal])).toBe(active);
  });

  it("falls back to the latest terminal pending intent", () => {
    const oldTerminal = pendingIntent({
      id: "old",
      status: "expired",
      updated_at: "2026-05-31T07:05:00.000Z"
    });
    const latestTerminal = pendingIntent({
      id: "latest",
      status: "cancelled",
      updated_at: "2026-05-31T07:15:00.000Z"
    });

    expect(selectPendingEntryForDetails(null, [oldTerminal, latestTerminal])).toBe(latestTerminal);
  });

  it("does not treat terminal active endpoint data as active", () => {
    const malformedActive = pendingIntent({ id: "cancelled-active", status: "cancelled" });
    const latestTerminal = pendingIntent({
      id: "latest",
      status: "expired",
      updated_at: "2026-05-31T07:15:00.000Z"
    });

    expect(selectPendingEntryForDetails(malformedActive, [latestTerminal])).toBe(latestTerminal);
  });
});

describe("real trade connection selection", () => {
  it("selects an active connection for the signal exchange only", () => {
    const disabledBybit = exchangeConnection({ id: "disabled", status: "disabled" });
    const activeBybit = exchangeConnection({ id: "active" });
    const activeOther = exchangeConnection({
      id: "binance",
      exchange_code: "binance",
      exchange_name: "Binance"
    });

    expect(selectRealTradeConnection([disabledBybit, activeOther, activeBybit], baseSignal)).toBe(activeBybit);
    expect(selectRealTradeConnection([activeOther], baseSignal)).toBeNull();
  });
});

function pendingIntent(overrides: Partial<PendingEntryIntent> = {}): PendingEntryIntent {
  return {
    id: "intent_1",
    user_id: "user_1",
    signal_id: baseSignal.id,
    strategy_id: null,
    mode: "virtual",
    status: "pending",
    exchange: baseSignal.exchange,
    symbol: baseSignal.symbol,
    side: baseSignal.direction,
    entry_min: 100,
    entry_max: 101,
    entry_price_policy: "accepted_entry_zone",
    stop_loss: 98,
    targets_snapshot: [{ label: "TP1", price: "110" }],
    accepted_trade_plan_snapshot: { entry: { min_price: "100", max_price: "101" } },
    accepted_trade_plan_hash: "sha256:test",
    accepted_signal_status: "ready",
    accepted_signal_version: null,
    accepted_signal_fingerprint: null,
    execution_profile_snapshot: {},
    request_snapshot: {},
    idempotency_key: "pending-entry:test",
    expires_at: null,
    created_at: "2026-05-31T07:00:00.000Z",
    updated_at: "2026-05-31T07:00:00.000Z",
    triggered_at: null,
    filled_at: null,
    filled_trade_id: null,
    failure_reason: null,
    ...overrides
  };
}

function exchangeConnection(overrides: Partial<ExchangeConnection> = {}): ExchangeConnection {
  return {
    id: "conn_1",
    user_id: "user_1",
    exchange_id: "ex_bybit",
    exchange_code: "bybit",
    exchange_name: "Bybit",
    label: "Bybit testnet",
    account_type: "linear",
    deleted_at: null,
    deletion_reason: null,
    key_ref: "vault:bybit:testnet",
    permissions: {},
    revoked_at: null,
    status: "active",
    last_sync_at: null,
    last_account_snapshot_at: null,
    environment: "testnet",
    order_placement_mode: "dry_run",
    can_place_orders: false,
    safety_blockers: ["ORDER_PLACEMENT_DRY_RUN"],
    mainnet_explicitly_enabled: false,
    account_snapshot_status: "missing",
    metadata: {},
    created_at: "2026-06-04T11:00:00.000Z",
    ...overrides
  };
}
