import type {
  AlertRule,
  BillingPlan,
  ExchangeCatalog,
  ExchangeConnection,
  ExchangeConnectionStatus,
  MarketPairOption,
  NotificationDelivery,
  PersistedNotification,
  SubscriptionState,
  SubscriptionStatus,
  SubscriptionTier,
  UserProfile,
  Watchlist
} from "@/features/server-state/types";
import type {
  CandleResponse,
  ExecutionGateStatus,
  ExecutionQualityGate,
  HealthStatus,
  ImpactRisk,
  LiquidityMetrics,
  OhlcvCandle,
  RadarConfig,
  RadarSignal,
  RadarStatus,
  TradeJournalEntry,
  TradeJournalResponse,
  VirtualAccount,
  VirtualExecutionReport,
  VirtualExecutionStatus,
  VirtualSimulationMode
} from "@/types";
import type { OhlcvCandleDto, RadarConfigDto, RadarSignalDto, TradeJournalEntryDto } from "./generated/schemas";

type TradeJournalEntryExtra = TradeJournalEntryDto & Partial<Pick<
  TradeJournalEntry,
  | "risk_amount"
  | "risk_reward"
  | "slippage_bps"
  | "close_reason"
  | "simulation_mode"
  | "execution_status"
  | "requested_size_usd"
  | "filled_size_usd"
  | "unfilled_size_usd"
  | "execution"
>>;

type VirtualAccountDto = Partial<VirtualAccount>;

export function normalizeSignal(signal: RadarSignalDto): RadarSignal {
  return {
    id: signal.id,
    symbol: signal.symbol,
    exchange: signal.exchange,
    strategy: signal.strategy,
    direction: signal.direction,
    confidence: signal.confidence,
    risk_reward: signal.risk_reward ?? null,
    urgency: signal.urgency ?? "medium",
    status: signal.status ?? "active",
    score: signal.score ?? 0,
    timeframe: signal.timeframe ?? "stream",
    entry_min: signal.entry_min ?? null,
    entry_max: signal.entry_max ?? null,
    stop_loss: signal.stop_loss ?? null,
    take_profit_1: signal.take_profit_1 ?? null,
    take_profit_2: signal.take_profit_2 ?? null,
    explanation: signal.explanation ?? [],
    risks: signal.risks ?? [],
    score_breakdown: signal.score_breakdown ?? {
      trend_score: 0,
      volume_score: 0,
      liquidity_score: 0,
      orderbook_score: 0,
      risk_reward_score: 0,
      volatility_score: 0,
      overheat_penalty: 0,
      news_event_risk_penalty: 0,
      total: 0
    },
    created_at: signal.created_at,
    updated_at: signal.updated_at,
    confirmed_trade_id: signal.confirmed_trade_id ?? null
  };
}

export function normalizeTrade(trade: TradeJournalEntryDto): TradeJournalEntry {
  const enriched = trade as TradeJournalEntryExtra;
  return {
    id: trade.id,
    user_id: trade.user_id,
    signal_id: trade.signal_id ?? null,
    mode: trade.mode,
    exchange: trade.exchange,
    symbol: trade.symbol,
    strategy: trade.strategy,
    timeframe: trade.timeframe,
    side: trade.side,
    entry_price: trade.entry_price,
    current_price: trade.current_price,
    exit_price: trade.exit_price ?? null,
    size_usd: trade.size_usd,
    quantity: trade.quantity,
    leverage: trade.leverage,
    risk_percent: trade.risk_percent,
    risk_amount: enriched.risk_amount ?? 0,
    risk_reward: enriched.risk_reward ?? 3,
    stop_loss: trade.stop_loss,
    take_profit: trade.take_profit ?? [],
    fees: trade.fees,
    slippage_bps: enriched.slippage_bps ?? 0,
    simulation_mode: normalizeSimulationMode(enriched.simulation_mode),
    execution_status: normalizeExecutionStatus(enriched.execution_status),
    requested_size_usd: enriched.requested_size_usd ?? null,
    filled_size_usd: enriched.filled_size_usd ?? null,
    unfilled_size_usd: enriched.unfilled_size_usd ?? 0,
    execution: normalizeExecutionReport(enriched.execution),
    status: trade.status,
    result: trade.result ?? null,
    close_reason: enriched.close_reason ?? null,
    pnl: trade.pnl ?? null,
    pnl_percent: trade.pnl_percent ?? null,
    mfe: trade.mfe,
    mae: trade.mae,
    screenshots: trade.screenshots ?? [],
    ai_review: trade.ai_review ?? null,
    opened_at: trade.opened_at,
    updated_at: trade.updated_at,
    closed_at: trade.closed_at ?? null
  };
}

