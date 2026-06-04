import type { TradeStatus } from "@/types";

export const ACTIVE_TRADE_STATUSES = [
  "open",
  "partially_closed"
] as const satisfies readonly TradeStatus[];

export const TERMINAL_TRADE_STATUSES = [
  "closed",
  "stopped",
  "invalidated",
  "expired",
  "cancelled"
] as const satisfies readonly TradeStatus[];

export const TRADE_STATUSES = [
  ...ACTIVE_TRADE_STATUSES,
  ...TERMINAL_TRADE_STATUSES
] as const satisfies readonly TradeStatus[];

const ACTIVE_TRADE_STATUS_SET = new Set<TradeStatus>(ACTIVE_TRADE_STATUSES);
const TERMINAL_TRADE_STATUS_SET = new Set<TradeStatus>(TERMINAL_TRADE_STATUSES);

export function isActiveTradeStatus(status: TradeStatus): boolean {
  return ACTIVE_TRADE_STATUS_SET.has(status);
}

export function isTerminalTradeStatus(status: TradeStatus): boolean {
  return TERMINAL_TRADE_STATUS_SET.has(status);
}
