import { z } from "zod";

import { SignalDirectionSchema, SignalStatusSchema, TimeframeSchema, TradeModeSchema, TradeStatusSchema } from "./common-schemas";

export const RadarFilterSchema = z.object({
  direction: z.union([SignalDirectionSchema, z.literal("all")]).default("all"),
  minScore: z.coerce.number().min(0).max(100).default(0),
  symbol: z.string().trim().optional()
});

export const SignalHistoryFilterSchema = z.object({
  status: SignalStatusSchema.optional(),
  symbol: z.string().trim().optional()
});

export const TradeJournalFilterSchema = z.object({
  mode: TradeModeSchema.optional(),
  signalId: z.string().trim().optional(),
  status: TradeStatusSchema.optional()
});

export const CandleFilterSchema = z.object({
  exchange: z.string().trim().optional(),
  includeOpen: z.coerce.boolean().default(true),
  limit: z.coerce.number().int().min(1).max(500).default(250),
  symbol: z.string().trim().min(1),
  timeframe: TimeframeSchema
});
