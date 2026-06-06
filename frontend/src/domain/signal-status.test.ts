import { describe, expect, it } from "vitest";

import type { RadarSignal } from "@/types";
import {
  canShowEnterButton,
  canShowSignalEntryAction,
  isBlockedSignal,
  isExecutionCandidateStatus,
  isExecutionFeedSignal,
  isExecutionReady,
  isMarketOpportunity,
  isTerminalSignalStatus,
  isWaitingEntry,
  isWatchlistSignal,
  RADAR_STATUS_FILTERS,
  signalFeedKind,
  statusBadgeLabel
} from "./signal-status";

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
  status: "active",
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
  expires_at: "2026-05-31T08:00:00.000Z"
};

describe("signal status domain helper", () => {
  it("treats active as market opportunity and waiting entry, not execution-ready", () => {
    expect(isMarketOpportunity("active")).toBe(true);
    expect(isWaitingEntry("active")).toBe(true);
    expect(isExecutionCandidateStatus("active")).toBe(false);
    expect(isExecutionReady("active")).toBe(false);
    expect(canShowEnterButton(baseSignal)).toBe(false);
    expect(canShowEnterButton({ ...baseSignal, can_enter: true })).toBe(false);
    expect(canShowEnterButton({
      ...baseSignal,
      can_enter: true,
      decision: {
        setup_valid: true,
        trade_plan_valid: true,
        market_context_score: 80,
        signal_actionable: true,
        execution_allowed_virtual: true,
        execution_allowed_real: true,
        blockers: [],
        warnings: []
      }
    })).toBe(false);
  });

  it("marks entry-touched/actionable consistently as execution candidates and invalidated/expired as terminal", () => {
    for (const status of ["entry_touched", "actionable"] as const) {
      expect(isExecutionCandidateStatus(status)).toBe(true);
      expect(canShowEnterButton(withBackendEnter({ ...baseSignal, status }, true))).toBe(true);
      expect(canShowEnterButton(withBackendEnter({ ...baseSignal, status }, false))).toBe(false);
    }
    expect(isExecutionCandidateStatus("confirmed")).toBe(true);
    expect(isTerminalSignalStatus("invalidated")).toBe(true);
    expect(isTerminalSignalStatus("expired")).toBe(true);
    expect(isTerminalSignalStatus("rejected")).toBe(true);
  });

  it("exposes rejected as a distinct terminal filter and badge label", () => {
    const rejected = { ...baseSignal, status: "rejected" } satisfies RadarSignal;

    expect(RADAR_STATUS_FILTERS).toContain("rejected");
    expect(statusBadgeLabel(rejected)).toBe("Отклонён");
  });

  it("requires backend permission for actionable and entry-touched signals", () => {
    expect(canShowEnterButton({ ...baseSignal, status: "actionable" })).toBe(false);
    expect(canShowEnterButton({ ...baseSignal, status: "entry_touched" })).toBe(false);
    expect(canShowEnterButton({ ...baseSignal, status: "actionable", can_enter: true })).toBe(false);
    expect(canShowEnterButton(withBackendEnter({ ...baseSignal, status: "actionable" }, true))).toBe(true);
    expect(canShowEnterButton(withBackendEnter({ ...baseSignal, status: "entry_touched" }, true))).toBe(true);
    expect(canShowEnterButton(withBackendEnter({ ...baseSignal, status: "entry_touched" }, false))).toBe(false);
  });

  it("ignores legacy decision snapshots for enter permission", () => {
    const signal: RadarSignal = {
      ...baseSignal,
      status: "actionable",
      decision: {
        setup_valid: true,
        trade_plan_valid: true,
        market_context_score: 80,
        signal_actionable: true,
        execution_allowed_virtual: true,
        execution_allowed_real: null,
        blockers: [],
        warnings: []
      }
    };

    expect(canShowEnterButton(signal)).toBe(false);
    expect(canShowEnterButton(withBackendEnter(signal, true))).toBe(true);
  });

  it("uses execution gate feed kind as the UI source of truth", () => {
    const executionSignal = withExecutionGate(baseSignal, "execution_signal", {
      can_show_in_execution_feed: true,
      can_enter_now: true,
      can_arm_pending: true
    });
    const watchlistSignal = withExecutionGate(baseSignal, "watchlist", {
      can_show_in_execution_feed: false,
      can_enter_now: false,
      can_arm_pending: true
    });
    const blockedSignal = withExecutionGate(baseSignal, "blocked", {
      can_show_in_execution_feed: false,
      can_enter_now: false,
      can_arm_pending: false
    });

    expect(signalFeedKind(executionSignal)).toBe("execution_signal");
    expect(isExecutionFeedSignal(executionSignal)).toBe(true);
    expect(isWatchlistSignal(watchlistSignal)).toBe(true);
    expect(isBlockedSignal(blockedSignal)).toBe(true);
    expect(canShowEnterButton({ ...executionSignal, details_view: null })).toBe(true);
    expect(canShowEnterButton({ ...blockedSignal, details_view: null })).toBe(false);
  });

  it("lets execution gate override legacy can_enter and details action state", () => {
    const blockedByGate = withExecutionGate(
      withBackendEnter({ ...baseSignal, status: "actionable", can_enter: true }, true),
      "blocked",
      {
        can_show_in_execution_feed: false,
        can_enter_now: false,
        can_arm_pending: false
      }
    );

    expect(signalFeedKind(blockedByGate)).toBe("blocked");
    expect(isExecutionFeedSignal(blockedByGate)).toBe(false);
    expect(canShowEnterButton(blockedByGate)).toBe(false);
    expect(canShowSignalEntryAction(blockedByGate)).toBe(false);
  });
});

function withBackendEnter(signal: RadarSignal, canEnterNow: boolean): RadarSignal {
  return {
    ...signal,
    details_view: {
      title: signal.symbol,
      side: signal.direction,
      primary_status: canEnterNow ? "execution_ready" : "blocked",
      primary_status_label: canEnterNow ? "Execution ready" : "Blocked",
      primary_status_tone: canEnterNow ? "green" : "red",
      primary_action_label: canEnterNow ? "Enter now" : "Locked",
      recommended_action_text: "Backend action-state owns this decision.",
      can_enter_now: canEnterNow,
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
      execution_summary: {
        preview_available: canEnterNow,
        risk_check_status: null,
        risk_decision_status: null,
        can_enter: canEnterNow,
        quality_gate_status: null,
        impact_risk: null,
        status_allows_trade: true
      },
      top_reasons: [],
      top_blockers: [],
      warnings: []
    }
  };
}

function withExecutionGate(
  signal: RadarSignal,
  feedKind: "market_idea" | "watchlist" | "execution_signal" | "blocked",
  flags: {
    can_show_in_execution_feed: boolean;
    can_enter_now: boolean;
    can_arm_pending: boolean;
  }
): RadarSignal {
  return {
    ...signal,
    execution_gate: {
      status: feedKind === "blocked" ? "blocked" : flags.can_show_in_execution_feed ? "passed" : "warning",
      feed_kind: feedKind,
      can_notify: flags.can_show_in_execution_feed,
      can_enter_now: flags.can_enter_now,
      can_arm_pending: flags.can_arm_pending,
      can_show_in_execution_feed: flags.can_show_in_execution_feed,
      reasons: feedKind === "blocked"
        ? [{ code: "no_trade_hard_block", severity: "blocker", source: "no_trade", message: "No-trade hard block", metadata: {} }]
        : [],
      warnings: [],
      metadata: {}
    }
  };
}