export function normalizeExecutionReport(value: unknown): VirtualExecutionReport | null {
  if (!isRecord(value)) return null;
  const liquidity = isRecord(value.liquidity) ? value.liquidity : {};
  return {
    mode: normalizeSimulationMode(value.mode),
    status: normalizeExecutionStatus(value.status),
    requested_size_usd: Number(value.requested_size_usd ?? 0),
    filled_size_usd: Number(value.filled_size_usd ?? 0),
    unfilled_size_usd: Number(value.unfilled_size_usd ?? 0),
    fill_ratio: Number(value.fill_ratio ?? 1),
    reference_price: Number(value.reference_price ?? 0),
    average_price: value.average_price == null ? null : Number(value.average_price),
    entry_slippage_bps: Number(value.entry_slippage_bps ?? 0),
    exit_slippage_bps: Number(value.exit_slippage_bps ?? 0),
    market_impact_percent: Number(value.market_impact_percent ?? 0),
    best_bid_before: value.best_bid_before == null ? null : Number(value.best_bid_before),
    best_ask_before: value.best_ask_before == null ? null : Number(value.best_ask_before),
    book_price_after: value.book_price_after == null ? null : Number(value.book_price_after),
    liquidity: normalizeLiquidityMetrics(liquidity),
    quality_gate: normalizeQualityGate(value.quality_gate),
    rejected_reason: value.rejected_reason == null ? null : String(value.rejected_reason),
    notes: Array.isArray(value.notes) ? value.notes.map(String) : []
  };
}

function normalizeLiquidityMetrics(value: Record<string, unknown>): LiquidityMetrics {
  return {
    spread_percent: Number(value.spread_percent ?? 0),
    orderbook_depth_0_1_percent_usd: Number(value.orderbook_depth_0_1_percent_usd ?? 0),
    orderbook_depth_0_5_percent_usd: Number(value.orderbook_depth_0_5_percent_usd ?? 0),
    orderbook_depth_1_percent_usd: Number(value.orderbook_depth_1_percent_usd ?? 0),
    volume_1m_usd: Number(value.volume_1m_usd ?? 0),
    volume_5m_usd: Number(value.volume_5m_usd ?? 0),
    volume_15m_usd: Number(value.volume_15m_usd ?? 0),
    average_trade_size_usd: Number(value.average_trade_size_usd ?? 0),
    volatility_1m_percent: Number(value.volatility_1m_percent ?? 0),
    liquidity_score: Number(value.liquidity_score ?? 0),
    impact_score: Number(value.impact_score ?? 0),
    impact_risk: normalizeImpactRisk(value.impact_risk)
  };
}

function normalizeQualityGate(value: unknown): ExecutionQualityGate {
  const gate = isRecord(value) ? value : {};
  return {
    status: normalizeGateStatus(gate.status),
    warnings: Array.isArray(gate.warnings) ? gate.warnings.map(String) : [],
    high_impact_reasons: Array.isArray(gate.high_impact_reasons) ? gate.high_impact_reasons.map(String) : [],
    blockers: Array.isArray(gate.blockers) ? gate.blockers.map(String) : [],
    suggested_max_size_usd: gate.suggested_max_size_usd == null ? null : Number(gate.suggested_max_size_usd),
    message: gate.message == null ? null : String(gate.message)
  };
}

function normalizeSimulationMode(value: unknown): VirtualSimulationMode {
  return value === "impact_aware" ? "impact_aware" : "passive";
}

