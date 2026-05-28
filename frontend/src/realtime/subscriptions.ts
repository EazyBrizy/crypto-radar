import type { RealtimeChannel, RealtimeOutboundMessage } from "./event-types";

export interface RealtimeSubscription {
  channels: RealtimeChannel[];
  symbols?: string[];
}

export const defaultRealtimeSubscription: RealtimeSubscription = {
  channels: ["signals", "trades", "orders", "positions", "health"]
};

export function createSubscribeMessage(subscription: RealtimeSubscription, lastEventId?: string | null): RealtimeOutboundMessage {
  return {
    type: "subscribe",
    channels: subscription.channels,
    symbols: subscription.symbols,
    lastEventId
  };
}
