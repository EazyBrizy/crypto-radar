export type SubscriptionTier = "free" | "pro" | "team";
export type SubscriptionState = "active" | "trialing" | "past_due" | "canceled" | "none";
export type ExchangeConnectionState = "available" | "connected" | "disconnected" | "error";
export type ExchangeConnectionLifecycleStatus = "active" | "disabled" | "revoked" | "deleted";
export type VirtualSimulationLevel = "mvp" | "advanced" | "pro";
export type VirtualSimulationLevelStatus = "active" | "stub";
export type RiskProfileName = "conservative" | "balanced" | "aggressive" | "custom";
export type StopLossMode = "fixed_percent" | "atr" | "structure";
export type TakeProfitMode = "risk_multiple";
export type TrailingMode = "atr" | "percent" | "structure";
export type VirtualRiskMode = "same_as_real" | "custom";
export type VirtualSlippageModel = "none" | "fixed_percent" | "spread_based" | "orderbook_based" | "volatility_based";
export type VirtualFeeModel = "manual" | "exchange_based";
export type RRGuardMode = "off" | "soft" | "hard";
export type RiskAmountMode = "percent" | "fixed";
export type RadarDisplayMode = "all_market_opportunities" | "execution_ready";
export type InstrumentType = "spot" | "futures";
export type RRTarget = "nearest" | "final";

export interface VirtualTradingSettings {
  simulation_level: VirtualSimulationLevel;
  simulation_level_status: VirtualSimulationLevelStatus;
  effective_simulation_level: VirtualSimulationLevel;
}

export interface RiskManagementSettings {
  risk_profile: RiskProfileName;
  risk_mode: RiskAmountMode;
  risk_per_trade_percent: number;
  fixed_risk_amount: number | null;
  fixed_risk_currency: string;
  radar_display_mode: RadarDisplayMode;
  min_rr_ratio: number;
  rr_guard_mode: RRGuardMode;
  discovery_rr_guard_mode: RRGuardMode;
  real_rr_guard_mode: RRGuardMode;
  virtual_rr_guard_mode: RRGuardMode;
  backtest_rr_guard_mode: RRGuardMode;
  strategy_rr_guard_modes: Record<string, RRGuardMode>;
  max_daily_loss_percent: number;
  max_weekly_loss_percent: number;
  max_account_drawdown_percent: number;
  max_open_risk_percent: number;
  max_correlated_risk_percent: number;
  max_spread_bps: number;
  max_slippage_bps: number;
  max_price_deviation_bps: number;
  max_orderbook_liquidity_ratio: number;
  include_fees_in_risk: boolean;
  include_slippage_in_risk: boolean;
  stop_loss_required: boolean;
  take_profit_required: boolean;
  stop_loss_mode: StopLossMode;
  default_stop_loss_percent: number;
  atr_period: number;
  atr_multiplier: number;
  take_profit_mode: TakeProfitMode;
  tp1_r_multiple: number;
  tp2_r_multiple: number;
  tp3_r_multiple: number;
  partial_take_profit_enabled: boolean;
  tp1_close_percent: number;
  tp2_close_percent: number;
  tp3_close_percent: number;
  move_sl_to_breakeven_after_r: number;
  breakeven_offset_percent: number;
  trailing_stop_enabled: boolean;
  trailing_mode: TrailingMode;
  trailing_atr_multiplier: number;
  trailing_stop_percent: number;
  max_leverage: number;
  min_liquidation_buffer_percent: number;
  liquidation_buffer_required: boolean;
  spot_risk_per_trade_percent: number;
  spot_max_position_size_percent: number;
  spot_stop_required: boolean;
  futures_risk_per_trade_percent: number;
  futures_max_leverage: number;
  futures_max_open_risk_percent: number;
  futures_liquidation_buffer_required: boolean;
  virtual_risk_mode: VirtualRiskMode;
  virtual_risk_per_trade_percent: number;
  virtual_starting_balance: number;
  virtual_slippage_model: VirtualSlippageModel;
  virtual_fee_model: VirtualFeeModel;
  virtual_trading_uses_realistic_execution: boolean;
  real_execution_enabled: boolean;
  real_requires_fresh_market_data: boolean;
  real_requires_positive_edge: boolean;
  real_fee_rate_ttl_seconds: number;
  no_trade_filters_enabled: boolean;
  max_spread_bps_for_entry: number;
  max_slippage_bps_for_entry: number;
  min_depth_usd_for_entry: number;
  max_obstacle_distance_r: number;
  cooldown_after_stop_minutes: number;
  max_strategy_losses_per_day: number;
  edge_min_sample_size: number;
  min_expectancy_after_costs_r: number;
  strategy_risk_multipliers: Record<string, number>;
  auto_reduce_risk_after_losses: boolean;
  allow_risk_increase_after_profit: boolean;
  increase_risk_after_profit_streak: boolean;
  max_risk_boost: number;
}

