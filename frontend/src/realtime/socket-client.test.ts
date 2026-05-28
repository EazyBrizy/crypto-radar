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
