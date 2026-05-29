import type { SignalStatus, Timeframe, TradeMode, TradeStatus } from "@/types";
import { CandleFilterSchema, SignalHistoryFilterSchema, TradeJournalFilterSchema } from "@/validation/filter-schemas";

export type TradeJournalFilters = {
  mode?: TradeMode;
  signalId?: string;
  status?: TradeStatus;
};

export type SignalHistoryFilters = {
  status?: SignalStatus;
  symbol?: string;
};

export type CandleFilters = {
  exchange?: string;
  includeOpen?: boolean;
  limit?: number;
  symbol: string;
  timeframe: Timeframe;
};

const normalizeTradeFilters = (filters: TradeJournalFilters = {}) => ({
  ...(() => {
    const parsed = TradeJournalFilterSchema.parse(filters);
    return {
      mode: parsed.mode ?? "all",
      signalId: parsed.signalId ?? "all",
      status: parsed.status ?? "all"
    };
  })()
});

const normalizeSignalFilters = (filters: SignalHistoryFilters = {}) => ({
  ...(() => {
    const parsed = SignalHistoryFilterSchema.parse(filters);
    return {
      status: parsed.status ?? "all",
      symbol: parsed.symbol ?? "all"
    };
  })()
});

const normalizeCandleFilters = (filters: CandleFilters) => {
  const parsed = CandleFilterSchema.parse(filters);
  return {
    exchange: parsed.exchange ?? "all",
    includeOpen: parsed.includeOpen,
    limit: parsed.limit,
    symbol: parsed.symbol,
    timeframe: parsed.timeframe
  };
};

export const serverStateKeys = {
  all: ["fastapi"] as const,
  health: () => [...serverStateKeys.all, "health"] as const,
  radar: {
    all: () => [...serverStateKeys.all, "radar"] as const,
    dashboard: () => [...serverStateKeys.radar.all(), "dashboard"] as const,
    status: () => [...serverStateKeys.radar.all(), "status"] as const
  },
  user: {
    all: () => [...serverStateKeys.all, "user"] as const,
    profile: (userId = "me") => [...serverStateKeys.user.all(), "profile", userId] as const
  },
  auth: {
    all: () => [...serverStateKeys.all, "auth"] as const,
    devices: () => [...serverStateKeys.auth.all(), "devices"] as const,
    exchangeKeySecurity: () => [...serverStateKeys.auth.all(), "exchange-key-security"] as const,
    session: () => [...serverStateKeys.auth.all(), "session"] as const,
    webSocketToken: () => [...serverStateKeys.auth.all(), "ws-token"] as const
  },
  settings: {
    all: () => [...serverStateKeys.all, "settings"] as const,
    radar: () => [...serverStateKeys.settings.all(), "radar"] as const
  },
  risk: {
    all: () => [...serverStateKeys.all, "risk"] as const,
    state: (userId = "me") => [...serverStateKeys.risk.all(), "state", userId] as const
  },
  watchlist: {
    all: () => [...serverStateKeys.all, "watchlist"] as const,
    current: () => [...serverStateKeys.watchlist.all(), "current"] as const,
    pairs: () => [...serverStateKeys.watchlist.all(), "pairs"] as const
  },
  alerts: {
    all: () => [...serverStateKeys.all, "alerts"] as const,
    rules: () => [...serverStateKeys.alerts.all(), "rules"] as const
  },
  notifications: {
    all: () => [...serverStateKeys.all, "notifications"] as const,
    list: () => [...serverStateKeys.notifications.all(), "list"] as const
  },
  subscription: {
    all: () => [...serverStateKeys.all, "subscription"] as const,
    status: (userId = "me") => [...serverStateKeys.subscription.all(), "status", userId] as const
  },
  billing: {
    all: () => [...serverStateKeys.all, "billing"] as const,
    plans: () => [...serverStateKeys.billing.all(), "plans"] as const,
    subscription: (userId = "me") => [...serverStateKeys.billing.all(), "subscription", userId] as const
  },
  exchangeConnections: {
    all: () => [...serverStateKeys.all, "exchange-connections"] as const,
    list: () => [...serverStateKeys.exchangeConnections.all(), "list"] as const
  },
  signals: {
    all: () => [...serverStateKeys.all, "signals"] as const,
    history: (filters?: SignalHistoryFilters) => [...serverStateKeys.signals.all(), "history", normalizeSignalFilters(filters)] as const,
    active: () => [...serverStateKeys.signals.all(), "active"] as const,
    open: () => [...serverStateKeys.signals.all(), "open"] as const,
    executionPreview: (signalId: string) => [...serverStateKeys.signals.all(), "execution-preview", signalId] as const
  },
  journal: {
    all: () => [...serverStateKeys.all, "journal"] as const,
    history: (filters?: TradeJournalFilters) => [...serverStateKeys.journal.all(), "history", normalizeTradeFilters(filters)] as const
  },
  trades: {
    all: () => [...serverStateKeys.all, "trades"] as const,
    list: (filters?: TradeJournalFilters) => [...serverStateKeys.trades.all(), "list", normalizeTradeFilters(filters)] as const,
    closed: () => [...serverStateKeys.trades.all(), "closed"] as const
  },
  candles: {
    all: () => [...serverStateKeys.all, "candles"] as const,
    series: (filters: CandleFilters) => [...serverStateKeys.candles.all(), "series", normalizeCandleFilters(filters)] as const
  }
};

export const queryKeys = {
  health: serverStateKeys.health(),
  radar: serverStateKeys.radar.dashboard(),
  radarStatus: serverStateKeys.radar.status(),
  signals: serverStateKeys.signals.open(),
  trades: serverStateKeys.journal.history(),
  config: serverStateKeys.settings.radar()
};