function normalizeExecutionStatus(value: unknown): VirtualExecutionStatus {
  if (value === "partially_filled" || value === "rejected_virtual_execution") return value;
  return "filled";
}

function normalizeImpactRisk(value: unknown): ImpactRisk {
  if (value === "medium" || value === "high") return value;
  return "low";
}

function normalizeGateStatus(value: unknown): ExecutionGateStatus {
  if (value === "warning" || value === "blocked") return value;
  return "passed";
}

export function normalizeCandle(candle: OhlcvCandleDto): OhlcvCandle {
  return {
    exchange: candle.exchange,
    symbol: candle.symbol,
    timeframe: candle.timeframe,
    open_time: candle.open_time,
    close_time: candle.close_time,
    open: candle.open,
    high: candle.high,
    low: candle.low,
    close: candle.close,
    volume: candle.volume,
    trades: candle.trades ?? 0,
    is_closed: candle.is_closed ?? false
  };
}

export function normalizeConfig(config: RadarConfigDto): RadarConfig {
  return {
    exchanges: config.exchanges ?? ["bybit"],
    symbols: config.symbols ?? [],
    use_all_symbols: config.use_all_symbols ?? false,
    timeframes: config.timeframes ?? ["1m", "5m", "15m", "1h", "4h", "1d"]
  };
}

export function normalizeCandleResponse(candles: OhlcvCandleDto[]): CandleResponse {
  return { candles: candles.map(normalizeCandle) };
}

export function normalizeVirtualAccount(account?: unknown): VirtualAccount | null {
  if (!account) return null;
  const value = account as VirtualAccountDto;
  return {
    user_id: value.user_id ?? "demo_user",
    starting_balance: value.starting_balance ?? 100,
    balance: value.balance ?? 100,
    equity: value.equity ?? value.balance ?? 100,
    realized_pnl: value.realized_pnl ?? 0,
    unrealized_pnl: value.unrealized_pnl ?? 0,
    risk_per_trade: value.risk_per_trade ?? 10,
    risk_reward: value.risk_reward ?? 3,
    open_positions: value.open_positions ?? 0,
    closed_trades: value.closed_trades ?? 0,
    wins: value.wins ?? 0,
    losses: value.losses ?? 0,
    breakeven: value.breakeven ?? 0,
    updated_at: value.updated_at ?? new Date().toISOString()
  };
}

export function normalizeTradeResponse(trades: TradeJournalEntryDto[], account?: unknown): TradeJournalResponse {
  return { trades: trades.map(normalizeTrade), account: normalizeVirtualAccount(account) };
}

export function normalizeWatchlist(config: RadarConfig): Watchlist {
  return {
    id: "config-derived",
    user_id: "demo_user",
    name: "Default",
    is_default: true,
    pairs: config.symbols.map((symbol) => ({
      id: symbol,
      exchange: config.exchanges[0] ?? "bybit",
      symbol,
      base_asset: symbol.replace(/USDT$/, ""),
      quote_asset: "USDT",
      status: "active",
      added_at: new Date(0).toISOString()
    })),
    symbols: config.symbols,
    use_all_symbols: config.use_all_symbols,
    created_at: new Date(0).toISOString(),
    updated_at: null
  };
}

export function normalizeMarketPair(value: unknown): MarketPairOption {
  const pair = value as Partial<MarketPairOption>;
  return {
    id: String(pair.id ?? ""),
    exchange: String(pair.exchange ?? "bybit"),
    symbol: String(pair.symbol ?? ""),
    base_asset: String(pair.base_asset ?? ""),
    quote_asset: String(pair.quote_asset ?? ""),
    status: String(pair.status ?? "active")
  };
}

export function normalizeWatchlistResponse(value: unknown): Watchlist {
  const watchlist = value as Partial<Watchlist>;
  const pairs = Array.isArray(watchlist.pairs)
    ? watchlist.pairs.map((pair) => ({
        ...normalizeMarketPair(pair),
        added_at: String((pair as { added_at?: unknown }).added_at ?? watchlist.created_at ?? new Date().toISOString())
      }))
    : [];
  return {
    id: String(watchlist.id ?? ""),
    user_id: String(watchlist.user_id ?? "demo_user"),
    name: String(watchlist.name ?? "Default"),
    is_default: Boolean(watchlist.is_default ?? true),
    pairs,
    symbols: pairs.map((pair) => pair.symbol),
    use_all_symbols: false,
    created_at: String(watchlist.created_at ?? new Date().toISOString()),
    updated_at: watchlist.updated_at ?? null
  };
}

