import type { QueryClient } from "@tanstack/react-query";

import { queryKeys, serverStateKeys } from "@/features/server-state/query-keys";
import { warnIfRealtimeEventExceedsBudget } from "@/performance/budgets";
import { useNotificationStore } from "@/stores/notification-store";
import { usePriceStore } from "@/stores/price-store";
import { useSignalStore, type SignalPatch } from "@/stores/signal-store";
import type { HealthStatus, RadarResponse, RadarSignal, RadarStatus, SignalStatus, TradeJournalEntry, TradeJournalResponse } from "@/types";
import { isOpenFeedSignal } from "@/utils";
import type { NotificationRealtimePayload, RealtimeMessage, StandardRealtimeEvent } from "./event-types";

const MAX_RECENT_EVENT_IDS = 1_000;

export interface RealtimeEventRouter {
  getLastEventId: () => string | null;
  route: (message: RealtimeMessage) => void;
}

export function createRealtimeEventRouter(options: {
  queryClient: QueryClient;
  onRealtimeEvent: () => void;
  onHeartbeat?: () => void;
}): RealtimeEventRouter {
  const recentEventIds: string[] = [];
  const recentEventIdSet = new Set<string>();

  return {
    getLastEventId() {
      return recentEventIds[recentEventIds.length - 1] ?? null;
    },
    route(message) {
      const startedAt = typeof performance === "undefined" ? 0 : performance.now();
      options.onRealtimeEvent();

      if (isStandardRealtimeEvent(message)) {
        if (seenEvent(message.id, recentEventIds, recentEventIdSet)) return;
        routeStandardEvent(message, options);
        warnIfRealtimeEventExceedsBudget(message.type, startedAt);
        return;
      }

      if (message.type === "snapshot") {
        applySignalSnapshot(options.queryClient, message.signals);
        warnIfRealtimeEventExceedsBudget(message.type, startedAt);
        return;
      }

      if (isSignalEvent(message)) {
        applySignalCreated(options.queryClient, message.signal);
        warnIfRealtimeEventExceedsBudget(message.type, startedAt);
        return;
      }

      if (message.type === "signal.invalidated" || message.type === "signal.expired") {
        applySignalTerminalStatus(options.queryClient, message.signalId, message.type === "signal.expired" ? "expired" : "invalidated");
        warnIfRealtimeEventExceedsBudget(message.type, startedAt);
        return;
      }

      if (message.type === "signal.entry_touched") {
        applySignalEntryTouched(options.queryClient, message.signalId, message.price);
        warnIfRealtimeEventExceedsBudget(message.type, startedAt);
        return;
      }

      if (message.type === "take_profit.hit") {
        pushTakeProfitNotification(message.pair, message.price, message.target, message.tradeId);
        return;
      }

      if (message.type === "stop_loss.hit") {
        pushStopLossNotification(message.pair, message.price, message.tradeId);
        return;
      }

      if (message.type === "exchange.disconnected") {
        pushExchangeDisconnectedNotification(message.exchange, message.reason);
        return;
      }

      if (message.type === "health") {
        options.queryClient.setQueryData<HealthStatus>(serverStateKeys.health(), message.health);
        return;
      }

      if (message.type === "radar.status" || message.type === "status") {
        options.queryClient.setQueryData<RadarStatus>(serverStateKeys.radar.status(), message.status);
        return;
      }

      if (message.type === "trade.created" || message.type === "trade.updated") {
        applyTradeUpdate(options.queryClient, message.trade);
        return;
      }

      if (message.type === "connection.health") {
        options.onHeartbeat?.();
      }
    }
  };
}

function seenEvent(eventId: string, eventIds: string[], eventIdSet: Set<string>): boolean {
  if (eventIdSet.has(eventId)) return true;
  eventIdSet.add(eventId);
  eventIds.push(eventId);

  if (eventIds.length > MAX_RECENT_EVENT_IDS) {
    const removed = eventIds.shift();
    if (removed) eventIdSet.delete(removed);
  }

  return false;
}

