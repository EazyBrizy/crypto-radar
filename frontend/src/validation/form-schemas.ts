import { z } from "zod";

export const ScannerSettingsFormSchema = z.object({
  exchanges: z.array(z.string().trim().min(1)).min(1),
  riskPercent: z.coerce.number().min(0.1).max(10),
  symbols: z.array(z.string().trim().min(1)),
  useAllSymbols: z.boolean()
});

export const ManualTradeFormSchema = z.object({
  accountBalance: z.coerce.number().positive(),
  leverage: z.coerce.number().int().min(1).max(100),
  maxOpenPositions: z.coerce.number().int().min(1).max(100),
  riskPercent: z.coerce.number().min(0.1).max(10)
});