export function normalizeAlertRule(value: unknown): AlertRule {
  const alert = value as Partial<AlertRule>;
  return {
    id: String(alert.id ?? ""),
    user_id: String(alert.user_id ?? "demo_user"),
    pair: alert.pair ? normalizeMarketPair(alert.pair) : null,
    strategy_version_id: alert.strategy_version_id ?? null,
    condition_type: String(alert.condition_type ?? "price_above"),
    condition_body: alert.condition_body ?? {},
    channels: Array.isArray(alert.channels) ? alert.channels.map(String) : ["websocket"],
    is_enabled: Boolean(alert.is_enabled ?? true),
    created_at: String(alert.created_at ?? new Date().toISOString())
  };
}

export function normalizeNotification(value: unknown): PersistedNotification {
  const notification = value as Partial<PersistedNotification>;
  return {
    id: String(notification.id ?? ""),
    user_id: String(notification.user_id ?? "demo_user"),
    type: String(notification.type ?? "system"),
    title: String(notification.title ?? "Notification"),
    body: notification.body == null ? null : String(notification.body),
    payload: isRecord(notification.payload) ? notification.payload : {},
    is_read: Boolean(notification.is_read),
    created_at: String(notification.created_at ?? new Date().toISOString()),
    deliveries: Array.isArray(notification.deliveries)
      ? notification.deliveries.map(normalizeNotificationDelivery)
      : []
  };
}

export function normalizeBillingPlan(value: unknown): BillingPlan {
  const plan = value as Partial<BillingPlan>;
  return {
    id: String(plan.id ?? ""),
    code: String(plan.code ?? "free"),
    name: String(plan.name ?? plan.code ?? "Free"),
    price_monthly: Number(plan.price_monthly ?? 0),
    currency: String(plan.currency ?? "USD"),
    limits: isRecord(plan.limits) ? plan.limits : {},
    features: isRecord(plan.features) ? plan.features : {},
    is_active: Boolean(plan.is_active ?? true),
    created_at: String(plan.created_at ?? new Date().toISOString())
  };
}

export function normalizeSubscriptionStatus(value: unknown): SubscriptionStatus {
  const subscription = value as Partial<SubscriptionStatus>;
  const tier = normalizeSubscriptionTier(subscription.tier ?? subscription.plan_code ?? "free");
  return {
    state: normalizeSubscriptionState(subscription.state ?? "none"),
    tier,
    plan_id: subscription.plan_id == null ? null : String(subscription.plan_id),
    plan_code: subscription.plan_code == null ? null : String(subscription.plan_code),
    plan_name: subscription.plan_name == null ? null : String(subscription.plan_name),
    current_period_start: subscription.current_period_start == null ? null : String(subscription.current_period_start),
    current_period_end: subscription.current_period_end == null ? null : String(subscription.current_period_end),
    external_provider: subscription.external_provider == null ? null : String(subscription.external_provider),
    external_id: subscription.external_id == null ? null : String(subscription.external_id),
    limits: isRecord(subscription.limits) ? subscription.limits : {},
    features: isRecord(subscription.features) ? subscription.features : {}
  };
}

export function normalizeUserProfile(value: unknown): UserProfile {
  const profile = value as Partial<UserProfile>;
  return {
    id: String(profile.id ?? ""),
    email: String(profile.email ?? ""),
    name: profile.name == null ? null : String(profile.name),
    created_at: String(profile.created_at ?? new Date().toISOString())
  };
}

