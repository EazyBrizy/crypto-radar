import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/i18n";
import { LOCALE_STORAGE_KEY } from "@/i18n/locale";
import type { PendingEntryIntent, RadarSignal } from "@/types";
import { SignalDetails, type RealTradeContext } from "./SignalDetails";

vi.mock("next/dynamic", () => ({
  default: () => () => null
}));

const signal: RadarSignal = {
  id: "sig_1",
  symbol: "ETHUSDT",
  exchange: "bybit",
  strategy: "volatility_squeeze_breakout",
  direction: "long",
  confidence: 0.84,
  risk_reward: 2.5,
  first_target_rr: 1,
  final_target_rr: 2.5,
  selected_rr: 2.5,
  selected_rr_target: "final",
  min_rr_ratio: 1.5,
  urgency: "medium",
  status: "actionable",
  score: 84,
  timeframe: "15m",
  entry_min: 2_100,
  entry_max: 2_105,
  stop_loss: 2_060,
  take_profit_1: 2_150,
  take_profit_2: 2_200,
  explanation: ["Breakout confirmed"],
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
    total: 84
  },
  status_reason: null,
  quality: null,
  regime: null,
  setup: null,
  confirmation: {
    passed: false,
    checks: [
      {
        name: "no_trade_filter",
        status: "failed",
        score: null,
        reason: "high_spread",
        metadata: {}
      }
    ]
  },
  invalidation: null,
  exit_plan: null,
  auto_entry: null,
  trade_plan: {
    version: "v1",
    entry: {
      price: 2_102,
      min_price: 2_100,
      max_price: 2_105,
      source: "aggressive_breakout",
      metadata: { entry_type: "aggressive_breakout" }
    },
    stop_loss: 2_060,
    targets: [
      { label: "TP1", price: 2_150, r_multiple: 1, action: "partial_close", close_percent: 40, source: "rr", metadata: {} },
      { label: "TP2", price: 2_200, r_multiple: 2, action: "reduce_runner", close_percent: 30, source: "rr", metadata: {} },
      { label: "TP3", price: 2_240, r_multiple: 2.8, action: "full_close", close_percent: 30, source: "range_measured_move", metadata: {} }
    ],
    invalidation: {
      price: 2_060,
      hard_stop: 2_060,
      conditions: ["Breakout fails"],
      metadata: {}
    },
    risk_rules: {
      risk_reward: 2.8,
      first_target_rr: 1,
      final_target_rr: 2.8,
      selected_rr: 2.8,
      selected_rr_target: "final",
      min_rr_ratio: 1.5,
      metadata: {}
    },
    metadata: {}
  },
  edge: {
    status: "positive",
    sample_size: 75,
    min_sample_size: 50,
    winrate: 0.61,
    avg_win_r: 1.8,
    avg_loss_r: -1,
    expectancy_r: 0.45,
    expectancy_after_costs_r: 0.37,
    profit_factor: 1.6,
    confidence_score: 0.72,
    source: "outcome",
    score_bucket: "80-89",
    metadata: {}
  },
  no_trade_filter: {
    enabled: true,
    blocked: true,
    hard_block: true,
    blockers: ["high_spread"],
    warnings: ["virtual-only recommended"],
    checks: [],
    metadata: {}
  },
  created_at: "2026-05-31T07:00:00.000Z",
  updated_at: "2026-05-31T07:00:00.000Z",
  expires_at: "2026-05-31T08:00:00.000Z"
};

