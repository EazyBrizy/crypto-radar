import type { RealtimeOutboundMessage } from "./event-types";

export class RealtimeHeartbeat {
  private heartbeatTimer: number | null = null;

  constructor(
    private readonly options: {
      intervalMs?: number;
      send: (message: RealtimeOutboundMessage) => void;
    }
  ) {}

  start() {
    this.stop();
    this.heartbeatTimer = window.setInterval(() => {
      this.options.send({ type: "ping", timestamp: Date.now() });
    }, this.options.intervalMs ?? 15_000);
  }

  stop() {
    if (this.heartbeatTimer === null) return;
    window.clearInterval(this.heartbeatTimer);
    this.heartbeatTimer = null;
  }
}
