import type { RealtimeConnectionStatus, RealtimeMessage, RealtimeOutboundMessage } from "./event-types";
import { RealtimeMessageSchema } from "./event-schemas";
import { RealtimeHeartbeat } from "./heartbeat";
import { createReconnectPolicy, type ReconnectPolicy } from "./reconnect-policy";
import { createSubscribeMessage, defaultRealtimeSubscription, type RealtimeSubscription } from "./subscriptions";

export interface RealtimeSocketClientOptions {
  webSocketUrl: string;
  readOnlyFallbackUrl?: string;
  authTokenProvider?: () => Promise<string | null>;
  getLastEventId?: () => string | null;
  onReconnect?: () => void | Promise<void>;
  tokenQueryParam?: string;
  heartbeatIntervalMs?: number;
  heartbeatTimeoutMs?: number;
  reconnectPolicy?: ReconnectPolicy;
  subscription?: RealtimeSubscription;
  onMessage: (message: RealtimeMessage) => void;
  onStatusChange: (status: RealtimeConnectionStatus) => void;
}

export class RealtimeSocketClient {
  private readonly heartbeat: RealtimeHeartbeat;
  private readonly reconnectPolicy: ReconnectPolicy;
  private reconnectAttempt = 0;
  private reconnectTimer: number | null = null;
  private heartbeatTimeoutTimer: number | null = null;
  private socket: WebSocket | null = null;
  private eventSource: EventSource | null = null;
  private subscription: RealtimeSubscription;
  private environmentListenersBound = false;
  private hasOpened = false;
  private connectGeneration = 0;
  private closed = false;

  constructor(private readonly options: RealtimeSocketClientOptions) {
    this.reconnectPolicy = options.reconnectPolicy ?? createReconnectPolicy();
    this.subscription = options.subscription ?? defaultRealtimeSubscription;
    this.heartbeat = new RealtimeHeartbeat({
      intervalMs: options.heartbeatIntervalMs,
      send: (message) => this.send(message)
    });
  }

  connect() {
    this.closed = false;
    this.bindEnvironmentListeners();
    void this.openWebSocket();
  }

  close() {
    this.closed = true;
    this.unbindEnvironmentListeners();
    this.clearReconnectTimer();
    this.clearHeartbeatTimeout();
    this.heartbeat.stop();
    this.socket?.close();
    this.eventSource?.close();
    this.socket = null;
    this.eventSource = null;
    this.options.onStatusChange("closed");
  }

  updateSubscription(subscription: RealtimeSubscription) {
    this.subscription = subscription;
    this.send(createSubscribeMessage(subscription, this.options.getLastEventId?.() ?? null));
  }

  send(message: RealtimeOutboundMessage) {
    if (this.socket?.readyState !== WebSocket.OPEN) return;
    this.socket.send(JSON.stringify(message));
  }

  private async openWebSocket() {
    if (this.closed) return;
    if (this.socket?.readyState === WebSocket.OPEN || this.socket?.readyState === WebSocket.CONNECTING) return;

    const generation = ++this.connectGeneration;
    const token = await this.resolveAuthToken();
    if (this.closed || generation !== this.connectGeneration) return;
    if (this.options.authTokenProvider && !token) {
      this.options.onStatusChange("unauthorized");
      this.openReadOnlyFallback();
      return;
    }

    this.options.onStatusChange(this.reconnectAttempt ? "reconnecting" : "connecting");
    const socket = new WebSocket(appendWebSocketToken(this.options.webSocketUrl, token, this.options.tokenQueryParam));
    this.socket = socket;

    socket.addEventListener("open", () => {
      if (socket !== this.socket) return;
      const shouldRefreshSnapshot = this.hasOpened;
      this.hasOpened = true;
      this.reconnectAttempt = 0;
      this.eventSource?.close();
      this.eventSource = null;
      this.options.onStatusChange("open");
      this.send(createSubscribeMessage(this.subscription, this.options.getLastEventId?.() ?? null));
      if (shouldRefreshSnapshot) void this.options.onReconnect?.();
      this.heartbeat.start();
      this.scheduleHeartbeatTimeout();
    });

    socket.addEventListener("message", (event) => {
      if (socket !== this.socket) return;
      this.scheduleHeartbeatTimeout();
      const message = parseRealtimeMessage(event.data);
      if (message) this.options.onMessage(message);
    });

    socket.addEventListener("error", () => {
      if (socket !== this.socket) return;
      if (!this.closed) this.options.onStatusChange("error");
    });

    socket.addEventListener("close", (event) => {
      if (socket !== this.socket) return;
      this.socket = null;
      this.heartbeat.stop();
      this.clearHeartbeatTimeout();
      if (this.closed) return;
      if (isAuthCloseCode(event.code)) {
        this.options.onStatusChange("unauthorized");
        this.openReadOnlyFallback();
        return;
      }
      this.scheduleReconnect();
      this.openReadOnlyFallback();
    });
  }