describe("SignalDetails", () => {
  it("renders compact trade plan and top blockers in the default view", () => {
    render(
      <SignalDetails
        busy={false}
        executionPreview={null}
        onPaperTrade={vi.fn()}
        onReject={vi.fn()}
        signal={signal}
      />
    );

    expect(screen.getByText("Trade Plan")).toBeInTheDocument();
    expect(screen.getByText("Entry zone / price")).toBeInTheDocument();
    expect(screen.getByText("Stop-loss")).toBeInTheDocument();
    expect(screen.getByText("TP1")).toBeInTheDocument();
    expect(screen.getByText("TP2")).toBeInTheDocument();
    expect(screen.getByText("Runner")).toBeInTheDocument();
    expect(screen.queryByText("Edge Snapshot")).not.toBeInTheDocument();
    expect(screen.queryByText("Risk blockers / warnings")).not.toBeInTheDocument();
    expect(screen.getAllByText("high_spread").length).toBeGreaterThan(0);
  });

  it("does not render active as an enter-ready action", () => {
    render(
      <SignalDetails
        busy={false}
        executionPreview={null}
        onPaperTrade={vi.fn()}
        onReject={vi.fn()}
        signal={{ ...signal, status: "active", no_trade_filter: null }}
      />
    );

    expect(screen.getByText("Market setup exists, wait for entry trigger")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Virtual entry locked/u })).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Virtual entry now/u })).not.toBeInTheDocument();
  });

  it("shows forming candle reason and disables actionable UI by default", () => {
    const formingSignal: RadarSignal = {
      ...signal,
      candle_state: "open",
      no_trade_filter: null,
      confirmation: {
        passed: false,
        checks: [
          {
            name: "candle_state_gate",
            status: "warning",
            score: null,
            reason: "forming_candle: forming candle preview is not actionable until the candle closes",
            metadata: {
              candle_state: "open",
              open_candle_preview: true,
              allow_open_candle_actionable: false,
              signal_actionable: false
            }
          }
        ]
      }
    };

    render(
      <SignalDetails
        busy={false}
        executionPreview={null}
        onPaperTrade={vi.fn()}
        onReject={vi.fn()}
        signal={formingSignal}
      />
    );

    expect(screen.getByText("forming candle")).toBeInTheDocument();
    expect(screen.getByText("preview")).toBeInTheDocument();
    expect(screen.getAllByText(/forming candle preview/u).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /Virtual entry locked/u })).toBeDisabled();
  });

  it("keeps actionable UI for open candles only when metadata explicitly allows it", () => {
    const allowedSignal: RadarSignal = {
      ...signal,
      can_enter: true,
      candle_state: "open",
      no_trade_filter: null,
      confirmation: {
        passed: true,
        checks: [
          {
            name: "candle_state_gate",
            status: "passed",
            score: null,
            reason: "Open candle actionability is explicitly allowed by configuration",
            metadata: {
              candle_state: "open",
              open_candle_preview: true,
              allow_open_candle_actionable: true,
              actionable_from_open_candle: true,
              signal_actionable: true
            }
          }
        ]
      },
      trade_plan: signal.trade_plan
        ? {
            ...signal.trade_plan,
            metadata: {
              ...signal.trade_plan.metadata,
              allow_open_candle_actionable: true,
              actionable_from_open_candle: true,
              signal_actionable: true
            },
            risk_rules: {
              ...signal.trade_plan.risk_rules,
              metadata: {
                ...signal.trade_plan.risk_rules.metadata,
                allow_open_candle_actionable: true,
                actionable_from_open_candle: true,
                signal_actionable: true
              }
            }
          }
        : signal.trade_plan
    };

    render(
      <SignalDetails
        busy={false}
        executionPreview={null}
        onPaperTrade={vi.fn()}
        onReject={vi.fn()}
        signal={allowedSignal}
      />
    );

    expect(screen.getByText("forming allowed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Virtual entry now/u })).toBeEnabled();
  });

  it("opens real confirmation modal without calling the API action immediately", () => {
    const onConfirmRealTrade = vi.fn();
    render(
      <SignalDetails
        busy={false}
        executionPreview={null}
        onConfirmRealTrade={onConfirmRealTrade}
        onPaperTrade={vi.fn()}
        onReject={vi.fn()}
        realTradeContext={realTradeContext()}
        signal={{ ...signal, can_enter: true, no_trade_filter: null }}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /Real wait entry/u }));

    expect(onConfirmRealTrade).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: /Подтверждение реального входа/u })).toBeInTheDocument();
  });

  it("disables real confirmation for a stale account snapshot", () => {
    render(
      <SignalDetails
        busy={false}
        executionPreview={null}
        onConfirmRealTrade={vi.fn()}
        onPaperTrade={vi.fn()}
        onReject={vi.fn()}
        realTradeContext={realTradeContext({ accountSnapshot: { ...accountSnapshot(), status: "stale" } })}
        signal={{ ...signal, can_enter: true, no_trade_filter: null }}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /Real wait entry/u }));

    expect(screen.getByText("Account snapshot устарел.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Подтвердить реальный вход/u })).toBeDisabled();
  });

  it("enables real confirmation for a fresh testnet snapshot", () => {
    const onConfirmRealTrade = vi.fn();
    render(
      <SignalDetails
        busy={false}
        executionPreview={null}
        onConfirmRealTrade={onConfirmRealTrade}
        onPaperTrade={vi.fn()}
        onReject={vi.fn()}
        realTradeContext={realTradeContext()}
        signal={{ ...signal, can_enter: true, no_trade_filter: null }}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /Real wait entry/u }));
    const confirmButton = screen.getByRole("button", { name: /Подтвердить реальный вход/u });

    expect(confirmButton).toBeEnabled();
    fireEvent.click(confirmButton);
    expect(onConfirmRealTrade).toHaveBeenCalledTimes(1);
  });

  it("keeps virtual action one-click", () => {
    const onPaperTrade = vi.fn();
    render(
      <SignalDetails
        busy={false}
        executionPreview={null}
        onPaperTrade={onPaperTrade}
        onReject={vi.fn()}
        signal={{ ...signal, can_enter: true, no_trade_filter: null }}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /Virtual entry now/u }));

    expect(onPaperTrade).toHaveBeenCalledTimes(1);
  });

  it("displays disabled reason from backend action-state", () => {
    render(
      <SignalDetails
        actionState={{
          can_enter_now: false,
          can_arm_pending: false,
          can_reconfirm: false,
          can_cancel: false,
          mode: "virtual",
          environment: "virtual",
          primary_action: null,
          disabled_reason_code: "risk_profile_unavailable",
          blockers: [
            {
              code: "risk_profile_unavailable",
              severity: "blocker",
              message: "Risk profile is unavailable.",
              display_label: "Risk profile unavailable",
              metadata: {}
            }
          ],
          warnings: [],
          accepted_trade_plan_snapshot: null,
          display_labels: { disabled_reason: "Risk profile unavailable" }
        }}
        busy={false}
        executionPreview={null}
        onPaperTrade={vi.fn()}
        onReject={vi.fn()}
        signal={{ ...signal, can_enter: true, no_trade_filter: null }}
      />
    );

    expect(screen.getAllByText("Risk profile unavailable").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /Virtual entry locked/u })).toBeDisabled();
  });

  it("renders core action buttons with Russian labels in RU mode", async () => {
    const onCancelPendingEntry = vi.fn();
    window.localStorage.setItem(LOCALE_STORAGE_KEY, "ru");

    render(
      <I18nProvider>
        <SignalDetails
          busy={false}
          executionPreview={null}
          onCancelPendingEntry={onCancelPendingEntry}
          onPaperTrade={vi.fn()}
          onReject={vi.fn()}
          pendingEntry={pendingIntent()}
          signal={{ ...signal, can_enter: true, no_trade_filter: null }}
        />
      </I18nProvider>
    );

    expect(await screen.findByRole("button", { name: /Ждать вход виртуально/u })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Виртуальная сделка/u })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Открыть биржу/u })).toBeDisabled();
    expect(screen.getAllByText("Ждём вход").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: /Отменить ожидание/u }));

    expect(onCancelPendingEntry).toHaveBeenCalledTimes(1);
  });

  it("does not render decision snapshot by default and shows it in diagnostics", () => {
    const decisionSignal: RadarSignal = {
      ...signal,
      decision: {
        setup_valid: true,
        trade_plan_valid: false,
        market_context_score: 58,
        signal_actionable: false,
        execution_allowed_virtual: false,
        execution_allowed_real: null,
        blockers: [
          {
            code: "risk_reward_guard",
            message: "Risk/reward is below the hard guard.",
            source: "rr",
            severity: "blocker",
            scope: "virtual",
            metadata: {}
          }
        ],
        warnings: [
          {
            code: "candle_state_gate",
            message: "Open candle preview.",
            source: "data",
            severity: "warning",
            scope: "discovery",
            metadata: {}
          }
        ]
      }
    };

    render(
      <SignalDetails
        busy={false}
        executionPreview={null}
        onPaperTrade={vi.fn()}
        onReject={vi.fn()}
        signal={decisionSignal}
      />
    );

    expect(screen.queryByText("Decision Snapshot")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Диагностика/u }));

    expect(screen.getByText("Decision Snapshot")).toBeInTheDocument();
    expect(screen.getByText(/rr \/ virtual: Risk\/reward is below the hard guard\./u)).toBeInTheDocument();
    expect(screen.getByText(/data \/ discovery: Open candle preview\./u)).toBeInTheDocument();
  });

  it("renders old signals without decision snapshots", () => {
    render(
      <SignalDetails
        busy={false}
        executionPreview={null}
        onPaperTrade={vi.fn()}
        onReject={vi.fn()}
        signal={{ ...signal, decision: null }}
      />
    );

    expect(screen.getByText("Trade Plan")).toBeInTheDocument();
    expect(screen.queryByText("Decision Snapshot")).not.toBeInTheDocument();
  });

  it("hides unknown edge snapshot in the default view", () => {
    render(
      <SignalDetails
        busy={false}
        executionPreview={null}
        onPaperTrade={vi.fn()}
        onReject={vi.fn()}
        signal={{ ...signal, edge: null }}
      />
    );

    expect(screen.queryByText("Edge Snapshot")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Диагностика/u }));

    expect(screen.getByText("Edge Snapshot")).toBeInTheDocument();
    expect(screen.getByText("unknown edge")).toBeInTheDocument();
  });

  it("renders deduplicated top blocker messages", () => {
    const duplicateMessage = "Duplicate blocker message.";
    const duplicateSignal: RadarSignal = {
      ...signal,
      no_trade_filter: {
        enabled: true,
        blocked: true,
        hard_block: true,
        blockers: [duplicateMessage],
        warnings: [],
        checks: [],
        metadata: {}
      },
      decision: {
        setup_valid: true,
        trade_plan_valid: true,
        market_context_score: 60,
        signal_actionable: false,
        execution_allowed_virtual: false,
        execution_allowed_real: null,
        blockers: [
          {
            code: "duplicate_blocker",
            message: duplicateMessage,
            source: "risk",
            severity: "blocker",
            scope: "virtual",
            metadata: {}
          }
        ],
        warnings: []
      }
    };

    render(
      <SignalDetails
        busy={false}
        executionPreview={null}
        onPaperTrade={vi.fn()}
        onReject={vi.fn()}
        signal={duplicateSignal}
      />
    );

    const topBlockers = screen.getByText("Top blockers").closest(".top-blocker-list");
    expect(topBlockers).not.toBeNull();
    expect(within(topBlockers as HTMLElement).getAllByText(duplicateMessage)).toHaveLength(1);
  });

  it("creates a pending entry from the accept-and-wait button", () => {
    const onAcceptPendingEntry = vi.fn();
    render(
      <SignalDetails
        busy={false}
        executionPreview={null}
        onAcceptPendingEntry={onAcceptPendingEntry}
        onPaperTrade={vi.fn()}
        onReject={vi.fn()}
        signal={{ ...signal, status: "ready", no_trade_filter: null }}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /Virtual wait entry/u }));

    expect(onAcceptPendingEntry).toHaveBeenCalledTimes(1);
  });

  it("shows pending intent state, entry zone and cancel action", () => {
    const onCancelPendingEntry = vi.fn();
    render(
      <SignalDetails
        busy={false}
        executionPreview={null}
        onCancelPendingEntry={onCancelPendingEntry}
        onPaperTrade={vi.fn()}
        onReject={vi.fn()}
        pendingEntry={pendingIntent()}
        signal={{ ...signal, status: "ready", no_trade_filter: null }}
      />
    );

    expect(screen.getByRole("heading", { name: "Active Pending Entry" })).toBeInTheDocument();
    expect(screen.getAllByText("Waiting entry").length).toBeGreaterThan(0);
    expect(screen.getByText("100 - 101")).toBeInTheDocument();
    expect(screen.getByText("95")).toBeInTheDocument();
    expect(screen.getByText("no expiry")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Virtual wait entry/u })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /Cancel waiting/u }));
    expect(onCancelPendingEntry).toHaveBeenCalledTimes(1);
  });

  it("renders cancelled pending intent only as collapsed history", () => {
    render(
      <SignalDetails
        busy={false}
        executionPreview={null}
        onPaperTrade={vi.fn()}
        onReject={vi.fn()}
        pendingEntry={pendingIntent({
          status: "cancelled",
          failure_reason: "Cancelled by user.",
          updated_at: "2026-05-31T07:15:00.000Z"
        })}
        signal={{ ...signal, status: "ready", no_trade_filter: null }}
      />
    );

    expect(screen.queryByRole("heading", { name: "Active Pending Entry" })).not.toBeInTheDocument();
    expect(screen.queryByText("Accepted setup is waiting for the backend trigger service to detect the entry zone.")).not.toBeInTheDocument();
    expect(screen.queryByText("История ожидания входа")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Диагностика/u }));

    expect(screen.getByText("История ожидания входа")).toBeInTheDocument();
    expect(screen.getAllByText("cancelled").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByText("История ожидания входа"));
    expect(screen.getByText("Cancelled by user.")).toBeInTheDocument();
    expect(screen.getByText("2026-05-31 07:15:00Z")).toBeInTheDocument();
  });

  it("does not render cancelled legacy auto-entry as an active pending card", () => {
    render(
      <SignalDetails
        busy={false}
        executionPreview={null}
        onPaperTrade={vi.fn()}
        onReject={vi.fn()}
        signal={{
          ...signal,
          status: "ready",
          no_trade_filter: null,
          auto_entry: autoEntry({
            status: "cancelled",
            message: "AutoEntry cancelled"
          })
        }}
      />
    );

    expect(screen.queryByRole("heading", { name: "Active Pending Entry" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Legacy auto-entry state" })).not.toBeInTheDocument();
    expect(screen.queryByText("Accepted setup is waiting for the backend trigger service to detect the entry zone.")).not.toBeInTheDocument();
    expect(screen.queryByText("Auto-entry diagnostics")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Диагностика/u }));

    expect(screen.getByText("Auto-entry diagnostics")).toBeInTheDocument();
  });

  it("shows requires reconfirmation banner", () => {
    const onReconfirmPendingEntry = vi.fn();
    render(
      <SignalDetails
        busy={false}
        executionPreview={null}
        onReconfirmPendingEntry={onReconfirmPendingEntry}
        onPaperTrade={vi.fn()}
        onReject={vi.fn()}
        pendingEntry={pendingIntent({
          status: "requires_reconfirmation",
          failure_reason: "Trade plan changed after acceptance; reconfirmation required."
        })}
        signal={{ ...signal, status: "ready", no_trade_filter: null }}
      />
    );

    expect(screen.getAllByText("Requires reconfirmation").length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { name: "Active Pending Entry" })).toBeInTheDocument();
    expect(screen.getByText("Trade plan changed after acceptance; reconfirmation required.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Reconfirm plan/u }));
    expect(onReconfirmPendingEntry).toHaveBeenCalledTimes(1);
  });
});