function routeStandardEvent(
  event: StandardRealtimeEvent,
  options: {
    queryClient: QueryClient;
    onHeartbeat?: () => void;
  },
) {
  if (event.type === "signal.created") {
    applySignalCreated(options.queryClient, event.payload.signal);
    return;
  }

  if (event.type === "signal.updated") {
    if (event.payload.signal) {
      applySignalCreated(options.queryClient, event.payload.signal);
      return;
    }
    applySignalPatch(options.queryClient, event.payload.signalId, event.payload.patch ?? {});
    return;
  }

  if (event.type === "signal.invalidated" || event.type === "signal.expired") {
    const status = event.type === "signal.expired" ? "expired" : "invalidated";
    if (event.payload.signal) {
      applySignalCreated(options.queryClient, { ...event.payload.signal, status });
      return;
    }
    applySignalTerminalStatus(options.queryClient, event.payload.signalId, status);
    return;
  }

  if (event.type === "signal.entry_touched") {
    if (event.payload.signal) {
      applySignalCreated(options.queryClient, { ...event.payload.signal, status: "entry_touched" });
    } else {
      applySignalEntryTouched(options.queryClient, event.payload.signalId, event.payload.price);
    }
    return;
  }

  if (event.type === "trade.activated" || event.type === "trade.updated" || event.type === "trade.closed") {
    applyTradeUpdate(options.queryClient, event.payload.trade);
    if (event.type === "trade.closed") pushTradeClosedNotification(event.payload.trade);
    return;
  }

  if (event.type === "take_profit.hit") {
    pushTakeProfitNotification(event.payload.pair, event.payload.price, event.payload.target, event.payload.tradeId);
    return;
  }

  if (event.type === "stop_loss.hit") {
    pushStopLossNotification(event.payload.pair, event.payload.price, event.payload.tradeId);
    return;
  }

  if (event.type === "exchange.disconnected") {
    pushExchangeDisconnectedNotification(event.payload.exchange, event.payload.reason);
    return;
  }

  if (event.type === "price.touched_entry") {
    usePriceStore.getState().queuePrice(event.payload.pair, event.payload.price);
    return;
  }

  if (event.type === "radar.status") {
    options.queryClient.setQueryData<RadarStatus>(serverStateKeys.radar.status(), event.payload.status);
    if (event.payload.status.last_symbol && typeof event.payload.status.last_price === "number") {
      usePriceStore.getState().queuePrice(event.payload.status.last_symbol, event.payload.status.last_price);
    }
    return;
  }

  if (event.type === "notification.created") {
    pushPersistedNotification(event.payload);
    void options.queryClient.invalidateQueries({ queryKey: serverStateKeys.notifications.all() });
    return;
  }

  if (event.type === "connection.heartbeat") {
    options.onHeartbeat?.();
  }
}

function applySignalSnapshot(queryClient: QueryClient, signals: RadarSignal[]) {
  const openSignals = signals.filter(isOpenFeedSignal);
  useSignalStore.getState().replaceSignals(openSignals);
  queryClient.setQueryData(queryKeys.signals, openSignals);
  queryClient.setQueryData(serverStateKeys.signals.history(), signals);
  queryClient.setQueryData<RadarResponse>(queryKeys.radar, { signals: openSignals });
}

function applySignalCreated(queryClient: QueryClient, signal: RadarSignal) {
  if (isOpenFeedSignal(signal)) {
    useSignalStore.getState().addSignal(signal);
  } else {
    useSignalStore.getState().removeSignal(signal.id);
  }

  queryClient.setQueryData<RadarSignal[]>(queryKeys.signals, (current = []) => {
    return isOpenFeedSignal(signal) ? insertSignalToTop(current, signal) : current.filter((item) => item.id !== signal.id);
  });
  queryClient.setQueryData<RadarSignal[]>(serverStateKeys.signals.history(), (current = []) => insertSignalToTop(current, signal));
  queryClient.setQueryData<RadarResponse>(queryKeys.radar, (current) => ({
    signals: isOpenFeedSignal(signal)
      ? insertSignalToTop(current?.signals ?? [], signal)
      : (current?.signals ?? []).filter((item) => item.id !== signal.id)
  }));
}

function applySignalPatch(queryClient: QueryClient, signalId: string, patch: SignalPatch) {
  useSignalStore.getState().updateSignal(signalId, patch);
  patchSignalInCache(queryClient, signalId, patch);
}

function applySignalTerminalStatus(queryClient: QueryClient, signalId: string, status: "expired" | "invalidated") {
  applySignalStatus(queryClient, signalId, status);
}

function applySignalEntryTouched(queryClient: QueryClient, signalId: string, price: number) {
  applySignalStatus(queryClient, signalId, "entry_touched");
  const signal = useSignalStore.getState().signalsById[signalId];
  if (signal) usePriceStore.getState().queuePrice(signal.symbol, price);
  useNotificationStore.getState().push({
    kind: "signal",
    message: signal ? `${signal.symbol} touched the entry zone at ${price}` : `Signal ${signalId} touched the entry zone`,
    signalId,
    title: "Entry zone touched"
  });
}

function pushNewSignalNotification(signal: RadarSignal) {
  useNotificationStore.getState().push({
    kind: "signal",
    message: `${signal.symbol} ${signal.direction.toUpperCase()} · score ${Math.round(signal.score)}`,
    signalId: signal.id,
    title: "New signal"
  });
}

