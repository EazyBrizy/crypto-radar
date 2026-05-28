import { z } from "zod";

import { RadarSignalSchema, RadarStatusSchema, SignalSideSchema, TradeJournalEntrySchema } from "@/validation/common-schemas";

const EventEnvelopeBaseSchema = z.object({
  id: z.string().min(1),
  version: z.number().int().min(1),
  timestamp: z.string().min(1)
});

const EntryZoneSchema = z.object({
  from: z.number().nullable(),
  to: z.number().nullable()
});

const SignalPayloadSchema = z.object({
  signal: RadarSignalSchema,
  signalId: z.string().min(1),
  pair: z.string().min(1),
  exchange: z.string().min(1),
  side: SignalSideSchema,
  strategy: z.string().min(1),
  confidence: z.number(),
  risk: z.string().min(1),
  entryZone: EntryZoneSchema,
  stopLoss: z.number().nullable(),
  takeProfit: z.array(z.number()),
  timeframe: z.string().min(1),
  reason: z.string().nullable().optional()
});

const SignalPatchSchema = RadarSignalSchema.partial().extend({
  id: z.string().optional()
});

const SignalUpdatedPayloadSchema = z.object({
  patch: SignalPatchSchema.optional(),
  signal: RadarSignalSchema.optional(),
  signalId: z.string().min(1)
}).refine((payload) => payload.signal || payload.patch, {
  message: "signal.updated requires either signal or patch"
});

const SignalInvalidatedPayloadSchema = z.object({
  reason: z.string().nullable().optional(),
  signal: RadarSignalSchema.optional(),
  signalId: z.string().min(1)
});

const SignalEntryTouchedPayloadSchema = z.object({
  pair: z.string().optional(),
  price: z.number(),
  signal: RadarSignalSchema.optional(),
  signalId: z.string().min(1)
});

const TradeTargetHitPayloadSchema = z.object({
  pair: z.string().min(1),
  price: z.number(),
  signalId: z.string().nullable().optional(),
  target: z.enum(["TP1", "TP2", "TP3"]).optional(),
  tradeId: z.string().nullable().optional()
});

const ExchangeDisconnectedPayloadSchema = z.object({
  exchange: z.string().min(1),
  reason: z.string().nullable().optional()
});

const NotificationKindSchema = z.enum(["signal", "trade", "order", "connection", "alert", "system"]);

const PersistedNotificationSchema = z.object({
  id: z.string().min(1),
  user_id: z.string().min(1),
  type: z.string().min(1),
  title: z.string().min(1),
  body: z.string().nullable(),
  payload: z.record(z.string(), z.unknown()).default({}),
  is_read: z.boolean(),
  created_at: z.string().min(1)
}).passthrough();

const NotificationPayloadSchema = z.object({
  notification: PersistedNotificationSchema,
  notificationId: z.string().min(1),
  userId: z.string().min(1),
  kind: NotificationKindSchema,
  title: z.string().min(1),
  body: z.string().nullable().optional(),
  payload: z.record(z.string(), z.unknown()).default({}),
  isRead: z.boolean(),
  createdAt: z.string().min(1)
});

const TradePayloadSchema = z.object({
  trade: TradeJournalEntrySchema,
  tradeId: z.string().min(1),
  signalId: z.string().nullable(),
  pair: z.string().min(1),
  exchange: z.string().min(1),
  side: SignalSideSchema,
  status: z.string().min(1),
  entryPrice: z.number().optional(),
  currentPrice: z.number().optional(),
  exitPrice: z.number().nullable().optional(),
  stopLoss: z.number().optional(),
  takeProfit: z.array(z.number()).optional(),
  riskAmount: z.number().optional(),
  riskReward: z.number().optional(),
  pnl: z.number().nullable().optional(),
  pnlPercent: z.number().nullable().optional(),
  closeReason: z.string().nullable().optional()
});

