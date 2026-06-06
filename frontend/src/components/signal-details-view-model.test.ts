import { describe, expect, it } from "vitest";

import type { PendingEntryIntent, RadarSignal, SignalActionState, SignalDetailsView } from "@/types";
import { buildSignalDetailsViewModel } from "./signal-details-view-model";

describe("buildSignalDetailsViewModel", () => {
  it("uses backend details view and backend action-state for actions/blockers", () => {
    const viewModel = buildSignalDetailsViewModel(baseSignal(), null, {
      actionState: actionState({
        can_enter_now: false,
        can_arm_pending: true,
        primary_action: "arm_pending_entry",
        blockers: [
          {
            code: "risk_profile_unavailable",
            severity: "blocker",
            message: "Risk profile is unavailable.",
            display_label: "Risk profile unavailable",
            metadata: {}
          }
        ],
        display_labels: {
          primary_action: "Wait for backend trigger",
          disabled_reason: "Risk profile unavailable"
        }
      })
    });

    expect(viewModel.canEnterNow).toBe(false);
    expect(viewModel.primaryActionLabel).toBe("Wait for backend trigger");
    expect(viewModel.recommendedActionText).toBe("Risk profile unavailable");
    expect(viewModel.topBlockers.map((blocker) => blocker.userMessage)).toEqual([
      "Risk profile unavailable",
      "Backend liquidity blocker"
    ]);
  });

  it("surfaces a contract error when SignalDetailsView is missing", () => {
    const viewModel = buildSignalDetailsViewModel({ ...baseSignal(), details_view: null }, null);

    expect(viewModel.contractError).toBe("API contract error: SignalDetailsView is missing");
    expect(viewModel.primaryActionLabel).toBe("Action state unavailable");
    expect(viewModel.tradePlanSummary.entry_type).toBe("API contract error");
  });

  it("labels rejected and invalidated signals as different terminal states", () => {
    const rejected = buildSignalDetailsViewModel(
      baseSignal({ status: "rejected", details_view: detailsView({ primary_status_label: "Invalidated" }) }),
      null
    );
    const invalidated = buildSignalDetailsViewModel(
      baseSignal({ status: "invalidated", details_view: detailsView({ primary_status_label: "Rejected" }) }),
      null
    );

    expect(rejected.primaryStatusLabel).toBe("Отклонено фильтром");
    expect(invalidated.primaryStatusLabel).toBe("Сломано рынком / потеряло актуальность");
    expect(rejected.primaryStatusLabel).not.toBe(invalidated.primaryStatusLabel);
  });

  it("classifies active and terminal pending entries without changing backend primary status", () => {
    const active = buildSignalDetailsViewModel(baseSignal({ details_view: detailsView({ primary_status: "waiting_entry" }) }), pendingIntent({ status: "pending" }));
    const terminal = buildSignalDetailsViewModel(baseSignal(), pendingIntent({ status: "cancelled" }));
    const reconfirm = buildSignalDetailsViewModel(baseSignal({ details_view: detailsView({ primary_status: "requires_reconfirmation" }) }), pendingIntent({ status: "requires_reconfirmation" }));

    expect(active.activePendingEntry?.status).toBe("pending");
    expect(active.terminalPendingEntry).toBeNull();
    expect(active.primaryStatus).toBe("waiting_entry");
    expect(terminal.activePendingEntry).toBeNull();
    expect(terminal.terminalPendingEntry?.status).toBe("cancelled");
    expect(reconfirm.activePendingEntry?.status).toBe("requires_reconfirmation");
    expect(reconfirm.primaryStatus).toBe("requires_reconfirmation");
  });

  it("ignores legacy signal auto_entry when pending-entry DTO is absent", () => {
    const viewModel = buildSignalDetailsViewModel(
      baseSignal({
        auto_entry: {
          enabled: true,
          status: "pending",
          mode: "virtual",
          user_id: "user_1",
          armed_at: "2026-05-31T07:00:00.000Z",
          triggered_at: null,
          message: "Legacy mirror",
          request: {},
          trade_id: null,
          real_execution: null
        }
      }),
      null,
      { actionState: actionState({ can_enter_now: true, can_arm_pending: false }) }
    );

    expect(viewModel.activePendingEntry).toBeNull();
    expect(viewModel.terminalPendingEntry).toBeNull();
    expect(viewModel.canEnterNow).toBe(true);
    expect(viewModel.primaryActionLabel).toBe("Enter now");
    expect(viewModel.diagnostics.pendingEntryStatus).toBeNull();
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
        code: "backend_liquidity",
        severity: "blocker",
        category: "liquidity",
        user_message: "Backend liquidity blocker",
        debug_messages: ["liquidity"]
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
    reason_code: null,
    localized_reason: null,
    view: null,
    ...overrides
  };
}
