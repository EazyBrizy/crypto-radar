import { describe, expect, it, vi } from "vitest";

import { appendWebSocketToken, parseRealtimeMessage } from "./socket-client";
import { createSubscribeMessage } from "./subscriptions";

const signal = {
  id: "sig_123",
  symbol: "BTCUSDT",
  exchange: "BINANCE",
  strategy: "EMA_PULLBACK",
  direction: "long",
  confidence: 0.84,
  risk_reward: null,
  urgency: "medium",
  status: "active",
  score: 84,
  timeframe: "15m",
  entry_min: 67850,
  entry_max: 68100,
  stop_loss: 67420,
  take_profit_1: 68900,
  take_profit_2: 69450,
  explanation: [],
  risks: [],
  card_view: {
    status_label: "Execution-ready",
    status_tone: "green",
    opportunity_label: "Execution-ready",
    opportunity_tone: "green",
    risk_label: "Medium",
    risk_meta: "Risk: Medium | score 84 | urgency medium",
    badges: [{ code: "opportunity", label: "Execution-ready", tone: "green" }],
    entry_label: "trade plan",
    entry_value: "67850-68100",
    stop_loss: 67420,
    targets: [{ label: "TP1", price: 68900, r_multiple: 1.5, action: null }],
    selected_rr: 2.1,
    reason: "Backend view model",
    backend_extra: "card-extra"
  },
  details_view: {
    title: "BTCUSDT LONG Signal",
    side: "long",
    primary_status: "execution_ready",
    primary_status_label: "execution ready",
    primary_status_tone: "green",
    primary_action_label: "Enter now",
    recommended_action_text: "Backend returned action context.",
    can_enter_now: true,
    trade_plan: {
      has_trade_plan: true,
      entry_type: "trade plan",
      entry_zone: "67850-68100",
      entry_price: 67975,
      stop_loss: 67420,
      targets: [{ label: "TP1", price: 68900, r_multiple: 1.5, action: null }],
      selected_rr: 2.1,
      selected_rr_target: "final",
      min_rr: 2,
      trade_plan_complete: true,
      fallback_used: false,
      missing: [],
      invalidation: "-"
    },
    risk_summary: {
      label: "Medium",
      risk_failed: false,
      risk_reward_blocked: false,
      risk_reward_warning: null,
      forming_candle: false,
      open_candle_allowed: true,
      forming_reason: null,
      status_allows_trade: true,
      trade_plan_complete: true,
      risk_reward_ok: true,
      is_market_opportunity: true
    },
    execution_summary: {
      preview_available: true,
      risk_check_status: "passed",
      risk_decision_status: "passed",
      can_enter: true,
      quality_gate_status: null,
      impact_risk: null,
      status_allows_trade: true
    },
    top_reasons: ["Backend view model"],
    top_blockers: [],
    warnings: [],
    backend_extra: "details-extra"
  },
  backend_extra: "signal-extra",
  created_at: "2026-05-25T10:12:41.231Z",
  updated_at: "2026-05-25T10:12:41.231Z"
};

describe("parseRealtimeMessage", () => {
  it("accepts a valid signal.created event envelope", () => {
    const parsed = parseRealtimeMessage(JSON.stringify({
      id: "evt_01HX",
      type: "signal.created",
      version: 1,
      timestamp: "2026-05-25T10:12:41.231Z",
      payload: {
        signal,
        signalId: "sig_123",
        pair: "BTCUSDT",
        exchange: "BINANCE",
        side: "LONG",
        strategy: "EMA_PULLBACK",
        confidence: 84,
        risk: "MEDIUM",
        entryZone: { from: 67850, to: 68100 },
        stopLoss: 67420,
        takeProfit: [68900, 69450],
        timeframe: "15m"
      }
    }));

    expect(parsed?.type).toBe("signal.created");
    if (parsed?.type === "signal.created") {
      expect(parsed.payload.signal.card_view?.status_label).toBe("Execution-ready");
      expect(parsed.payload.signal.details_view?.primary_status).toBe("execution_ready");
      expect((parsed.payload.signal as Record<string, unknown>).backend_extra).toBe("signal-extra");
      expect((parsed.payload.signal.card_view as Record<string, unknown> | null)?.backend_extra).toBe("card-extra");
      expect((parsed.payload.signal.details_view as Record<string, unknown> | null)?.backend_extra).toBe("details-extra");
    }
  });

  it("drops invalid realtime payloads", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);

    const parsed = parseRealtimeMessage(JSON.stringify({
      id: "evt_bad",
      type: "signal.created",
      version: 1,
      timestamp: "2026-05-25T10:12:41.231Z",
      payload: {
        signalId: "sig_123",
        pair: "BTCUSDT",
        side: "SIDEWAYS",
        confidence: "high"
      }
    }));

    expect(parsed).toBeNull();
    expect(warn).toHaveBeenCalledOnce();
    warn.mockRestore();
  });
});

describe("appendWebSocketToken", () => {
  it("adds a short-lived token to the websocket handshake url", () => {
    const url = appendWebSocketToken("wss://api.crypto-radar.com/ws?channel=signals", "short_lived_ws_token");

    expect(url).toBe("wss://api.crypto-radar.com/ws?channel=signals&token=short_lived_ws_token");
  });

  it("does not change the url when no token is available", () => {
    const url = appendWebSocketToken("ws://127.0.0.1:8000/api/v1/realtime/ws", null);

    expect(url).toBe("ws://127.0.0.1:8000/api/v1/realtime/ws");
  });
});

describe("createSubscribeMessage", () => {
  it("includes lastEventId for replay-aware resubscribe", () => {
    expect(createSubscribeMessage({ channels: ["signals"], symbols: ["BTCUSDT"] }, "evt_123")).toEqual({
      type: "subscribe",
      channels: ["signals"],
      symbols: ["BTCUSDT"],
      lastEventId: "evt_123"
    });
  });
});