export const StandardRealtimeEventSchema = z.discriminatedUnion("type", [
  EventEnvelopeBaseSchema.extend({
    type: z.literal("signal.created"),
    payload: SignalPayloadSchema
  }),
  EventEnvelopeBaseSchema.extend({
    type: z.literal("signal.updated"),
    payload: SignalUpdatedPayloadSchema
  }),
  EventEnvelopeBaseSchema.extend({
    type: z.literal("signal.invalidated"),
    payload: SignalInvalidatedPayloadSchema
  }),
  EventEnvelopeBaseSchema.extend({
    type: z.literal("signal.entry_touched"),
    payload: SignalEntryTouchedPayloadSchema
  }),
  EventEnvelopeBaseSchema.extend({
    type: z.literal("take_profit.hit"),
    payload: TradeTargetHitPayloadSchema
  }),
  EventEnvelopeBaseSchema.extend({
    type: z.literal("stop_loss.hit"),
    payload: TradeTargetHitPayloadSchema
  }),
  EventEnvelopeBaseSchema.extend({
    type: z.literal("trade.activated"),
    payload: TradePayloadSchema
  }),
  EventEnvelopeBaseSchema.extend({
    type: z.literal("trade.updated"),
    payload: TradePayloadSchema
  }),
  EventEnvelopeBaseSchema.extend({
    type: z.literal("trade.closed"),
    payload: TradePayloadSchema
  }),
  EventEnvelopeBaseSchema.extend({
    type: z.literal("exchange.disconnected"),
    payload: ExchangeDisconnectedPayloadSchema
  }),
  EventEnvelopeBaseSchema.extend({
    type: z.literal("price.touched_entry"),
    payload: SignalPayloadSchema.extend({ price: z.number() })
  }),
  EventEnvelopeBaseSchema.extend({
    type: z.literal("order.status_changed"),
    payload: z.object({
      orderId: z.string().min(1),
      status: z.string().min(1),
      details: z.record(z.string(), z.unknown()).default({})
    })
  }),
  EventEnvelopeBaseSchema.extend({
    type: z.literal("notification.created"),
    payload: NotificationPayloadSchema
  }),
  EventEnvelopeBaseSchema.extend({
    type: z.literal("connection.heartbeat"),
    payload: z.object({ status: z.string().min(1) })
  }),
  EventEnvelopeBaseSchema.extend({
    type: z.literal("subscription.updated"),
    payload: z.object({
      status: z.string().min(1),
      channels: z.array(z.string()).default([])
    })
  }),
  EventEnvelopeBaseSchema.extend({
    type: z.literal("radar.status"),
    payload: z.object({ status: RadarStatusSchema })
  })
]);

export const LegacyRealtimeMessageSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("snapshot"), signals: z.array(RadarSignalSchema) }),
  z.object({ type: z.literal("signal.created"), signal: RadarSignalSchema }),
  z.object({ type: z.literal("signal.updated"), signal: RadarSignalSchema }),
  z.object({ type: z.literal("signals.created"), signal: RadarSignalSchema }),
  z.object({ type: z.literal("signals.updated"), signal: RadarSignalSchema }),
  z.object({ type: z.literal("signal.invalidated"), signalId: z.string().min(1) }),
  z.object({ type: z.literal("signal.entry_touched"), price: z.number(), signalId: z.string().min(1) }),
  z.object({ type: z.literal("take_profit.hit"), pair: z.string().min(1), price: z.number(), target: z.enum(["TP1", "TP2", "TP3"]).optional(), tradeId: z.string().nullable().optional() }),
  z.object({ type: z.literal("stop_loss.hit"), pair: z.string().min(1), price: z.number(), tradeId: z.string().nullable().optional() }),
  z.object({ type: z.literal("exchange.disconnected"), exchange: z.string().min(1), reason: z.string().nullable().optional() }),
  z.object({ type: z.literal("radar.status"), status: RadarStatusSchema }),
  z.object({ type: z.literal("status"), status: RadarStatusSchema }),
  z.object({ type: z.literal("health"), health: z.unknown() }),
  z.object({ type: z.literal("trade.created"), trade: TradeJournalEntrySchema }),
  z.object({ type: z.literal("trade.updated"), trade: TradeJournalEntrySchema }),
  z.object({ type: z.literal("connection.health"), status: z.string() }),
  z.object({ type: z.literal("subscription.updated"), status: z.string() })
]);

export const RealtimeMessageSchema = z.union([
  StandardRealtimeEventSchema,
  LegacyRealtimeMessageSchema
]);
