import { describe, expect, it, vi } from "vitest";

import type { PendingEntryIntent, RadarSignal, SignalStatus } from "@/types";
import { canArmAutoEntry, canSendPaperTrade, selectPendingEntryForDetails, selectRealTradeConnection, shouldRequestExecutionPreview } from "./RadarRoute";
import type { ExchangeConnection } from "@/features/server-state/types";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() })
}));

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
  expires_at: "2026-05-31T08:00:00.000Z"
};

function signalWithStatus(status: SignalStatus): RadarSignal {
  return { ...baseSignal, status };
}

describe("shouldRequestExecutionPreview", () => {
  it("keeps Reality Check populated for armed and pending Trend Pullback statuses", () => {
    expect(shouldRequestExecutionPreview(signalWithStatus("new"), "open", false)).toBe(true);
    expect(shouldRequestExecutionPreview(signalWithStatus("watchlist"), "open", false)).toBe(true);
    expect(shouldRequestExecutionPreview(signalWithStatus("ready"), "open", false)).toBe(true);
    expect(shouldRequestExecutionPreview(signalWithStatus("wait_for_pullback"), "open", false)).toBe(true);
  });

  it("does not preview history, blocked UI state, or terminal signals", () => {
    expect(shouldRequestExecutionPreview(signalWithStatus("ready"), "history", false)).toBe(false);
    expect(shouldRequestExecutionPreview(signalWithStatus("ready"), "open", true)).toBe(false);
    expect(shouldRequestExecutionPreview(signalWithStatus("expired"), "open", false)).toBe(false);
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
    expect(canSendPaperTrade({ ...signalWithStatus("actionable"), can_enter: true })).toBe(true);
    expect(canSendPaperTrade({ ...signalWithStatus("entry_touched"), can_enter: true })).toBe(true);
    expect(canSendPaperTrade({ ...signalWithStatus("entry_touched"), can_enter: false })).toBe(false);
  });

  it("does not turn soft or legacy RR warnings into enter permission", () => {
    const lowRrSignal: RadarSignal = {
      ...baseSignal,
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

    expect(canArmAutoEntry(lowRrSignal)).toBe(true);
    expect(canSendPaperTrade(lowRrSignal)).toBe(false);
  });

  it("allows market opportunities to arm pending entry and blocks duplicate pending arms", () => {
    expect(canArmAutoEntry(signalWithStatus("active"))).toBe(true);
    expect(canArmAutoEntry({
      ...signalWithStatus("ready"),
      auto_entry: {
        enabled: true,
        status: "pending",
        mode: "virtual",
        user_id: "user_1",
        armed_at: "2026-05-31T07:00:00.000Z",
        triggered_at: null,
        message: null,
        request: {},
        trade_id: null,
        real_execution: null
      }
    })).toBe(false);
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
    key_ref: "vault:bybit:testnet",
    permissions: {},
    status: "active",
    last_sync_at: null,
    metadata: { testnet: true },
    created_at: "2026-06-04T11:00:00.000Z",
    ...overrides
  };
}
