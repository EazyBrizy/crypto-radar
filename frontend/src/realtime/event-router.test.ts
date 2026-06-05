import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, beforeEach, vi } from "vitest";

import { queryKeys, serverStateKeys } from "@/features/server-state/query-keys";
import { useNotificationStore } from "@/stores/notification-store";
import { useSignalStore } from "@/stores/signal-store";
import type { PendingEntryIntent, RadarResponse, RadarSignal, TradeJournalEntry } from "@/types";
import { createRealtimeEventRouter } from "./event-router";

const baseSignal: RadarSignal = {
  id: "sig_1",
  symbol: "BTCUSDT",
  exchange: "BINANCE",
  strategy: "EMA_PULLBACK",
  direction: "long",
  confidence: 0.84,
  risk_reward: 2.1,
  first_target_rr: 1.4,
  final_target_rr: 2.1,
  selected_rr: 2.1,
  selected_rr_target: "final",
  min_rr_ratio: 2,
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
  status_reason: null,
  quality: null,
  regime: null,
  setup: null,
  confirmation: null,
  invalidation: null,
  exit_plan: null,
  auto_entry: null,
  created_at: "2026-05-25T10:12:41.231Z",
  updated_at: "2026-05-25T10:12:41.231Z",
  expires_at: "2099-05-25T11:12:41.231Z"
};

