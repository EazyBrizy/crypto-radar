import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { PendingEntryIntent, RadarSignal, SignalActionState, SignalDetailsView } from "@/types";
import { SignalDetails, type RealTradeContext } from "./SignalDetails";

vi.mock("next/dynamic", () => ({
  default: () => () => null
}));

describe("SignalDetails", () => {
  it("renders backend details and disables actions from backend action-state", () => {
    render(
      <SignalDetails
        actionState={actionState({
          can_enter_now: false,
          can_arm_pending: false,
          blockers: [
            {
              code: "backend_blocked",
              severity: "blocker",
              message: "Backend says execution is blocked.",
              display_label: "Backend blocked",
              metadata: {}
            }
          ],
          display_labels: {
            primary_action: "Wait for backend trigger",
            disabled_reason: "Backend blocked"
          }
        })}
        busy={false}
        executionPreview={null}
        onPaperTrade={vi.fn()}
        onReject={vi.fn()}
        signal={baseSignal()}
      />
    );

    expect(screen.getByText("Wait for backend trigger")).toBeInTheDocument();
    expect(screen.getAllByText("Backend blocked").length).toBeGreaterThan(0);
    expect(screen.getByText("Backend detail blocker")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Virtual entry locked/u })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Virtual wait entry/u })).toBeDisabled();
  });

  it("keeps virtual entry as a minimal intent when backend allows enter-now", () => {
    const onPaperTrade = vi.fn();
    render(
      <SignalDetails
        actionState={actionState({ can_enter_now: true, primary_action: "enter_now" })}
        busy={false}
        executionPreview={null}
        onPaperTrade={onPaperTrade}
        onReject={vi.fn()}
        signal={baseSignal()}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /Virtual entry now/u }));

    expect(onPaperTrade).toHaveBeenCalledTimes(1);
  });

  it("sends pending-entry intent only when backend action-state allows arming", () => {
    const onAcceptPendingEntry = vi.fn();
    render(
      <SignalDetails
        actionState={actionState({
          can_enter_now: false,
          can_arm_pending: true,
          primary_action: "arm_pending_entry",
          display_labels: { primary_action: "Wait for entry" }
        })}
        busy={false}
        executionPreview={null}
        onAcceptPendingEntry={onAcceptPendingEntry}
        onPaperTrade={vi.fn()}
        onReject={vi.fn()}
        signal={baseSignal({ details_view: detailsView({ primary_status: "waiting_entry", primary_action_label: "Wait for entry", can_enter_now: false }) })}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /Virtual wait entry/u }));

    expect(onAcceptPendingEntry).toHaveBeenCalledTimes(1);
  });

  it("renders backend pending-entry view and cancel intent state", () => {
    const onCancelPendingEntry = vi.fn();
    render(
      <SignalDetails
        actionState={actionState({ can_enter_now: false, can_arm_pending: false, can_cancel: true })}
        busy={false}
        executionPreview={null}
        onCancelPendingEntry={onCancelPendingEntry}
        onPaperTrade={vi.fn()}
        onReject={vi.fn()}
        pendingEntry={pendingIntent()}
        signal={baseSignal({ details_view: detailsView({ primary_status: "waiting_entry", primary_status_label: "Waiting entry", can_enter_now: false }) })}
      />
    );

    expect(screen.getByRole("heading", { name: "Active pending entry" })).toBeInTheDocument();
    expect(screen.getAllByText("Backend waiting").length).toBeGreaterThan(0);
    expect(screen.getByText("backend_waiting_entry")).toBeInTheDocument();
    expect(screen.getByText("Backend trigger service is waiting for entry.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Cancel waiting/u }));

    expect(onCancelPendingEntry).toHaveBeenCalledTimes(1);
  });

  it("uses real action-state for the real confirmation modal", () => {
    const onConfirmRealTrade = vi.fn();
    render(
      <SignalDetails
        actionState={actionState()}
        busy={false}
        executionPreview={null}
        onConfirmRealTrade={onConfirmRealTrade}
        onPaperTrade={vi.fn()}
        onReject={vi.fn()}
        realActionState={actionState({
          mode: "real",
          environment: "testnet",
          can_enter_now: false,
          can_arm_pending: true,
          primary_action: "arm_pending_entry",
          warnings: [
            {
              code: "dry_run",
              severity: "warning",
              message: "Exchange is in dry-run.",
              display_label: "Dry-run exchange",
              metadata: {}
            }
          ]
        })}
        realTradeContext={realTradeContext()}
        signal={baseSignal()}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /Real wait entry/u }));
    const dialog = screen.getByRole("dialog");

    expect(within(dialog).getByText("Real execution availability is backend-owned. Confirm only sends the selected intent.")).toBeInTheDocument();
    expect(within(dialog).getByText("Dry-run")).toBeInTheDocument();

    const buttons = within(dialog).getAllByRole("button");
    fireEvent.click(buttons[1] as HTMLButtonElement);

    expect(onConfirmRealTrade).toHaveBeenCalledTimes(1);
  });

  it("shows an API contract error when SignalDetailsView is missing", () => {
    render(
      <SignalDetails
        busy={false}
        executionPreview={null}
        onPaperTrade={vi.fn()}
        onReject={vi.fn()}
        signal={{ ...baseSignal(), details_view: null }}
      />
    );

    expect(screen.getAllByText("API contract error: SignalDetailsView is missing").length).toBeGreaterThan(0);
    expect(screen.getAllByText("API contract error").length).toBeGreaterThan(0);
  });
});