function normalizeNotificationDelivery(value: unknown): NotificationDelivery {
  const delivery = value as Partial<NotificationDelivery>;
  return {
    id: String(delivery.id ?? ""),
    notification_id: String(delivery.notification_id ?? ""),
    channel: String(delivery.channel ?? "websocket"),
    status: String(delivery.status ?? "unknown"),
    provider_msg_id: delivery.provider_msg_id == null ? null : String(delivery.provider_msg_id),
    sent_at: delivery.sent_at == null ? null : String(delivery.sent_at),
    error: delivery.error == null ? null : String(delivery.error)
  };
}

export function normalizeExchangeCatalog(catalog: Record<string, string[]>): ExchangeCatalog {
  return {
    supported_exchanges: catalog.supported_exchanges ?? [],
    supported_symbols: catalog.supported_symbols ?? [],
    supported_timeframes: catalog.supported_timeframes ?? []
  };
}

export function normalizeExchangeConnections(catalog: ExchangeCatalog): ExchangeConnectionStatus[] {
  return catalog.supported_exchanges.map((exchange) => ({
    exchange,
    state: "available",
    account_label: null,
    last_sync_at: null
  }));
}

export function normalizeExchangeConnection(value: unknown): ExchangeConnection {
  const connection = value as Partial<ExchangeConnection>;
  return {
    id: String(connection.id ?? ""),
    user_id: String(connection.user_id ?? "demo_user"),
    exchange_id: String(connection.exchange_id ?? ""),
    exchange_code: String(connection.exchange_code ?? ""),
    exchange_name: String(connection.exchange_name ?? connection.exchange_code ?? ""),
    label: String(connection.label ?? ""),
    account_type: String(connection.account_type ?? "spot"),
    key_ref: String(connection.key_ref ?? ""),
    permissions: isRecord(connection.permissions) ? connection.permissions : {},
    status: String(connection.status ?? "active"),
    last_sync_at: connection.last_sync_at == null ? null : String(connection.last_sync_at),
    metadata: isRecord(connection.metadata) ? connection.metadata : {},
    created_at: String(connection.created_at ?? new Date().toISOString())
  };
}

export function normalizeHealth(value: unknown): HealthStatus {
  const health = value as Partial<HealthStatus>;
  return {
    status: String(health.status ?? "unknown"),
    scanner_enabled: Boolean(health.scanner_enabled),
    scanner_running: Boolean(health.scanner_running),
    scanner_stopping: Boolean(health.scanner_stopping),
    processed_signals: Number(health.processed_signals ?? 0),
    ticks_processed: Number(health.ticks_processed ?? 0),
    features_built: Number(health.features_built ?? 0),
    strategy_evaluations: Number(health.strategy_evaluations ?? 0),
    signals_found: Number(health.signals_found ?? 0),
    candles_seeded: Number(health.candles_seeded ?? 0),
    last_symbol: health.last_symbol ?? null,
    last_price: health.last_price ?? null
  };
}

export function normalizeRadarStatus(value: unknown): RadarStatus {
  const status = value as Partial<RadarStatus>;
  return {
    ...normalizeHealth(status),
    exchanges: status.exchanges ?? [],
    symbols: status.symbols ?? [],
    timeframes: status.timeframes ?? [],
    strategies: status.strategies ?? [],
    ticks_processed: Number(status.ticks_processed ?? 0),
    candles_updated: Number(status.candles_updated ?? 0),
    features_built: Number(status.features_built ?? 0),
    strategy_evaluations: Number(status.strategy_evaluations ?? 0),
    signals_found: Number(status.signals_found ?? 0),
    candles_seeded: Number(status.candles_seeded ?? 0),
    last_tick_at: status.last_tick_at ?? null,
    last_signal_at: status.last_signal_at ?? null,
    last_exchange: status.last_exchange ?? null,
    last_symbol: status.last_symbol ?? null,
    last_price: status.last_price ?? null,
    candle_history: status.candle_history ?? {}
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function normalizeSubscriptionTier(value: unknown): SubscriptionTier {
  return value === "pro" || value === "team" ? value : "free";
}

function normalizeSubscriptionState(value: unknown): SubscriptionState {
  if (value === "active" || value === "trialing" || value === "past_due" || value === "canceled") return value;
  return "none";
}