export interface StrategyExecutionSettings extends Record<string, unknown> {
  risk_mode?: RiskAmountMode;
  risk_percent?: number | string | null;
  fixed_risk_amount?: number | string | null;
  fixed_risk_currency?: string;
  leverage?: number | string | null;
  instrument_type?: InstrumentType | null;
  rr_guard_mode?: RRGuardMode | null;
  min_rr_ratio?: number | string | null;
  rr_target?: RRTarget | null;
  radar_display_mode?: RadarDisplayMode | null;
  risk_per_trade_percent?: number | string | null;
  futures_risk_per_trade_percent?: number | string | null;
  spot_risk_per_trade_percent?: number | string | null;
  virtual_risk_per_trade_percent?: number | string | null;
}

export interface UserSettingsPatch {
  virtual_simulation_level?: VirtualSimulationLevel;
  risk_profile?: RiskProfileName;
  risk_management?: Partial<RiskManagementSettings>;
}

export interface UserProfile {
  id: string;
  email: string;
  name: string | null;
  risk_profile: RiskProfileName;
  settings: {
    virtual_trading: VirtualTradingSettings;
    risk_management: RiskManagementSettings;
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

export type MarketUniverseLimit = "top_100" | "top_200" | "top_500" | "all";

export interface MarketUniversePairsQuery {
  exchange?: string;
  category?: string;
  quote?: string;
  limit?: MarketUniverseLimit;
  search?: string;
  sort?: string;
  liquidity_tier?: string;
  status?: string;
}

export interface MarketUniversePair extends MarketPairOption {
  category: string | null;
  market_type: string | null;
  turnover_24h: string | null;
  volume_24h: string | null;
  last_price: string | null;
  mark_price: string | null;
  bid_price: string | null;
  ask_price: string | null;
  spread_bps: string | null;
  funding_rate: string | null;
  liquidity_rank: number | null;
  liquidity_tier: string | null;
  synced_at: string | null;
}

export interface MarketUniverseSyncRequest {
  exchange?: string;
  category?: string;
  quote?: string;
  limit?: MarketUniverseLimit;
  sort?: string;
  persist?: boolean;
}

export interface MarketUniverseSyncResponse {
  exchange: string;
  category: string;
  quote: string;
  requested_limit: MarketUniverseLimit;
  synced_count: number;
  total_available_count: number;
  skipped_count: number;
  synced_at: string;
  warnings: string[];
}

export interface StrategyPairScope {
  exchange: string;
  symbol: string;
}

export interface StrategyConfig {
  id: string;
  user_id: string;
  strategy_version_id: string;
  strategy_code: string;
  strategy_name: string;
  strategy_version: string;
  name: string;
  exchanges: string[];
  pairs: StrategyPairScope[];
  timeframes: string[];
  params: Record<string, unknown>;
  risk_settings: StrategyExecutionSettings;
  is_enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface StrategyConfigPatch {
  name?: string;
  exchanges?: string[];
  pairs?: StrategyPairScope[];
  timeframes?: string[];
  params?: Record<string, unknown>;
  risk_settings?: StrategyExecutionSettings;
  is_enabled?: boolean;
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
  status: ExchangeConnectionLifecycleStatus;
  last_sync_at: string | null;
  revoked_at: string | null;
  deleted_at: string | null;
  deletion_reason: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface ExchangeFeeRate {
  connection_id: string;
  exchange_code: string;
  account_type: string | null;
  category: string;
  symbol: string | null;
  maker_fee_rate: number;
  taker_fee_rate: number;
  source: string;
  fetched_at: string;
}

export type AccountSnapshotStatus = "fresh" | "stale" | "missing";
export type AccountSnapshotSource = "exchange" | "request" | "virtual" | "dry_run" | "demo";

export interface PositionRiskSummary {
  symbol: string | null;
  side: "long" | "short" | "unknown";
  quantity: number | null;
  notional: number | null;
  entry_price: number | null;
  mark_price: number | null;
  unrealized_pnl: number | null;
  risk_amount: number | null;
  initial_margin: number | null;
  maintenance_margin: number | null;
  margin_mode: string | null;
}

export interface AccountRiskSnapshot {
  status: AccountSnapshotStatus;
  fetched_at: string | null;
  account_equity: number | null;
  available_balance: number | null;
  wallet_balance: number | null;
  margin_mode: string | null;
  total_initial_margin: number | null;
  total_maintenance_margin: number | null;
  maintenance_margin_rate: number | null;
  positions: PositionRiskSummary[];
  open_risk_amount: number;
  source: AccountSnapshotSource;
  warnings: string[];
}

export interface ExchangeWalletCoinBalance {
  coin: string;
  equity: number | null;
  usd_value: number | null;
  wallet_balance: number | null;
  available_to_withdraw: number | null;
  locked: number | null;
  borrow_amount: number | null;
  accrued_interest: number | null;
  total_order_im: number | null;
  total_position_im: number | null;
  total_position_mm: number | null;
  unrealised_pnl: number | null;
}

export interface ExchangeWalletBalance {
  exchange: string;
  connection_id: string;
  account_type: string;
  total_equity: number | null;
  total_wallet_balance: number | null;
  total_available_balance: number | null;
  coins: ExchangeWalletCoinBalance[];
  fetched_at: string | null;
  status: AccountSnapshotStatus;
  warnings: string[];
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