function baseSignal(overrides: Partial<RadarSignal> = {}): RadarSignal {
  return {
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
    confirmation: null,
    invalidation: null,
    exit_plan: null,
    auto_entry: null,
    card_view: null,
    details_view: detailsView(),
    created_at: "2026-05-31T07:00:00.000Z",
    updated_at: "2026-05-31T07:00:00.000Z",
    expires_at: "2026-05-31T08:00:00.000Z",
    ...overrides
  };
}

function detailsView(overrides: Partial<SignalDetailsView> = {}): SignalDetailsView {
  return {
    title: "ETHUSDT backend detail",
    side: "long",
    primary_status: "execution_ready",
    primary_status_label: "Execution ready",
    primary_status_tone: "green",
    primary_action_label: "Enter now",
    recommended_action_text: "Backend says this signal is ready.",
    can_enter_now: true,
    trade_plan: {
      has_trade_plan: true,
      entry_type: "Backend entry",
      entry_zone: "2100 - 2105",
      entry_price: 2_102,
      stop_loss: 2_060,
      targets: [
        { label: "TP1", price: 2_150, r_multiple: 1, action: "partial_close" },
        { label: "TP2", price: 2_200, r_multiple: 2.5, action: "full_close" }
      ],
      selected_rr: 2.5,
      selected_rr_target: "final",
      min_rr: 1.5,
      trade_plan_complete: true,
      fallback_used: false,
      missing: [],
      invalidation: "Below 2060"
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
    execution_summary: {
      preview_available: false,
      risk_check_status: null,
      risk_decision_status: null,
      can_enter: true,
      quality_gate_status: null,
      impact_risk: null,
      status_allows_trade: true
    },
    top_reasons: ["Backend reason"],
    top_blockers: [
      {
        code: "backend_detail_blocker",
        severity: "blocker",
        category: "execution",
        user_message: "Backend detail blocker",
        debug_messages: ["backend_detail_blocker"]
      }
    ],
    warnings: [],
    ...overrides
  };
}

function actionState(overrides: Partial<SignalActionState> = {}): SignalActionState {
  return {
    can_enter_now: true,
    can_arm_pending: false,
    can_reconfirm: false,
    can_cancel: false,
    mode: "virtual",
    environment: "virtual",
    primary_action: "enter_now",
    disabled_reason_code: null,
    blockers: [],
    warnings: [],
    accepted_trade_plan_snapshot: null,
    display_labels: {},
    ...overrides
  };
}

function pendingIntent(overrides: Partial<PendingEntryIntent> = {}): PendingEntryIntent {
  return {
    id: "intent_1",
    user_id: "user_1",
    signal_id: "sig_1",
    strategy_id: null,
    mode: "virtual",
    status: "pending",
    exchange: "bybit",
    symbol: "ETHUSDT",
    side: "long",
    entry_min: 2_100,
    entry_max: 2_105,
    entry_price_policy: "accepted_entry_zone",
    stop_loss: 2_060,
    targets_snapshot: [{ label: "TP1", price: "2150" }],
    accepted_trade_plan_snapshot: {},
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
    current_price: null,
    reason_code: "backend_waiting_entry",
    localized_reason: null,
    view: {
      status_label: "Backend waiting",
      status_tone: "yellow",
      reason_code: "backend_waiting_entry",
      reason: "Backend trigger service is waiting for entry.",
      entry_zone: "2100 - 2105",
      current_price: 2_101
    },
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
      deleted_at: null,
      deletion_reason: null,
      key_ref: "vault:bybit:testnet",
      permissions: {},
      revoked_at: null,
      status: "active",
      last_sync_at: "2026-06-04T12:00:00.000Z",
      last_account_snapshot_at: null,
      environment: "testnet",
      order_placement_mode: "dry_run",
      can_place_orders: false,
      safety_blockers: ["ORDER_PLACEMENT_DRY_RUN"],
      mainnet_explicitly_enabled: false,
      account_snapshot_status: "missing",
      metadata: {},
      created_at: "2026-06-04T11:00:00.000Z"
    },
    accountSnapshot: {
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
    },
    riskState: null,
    realExecutionEnabled: true,
    loading: false,
    ...overrides
  };
}