const baseTrade: TradeJournalEntry = {
  id: "trade_1",
  user_id: "demo_user",
  signal_id: "sig_1",
  mode: "virtual",
  source: "virtual",
  tags: [],
  run_id: null,
  exchange: "bybit",
  symbol: "BTCUSDT",
  strategy: "trend_pullback_continuation",
  timeframe: "15m",
  side: "long",
  entry_price: 100,
  current_price: 95,
  exit_price: null,
  size_usd: 100,
  quantity: 1,
  leverage: 1,
  risk_percent: 1,
  risk_amount: 1,
  risk_reward: 2,
  stop_loss: 90,
  take_profit: [110],
  fees: 0,
  slippage_bps: 0,
  simulation_mode: "passive",
  execution_status: "filled",
  requested_size_usd: null,
  filled_size_usd: null,
  unfilled_size_usd: 0,
  execution: null,
  status: "open",
  result: null,
  close_reason: null,
  pnl: null,
  pnl_percent: null,
  mfe: 0,
  mae: 0,
  screenshots: [],
  ai_review: null,
  opened_at: "2026-05-25T10:12:41.231Z",
  updated_at: "2026-05-25T10:12:41.231Z",
  closed_at: null
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

  it("updates full signal.updated payloads without moving an old signal to the top", () => {
    const queryClient = new QueryClient();
    const topSignal = { ...baseSignal, id: "sig_top", symbol: "ETHUSDT" };
    const updatedSignal = { ...baseSignal, score: 91, updated_at: "2026-05-25T10:13:43.231Z" };
    queryClient.setQueryData(queryKeys.signals, [topSignal, baseSignal]);
    queryClient.setQueryData(queryKeys.radar, { signals: [topSignal, baseSignal] });
    useSignalStore.getState().replaceSignals([topSignal, baseSignal]);
    const router = createRealtimeEventRouter({ queryClient, onRealtimeEvent: () => undefined });

    router.route({
      id: "evt_updated_full",
      type: "signal.updated",
      version: 1,
      timestamp: "2026-05-25T10:13:43.231Z",
      payload: {
        signal: updatedSignal,
        signalId: "sig_1"
      }
    });

    expect(useSignalStore.getState().signalIds).toEqual(["sig_top", "sig_1"]);
    expect(useSignalStore.getState().signalsById.sig_1.score).toBe(91);
    expect(queryClient.getQueryData<RadarSignal[]>(queryKeys.signals)?.map((signal) => signal.id)).toEqual(["sig_top", "sig_1"]);
    expect(queryClient.getQueryData<RadarResponse>(queryKeys.radar)?.signals.map((signal) => signal.id)).toEqual(["sig_top", "sig_1"]);
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

  it("stores trade.invalidation alerts and pushes a notification", () => {
    const queryClient = new QueryClient();
    const router = createRealtimeEventRouter({ queryClient, onRealtimeEvent: () => undefined });

    router.route({
      id: "evt_trade_invalidation",
      type: "trade.invalidation",
      version: 1,
      timestamp: "2026-05-25T10:12:46.231Z",
      payload: {
        alert: {
          trade_id: baseTrade.id,
          signal_id: baseTrade.signal_id,
          exchange: baseTrade.exchange,
          symbol: baseTrade.symbol,
          strategy: baseTrade.strategy,
          timeframe: baseTrade.timeframe,
          side: baseTrade.side,
          status: "invalidated",
          invalidated: true,
          reason: "Close below EMA50",
          triggered_conditions: ["Close below EMA50"],
          watched_conditions: ["Close below EMA50"],
          suggested_action: "close_market_or_wait_stop",
          current_price: 95,
          stop_loss: 90,
          invalidation_price: 96,
          detected_at: "2026-05-25T10:12:46.231Z",
          fingerprint: "fp_1",
          user_action: null,
          user_action_at: null,
          action_dismissed: false,
          metadata: {}
        },
        tradeId: baseTrade.id,
        signalId: baseTrade.signal_id,
        pair: baseTrade.symbol,
        exchange: baseTrade.exchange,
        side: "LONG",
        reason: "Close below EMA50",
        triggeredConditions: ["Close below EMA50"],
        fingerprint: "fp_1"
      }
    });

    expect(queryClient.getQueryData(serverStateKeys.trades.invalidation(baseTrade.id))).toMatchObject({
      invalidated: true,
      trade_id: baseTrade.id
    });
    expect(useNotificationStore.getState().notifications[0]?.title).toBe("Strategy invalidation");
  });

  it("routes pending_entry.updated events into pending-entry caches", () => {
    const queryClient = new QueryClient();
    const intent = pendingIntent();
    const activeKey = serverStateKeys.signals.pendingEntry("sig_1", "user_1");
    const historyKey = serverStateKeys.signals.pendingEntryHistory("sig_1", "user_1");
    const activeQueueKey = serverStateKeys.signals.pendingEntries("active", "user_1");
    const historyQueueKey = serverStateKeys.signals.pendingEntries("history", "user_1");
    queryClient.setQueryData(activeKey, intent);
    queryClient.setQueryData(historyKey, []);
    queryClient.setQueryData(activeQueueKey, [intent]);
    queryClient.setQueryData(historyQueueKey, []);
    queryClient.setQueryData(queryKeys.signals, [{
      ...baseSignal,
      auto_entry: {
        enabled: true,
        status: "pending",
        mode: "virtual",
        user_id: "user_1",
        armed_at: "2026-05-25T10:12:41.231Z",
        triggered_at: null,
        message: null,
        request: {},
        trade_id: null,
        real_execution: null
      }
    }]);
    useSignalStore.getState().addSignal({
      ...baseSignal,
      auto_entry: {
        enabled: true,
        status: "pending",
        mode: "virtual",
        user_id: "user_1",
        armed_at: "2026-05-25T10:12:41.231Z",
        triggered_at: null,
        message: null,
        request: {},
        trade_id: null,
        real_execution: null
      }
    });
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
    const router = createRealtimeEventRouter({ queryClient, onRealtimeEvent: () => undefined });

    router.route({
      id: "evt_pending_entry_filled",
      type: "pending_entry.updated",
      version: 1,
      timestamp: "2026-05-25T10:12:47.231Z",
      payload: {
        user_id: "user_1",
        signal_id: "sig_1",
        pending_entry_id: "intent_1",
        status: "filled",
        mode: "virtual",
        reason: "Virtual trade filled.",
        message: "Virtual trade filled.",
        updated_at: "2026-05-25T10:12:47.231Z"
      }
    });

    expect(queryClient.getQueryData(activeKey)).toBeNull();
    expect(queryClient.getQueryData<PendingEntryIntent[]>(historyKey)?.[0]).toMatchObject({
      id: "intent_1",
      status: "filled",
      failure_reason: "Virtual trade filled."
    });
    expect(queryClient.getQueryData<PendingEntryIntent[]>(activeQueueKey)).toEqual([]);
    expect(queryClient.getQueryData<PendingEntryIntent[]>(historyQueueKey)?.[0]).toMatchObject({
      id: "intent_1",
      status: "filled",
      failure_reason: "Virtual trade filled."
    });
    expect(useSignalStore.getState().signalsById.sig_1.auto_entry?.status).toBe("filled");
    expect(queryClient.getQueryData<RadarSignal[]>(queryKeys.signals)?.[0]?.auto_entry?.status).toBe("filled");
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: activeKey });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: historyKey });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: activeQueueKey });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: historyQueueKey });
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: serverStateKeys.signals.pendingEntry("sig_1", "demo_user")
    });
  });
});

function pendingIntent(overrides: Partial<PendingEntryIntent> = {}): PendingEntryIntent {
  return {
    id: "intent_1",
    user_id: "user_1",
    signal_id: "sig_1",
    strategy_id: null,
    mode: "virtual",
    status: "pending",
    exchange: "bybit",
    symbol: "BTCUSDT",
    side: "long",
    entry_min: 67850,
    entry_max: 68100,
    entry_price_policy: "accepted_entry_zone",
    stop_loss: 67420,
    targets_snapshot: [{ label: "TP1", price: "68900" }],
    accepted_trade_plan_snapshot: { entry: { min_price: "67850", max_price: "68100" } },
    accepted_trade_plan_hash: "sha256:test",
    accepted_signal_status: "active",
    accepted_signal_version: null,
    accepted_signal_fingerprint: null,
    execution_profile_snapshot: {},
    request_snapshot: {},
    idempotency_key: "pending-entry:test",
    expires_at: "2099-05-25T11:12:41.231Z",
    created_at: "2026-05-25T10:12:41.231Z",
    updated_at: "2026-05-25T10:12:41.231Z",
    triggered_at: null,
    filled_at: null,
    filled_trade_id: null,
    failure_reason: null,
    ...overrides
  };
}