  private async resolveAuthToken(): Promise<string | null> {
    if (!this.options.authTokenProvider) return null;
    this.options.onStatusChange("authenticating");

    try {
      return await this.options.authTokenProvider();
    } catch {
      this.options.onStatusChange("error");
      return null;
    }
  }

  private scheduleReconnect() {
    this.clearReconnectTimer();
    this.reconnectAttempt += 1;
    this.options.onStatusChange("reconnecting");
    this.reconnectTimer = window.setTimeout(() => void this.openWebSocket(), this.reconnectPolicy.nextDelay(this.reconnectAttempt));
  }

  private scheduleHeartbeatTimeout() {
    this.clearHeartbeatTimeout();
    const timeoutMs = this.options.heartbeatTimeoutMs ?? 45_000;
    this.heartbeatTimeoutTimer = window.setTimeout(() => {
      if (this.socket?.readyState !== WebSocket.OPEN || this.closed) return;
      this.options.onStatusChange("delayed");
      this.socket.close(4000, "heartbeat-timeout");
    }, timeoutMs);
  }

  private openReadOnlyFallback() {
    if (!this.options.readOnlyFallbackUrl || this.eventSource || this.closed) return;
    if (this.socket?.readyState === WebSocket.OPEN || this.socket?.readyState === WebSocket.CONNECTING) return;

    this.eventSource = new EventSource(this.options.readOnlyFallbackUrl);
    this.eventSource.addEventListener("open", () => {
      this.options.onStatusChange("fallback");
    });
    this.eventSource.addEventListener("message", (event) => {
      const message = parseRealtimeMessage(event.data);
      if (message) this.options.onMessage(message);
    });
    this.eventSource.addEventListener("error", () => {
      if (this.socket?.readyState === WebSocket.OPEN) return;
      if (!this.closed) this.options.onStatusChange("error");
    });
  }

  private clearReconnectTimer() {
    if (this.reconnectTimer === null) return;
    window.clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
  }

  private clearHeartbeatTimeout() {
    if (this.heartbeatTimeoutTimer === null) return;
    window.clearTimeout(this.heartbeatTimeoutTimer);
    this.heartbeatTimeoutTimer = null;
  }

  private bindEnvironmentListeners() {
    if (this.environmentListenersBound) return;
    this.environmentListenersBound = true;
    window.addEventListener("online", this.handleOnline);
    window.addEventListener("offline", this.handleOffline);
    document.addEventListener("visibilitychange", this.handleVisibilityChange);
  }

  private unbindEnvironmentListeners() {
    if (!this.environmentListenersBound) return;
    this.environmentListenersBound = false;
    window.removeEventListener("online", this.handleOnline);
    window.removeEventListener("offline", this.handleOffline);
    document.removeEventListener("visibilitychange", this.handleVisibilityChange);
  }

  private readonly handleOnline = () => {
    if (this.closed) return;
    if (this.socket?.readyState === WebSocket.OPEN) return;
    this.clearReconnectTimer();
    void this.openWebSocket();
  };

  private readonly handleOffline = () => {
    if (this.closed) return;
    this.options.onStatusChange("offline");
  };

  private readonly handleVisibilityChange = () => {
    if (this.closed || document.visibilityState !== "visible") return;
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.send({ type: "ping", timestamp: Date.now() });
      this.scheduleHeartbeatTimeout();
      return;
    }
    this.clearReconnectTimer();
    void this.openWebSocket();
  };
}

export function appendWebSocketToken(webSocketUrl: string, token: string | null, queryParam = "token"): string {
  if (!token) return webSocketUrl;

  const url = new URL(webSocketUrl, getLocationHref());
  url.searchParams.set(queryParam, token);
  return url.toString();
}

function getLocationHref(): string {
  return globalThis.location?.href ?? "http://127.0.0.1:3000";
}

function isAuthCloseCode(code: number): boolean {
  return code === 4401 || code === 4403;
}

export function parseRealtimeMessage(rawData: unknown): RealtimeMessage | null {
  if (typeof rawData !== "string") return null;

  try {
    const parsed = RealtimeMessageSchema.safeParse(JSON.parse(rawData));
    if (!parsed.success) {
      console.warn("[realtime] dropped invalid event", parsed.error.issues);
      return null;
    }
    return parsed.data as RealtimeMessage;
  } catch {
    return null;
  }
}