function pendingIntent(overrides: Partial<PendingEntryIntent> = {}): PendingEntryIntent {
  return {
    id: "intent_1",
    user_id: "user_1",
    signal_id: signal.id,
    strategy_id: null,
    mode: "virtual",
    status: "pending",
    exchange: signal.exchange,
    symbol: signal.symbol,
    side: signal.direction,
    entry_min: 100,
    entry_max: 101,
    entry_price_policy: "accepted_entry_zone",
    stop_loss: 95,
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

function realTradeContext(overrides: Partial<RealTradeContext> = {}): RealTradeContext {
  return {
    userId: "user_1",
    connection: {
      id: "conn_1",
      user_id: "user_1",
      exchange_id: "ex_bybit",
      exchange_code: "bybit",
      exchange_name: "Bybit",
      label: "Bybit testnet",
      account_type: "linear",
      key_ref: "vault:bybit:testnet",
      permissions: {},
      status: "active",
      last_sync_at: "2026-06-04T12:00:00.000Z",
      metadata: { testnet: true },
      created_at: "2026-06-04T11:00:00.000Z"
    },
    accountSnapshot: accountSnapshot(),
    riskState: null,
    realExecutionEnabled: true,
    loading: false,
    ...overrides
  };
}

function accountSnapshot(): NonNullable<RealTradeContext["accountSnapshot"]> {
  return {
    status: "fresh",
    fetched_at: new Date().toISOString(),
    account_equity: 10_000,
    available_balance: 8_000,
    wallet_balance: 10_000,
    margin_mode: "cross",
    total_initial_margin: 500,
    total_maintenance_margin: 50,
    maintenance_margin_rate: 0.005,
    positions: [],
    open_risk_amount: 0,
    source: "exchange",
    warnings: []
  };
}

function autoEntry(
  overrides: Partial<NonNullable<RadarSignal["auto_entry"]>> = {}
): NonNullable<RadarSignal["auto_entry"]> {
  return {
    enabled: true,
    status: "pending",
    mode: "virtual",
    user_id: "user_1",
    armed_at: "2026-05-31T07:00:00.000Z",
    triggered_at: null,
    message: null,
    request: {},
    trade_id: null,
    real_execution: null,
    ...overrides
  };
}
