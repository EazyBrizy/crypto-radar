export type SubscriptionTier = "free" | "pro" | "team";
export type SubscriptionState = "active" | "trialing" | "past_due" | "canceled" | "none";
export type ExchangeConnectionState = "available" | "connected" | "disconnected" | "error";
export type VirtualSimulationLevel = "mvp" | "advanced" | "pro";
export type VirtualSimulationLevelStatus = "active" | "stub";

export interface VirtualTradingSettings {
  simulation_level: VirtualSimulationLevel;
  simulation_level_status: VirtualSimulationLevelStatus;
  effective_simulation_level: VirtualSimulationLevel;
}

export interface UserProfile {
  id: string;
  email: string;
  name: string | null;
  settings: {
    virtual_trading: VirtualTradingSettings;
    [key: string]: unknown;
  };
  created_at: string;
}

export interface UserSettings {
  locale: string;
  timezone: string;
  risk_percent: number;
  default_exchange: string;
  default_timeframes: string[];
}

export interface MarketPairOption {
  id: string;
  exchange: string;
  symbol: string;
  base_asset: string;
  quote_asset: string;
  status: string;
}

export interface WatchlistPair extends MarketPairOption {
  added_at: string;
}

export interface Watchlist {
  id: string;
  user_id: string;
  name: string;
  is_default: boolean;
  pairs: WatchlistPair[];
  symbols: string[];
  use_all_symbols: boolean;
  created_at: string;
  updated_at: string | null;
}

export interface AlertRule {
  id: string;
  user_id: string;
  pair: MarketPairOption | null;
  strategy_version_id: string | null;
  condition_type: string;
  condition_body: Record<string, unknown>;
  channels: string[];
  is_enabled: boolean;
  created_at: string;
}

export interface AlertRuleDraft {
  pair_id?: string | null;
  strategy_version_id?: string | null;
  condition_type: string;
  condition_body: Record<string, unknown>;
  channels?: string[];
  is_enabled?: boolean;
}

export interface NotificationDelivery {
  id: string;
  notification_id: string;
  channel: string;
  status: string;
  provider_msg_id: string | null;
  sent_at: string | null;
  error: string | null;
}

export interface PersistedNotification {
  id: string;
  user_id: string;
  type: string;
  title: string;
  body: string | null;
  payload: Record<string, unknown>;
  is_read: boolean;
  created_at: string;
  deliveries: NotificationDelivery[];
}

export interface BillingPlan {
  id: string;
  code: SubscriptionTier | string;
  name: string;
  price_monthly: number;
  currency: string;
  limits: Record<string, unknown>;
  features: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
}

export interface NotificationDraft {
  type: string;
  title: string;
  body?: string | null;
  payload?: Record<string, unknown>;
  channels?: string[];
}

export interface SubscriptionStatus {
  state: SubscriptionState;
  tier: SubscriptionTier;
  plan_id?: string | null;
  plan_code?: string | null;
  plan_name?: string | null;
  current_period_start?: string | null;
  current_period_end: string | null;
  external_provider?: string | null;
  external_id?: string | null;
  limits?: Record<string, unknown>;
  features?: Record<string, unknown>;
}

export interface ExchangeCatalog {
  supported_exchanges: string[];
  supported_symbols: string[];
  supported_timeframes: string[];
}

export interface ExchangeConnectionStatus {
  exchange: string;
  state: ExchangeConnectionState;
  account_label: string | null;
  last_sync_at: string | null;
}

export interface ExchangeConnection {
  id: string;
  user_id: string;
  exchange_id: string;
  exchange_code: string;
  exchange_name: string;
  label: string;
  account_type: string;
  key_ref: string;
  permissions: Record<string, unknown>;
  status: string;
  last_sync_at: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface ExchangeConnectionDraft {
  exchange_code: string;
  label: string;
  account_type?: string;
  api_key?: string | null;
  api_secret?: string | null;
  api_passphrase?: string | null;
  permissions?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}