function pushTakeProfitNotification(pair: string, price: number, target = "TP1", tradeId?: string | null) {
  useNotificationStore.getState().push({
    id: tradeId ? `tp_${tradeId}_${target}` : undefined,
    kind: "trade",
    message: `${pair} reached ${target} at ${price}`,
    title: `${target} hit`
  });
}

function pushStopLossNotification(pair: string, price: number, tradeId?: string | null) {
  useNotificationStore.getState().push({
    id: tradeId ? `sl_${tradeId}` : undefined,
    kind: "trade",
    message: `${pair} hit stop loss at ${price}`,
    title: "SL hit"
  });
}

function pushPersistedNotification(payload: NotificationRealtimePayload) {
  const notification = payload.notification;
  useNotificationStore.getState().upsertMany([{
    createdAt: Date.parse(notification.created_at || payload.createdAt) || Date.now(),
    id: notification.id,
    kind: payload.kind,
    message: notification.body ?? payload.body ?? "",
    read: notification.is_read ?? payload.isRead,
    signalId: typeof notification.payload.signal_id === "string" ? notification.payload.signal_id : undefined,
    title: notification.title,
    type: notification.type
  }]);
}

function pushTradeClosedNotification(trade: TradeJournalEntry) {
  const pnl = typeof trade.pnl === "number" ? ` · PnL ${trade.pnl.toFixed(2)}` : "";
  useNotificationStore.getState().push({
    id: `trade_closed_${trade.id}`,
    kind: "trade",
    message: `${trade.symbol} ${trade.side.toUpperCase()} closed${pnl}`,
    title: "Trade closed"
  });
}

function pushExchangeDisconnectedNotification(exchange: string, reason?: string | null) {
  useNotificationStore.getState().push({
    id: `exchange_disconnected_${exchange}`,
    kind: "connection",
    message: reason ? `${exchange} disconnected: ${reason}` : `${exchange} disconnected`,
    title: "Exchange disconnected"
  });
}

function applySignalStatus(queryClient: QueryClient, signalId: string, status: SignalStatus) {
  useSignalStore.getState().updateSignalStatus(signalId, status);
  patchSignalInCache(queryClient, signalId, { status, updated_at: new Date().toISOString() });
}

function patchSignalInCache(queryClient: QueryClient, signalId: string, patch: SignalPatch) {
  const patchOpenById = (current: RadarSignal[] = []) => patchBySignalId(current, signalId, patch).filter(isOpenFeedSignal);
  const patchHistoryById = (current: RadarSignal[] = []) => patchBySignalId(current, signalId, patch);
  queryClient.setQueryData<RadarSignal[]>(queryKeys.signals, patchOpenById);
  queryClient.setQueryData<RadarSignal[]>(serverStateKeys.signals.history(), patchHistoryById);
  queryClient.setQueryData<RadarResponse>(queryKeys.radar, (current) => ({
    signals: patchBySignalId(current?.signals ?? [], signalId, patch).filter(isOpenFeedSignal)
  }));
}

function applyTradeUpdate(queryClient: QueryClient, trade: TradeJournalEntry) {
  queryClient.setQueryData<TradeJournalResponse>(queryKeys.trades, (current) => ({
    trades: upsertById(current?.trades ?? [], trade),
    account: current?.account ?? null
  }));
  void queryClient.invalidateQueries({ queryKey: serverStateKeys.journal.all() });
  void queryClient.invalidateQueries({ queryKey: serverStateKeys.trades.all() });
}

function isSignalEvent(message: RealtimeMessage): message is Extract<RealtimeMessage, { signal: RadarSignal }> {
  return message.type === "signal.created" || message.type === "signal.updated" || message.type === "signals.created" || message.type === "signals.updated";
}

function patchBySignalId(items: RadarSignal[], signalId: string, patch: SignalPatch): RadarSignal[] {
  return items.map((item) => (item.id === signalId ? { ...item, ...patch, id: item.id } : item));
}

function insertSignalToTop<T extends { id: string }>(items: T[], item: T): T[] {
  return [item, ...items.filter((current) => current.id !== item.id)];
}

function isStandardRealtimeEvent(message: RealtimeMessage): message is StandardRealtimeEvent {
  return "id" in message && "version" in message && "timestamp" in message && "payload" in message;
}

function upsertById<T extends { id: string }>(items: T[], item: T): T[] {
  return items.some((current) => current.id === item.id)
    ? items.map((current) => (current.id === item.id ? item : current))
    : [item, ...items];
}
