import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, beforeEach } from "vitest";

import { queryKeys, serverStateKeys } from "@/features/server-state/query-keys";
import { useNotificationStore } from "@/stores/notification-store";
import { useSignalStore } from "@/stores/signal-store";
import type { RadarSignal } from "@/types";
import { createRealtimeEventRouter } from "./event-router";

const baseSignal: RadarSignal = {
  id: "sig_1",
  symbol: "BTCUSDT",
  exchange: "BINANCE",
  strategy: "EMA_PULLBACK",
  direction: "long",
  confidence: 0.84,
  risk_reward: 2.1,
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
  created_at: "2026-05-25T10:12:41.231Z",
  updated_at: "2026-05-25T10:12:41.231Z",
  expires_at: "2099-05-25T11:12:41.231Z"
};

describe("createRealtimeEventRouter signal feed updates", () => {
  beforeEach(() => {
    useSignalStore.getState().clearSignals();
    useNotificationStore.getState().clear();
  });

  it("inserts a created signal at the top of the active query cache", () => {
    const queryClient = new QueryClient();
    const existing = { ...baseSignal, id: "sig_old", symbol: "ETHUSDT" };
    queryClient.setQueryData(queryKeys.signals, [existing]);
    const router = createRealtimeEventRouter({ queryClient, onRealtimeEvent: () => undefined });

    router.route({
      id: "evt_created",
      type: "signal.created",
      version: 1,
      timestamp: "2026-05-25T10:12:42.231Z",
      payload: {
        signal: baseSignal,
        signalId: baseSignal.id,
        pair: baseSignal.symbol,
        exchange: baseSignal.exchange,
        side: "LONG",
        strategy: baseSignal.strategy,
        confidence: 84,
        risk: "MEDIUM",
        entryZone: { from: baseSignal.entry_min, to: baseSignal.entry_max },
        stopLoss: baseSignal.stop_loss,
        takeProfit: [baseSignal.take_profit_1, baseSignal.take_profit_2].filter((price): price is number => typeof price === "number"),
        timeframe: baseSignal.timeframe
      }
    });

    expect(useSignalStore.getState().signalIds[0]).toBe("sig_1");
    expect(queryClient.getQueryData<RadarSignal[]>(queryKeys.signals)?.[0]?.id).toBe("sig_1");
  });

  it("applies signal.updated patches without replacing the whole feed", () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(queryKeys.signals, [baseSignal]);
    useSignalStore.getState().addSignal(baseSignal);
    const router = createRealtimeEventRouter({ queryClient, onRealtimeEvent: () => undefined });

    router.route({
      id: "evt_updated",
      type: "signal.updated",
      version: 1,
      timestamp: "2026-05-25T10:12:43.231Z",
      payload: {
        signalId: "sig_1",
        patch: { score: 91 }
      }
    });

    expect(useSignalStore.getState().signalsById.sig_1.score).toBe(91);
    expect(queryClient.getQueryData<RadarSignal[]>(queryKeys.signals)?.[0]?.score).toBe(91);
  });

  it("marks entry touched and pushes a notification", () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(queryKeys.signals, [baseSignal]);
    useSignalStore.getState().addSignal(baseSignal);
    const router = createRealtimeEventRouter({ queryClient, onRealtimeEvent: () => undefined });

    router.route({
      id: "evt_entry",
      type: "signal.entry_touched",
      version: 1,
      timestamp: "2026-05-25T10:12:44.231Z",
      payload: {
        price: 67900,
        signalId: "sig_1"
      }
    });

    expect(useSignalStore.getState().signalsById.sig_1.status).toBe("entry_touched");
    expect(useNotificationStore.getState().notifications[0]?.title).toBe("Entry zone touched");
  });

  it("removes expired signals from the active feed", () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(queryKeys.signals, [baseSignal]);
    useSignalStore.getState().addSignal(baseSignal);
    const router = createRealtimeEventRouter({ queryClient, onRealtimeEvent: () => undefined });

    router.route({
      id: "evt_expired",
      type: "signal.expired",
      version: 1,
      timestamp: "2026-05-25T10:12:45.231Z",
      payload: {
        signalId: "sig_1",
        reason: "ttl_expired"
      }
    });

    expect(useSignalStore.getState().signalIds).toEqual([]);
    expect(queryClient.getQueryData<RadarSignal[]>(queryKeys.signals)).toEqual([]);
  });

  it("routes persisted notification.created events into the notification store", () => {
    const queryClient = new QueryClient();
    const router = createRealtimeEventRouter({ queryClient, onRealtimeEvent: () => undefined });

    router.route({
      id: "evt_notification",
      type: "notification.created",
      version: 1,
      timestamp: "2026-05-25T10:12:45.231Z",
      payload: {
        notification: {
          id: "ntf_1",
          user_id: "user_1",
          type: "alert.rule_test",
          title: "Alert test",
          body: "BTCUSDT price_above",
          payload: { alert_rule_id: "rule_1" },
          is_read: false,
          created_at: "2026-05-25T10:12:45.231Z"
        },
        notificationId: "ntf_1",
        userId: "user_1",
        kind: "alert",
        title: "Alert test",
        body: "BTCUSDT price_above",
        payload: { alert_rule_id: "rule_1" },
        isRead: false,
        createdAt: "2026-05-25T10:12:45.231Z"
      }
    });

    expect(useNotificationStore.getState().notifications[0]?.id).toBe("ntf_1");
    expect(useNotificationStore.getState().notifications[0]?.kind).toBe("alert");
    expect(queryClient.isFetching({ queryKey: serverStateKeys.notifications.all() })).toBe(0);
  });
});
