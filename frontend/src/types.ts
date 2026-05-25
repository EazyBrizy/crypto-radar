export type SignalDirection = "long" | "short";
export type SignalStatus = "active" | "watchlist" | "confirmed" | "rejected" | "expired" | "invalidated";
export type TradeMode = "virtual" | "real";
export type TradeStatus = "open" | "closed" | "cancelled";

export interface RadarSignal {
  id: string;
  symbol: string;
  exchange: string;
  strategy: string;
  direction: SignalDirection;
  confidence: number;
  risk_reward: number | null;
  urgency: "low" | "medium" | "high";
  status: SignalStatus;
  score: number;
  timeframe: string;
  entry_min: number | null;
  entry_max: number | null;
  stop_loss: number | null;
  take_profit_1: number | null;
  take_profit_2: number | null;
  explanation: string[];
  risks: string[];
  created_at: string;
  updated_at: string;
  confirmed_trade_id?: string | null;
}

export interface RadarResponse {
  signals: RadarSignal[];
}

export interface TradeJournalEntry {
  id: string;
  user_id: string;
  signal_id: string | null;
  mode: TradeMode;
  exchange: string;
  symbol: string;
  strategy: string;
  timeframe: string;
  side: SignalDirection;
  entry_price: number;
  current_price: number;
  exit_price: number | null;
  size_usd: number;
  quantity: number;
  leverage: number;
  risk_percent: number;
  stop_loss: number;
  take_profit: number[];
  fees: number;
  status: TradeStatus;
  result: "win" | "loss" | "breakeven" | null;
  pnl: number | null;
  pnl_percent: number | null;
  mfe: number;
  mae: number;
  screenshots: string[];
  ai_review: string | null;
  opened_at: string;
  updated_at: string;
  closed_at: string | null;
}

export interface TradeJournalResponse {
  trades: TradeJournalEntry[];
}

export interface RadarConfig {
  exchanges: string[];
  symbols: string[];
  use_all_symbols: boolean;
  timeframes: string[];
}

export interface HealthStatus {
  status: string;
  scanner_enabled: boolean;
  scanner_running: boolean;
  processed_signals: number;
}
