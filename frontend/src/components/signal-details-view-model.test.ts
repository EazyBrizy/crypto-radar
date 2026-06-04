import { describe, expect, it } from "vitest";

import type { PendingEntryIntent, RadarSignal } from "@/types";
import { buildSignalDetailsViewModel } from "./signal-details-view-model";

const formingCandleRawReason = "forming_candle: forming candle preview is not actionable until the candle closes";

describe("buildSignalDetailsViewModel", () => {
  it("collapses duplicate forming_candle messages into one entry blocker", () => {
    const signal = baseSignal({
      candle_state: "open",
      can_enter: false,
      confirmation: {
        passed: false,
        checks: [
          {
            name: "candle_state_gate",
            status: "failed",
            score: null,
            reason: formingCandleRawReason,
            metadata: { reason_code: "forming_candle" }
          }
        ]
      },
      decision: {
        setup_valid: true,
        trade_plan_valid: true,
        market_context_score: 72,
        signal_actionable: false,
        execution_allowed_virtual: false,
        execution_allowed_real: null,
        blockers: [
          {
            code: "forming_candle",
            message: formingCandleRawReason,
            source: "data",
            severity: "blocker",
            scope: "virtual",
            metadata: {}
          }
        ],
        warnings: []
      },
      risks: [formingCandleRawReason]
    });

    const viewModel = buildSignalDetailsViewModel(signal, null);
    const formingBlockers = viewModel.topBlockers.filter((blocker) => blocker.code === "forming_candle");

    expect(formingBlockers).toHaveLength(1);
    expect(formingBlockers[0].category).toBe("entry");
    expect(formingBlockers[0].userMessage).toBe("Свеча ещё формируется. Вход будет доступен после закрытия свечи.");
    expect(formingBlockers[0].debugMessages.length).toBeGreaterThan(1);
  });

  it("collapses multiple liquidation missing-field messages into one technical blocker", () => {
    const signal = baseSignal({
      no_trade_filter: {
        enabled: true,
        blocked: true,
        hard_block: true,
        blockers: [
          "liquidation_price is missing",
          "liquidation_buffer_percent is missing for liquidation guard"
        ],
        warnings: [],
        checks: [],
        metadata: {}
      }
    });

    const viewModel = buildSignalDetailsViewModel(signal, null);
    const liquidationBlockers = viewModel.topBlockers.filter((blocker) => blocker.code === "liquidation_missing_fields");

    expect(liquidationBlockers).toHaveLength(1);
    expect(liquidationBlockers[0].category).toBe("technical");
    expect(liquidationBlockers[0].severity).toBe("blocker");
    expect(liquidationBlockers[0].debugMessages).toEqual(expect.arrayContaining([
      "liquidation_price is missing",
      "liquidation_buffer_percent is missing for liquidation guard"
    ]));
  });

  it("treats cancelled pendingEntry as terminal instead of active", () => {
    const viewModel = buildSignalDetailsViewModel(baseSignal(), pendingIntent({ status: "cancelled" }));

    expect(viewModel.activePendingEntry).toBeNull();
    expect(viewModel.terminalPendingEntry?.status).toBe("cancelled");
    expect(viewModel.primaryStatus).toBe("execution_ready");
  });

  it("uses waiting_entry primary status for active pending entry", () => {
    const viewModel = buildSignalDetailsViewModel(baseSignal(), pendingIntent({ status: "pending" }));

    expect(viewModel.activePendingEntry?.status).toBe("pending");
    expect(viewModel.terminalPendingEntry).toBeNull();
    expect(viewModel.primaryStatus).toBe("waiting_entry");
  });

  it("uses requires_reconfirmation primary status for reconfirmation pending entry", () => {
    const viewModel = buildSignalDetailsViewModel(baseSignal(), pendingIntent({ status: "requires_reconfirmation" }));

    expect(viewModel.activePendingEntry?.status).toBe("requires_reconfirmation");
    expect(viewModel.primaryStatus).toBe("requires_reconfirmation");
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
    confirmation: {
      passed: true,
      checks: []
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
        { label: "TP2", price: 2_200, r_multiple: 2.5, action: "full_close", close_percent: 60, source: "rr", metadata: {} }
      ],
      invalidation: {
        price: 2_060,
        hard_stop: 2_060,
        conditions: ["Breakout fails"],
        metadata: {}
      },
      risk_rules: {
        risk_reward: 2.5,
        first_target_rr: 1,
        final_target_rr: 2.5,
        selected_rr: 2.5,
        selected_rr_target: "final",
        min_rr_ratio: 1.5,
        metadata: {}
      },
      metadata: {}
    },
    no_trade_filter: null,
    edge: null,
    decision: {
      setup_valid: true,
      trade_plan_valid: true,
      market_context_score: 84,
      signal_actionable: true,
      execution_allowed_virtual: true,
      execution_allowed_real: null,
      blockers: [],
      warnings: []
    },
    rr_status: "passed",
    risk_gate_status: "passed",
    can_enter: true,
    display_reason: null,
    created_at: "2026-05-31T07:00:00.000Z",
    updated_at: "2026-05-31T07:00:00.000Z",
    expires_at: "2026-05-31T08:00:00.000Z",
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
    accepted_trade_plan_snapshot: { entry: { min_price: "2100", max_price: "2105" } },
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
