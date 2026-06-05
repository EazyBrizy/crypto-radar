import type { HealthStatus, PendingEntryIntent, PendingEntryIntentStatus, RadarSignal, RadarStatus, TradeInvalidationAlert, TradeJournalEntry, TradeMode } from "@/types";

export type RealtimeConnectionStatus =
  | "idle"
  | "authenticating"
  | "connecting"
  | "reconnecting"
  | "open"
  | "fallback"
  | "closed"
  | "delayed"
  | "offline"
  | "unauthorized"
  | "error";

export type RealtimeEventType =
  | "signal.created"
  | "signal.updated"
  | "signal.invalidated"
  | "signal.expired"
  | "signal.entry_touched"
  | "take_profit.hit"
  | "stop_loss.hit"
  | "trade.activated"
  | "trade.updated"
  | "trade.closed"
  | "trade.invalidation"
  | "exchange.disconnected"
  | "price.touched_entry"
  | "order.status_changed"
  | "pending_entry.updated"
  | "notification.created"
  | "connection.heartbeat"
  | "subscription.updated"
  | "radar.status";

export interface RealtimeEventEnvelope<TType extends RealtimeEventType = RealtimeEventType, TPayload = unknown> {
  id: string;
  type: TType;
  version: number;
  timestamp: string;
  payload: TPayload;
}

export interface SignalRealtimePayload {
  signal: RadarSignal;
  signalId: string;
  pair: string;
  exchange: string;
  side: string;
  strategy: string;
  confidence: number;
  risk: string;
  entryZone: {
    from: number | null;
    to: number | null;
  };
  stopLoss: number | null;
  takeProfit: number[];
  timeframe: string;
  reason?: string | null;
}

export interface SignalUpdatedPayload {
  patch?: Partial<RadarSignal>;
  signal?: RadarSignal;
  signalId: string;
}

export interface SignalInvalidatedPayload {
  reason?: string | null;
  signal?: RadarSignal;
  signalId: string;
}

export type SignalExpiredPayload = SignalInvalidatedPayload;

export interface TradeRealtimePayload {
  trade: TradeJournalEntry;
  tradeId: string;
  signalId: string | null;
  pair: string;
  exchange: string;
  side: string;
  status: string;
  entryPrice?: number;
  currentPrice?: number;
  exitPrice?: number | null;
  stopLoss?: number;
  takeProfit?: number[];
  riskAmount?: number;
  riskReward?: number;
  pnl?: number | null;
  pnlPercent?: number | null;
  closeReason?: string | null;
}

export interface TradeInvalidationRealtimePayload {
  alert: TradeInvalidationAlert;
  tradeId: string;
  signalId: string | null;
  pair: string;
  exchange: string;
  side: string;
  reason?: string | null;
  triggeredConditions: string[];
  fingerprint?: string | null;
}

export interface ConnectionHeartbeatPayload {
  status: string;
}

export interface SubscriptionUpdatedPayload {
  status: string;
  channels: string[];
}

export interface PriceTouchedEntryPayload extends SignalRealtimePayload {
  price: number;
}

export interface SignalEntryTouchedPayload {
  pair?: string;
  price: number;
  signal?: RadarSignal;
  signalId: string;
}

export interface TradeTargetHitPayload {
  pair: string;
  price: number;
  signalId?: string | null;
  target?: "TP1" | "TP2" | "TP3";
  tradeId?: string | null;
}

export interface ExchangeDisconnectedPayload {
  exchange: string;
  reason?: string | null;
}

export interface OrderStatusChangedPayload {
  orderId: string;
  status: string;
  details: Record<string, unknown>;
}

export interface PendingEntryUpdatedPayload {
  pending_entry?: PendingEntryIntent;
  user_id: string;
  signal_id: string;
  pending_entry_id: string;
  status: PendingEntryIntentStatus;
  mode: TradeMode;
  reason?: string | null;
  message?: string | null;
  updated_at: string;
}

export interface NotificationRealtimePayload {
  notification: {
    id: string;
    user_id: string;
    type: string;
    title: string;
    body: string | null;
    payload: Record<string, unknown>;
    is_read: boolean;
    created_at: string;
  };
  notificationId: string;
  userId: string;
  kind: "signal" | "trade" | "order" | "connection" | "alert" | "system";
  title: string;
  body?: string | null;
  payload: Record<string, unknown>;
  isRead: boolean;
  createdAt: string;
}

export type StandardRealtimeEvent =
  | RealtimeEventEnvelope<"signal.created", SignalRealtimePayload>
  | RealtimeEventEnvelope<"signal.updated", SignalUpdatedPayload>
  | RealtimeEventEnvelope<"signal.invalidated", SignalInvalidatedPayload>
  | RealtimeEventEnvelope<"signal.expired", SignalExpiredPayload>
  | RealtimeEventEnvelope<"signal.entry_touched", SignalEntryTouchedPayload>
  | RealtimeEventEnvelope<"take_profit.hit", TradeTargetHitPayload>
  | RealtimeEventEnvelope<"stop_loss.hit", TradeTargetHitPayload>
  | RealtimeEventEnvelope<"trade.activated" | "trade.updated" | "trade.closed", TradeRealtimePayload>
  | RealtimeEventEnvelope<"trade.invalidation", TradeInvalidationRealtimePayload>
  | RealtimeEventEnvelope<"exchange.disconnected", ExchangeDisconnectedPayload>
  | RealtimeEventEnvelope<"price.touched_entry", PriceTouchedEntryPayload>
  | RealtimeEventEnvelope<"order.status_changed", OrderStatusChangedPayload>
  | RealtimeEventEnvelope<"pending_entry.updated", PendingEntryUpdatedPayload>
  | RealtimeEventEnvelope<"notification.created", NotificationRealtimePayload>
  | RealtimeEventEnvelope<"connection.heartbeat", ConnectionHeartbeatPayload>
  | RealtimeEventEnvelope<"subscription.updated", SubscriptionUpdatedPayload>
  | RealtimeEventEnvelope<"radar.status", { status: RadarStatus }>;

export type LegacyRealtimeMessage =
  | { type: "snapshot"; signals: RadarSignal[] }
  | { type: "signal.created" | "signal.updated" | "signals.created" | "signals.updated"; signal: RadarSignal }
  | { type: "signal.invalidated"; signalId: string }
  | { type: "signal.expired"; signalId: string }
  | { type: "signal.entry_touched"; price: number; signalId: string }
  | { type: "take_profit.hit"; pair: string; price: number; target?: "TP1" | "TP2" | "TP3"; tradeId?: string | null }
  | { type: "stop_loss.hit"; pair: string; price: number; tradeId?: string | null }
  | { type: "exchange.disconnected"; exchange: string; reason?: string | null }
  | { type: "radar.status" | "status"; status: RadarStatus }
  | { type: "health"; health: HealthStatus }
  | { type: "trade.created" | "trade.updated"; trade: TradeJournalEntry }
  | { type: "connection.health"; status: string }
  | { type: "subscription.updated"; status: string };

export type RealtimeMessage = StandardRealtimeEvent | LegacyRealtimeMessage;

export type RealtimeOutboundMessage =
  | { type: "ping"; timestamp: number }
  | { type: "subscribe"; channels: RealtimeChannel[]; symbols?: string[]; lastEventId?: string | null };

export type RealtimeChannel = "signals" | "trades" | "orders" | "positions" | "health" | "market";
