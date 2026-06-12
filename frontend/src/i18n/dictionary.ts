import type { Locale } from "./locale";

type TranslationMap = Partial<Record<Locale, string>>;

type DictionaryLocale = "ru" | "en";
type TranslationValue = string | number | boolean | null | undefined;
type TranslationParams = Record<string, TranslationValue>;
type TranslationTree = {
  [key: string]: string | TranslationTree;
};

type DotKeys<T> = {
  [K in Extract<keyof T, string>]: T[K] extends string
    ? K
    : T[K] extends Record<string, unknown>
      ? `${K}.${DotKeys<T[K]>}`
      : never;
}[Extract<keyof T, string>];

const typedDictionary = {
  en: {
    navigation: {
      radar: "Radar",
      watchlist: "Watchlist",
      trades: "Trades",
      settings: "Settings",
      billing: "Billing"
    },
    common: {
      actions: "Actions",
      active: "Active",
      add: "Add",
      all: "All",
      allPairs: "All pairs",
      analytics: "Analytics",
      balance: "Balance",
      cancel: "Cancel",
      checking: "Checking",
      close: "Close",
      collapsed: "Collapsed",
      current: "Current",
      custom: "Custom",
      default: "Default",
      delete: "Delete",
      disabled: "Disabled",
      enabled: "Enabled",
      error: "Error",
      exchange: "Exchange",
      history: "History",
      journal: "Journal",
      loading: "Loading...",
      market: "Market",
      none: "None",
      no: "No",
      noData: "No data",
      noExpiry: "No expiry",
      off: "Off",
      on: "On",
      open: "Open",
      openLower: "open",
      refresh: "Refresh",
      remove: "Remove",
      save: "Save",
      search: "Search",
      select: "Select",
      sort: "Sort",
      status: "Status",
      sync: "Sync",
      test: "Test",
      unknown: "Unknown",
      updated: "Updated",
      warning: "Warning",
      yes: "Yes",
      emptyDash: "-"
    },
    commonErrors: {
      unknown: "Unknown error",
      network: "Network request failed.",
      apiContract: "API contract error",
      signalRejectFailed: "Signal reject failed.",
      virtualTradeRejected: "Virtual trade was rejected by execution quality checks.",
      realTradeRejected: "Real trade was rejected by execution safeguards.",
      pendingEntryRejected: "Pending entry was rejected.",
      pendingEntryCancelFailed: "Pending entry cancel failed.",
      pendingEntryReconfirmFailed: "Pending entry reconfirmation failed.",
      pendingEntryUnavailable: "This signal is not available for pending entry.",
      onlyOpenIdeas: "Only open strategy ideas can be armed or sent to virtual trading.",
      marketPairNotFoundInUniverse: "Pair is not found in the local universe. Sync pairs from the exchange first.",
      exchangeConnectionNotFound: "Exchange connection is not found.",
      exchangeConnectionHasHistory: "Exchange connection is linked to historical orders or trades, so hard delete is unavailable.",
      hardDeleteRequiresAdmin: "Hard delete is available only to an internal administrator."
    },
    navigationLabels: {
      appName: "Crypto Radar",
      signalFeed: "Signal Feed",
      riskBalanced: "Risk: Balanced"
    },
    radar: {
      eyebrow: "Signal First Radar",
      title: "Market opportunities",
      marketStatus: "Market status",
      executionReady: "Execution ready",
      highConfidence: "High confidence",
      positiveEdge: "Positive edge",
      blockedIdeas: "Blocked ideas",
      ticks: "Ticks",
      strategyChecks: "Strategy checks",
      features: "Features",
      scanner: "scanner",
      riskGate: "RiskGate",
      score80: "score 80+",
      evGate: "EV gate",
      backend: "backend",
      marketData: "market data",
      evaluated: "evaluated",
      candlesAnalyzed: "candles analyzed",
      online: "Online",
      offline: "Offline",
      scannerActivity: "Scanner activity",
      scannerLive: "Scanner live",
      scannerOffline: "Scanner offline",
      scannerDelayed: "Scanner data delayed",
      scannerConnecting: "Connecting",
      scannerError: "Scanner error",
      dataStale: "Data stale",
      waitingMarketData: "Waiting for market data",
      warmupProgress: "Warmup: {completed}/{total}, failed {failed}",
      lastTickAge: "Last tick: {age}",
      noTicksYet: "no ticks yet",
      justNow: "just now",
      lastError: "Last error: {error}",
      signalsFound: "Signals found: {count}",
      seededCandles: "Seeded candles: {count}",
      pairs: "Pairs: {count}",
      universe: "Universe: {universe}",
      estimatedEvaluations: "Estimated evaluations: {count}",
      timeframes: "Timeframes: {timeframes}",
      warning: "Warning: {warning}",
      candles: "{count} candles",
      candleHistoryWarming: "Candle history is still warming up",
      openIdeas: "open ideas",
      history: "history",
      allMarketOpportunities: "all market opportunities",
      executionReadyFilter: "execution ready",
      allIdeasFilter: "All ideas",
      watchlistFilter: "Watchlist",
      readyToExecuteFilter: "Ready to execute",
      blockedFilter: "Blocked",
      allFilter: "all",
      longFilter: "long",
      shortFilter: "short",
      noHistoricalSignals: "No historical signals yet",
      noMarketOpportunities: "No market opportunities yet",
      historicalSignalsEmpty: "Invalidated and expired ideas will appear here after lifecycle transitions.",
      marketOpportunitiesEmpty: "The scanner may still be building candle history, or the market has not produced a valid setup."
    },
    signalDetails: {
      title: "Signal details",
      emptyTitle: "Select a signal",
      emptyBody: "Backend signal details will appear here.",
      missingTitle: "Signal is no longer visible",
      missingBody: "Selected signal is no longer visible.",
      selectLatestSignal: "Select latest signal",
      decision: "Decision",
      trigger: "Trigger",
      strategyEligibility: "Strategy eligibility",
      deduplication: "Deduplication",
      latestPendingEntryOutcome: "Latest pending-entry outcome",
      recommendedAction: "Recommended action",
      canEnterNow: "Can enter now",
      topBlockers: "Top blockers",
      noActiveBlockers: "No active blockers from backend action-state.",
      tradePlan: "Trade plan",
      entryType: "Entry type",
      entryZonePrice: "Entry zone / price",
      stopLoss: "Stop-loss",
      runner: "Runner",
      selectedRr: "Selected RR",
      invalidation: "Invalidation",
      risk: "Risk",
      riskAmountPercent: "Risk amount / %",
      marginLeverage: "Margin / leverage",
      executionQuality: "Execution quality",
      whyThisSignal: "Why this signal?",
      actions: "Actions",
      executionEnvironment: "Execution environment: {environment}",
      noExchangeConnection: "No exchange connection",
      virtualWaitEntry: "Virtual wait entry",
      realWaitEntry: "Real wait entry",
      virtualEntryNow: "Virtual entry now",
      virtualEntryLocked: "Virtual entry locked",
      cancelWaiting: "Cancel waiting",
      hideChart: "Hide chart",
      openChart: "Open chart",
      rejectIgnore: "Reject / ignore",
      tradingDisabled: "Trading actions disabled until realtime data is current.",
      diagnostics: "Diagnostics",
      backendActionState: "Backend action state",
      signalStatus: "Signal status",
      primaryAction: "Primary action",
      canEnter: "Can enter",
      canArmPending: "Can arm pending",
      canCancel: "Can cancel",
      environment: "Environment",
      backendExecutionPreview: "Backend execution preview",
      qualityGate: "Quality gate",
      impactRisk: "Impact risk",
      requestedSize: "Requested size",
      filledSize: "Filled size",
      entrySlippage: "Entry slippage",
      slippageUnavailable: "slippage -",
      slippageBps: "slippage {value} bps",
      reason: "Reason",
      previewError: "Preview error",
      previewLoading: "Backend execution preview is loading.",
      previewNotRequested: "No execution preview requested.",
      notEvaluated: "not evaluated",
      notPreviewed: "not previewed",
      yes: "yes",
      no: "no"
    },
    pendingEntry: {
      queueEyebrow: "Pending entries queue",
      selectedEntries: "Selected entries",
      activeCount: "{count} active",
      loading: "Loading pending entries",
      noActive: "No active pending entries",
      history: "History",
      noHistory: "No pending entry history",
      activePendingEntry: "Active pending entry",
      pendingEntry: "Pending entry",
      historyTitle: "Pending entry history",
      state: "State",
      status: "Status",
      entryZone: "Entry zone",
      currentPrice: "Current price",
      expires: "Expires",
      expiryTtl: "Expiry / TTL",
      stop: "Stop",
      mode: "Mode",
      acceptedStatus: "Accepted status",
      reasonCode: "Reason code",
      reason: "Reason",
      updated: "Updated",
      selectSignal: "Select signal",
      reconfirm: "Reconfirm",
      reconfirmPlan: "Reconfirm plan",
      cancel: "Cancel",
      noBackendReason: "No backend reason.",
      noReasonFromBackend: "No reason from backend",
      noExpiry: "no expiry",
      expired: "expired",
      ttlUnknown: "TTL unknown",
      minutesLeft: "{count}m left",
      hoursLeft: "{count}h left",
      realPendingUnavailable: "Real pending entry is not available yet."
    },
    trades: {
      eyebrow: "Trades",
      title: "Trades and journal",
      active: "Active",
      journal: "Journal",
      analytics: "Analytics",
      balance: "Balance",
      equity: "Equity",
      realizedPnl: "Realized PnL",
      openPositions: "Open positions",
      riskPerTrade: "Risk {amount} per trade",
      unrealized: "Unrealized {amount}",
      unrealizedLabel: "Unrealized",
      winLossBreakeven: "{wins}W / {losses}L / {breakeven}BE",
      rr: "RR 1:{value}",
      loadingTable: "Loading table...",
      loadingAnalytics: "Loading analytics...",
      loadingChart: "Loading chart...",
      noActiveTrades: "No active trades",
      journalEmpty: "Journal is empty",
      hit: "hit",
      pair: "Pair",
      mode: "Mode",
      executionShort: "Exec",
      side: "Side",
      lifecycle: "Lifecycle",
      beMoved: "BE moved",
      trailing: "Trailing",
      entry: "Entry",
      takeProfit: "Take profit",
      stop: "Stop",
      execution: "Execution",
      model: "Model",
      remaining: "Remaining",
      remain: "Remain",
      realized: "Realized",
      size: "Size",
      partial: "Partial",
      impact: "Impact",
      passive: "Passive",
      closeMarket: "Close market",
      backtestCloseUnavailable: "Backtest trades cannot be closed from the journal",
      realCloseStub: "Real close stub",
      keepStopLoss: "Keep stop loss",
      noCandleData: "No candle data for this trade",
      postImpact: "Post-impact",
      decay60s: "Decay 60s"
    },
    settings: {
      eyebrow: "Settings",
      title: "Radar settings",
      exchanges: "Exchanges",
      exchangeConnections: "Exchange connections",
      connectionCount: "{count} connection{suffix}",
      noExchangeConnections: "No exchange connections",
      strategies: "Strategies",
      strategyCount: "{enabled}/{total} on",
      strategyTesting: "Strategy Testing",
      backtestLab: "Backtest Lab",
      confirmMainnetLive: "Confirm mainnet live",
      mainnetLive: "Mainnet live",
      testnet: "Testnet",
      mainnet: "Mainnet",
      dryRun: "Dry-run",
      dryRunOrders: "Dry-run orders",
      testnetRealOrders: "Testnet real orders",
      mainnetSmallSize: "Mainnet small size",
      mainnetScaled: "Mainnet scaled",
      live: "Live",
      soft: "Soft",
      hard: "Hard",
      noStrategyConfigs: "No strategy configs",
      activeOnly: "Active only",
      allSetups: "All setups",
      onlyActiveSetups: "Only active setups",
      riskProfile: "Risk profile",
      tradeRules: "Trade rules",
      futuresProtection: "Futures protection",
      virtualTrading: "Virtual trading",
      guide: "Guide",
      sync: "Sync",
      test: "Test",
      softDelete: "soft delete",
      connect: "Connect",
      deleteExchangeConnection: "Delete exchange connection?",
      deleteExchangeConnectionBody: "Connection {exchange} / {label} will be hidden from the active list. Historical orders and trades remain linked to it.",
      strategyPairs: "Strategy trading pairs",
      selectedPairsCount: "{count} pairs selected",
      allPairsFromScannerUniverse: "All pairs from scanner universe",
      lastSync: "Last sync: {value}",
      syncPairsFromExchange: "Sync pairs from exchange",
      selectVisible: "Select visible",
      selectVisibleLimit: "Select {limit} visible",
      clear: "Clear",
      noData: "no data",
      universeLoading: "Loading universe...",
      universeEmpty: "No pairs in the local universe. Sync pairs from the exchange.",
      selectedLowLiquidityPairs: "Selected low-liquidity pairs: {pairs}",
      universeLoadFailed: "Could not load universe: {error}",
      universeSyncFailed: "Could not sync universe: {error}",
      selectPair: "Select pair {symbol}",
      alerts: "Alerts",
      ruleCount: "{count} rule{suffix}",
      alertPair: "Alert pair",
      alertCondition: "Alert condition",
      alertPrice: "Alert price",
      selectPairOption: "Select pair",
      noPairs: "No pairs",
      priceAbove: "Price above",
      priceBelow: "Price below",
      signalGenerated: "Signal generated",
      global: "Global",
      noAlertRules: "No alert rules",
      enabled: "Enabled",
      contextTf: "Context TF",
      min24hVolume: "Min 24h volume",
      maxSpreadBps: "Max spread bps",
      minHistory: "Min history",
      minSrAtr: "Min S/R ATR",
      srStrength: "S/R strength",
      maxBodyAtr: "Max body ATR",
      maxRangeAtr: "Max range ATR",
      riskMode: "Risk mode",
      strategyRiskPercent: "Strategy risk %",
      riskPerTrade: "Risk / trade",
      fixedRisk: "Fixed risk",
      fixedCurrency: "Fixed currency",
      leverage: "Leverage",
      radarMode: "Radar mode",
      minRrExecutionReporting: "Min R:R for execution / reporting",
      rrTarget: "RR target",
      finalTarget: "Final target",
      nearestTarget: "Nearest target",
      rrGuard: "R:R guard",
      hideLowRrCards: "Hide low-RR cards",
      apply: "Apply",
      saveCustom: "Save custom",
      riskManagement: "Risk management",
      riskManagementSections: "Risk management sections",
      protectionLabel: "Protection:",
      closeOnly: "Close-only",
      daily: "Daily",
      weekly: "Weekly",
      drawdown: "Drawdown",
      openRiskShort: "Open",
      correlated: "Correlated",
      rules: "Rules",
      adaptiveMultiplier: "Adaptive x",
      executionProfile: "Execution profile",
      currency: "Currency",
      feesIncluded: "Fees included",
      slippageIncluded: "Slippage included",
      stopRequired: "Stop required",
      tpRequired: "TP required",
      spotRisk: "Spot risk",
      spotStopRequired: "Spot stop required",
      adaptiveRisk: "Adaptive risk",
      autoReduceAfterLosses: "Auto reduce after losses",
      allowRiskIncrease: "Allow risk increase",
      maxRiskBoost: "Max risk boost",
      rrGuardPolicy: "R:R guard policy",
      stopLoss: "Stop-loss",
      takeProfit: "Take-profit",
      riskMultiple: "Risk multiple",
      partialTakeProfit: "Partial take-profit",
      breakeven: "Breakeven",
      trailingStop: "Trailing stop",
      strategyMultipliers: "Strategy multipliers",
      riskMultiplier: "Risk multiplier",
      liquidationBufferRequired: "Liquidation buffer required",
      futuresRiskBudget: "Futures risk budget",
      futuresLiquidationBufferRequired: "Futures liquidation buffer required",
      virtualRiskBudget: "Virtual risk budget",
      virtualExecution: "Virtual execution",
      realisticExecution: "Realistic execution",
      balancedDefaultSafety: "Balanced is the default profile. Limits reduce risk exposure but cannot guarantee safety.",
      simulation: "Simulation",
      universeSize: "Universe size",
      liquidityTier: "Liquidity tier",
      symbol: "Symbol",
      turnover24h: "24h turnover",
      spreadBps: "Spread bps",
      funding: "Funding",
      rank: "Rank",
      riskGuideTitle: "How to configure risk management",
      riskGuideIntro: "Backend checks allowed risk, position size, margin, and blocker reasons before entry.",
      currentProfile: "Current profile",
      riskGuideBlockedTitle: "If no trade opens",
      riskGuideBlocked1: "Check Open risk in the status row. If it is above the limit, close old virtual positions or temporarily raise Open risk cap in Custom.",
      riskGuideBlocked2: "Check Correlated risk. Multiple trades in one cluster and direction can block a new entry before the global limit.",
      riskGuideBlocked3: "For paper trading, enable Virtual Trading > Separate and set separate virtual risk, balance, and limits.",
      riskGuideBlocked4: "To disable a specific limit, set it to 0. The interface will show that limit as Off.",
      riskGuideBlocked5: "If R:R or price drift blocks execution, price has moved away from the signal. It is better to wait for a new signal than loosen all limits at once.",
      riskGuideBlocked6: "Change one field at a time and watch the risk card in Radar: backend should show passed, warning, or failed with the exact reason.",
      riskGuideRelaxTitle: "What can be relaxed for training",
      riskGuideRelax1: "Min R:R for execution / reporting: temporarily 1.5R instead of 2R for virtual.",
      riskGuideRelax2: "Open risk cap: higher when many virtual tests run in parallel.",
      riskGuideRelax3: "Correlated risk: higher when you deliberately test one sector.",
      riskGuideRelax4: "Virtual balance: closer to the real size of the training deposit.",
      timeframes: "Timeframes"
    },
    exchange: {
      noConnections: "No exchange connections",
      connection: "Exchange connection",
      connectionLabel: "Connection label",
      connectionEnvironment: "Connection environment",
      orderPlacementMode: "Order placement mode",
      apiKey: "API key",
      apiSecret: "API secret",
      apiPassphrase: "API passphrase",
      refreshBalance: "Refresh balance",
      accountEquity: "Account equity",
      equity: "Equity",
      available: "Available",
      availableBalance: "Available balance",
      walletBalance: "Wallet balance",
      snapshotAge: "Snapshot age {value}",
      ordersEnabled: "Orders enabled",
      orderPlacementDisabled: "Order placement disabled",
      orderPlacementDryRun: "Order placement dry-run",
      orderPlacementDryRunOrders: "Dry-run order intents",
      orderPlacementTestnetRealOrders: "Testnet real orders",
      orderPlacementMainnetSmallSize: "Mainnet small size",
      orderPlacementMainnetScaled: "Mainnet scaled",
      orderPlacementLive: "Order placement live",
      testnetLive: "Testnet live",
      testnetDryRun: "Testnet dry-run",
      mainnetLiveEnabled: "Mainnet live enabled",
      mainnetBlocked: "Mainnet blocked",
      noOrderSent: "No exchange order will be sent",
      liveSafetyPending: "Live safety pending"
    },
    risk: {
      profile: "Risk profile",
      riskPerTrade: "Risk / trade",
      openRisk: "Open risk",
      correlated: "Correlated",
      drawdown: "Drawdown",
      protection: "Protection",
      closeOnly: "Close-only",
      feesIncluded: "Fees included",
      slippageIncluded: "Slippage included",
      stopRequired: "Stop required",
      tpRequired: "TP required",
      riskMultiple: "Risk multiple",
      liquidationBufferRequired: "Liquidation buffer required"
    },
    execution: {
      real: "Real execution",
      virtual: "Virtual execution",
      confirmRealEntry: "Confirm real entry",
      availabilityBackendOwned: "Real execution availability is backend-owned. Confirm only sends the selected intent.",
      backendBlockersWarnings: "Backend blockers / warnings",
      noBlockers: "No blockers.",
      accountEquity: "Account equity",
      availableBalance: "Available balance",
      symbolSide: "Symbol / side",
      riskGate: "RiskGate",
      cancel: "Cancel",
      confirmReal: "Confirm real entry",
      dryRun: "Dry-run",
      submitted: "Submitted",
      partiallyFilled: "Partially filled",
      failed: "Failed"
    },
    toast: {
      entryZoneTouchedTitle: "Entry zone touched",
      entryZoneTouched: "{symbol} touched the entry zone at {price}",
      signalTouchedEntryZone: "Signal {signalId} touched the entry zone",
      takeProfitHitTitle: "{target} hit",
      takeProfitHit: "{pair} reached {target} at {price}",
      stopLossHitTitle: "SL hit",
      stopLossHit: "{pair} hit stop loss at {price}",
      tradeClosedTitle: "Trade closed",
      tradeClosed: "{symbol} {side} closed{pnl}",
      exchangeDisconnectedTitle: "Exchange disconnected",
      exchangeDisconnected: "{exchange} disconnected",
      exchangeDisconnectedReason: "{exchange} disconnected: {reason}",
      strategyInvalidationTitle: "Strategy invalidation",
      strategyInvalidated: "{symbol} strategy idea is invalidated"
    },
    reasonCodes: {
      filled: "Filled",
      partial_filled: "Partially filled",
      partially_filled: "Partially filled",
      dry_run: "Dry-run",
      rejected_virtual_execution: "Virtual execution rejected",
      backend_waiting_entry: "Backend trigger service is waiting for entry.",
      forming_candle: "Forming candle preview; execution waits for candle close",
      entry_candle_open_allowed: "Entry candle is open; trigger was confirmed on a closed candle",
      trigger_not_confirmed: "Trigger not confirmed",
      breakout_close_missing: "Breakout close is not confirmed",
      breakout_compression_missing: "Breakout requires prior compression",
      breakout_level_not_closed: "Breakout did not close outside the level",
      breakout_retest_required: "Breakout retest is required",
      liquidity_absorption_missing: "Liquidity sweep needs absorption confirmation",
      liquidity_oi_flush_missing: "Liquidity sweep needs OI flush confirmation",
      liquidity_reclaim_missing: "Liquidity reclaim close is missing",
      liquidity_sweep_level_missing: "Liquidity sweep level is missing",
      trend_chop_blocked: "Trend pullback is blocked by EMA200 chop",
      trend_htf_alignment_missing: "Trend pullback needs higher-timeframe alignment",
      trend_pullback_hold_missing: "Trend pullback needs hold, reclaim, or absorption",
      trend_structural_zone_missing: "Trend pullback structural zone is missing",
      strategy_eligibility_failed: "Strategy eligibility failed",
      strategy_eligibility_missing: "Strategy eligibility is missing",
      dedup_suppressed_by_better_signal: "Suppressed by a better same-direction signal",
      dedup_replaced_by_better_signal: "Replaced by a better same-direction signal",
      entry_zone_not_touched: "Entry zone was not touched",
      entry_zone_missed_wait_for_retest: "Entry zone was missed; waiting for retest",
      entry_zone_not_reached_wait_for_retest: "Entry zone was not reached; waiting for retest",
      virtual_execution_rejected: "Virtual execution rejected",
      temporary_execution_failure: "Temporary execution failure; waiting for fresh data",
      riskgate_rejected: "Risk gate rejected execution",
      deterministic_test_fill: "Deterministic test fill",
      insufficient_liquidity: "Insufficient liquidity",
      btc_risk_off: "BTC market context is risk-off",
      eth_risk_off: "ETH market context is risk-off",
      funding_extreme: "Funding is extreme for this direction",
      oi_unstable: "Open interest is unstable",
      spread_too_wide: "Spread is too wide",
      depth_insufficient: "Orderbook depth is insufficient",
      execution_depth_insufficient: "Execution depth is insufficient",
      market_data_missing: "Market data is missing",
      market_data_stale: "Market data is stale",
      market_data_missing_relaxed_fallback: "Market data is missing; relaxed paper fallback is active",
      market_data_stale_relaxed_fallback: "Market data is stale; relaxed paper fallback is active",
      orderbook_missing_relaxed_fallback: "Orderbook is missing; relaxed paper fallback is active",
      low_liquidity_not_allowed: "Low-liquidity instruments are blocked",
      low_liquidity_tier_relaxed_warning: "Low-liquidity tier warning",
      spread_above_1_percent_market_order_blocked: "Spread is above 1%; market order is blocked",
      spread_above_0_3_percent: "Spread is above 0.3%",
      position_above_20_percent_depth_0_5: "Position consumes more than 20% of 0.5% depth",
      position_above_50_percent_depth_1: "Position consumes more than 50% of 1% depth",
      position_above_30_percent_volume_5m: "Position consumes more than 30% of 5m volume",
      position_above_10_percent_volume_5m: "Position consumes more than 10% of 5m volume",
      expected_slippage_above_1_5_percent: "Expected slippage is above 1.5%",
      expected_slippage_above_0_5_percent: "Expected slippage is above 0.5%",
      requested_notional_above_safe_size: "Requested size is above the safe size",
      execution_quality_blocked: "Execution quality gate blocked the trade",
      risk_gate_blocked: "Risk gate blocked execution",
      risk_reward_below_minimum: "R:R is below the minimum",
      risk_reward_soft_warning: "R:R is below the soft warning threshold",
      edge_unknown: "Edge is unknown",
      edge_missing: "Edge profile is missing",
      edge_negative: "Edge is negative",
      insufficient_sample: "Insufficient sample size",
      trade_plan_incomplete: "Trade plan is incomplete",
      missing_entry_zone: "Entry zone is missing",
      missing_stop_loss: "Stop-loss is missing",
      missing_target: "Take-profit target is missing",
      rr_failed: "Risk/reward check failed",
      risk_profile_unavailable: "Risk profile is unavailable",
      kill_switch_stale_market_data: "Kill-switch paused execution because market data is stale",
      kill_switch_spread_too_wide: "Kill-switch paused execution because spread is too wide",
      kill_switch_slippage_too_high: "Kill-switch paused execution because slippage is too high",
      kill_switch_daily_loss_exceeded: "Kill-switch stopped execution after daily loss limit",
      kill_switch_drawdown_exceeded: "Kill-switch stopped execution after account drawdown",
      kill_switch_execution_rejections: "Kill-switch paused execution after too many rejections",
      kill_switch_consecutive_losses: "Kill-switch paused execution after consecutive losses",
      kill_switch_exchange_degraded: "Exchange health is degraded",
      kill_switch_external_kill: "Execution kill-switch is active",
      kill_switch_manual_unlock_required: "Manual unlock is required before execution can resume",
      execution_policy_rejected: "Execution policy rejected the action",
      execution_policy_limit: "Execution policy selected limit entry",
      execution_policy_market: "Execution policy selected market entry",
      late_entry_price_deviation_exceeded: "Late-entry price deviation is too high",
      late_entry_rr_below_min: "Late-entry R:R is below the minimum",
      late_entry_rr_recalculated: "Late-entry R:R was recalculated",
      late_entry_rr_recalculation_required: "Late-entry R:R recalculation is required",
      probe_entry_rr_recalculated: "Probe-entry R:R was recalculated",
      strategy_regime_incompatible: "Strategy is incompatible with the current market regime",
      no_trade_hard_block: "No-trade hard block is active",
      score_below_execution_threshold: "Score is below the execution threshold",
      status_not_execution_candidate: "Signal status does not allow this action",
      pending_entry_exists: "Pending entry already exists for this signal",
      pending_entry_requires_reconfirmation: "Pending entry requires reconfirmation",
      real_trading_disabled: "Real trading is disabled",
      real_trading_unlock_required: "Real trading requires explicit unlock",
      available_balance_unavailable: "Available balance is unavailable",
      max_account_drawdown_exceeded: "Account drawdown limit is exceeded",
      real_entries_disabled: "Real entries are disabled by the active risk protection state",
      virtual_entries_disabled: "Virtual entries are disabled by the active risk protection state",
      reduce_only_required: "Reduce-only mode is required by the active risk protection state",
      market_entry_price_moved_rr: "Market entry price moved far enough to invalidate R:R",
      take_profit_required: "Take-profit plan is required",
      margin_exceeds_balance: "Required margin exceeds available balance",
      position_size_below_exchange_min: "Position size is below exchange minimum order size",
      position_size_above_exchange_max: "Position size is above exchange maximum order size",
      position_notional_below_exchange_min: "Position notional is below exchange minimum notional",
      leverage_exceeds_exchange_max: "Leverage exceeds exchange maximum leverage",
      exchange_rules_missing: "Exchange instrument rules are missing",
      exchange_rules_stale: "Exchange instrument rules are stale",
      market_data_unavailable: "Market data is unavailable",
      market_data_incomplete: "Market data is incomplete",
      orderbook_unavailable: "Orderbook liquidity is unavailable",
      ticker_bid_ask_unavailable: "Ticker bid/ask is unavailable",
      spread_above_configured_max: "Spread is above the configured maximum",
      slippage_above_configured_max: "Expected slippage is above the configured maximum",
      execution_price_unavailable: "Execution price is unavailable",
      execution_slippage_limit_exceeded: "Execution slippage limit is exceeded",
      execution_spread_limit_exceeded: "Execution spread limit is exceeded",
      price_moved_from_signal_entry: "Price moved too far from the signal entry",
      orderbook_vwap_slippage_above_max: "Orderbook VWAP slippage is above the configured maximum",
      risk_limit_exceeded: "Risk per trade exceeds the adjusted risk limit",
      spot_position_size_exceeds_max: "Spot position size exceeds the configured maximum",
      orderbook_liquidity_unavailable: "Orderbook liquidity is unavailable",
      orderbook_liquidity_empty: "Orderbook liquidity is empty for the entry side",
      orderbook_liquidity_insufficient: "Orderbook liquidity is insufficient for calculated position size",
      orderbook_depth_cannot_fill: "Orderbook depth cannot fill calculated position size",
      visible_orderbook_depth_half_consumed: "Calculated position would consume more than half of visible orderbook depth",
      daily_loss_limit_exceeded: "Daily loss limit would be exceeded",
      max_open_risk_exceeded: "Max open risk would be exceeded",
      max_symbol_risk_exceeded: "Max symbol risk would be exceeded",
      max_strategy_exposure_exceeded: "Max strategy exposure would be exceeded",
      max_correlated_risk_exceeded: "Max correlated risk would be exceeded",
      max_concurrent_positions_exceeded: "Max concurrent position count is reached",
      max_strategy_losses_per_day_exceeded: "Max strategy losses per day is reached",
      signal_score_below_minimum: "Signal score is below the minimum tradable threshold",
      signal_virtual_only_real_blocked: "Signal score is virtual-only; real execution is blocked",
      risk_protection_blocked: "Risk protection mode blocks new entries",
      risk_protection_virtual_only: "Risk protection mode allows virtual trading only",
      risk_protection_reduced: "Risk protection mode reduced the current risk multiplier",
      signal_edge_unknown: "Signal edge is unknown",
      signal_edge_insufficient_sample: "Signal edge has insufficient sample size",
      signal_edge_negative: "Signal edge is negative",
      signal_expectancy_below_minimum: "Signal expectancy after costs is below the minimum",
      leverage_above_max: "Requested leverage exceeds max leverage",
      liquidation_price_unavailable: "Liquidation price is unavailable",
      liquidation_before_stop: "Liquidation may happen before stop-loss",
      liquidation_buffer_below_minimum: "Liquidation buffer is below the configured minimum",
      futures_risk_passed: "Futures leverage and liquidation checks passed",
      futures_risk_blocked: "Futures risk checks blocked the trade",
      futures_liquidation_buffer_required: "Futures liquidation buffer is required",
      futures_liquidation_before_stop: "Futures liquidation would occur before stop-loss",
      exchange_connection_required: "Real execution requires an exchange connection",
      exchange_connection_forbidden: "Exchange connection belongs to another user",
      exchange_connection_not_found: "Exchange connection is not found",
      exchange_connection_exchange_mismatch: "Exchange connection does not match the signal exchange",
      exchange_connection_inactive: "Exchange connection is not active",
      exchange_credentials_unavailable: "Exchange credentials are unavailable",
      bybit_api_credentials_required: "Bybit API credentials are required",
      protective_stop_required: "Protective stop is required",
      order_placement_disabled: "Order placement is disabled for this exchange connection",
      order_placement_dry_run: "Order placement mode is dry-run; no exchange order will be sent",
      live_safety_pending: "Live order placement is waiting for backend safety checks",
      exchange_adapter_unsupported: "Live order placement is not supported for this exchange",
      enable_live_trading_false: "Live trading is disabled in backend settings",
      enable_bybit_live_order_placement_false: "Bybit live order placement is disabled in backend settings",
      enable_bybit_mainnet_order_placement_false: "Bybit mainnet order placement is disabled in backend settings",
      mainnet_connection_not_explicitly_enabled: "Mainnet live order placement requires explicit connection opt-in",
      real_trading_mode_disabled: "Real trading rollout mode is disabled",
      real_trading_dry_run_only: "Real trading rollout only permits dry-run order intents",
      real_trading_testnet_only: "Real trading rollout only permits testnet real orders",
      real_trading_mode_mismatch: "Exchange connection order mode does not match the configured rollout",
      mainnet_protective_stop_required: "Mainnet entry requires a protective stop",
      mainnet_kill_switch_not_healthy: "Mainnet entry requires a healthy kill-switch",
      mainnet_portfolio_risk_blocked: "Mainnet entry requires portfolio risk to pass",
      mainnet_calibration_not_positive: "Mainnet entry requires positive published calibration",
      mainnet_size_cap_exceeded: "Mainnet small-size rollout cap is exceeded",
      account_snapshot_unavailable: "Fresh exchange account snapshot is required",
      adapter_not_implemented: "Real execution adapter is not implemented",
      readiness_failed: "Real execution readiness failed",
      execution_plan_validation_failed: "Execution plan validation failed",
      live_protective_stop_required: "Live execution plan must include a protective stop before entry",
      live_take_profit_required: "Live execution plan must include take-profit orders before entry",
      live_protective_guarantee_required: "Live execution plan must use bracket/OCO/protective guarantee before entry",
      live_adapter_lacks_protective_guarantee: "Live adapter lacks bracket/OCO/protective guarantee",
      live_reduce_only_required: "Live adapter must support reduce-only protective orders",
      real_execution_dry_run: "Dry-run real execution plan built",
      real_execution_submitted: "Real execution adapter submitted the order plan",
      real_execution_partially_filled: "Real execution adapter returned a partial fill",
      real_execution_failed: "Real execution adapter returned a failed order placement result",
      real_pending_not_implemented: "Tick-driven real pending entry execution is not implemented",
      pending_entry_signal_missing: "Pending entry signal is missing",
      pending_entry_expired_before_touch: "Pending entry expired before entry touch",
      signal_terminal_at_trigger: "Signal is terminal at trigger time",
      signal_terminal: "Signal is terminal",
      pending_entry_material_change_requires_review: "Pending entry material change requires user review",
      pending_entry_live_signal_changed_no_material_impact: "Pending entry live signal changed without material execution-plan impact",
      trade_plan_reconfirmation_required: "Trade plan changed after acceptance; reconfirmation required",
      entry_zone_shifted: "Entry zone changed after acceptance",
      stop_loss_shifted: "Stop-loss changed after acceptance",
      take_profit_targets_shifted: "Take-profit targets changed after acceptance",
      risk_profile_restricted: "Risk profile changed materially after acceptance",
      triggered_pending_entry_missing_before_fill: "Triggered pending entry disappeared before fill",
      pending_real_trigger_not_enabled: "Tick-driven pending real execution is not enabled",
      cancelled_by_user: "Cancelled by user",
      pending_entry_reconfirmed: "Pending entry reconfirmed",
      no_backend_reason: "No reason from backend"
    }
  },
  ru: {
    navigation: {
      radar: "Радар",
      watchlist: "Watchlist",
      trades: "Сделки",
      settings: "Настройки",
      billing: "Биллинг"
    },
    common: {
      actions: "Действия",
      active: "Активные",
      add: "Добавить",
      all: "Все",
      allPairs: "Все пары",
      analytics: "Аналитика",
      balance: "Баланс",
      cancel: "Отмена",
      checking: "Проверка",
      close: "Закрыть",
      collapsed: "Свернуто",
      current: "Текущий",
      custom: "Свой",
      default: "По умолчанию",
      delete: "Удалить",
      disabled: "Выключено",
      enabled: "Включено",
      error: "Ошибка",
      exchange: "Биржа",
      history: "История",
      journal: "Журнал",
      loading: "Загрузка...",
      market: "Рынок",
      none: "Нет",
      no: "Нет",
      noData: "Нет данных",
      noExpiry: "Без срока",
      off: "Off",
      on: "On",
      open: "Открыть",
      openLower: "открыто",
      refresh: "Обновить",
      remove: "Удалить",
      save: "Сохранить",
      search: "Поиск",
      select: "Выбрать",
      sort: "Сортировка",
      status: "Статус",
      sync: "Синхронизировать",
      test: "Тест",
      unknown: "Неизвестно",
      updated: "Обновлено",
      warning: "Предупреждение",
      yes: "Да",
      emptyDash: "-"
    },
    commonErrors: {
      unknown: "Неизвестная ошибка",
      network: "Сетевой запрос не выполнен.",
      apiContract: "Ошибка API-контракта",
      signalRejectFailed: "Не удалось отклонить сигнал.",
      virtualTradeRejected: "Виртуальная сделка отклонена проверками качества исполнения.",
      realTradeRejected: "Реальная сделка отклонена защитными проверками исполнения.",
      pendingEntryRejected: "Ожидающий вход отклонен.",
      pendingEntryCancelFailed: "Не удалось отменить ожидающий вход.",
      pendingEntryReconfirmFailed: "Не удалось подтвердить ожидающий вход повторно.",
      pendingEntryUnavailable: "Этот сигнал недоступен для ожидающего входа.",
      onlyOpenIdeas: "Только открытые идеи стратегии можно поставить в ожидание или отправить в virtual trading.",
      marketPairNotFoundInUniverse: "Пара не найдена в локальном universe. Сначала синхронизируйте пары с биржи.",
      exchangeConnectionNotFound: "Подключение к бирже не найдено.",
      exchangeConnectionHasHistory: "Подключение связано с историческими ордерами или сделками, поэтому физическое удаление недоступно.",
      hardDeleteRequiresAdmin: "Физическое удаление доступно только внутреннему администратору."
    },
    navigationLabels: {
      appName: "Crypto Radar",
      signalFeed: "Лента сигналов",
      riskBalanced: "Риск: сбалансированный"
    },
    radar: {
      eyebrow: "Signal First Radar",
      title: "Рыночные возможности",
      marketStatus: "Статус рынка",
      executionReady: "Готово к исполнению",
      highConfidence: "Высокая уверенность",
      positiveEdge: "Положительный edge",
      blockedIdeas: "Заблокированные идеи",
      ticks: "Тики",
      strategyChecks: "Проверки стратегий",
      features: "Фичи",
      scanner: "сканер",
      riskGate: "RiskGate",
      score80: "score 80+",
      evGate: "EV gate",
      backend: "backend",
      marketData: "market data",
      evaluated: "проверено",
      candlesAnalyzed: "свечей проанализировано",
      online: "Online",
      offline: "Offline",
      scannerActivity: "Активность сканера",
      scannerLive: "Сканер live",
      scannerOffline: "Сканер offline",
      scannerDelayed: "Данные сканера задерживаются",
      scannerConnecting: "Подключается",
      scannerError: "Ошибка сканера",
      dataStale: "Данные устарели",
      waitingMarketData: "Ждем рыночные данные",
      warmupProgress: "Прогрев: {completed}/{total}, ошибок {failed}",
      lastTickAge: "Последний тик: {age}",
      noTicksYet: "тиков еще нет",
      justNow: "только что",
      lastError: "Последняя ошибка: {error}",
      signalsFound: "Сигналов найдено: {count}",
      seededCandles: "Свечей загружено: {count}",
      pairs: "Пары: {count}",
      universe: "Universe: {universe}",
      estimatedEvaluations: "Оценок ожидается: {count}",
      timeframes: "Таймфреймы: {timeframes}",
      warning: "Предупреждение: {warning}",
      candles: "{count} свечей",
      candleHistoryWarming: "История свечей еще прогревается",
      openIdeas: "открытые идеи",
      history: "история",
      allMarketOpportunities: "все рыночные возможности",
      executionReadyFilter: "готово к исполнению",
      allIdeasFilter: "Все идеи",
      watchlistFilter: "Watchlist",
      readyToExecuteFilter: "Готово к исполнению",
      blockedFilter: "Заблокировано",
      allFilter: "все",
      longFilter: "long",
      shortFilter: "short",
      noHistoricalSignals: "Истории сигналов пока нет",
      noMarketOpportunities: "Рыночных возможностей пока нет",
      historicalSignalsEmpty: "Отклоненные и истекшие идеи появятся здесь после переходов жизненного цикла.",
      marketOpportunitiesEmpty: "Сканер может еще строить историю свечей, или рынок пока не дал валидный setup."
    },
    signalDetails: {
      title: "Детали сигнала",
      emptyTitle: "Выберите сигнал",
      emptyBody: "Здесь появятся детали сигнала от backend.",
      missingTitle: "Сигнал больше не виден",
      missingBody: "Выбранный сигнал больше не отображается.",
      selectLatestSignal: "Выбрать последний сигнал",
      decision: "Решение",
      trigger: "Триггер",
      strategyEligibility: "Eligibility стратегии",
      deduplication: "Дедупликация",
      latestPendingEntryOutcome: "Последний исход pending-entry",
      recommendedAction: "Рекомендованное действие",
      canEnterNow: "Можно войти сейчас",
      topBlockers: "Главные блокеры",
      noActiveBlockers: "Активных блокеров из backend action-state нет.",
      tradePlan: "План сделки",
      entryType: "Тип входа",
      entryZonePrice: "Зона входа / цена",
      stopLoss: "Stop-loss",
      runner: "Runner",
      selectedRr: "Выбранный RR",
      invalidation: "Инвалидация",
      risk: "Риск",
      riskAmountPercent: "Сумма риска / %",
      marginLeverage: "Маржа / плечо",
      executionQuality: "Качество исполнения",
      whyThisSignal: "Почему этот сигнал?",
      actions: "Действия",
      executionEnvironment: "Среда исполнения: {environment}",
      noExchangeConnection: "Нет подключения к бирже",
      virtualWaitEntry: "Virtual wait entry",
      realWaitEntry: "Real wait entry",
      virtualEntryNow: "Virtual entry now",
      virtualEntryLocked: "Virtual entry locked",
      cancelWaiting: "Отменить ожидание",
      hideChart: "Скрыть график",
      openChart: "Открыть график",
      rejectIgnore: "Отклонить / игнорировать",
      tradingDisabled: "Торговые действия выключены, пока realtime-данные не актуальны.",
      diagnostics: "Диагностика",
      backendActionState: "Backend action state",
      signalStatus: "Статус сигнала",
      primaryAction: "Основное действие",
      canEnter: "Можно войти",
      canArmPending: "Можно поставить ожидание",
      canCancel: "Можно отменить",
      environment: "Среда",
      backendExecutionPreview: "Backend execution preview",
      qualityGate: "Quality gate",
      impactRisk: "Impact risk",
      requestedSize: "Запрошенный размер",
      filledSize: "Исполненный размер",
      entrySlippage: "Проскальзывание входа",
      slippageUnavailable: "slippage -",
      slippageBps: "slippage {value} bps",
      reason: "Причина",
      previewError: "Ошибка preview",
      previewLoading: "Backend execution preview загружается.",
      previewNotRequested: "Execution preview не запрошен.",
      notEvaluated: "не проверено",
      notPreviewed: "preview не было",
      yes: "да",
      no: "нет"
    },
    pendingEntry: {
      queueEyebrow: "Очередь ожидающих входов",
      selectedEntries: "Выбранные входы",
      activeCount: "{count} активных",
      loading: "Загружаем ожидающие входы",
      noActive: "Активных ожидающих входов нет",
      history: "История",
      noHistory: "Истории ожидающих входов нет",
      activePendingEntry: "Активный ожидающий вход",
      pendingEntry: "Ожидающий вход",
      historyTitle: "История ожидающего входа",
      state: "Состояние",
      status: "Статус",
      entryZone: "Зона входа",
      currentPrice: "Текущая цена",
      expires: "Истекает",
      expiryTtl: "Истечение / TTL",
      stop: "Стоп",
      mode: "Режим",
      acceptedStatus: "Принятый статус",
      reasonCode: "Код причины",
      reason: "Причина",
      updated: "Обновлено",
      selectSignal: "Выбрать сигнал",
      reconfirm: "Подтвердить",
      reconfirmPlan: "Подтвердить план",
      cancel: "Отменить",
      noBackendReason: "Backend не передал причину.",
      noReasonFromBackend: "Причина от backend отсутствует",
      noExpiry: "без срока",
      expired: "истекло",
      ttlUnknown: "TTL неизвестен",
      minutesLeft: "{count}м осталось",
      hoursLeft: "{count}ч осталось",
      realPendingUnavailable: "Real pending entry пока недоступен."
    },
    trades: {
      eyebrow: "Сделки",
      title: "Сделки и журнал",
      active: "Активные",
      journal: "Журнал",
      analytics: "Аналитика",
      balance: "Баланс",
      equity: "Equity",
      realizedPnl: "Realized PnL",
      openPositions: "Открытые позиции",
      riskPerTrade: "Риск {amount} на сделку",
      unrealized: "Нереализовано {amount}",
      unrealizedLabel: "Нереализовано",
      winLossBreakeven: "{wins}W / {losses}L / {breakeven}BE",
      rr: "RR 1:{value}",
      loadingTable: "Загружаем таблицу...",
      loadingAnalytics: "Загружаем аналитику...",
      loadingChart: "Загружаем график...",
      noActiveTrades: "Активных сделок нет",
      journalEmpty: "Журнал пуст",
      hit: "достигнут",
      pair: "Пара",
      mode: "Режим",
      executionShort: "Исп.",
      side: "Сторона",
      lifecycle: "Жизненный цикл",
      beMoved: "BE перенесен",
      trailing: "Трейлинг",
      entry: "Вход",
      takeProfit: "Take profit",
      stop: "Стоп",
      execution: "Исполнение",
      model: "Модель",
      remaining: "Остаток",
      remain: "Осталось",
      realized: "Реализовано",
      size: "Размер",
      partial: "Частично",
      impact: "Impact",
      passive: "Passive",
      closeMarket: "Закрыть по рынку",
      backtestCloseUnavailable: "Backtest-сделки нельзя закрыть из журнала",
      realCloseStub: "Закрытие real пока stub",
      keepStopLoss: "Оставить stop-loss",
      noCandleData: "Для этой сделки нет свечных данных",
      postImpact: "После impact",
      decay60s: "Decay 60s"
    },
    settings: {
      eyebrow: "Настройки",
      title: "Настройки радара",
      exchanges: "Биржи",
      exchangeConnections: "Подключения к биржам",
      connectionCount: "{count} подключ.",
      noExchangeConnections: "Нет подключений к биржам",
      strategies: "Стратегии",
      strategyCount: "{enabled}/{total} включено",
      strategyTesting: "Тестирование стратегий",
      backtestLab: "Backtest Lab",
      confirmMainnetLive: "Подтвердить mainnet live",
      mainnetLive: "Mainnet live",
      testnet: "Testnet",
      mainnet: "Mainnet",
      dryRun: "Dry-run",
      dryRunOrders: "Dry-run orders",
      testnetRealOrders: "Testnet real orders",
      mainnetSmallSize: "Mainnet small size",
      mainnetScaled: "Mainnet scaled",
      live: "Live",
      soft: "Soft",
      hard: "Hard",
      noStrategyConfigs: "Нет конфигов стратегий",
      activeOnly: "Только активные",
      allSetups: "Все setup",
      onlyActiveSetups: "Только активные setup",
      riskProfile: "Профиль риска",
      tradeRules: "Правила сделок",
      futuresProtection: "Защита futures",
      virtualTrading: "Virtual trading",
      guide: "Гайд",
      sync: "Синхронизировать",
      test: "Тест",
      softDelete: "soft delete",
      connect: "Подключить",
      deleteExchangeConnection: "Удалить подключение к бирже?",
      deleteExchangeConnectionBody: "Подключение {exchange} / {label} будет скрыто из активного списка. Исторические ордера и сделки останутся связаны с ним.",
      strategyPairs: "Торговые пары стратегии",
      selectedPairsCount: "Выбрано {count} пар",
      allPairsFromScannerUniverse: "Все пары из scanner universe",
      lastSync: "Последняя синхронизация: {value}",
      syncPairsFromExchange: "Синхронизировать пары с биржи",
      selectVisible: "Выбрать видимые",
      selectVisibleLimit: "Выбрать {limit} видимых",
      clear: "Очистить",
      noData: "нет данных",
      universeLoading: "Загрузка universe...",
      universeEmpty: "Нет пар в локальном universe. Синхронизируйте пары с биржи.",
      selectedLowLiquidityPairs: "Выбраны low-liquidity пары: {pairs}",
      universeLoadFailed: "Не удалось загрузить universe: {error}",
      universeSyncFailed: "Не удалось синхронизировать universe: {error}",
      selectPair: "Выбрать пару {symbol}",
      alerts: "Алерты",
      ruleCount: "{count} правил",
      alertPair: "Пара алерта",
      alertCondition: "Условие алерта",
      alertPrice: "Цена алерта",
      selectPairOption: "Выберите пару",
      noPairs: "Пар нет",
      priceAbove: "Цена выше",
      priceBelow: "Цена ниже",
      signalGenerated: "Сигнал создан",
      global: "Глобально",
      noAlertRules: "Нет правил алертов",
      enabled: "Включено",
      contextTf: "Контекст TF",
      min24hVolume: "Мин. объем 24ч",
      maxSpreadBps: "Макс. spread bps",
      minHistory: "Мин. история",
      minSrAtr: "Мин. S/R ATR",
      srStrength: "Сила S/R",
      maxBodyAtr: "Макс. тело ATR",
      maxRangeAtr: "Макс. диапазон ATR",
      riskMode: "Режим риска",
      strategyRiskPercent: "Риск стратегии %",
      riskPerTrade: "Риск / сделка",
      fixedRisk: "Фиксированный риск",
      fixedCurrency: "Валюта фикс. риска",
      leverage: "Плечо",
      radarMode: "Режим радара",
      minRrExecutionReporting: "Мин. R:R для исполнения / отчетности",
      rrTarget: "RR цель",
      finalTarget: "Финальная цель",
      nearestTarget: "Ближайшая цель",
      rrGuard: "R:R guard",
      hideLowRrCards: "Скрывать карточки с низким RR",
      apply: "Применить",
      saveCustom: "Сохранить custom",
      riskManagement: "Risk management",
      riskManagementSections: "Разделы risk management",
      protectionLabel: "Защита:",
      closeOnly: "Только закрытие",
      daily: "Дневной",
      weekly: "Недельный",
      drawdown: "Просадка",
      openRiskShort: "Открытый",
      correlated: "Корреляция",
      rules: "Правила",
      adaptiveMultiplier: "Адаптив x",
      executionProfile: "Профиль исполнения",
      currency: "Валюта",
      feesIncluded: "Комиссии учтены",
      slippageIncluded: "Slippage учтен",
      stopRequired: "Stop обязателен",
      tpRequired: "TP обязателен",
      spotRisk: "Spot риск",
      spotStopRequired: "Spot stop обязателен",
      adaptiveRisk: "Адаптивный риск",
      autoReduceAfterLosses: "Автоснижение после убытков",
      allowRiskIncrease: "Разрешить рост риска",
      maxRiskBoost: "Макс. boost риска",
      rrGuardPolicy: "Политика R:R guard",
      stopLoss: "Stop-loss",
      takeProfit: "Take-profit",
      riskMultiple: "Risk multiple",
      partialTakeProfit: "Частичный take-profit",
      breakeven: "Breakeven",
      trailingStop: "Trailing stop",
      strategyMultipliers: "Множители стратегий",
      riskMultiplier: "Множитель риска",
      liquidationBufferRequired: "Буфер ликвидации обязателен",
      futuresRiskBudget: "Бюджет futures риска",
      futuresLiquidationBufferRequired: "Futures буфер ликвидации обязателен",
      virtualRiskBudget: "Бюджет virtual риска",
      virtualExecution: "Virtual execution",
      realisticExecution: "Реалистичное исполнение",
      balancedDefaultSafety: "Balanced — профиль по умолчанию. Лимиты снижают риск, но не гарантируют безопасность.",
      simulation: "Симуляция",
      universeSize: "Размер universe",
      liquidityTier: "Liquidity tier",
      symbol: "Символ",
      turnover24h: "Оборот 24ч",
      spreadBps: "Spread bps",
      funding: "Funding",
      rank: "Ранг",
      riskGuideTitle: "Как настраивать risk management",
      riskGuideIntro: "Backend проверяет допустимый риск, размер позиции, маржу и причины блокировки перед входом.",
      currentProfile: "Текущий профиль",
      riskGuideBlockedTitle: "Если не открывается ни одна сделка",
      riskGuideBlocked1: "Проверьте Open risk в строке состояния. Если он выше лимита, закройте старые virtual-позиции или временно увеличьте Open risk cap в Custom.",
      riskGuideBlocked2: "Проверьте Correlated risk. Несколько сделок в одном кластере и направлении могут блокировать новый вход раньше общего лимита.",
      riskGuideBlocked3: "Для paper trading включите Virtual Trading > Separate и задайте отдельный virtual risk, balance и лимиты.",
      riskGuideBlocked4: "Чтобы выключить конкретный лимит, поставьте 0. В интерфейсе такой лимит будет показан как Off.",
      riskGuideBlocked5: "Если блокирует R:R или price drift, значит цена ушла от сигнала. Лучше дождаться нового сигнала, а не расширять все лимиты сразу.",
      riskGuideBlocked6: "Меняйте только одно поле за раз и смотрите на risk card в Radar: backend должен показать passed, warning или failed и точную причину.",
      riskGuideRelaxTitle: "Что можно ослабить для обучения",
      riskGuideRelax1: "Min R:R for execution / reporting: временно 1.5R вместо 2R для virtual.",
      riskGuideRelax2: "Open risk cap: выше, если на virtual много параллельных тестов.",
      riskGuideRelax3: "Correlated risk: выше, если вы сознательно тестируете один сектор.",
      riskGuideRelax4: "Virtual balance: ближе к реальному размеру учебного депозита.",
      timeframes: "Таймфреймы"
    },
    exchange: {
      noConnections: "Нет подключений к биржам",
      connection: "Подключение к бирже",
      connectionLabel: "Название подключения",
      connectionEnvironment: "Среда подключения",
      orderPlacementMode: "Режим выставления ордеров",
      apiKey: "API key",
      apiSecret: "API secret",
      apiPassphrase: "API passphrase",
      refreshBalance: "Обновить баланс",
      accountEquity: "Equity аккаунта",
      equity: "Equity",
      available: "Доступно",
      availableBalance: "Доступный баланс",
      walletBalance: "Баланс кошелька",
      snapshotAge: "Возраст snapshot: {value}",
      ordersEnabled: "Ордера включены",
      orderPlacementDisabled: "Выставление ордеров выключено",
      orderPlacementDryRun: "Выставление ордеров в dry-run",
      orderPlacementDryRunOrders: "Dry-run order intents",
      orderPlacementTestnetRealOrders: "Testnet real orders",
      orderPlacementMainnetSmallSize: "Mainnet small size",
      orderPlacementMainnetScaled: "Mainnet scaled",
      orderPlacementLive: "Выставление ордеров live",
      testnetLive: "Testnet live",
      testnetDryRun: "Testnet dry-run",
      mainnetLiveEnabled: "Mainnet live включен",
      mainnetBlocked: "Mainnet заблокирован",
      noOrderSent: "Ордер на биржу не будет отправлен",
      liveSafetyPending: "Live safety pending"
    },
    risk: {
      profile: "Профиль риска",
      riskPerTrade: "Risk / trade",
      openRisk: "Open risk",
      correlated: "Correlated",
      drawdown: "Drawdown",
      protection: "Protection",
      closeOnly: "Close-only",
      feesIncluded: "Комиссии учтены",
      slippageIncluded: "Slippage учтен",
      stopRequired: "Стоп обязателен",
      tpRequired: "TP обязателен",
      riskMultiple: "Risk multiple",
      liquidationBufferRequired: "Буфер ликвидации обязателен"
    },
    execution: {
      real: "Реальное исполнение",
      virtual: "Виртуальное исполнение",
      confirmRealEntry: "Подтверждение реального входа",
      availabilityBackendOwned: "Доступность real execution контролирует backend. Подтверждение отправляет только выбранный intent.",
      backendBlockersWarnings: "Backend blockers / warnings",
      noBlockers: "Блокеров нет.",
      accountEquity: "Equity аккаунта",
      availableBalance: "Доступный баланс",
      symbolSide: "Символ / сторона",
      riskGate: "RiskGate",
      cancel: "Отмена",
      confirmReal: "Подтвердить реальный вход",
      dryRun: "Dry-run",
      submitted: "Отправлено",
      partiallyFilled: "Частично исполнено",
      failed: "Ошибка"
    },
    toast: {
      entryZoneTouchedTitle: "Зона входа задета",
      entryZoneTouched: "{symbol} коснулся зоны входа по {price}",
      signalTouchedEntryZone: "Сигнал {signalId} коснулся зоны входа",
      takeProfitHitTitle: "{target} достигнут",
      takeProfitHit: "{pair} дошел до {target} по {price}",
      stopLossHitTitle: "SL сработал",
      stopLossHit: "{pair} задел stop loss по {price}",
      tradeClosedTitle: "Сделка закрыта",
      tradeClosed: "{symbol} {side} закрыт{pnl}",
      exchangeDisconnectedTitle: "Биржа отключилась",
      exchangeDisconnected: "{exchange} отключилась",
      exchangeDisconnectedReason: "{exchange} отключилась: {reason}",
      strategyInvalidationTitle: "Инвалидация стратегии",
      strategyInvalidated: "{symbol} идея стратегии инвалидирована"
    },
    reasonCodes: {
      filled: "Исполнено",
      partial_filled: "Частично исполнено",
      partially_filled: "Частично исполнено",
      dry_run: "Dry-run",
      rejected_virtual_execution: "Виртуальное исполнение отклонено",
      backend_waiting_entry: "Backend ждёт касания зоны входа.",
      forming_candle: "Свеча еще формируется; исполнение ждет закрытия",
      entry_candle_open_allowed: "Свеча входа еще открыта; триггер подтвержден закрытой свечой",
      trigger_not_confirmed: "Триггер не подтвержден",
      breakout_close_missing: "Закрытие breakout не подтверждено",
      breakout_compression_missing: "Breakout требует предварительного сжатия",
      breakout_level_not_closed: "Breakout не закрылся за уровнем",
      breakout_retest_required: "Требуется ретест breakout",
      liquidity_absorption_missing: "Снятию ликвидности нужно подтверждение absorption",
      liquidity_oi_flush_missing: "Снятию ликвидности нужно подтверждение OI flush",
      liquidity_reclaim_missing: "Нет закрытия reclaim после снятия ликвидности",
      liquidity_sweep_level_missing: "Уровень снятия ликвидности отсутствует",
      trend_chop_blocked: "Trend pullback заблокирован EMA200 chop",
      trend_htf_alignment_missing: "Trend pullback требует HTF alignment",
      trend_pullback_hold_missing: "Trend pullback требует hold, reclaim или absorption зоны",
      trend_structural_zone_missing: "Структурная зона trend pullback отсутствует",
      strategy_eligibility_failed: "Стратегия не прошла eligibility-проверку",
      strategy_eligibility_missing: "Eligibility стратегии отсутствует",
      dedup_suppressed_by_better_signal: "Подавлено более сильным сигналом в том же направлении",
      dedup_replaced_by_better_signal: "Заменено более сильным сигналом в том же направлении",
      entry_zone_not_touched: "Зона входа не была затронута",
      virtual_execution_rejected: "Виртуальное исполнение отклонено",
      temporary_execution_failure: "Временная ошибка исполнения; ждем свежие данные",
      riskgate_rejected: "Risk gate отклонил исполнение",
      deterministic_test_fill: "Детерминированное тестовое исполнение",
      insufficient_liquidity: "Недостаточно ликвидности",
      btc_risk_off: "BTC в режиме risk-off",
      eth_risk_off: "ETH в режиме risk-off",
      funding_extreme: "Фандинг экстремален для этого направления",
      oi_unstable: "Open interest нестабилен",
      spread_too_wide: "Спред слишком широкий",
      depth_insufficient: "Глубина стакана недостаточна",
      market_data_missing: "Рыночные данные отсутствуют",
      market_data_stale: "Рыночные данные устарели",
      market_data_missing_relaxed_fallback: "Рыночные данные отсутствуют; включен relaxed paper fallback",
      market_data_stale_relaxed_fallback: "Рыночные данные устарели; включен relaxed paper fallback",
      orderbook_missing_relaxed_fallback: "Стакан отсутствует; включен relaxed paper fallback",
      low_liquidity_not_allowed: "Инструменты с низкой ликвидностью заблокированы",
      low_liquidity_tier_relaxed_warning: "Предупреждение по low-liquidity tier",
      spread_above_1_percent_market_order_blocked: "Spread выше 1%; market-ордер заблокирован",
      spread_above_0_3_percent: "Spread выше 0.3%",
      position_above_20_percent_depth_0_5: "Позиция занимает больше 20% глубины 0.5%",
      position_above_50_percent_depth_1: "Позиция занимает больше 50% глубины 1%",
      position_above_30_percent_volume_5m: "Позиция занимает больше 30% объема за 5 минут",
      position_above_10_percent_volume_5m: "Позиция занимает больше 10% объема за 5 минут",
      expected_slippage_above_1_5_percent: "Ожидаемый slippage выше 1.5%",
      expected_slippage_above_0_5_percent: "Ожидаемый slippage выше 0.5%",
      requested_notional_above_safe_size: "Запрошенный размер выше безопасного",
      execution_quality_blocked: "Quality gate исполнения заблокировал сделку",
      risk_gate_blocked: "Risk gate заблокировал исполнение",
      risk_reward_below_minimum: "R:R ниже минимума",
      risk_reward_soft_warning: "R:R ниже порога soft warning",
      edge_unknown: "Edge неизвестен",
      edge_missing: "Edge-профиль отсутствует",
      edge_negative: "Edge отрицательный",
      insufficient_sample: "Недостаточный размер выборки",
      trade_plan_incomplete: "План сделки неполный",
      missing_entry_zone: "Зона входа отсутствует",
      missing_stop_loss: "Stop-loss отсутствует",
      missing_target: "Цель take-profit отсутствует",
      rr_failed: "Проверка risk/reward не пройдена",
      risk_profile_unavailable: "Risk profile недоступен",
      kill_switch_stale_market_data: "Kill-switch остановил исполнение из-за устаревших данных",
      kill_switch_spread_too_wide: "Kill-switch остановил исполнение из-за широкого спреда",
      kill_switch_slippage_too_high: "Kill-switch остановил исполнение из-за высокого slippage",
      kill_switch_daily_loss_exceeded: "Kill-switch остановил исполнение после дневного лимита убытка",
      kill_switch_drawdown_exceeded: "Kill-switch остановил исполнение после лимита просадки",
      kill_switch_execution_rejections: "Kill-switch остановил исполнение после частых отклонений",
      kill_switch_consecutive_losses: "Kill-switch остановил исполнение после серии убытков",
      kill_switch_exchange_degraded: "Состояние биржи degraded",
      kill_switch_external_kill: "Execution kill-switch активен",
      kill_switch_manual_unlock_required: "Перед возобновлением нужен manual unlock",
      execution_policy_rejected: "Execution policy отклонила действие",
      strategy_regime_incompatible: "Стратегия несовместима с текущим рыночным режимом",
      no_trade_hard_block: "Активен жесткий no-trade блок",
      score_below_execution_threshold: "Скор ниже порога исполнения",
      status_not_execution_candidate: "Статус сигнала не разрешает это действие",
      pending_entry_exists: "Pending entry уже существует для этого сигнала",
      pending_entry_requires_reconfirmation: "Pending entry требует повторного подтверждения",
      real_trading_disabled: "Real trading выключен",
      real_trading_unlock_required: "Real trading требует явного unlock",
      available_balance_unavailable: "Доступный баланс недоступен",
      max_account_drawdown_exceeded: "Лимит просадки аккаунта превышен",
      real_entries_disabled: "Real-входы выключены активным состоянием защиты риска",
      virtual_entries_disabled: "Virtual-входы выключены активным состоянием защиты риска",
      reduce_only_required: "Активная защита риска требует reduce-only режим",
      market_entry_price_moved_rr: "Рыночная цена входа ушла настолько, что R:R стал невалидным",
      take_profit_required: "План take-profit обязателен",
      margin_exceeds_balance: "Требуемая маржа выше доступного баланса",
      position_size_below_exchange_min: "Размер позиции ниже минимального размера ордера биржи",
      position_size_above_exchange_max: "Размер позиции выше максимального размера ордера биржи",
      position_notional_below_exchange_min: "Номинал позиции ниже минимального номинала биржи",
      leverage_exceeds_exchange_max: "Плечо выше максимума биржи",
      exchange_rules_missing: "Правила инструмента биржи отсутствуют",
      exchange_rules_stale: "Правила инструмента биржи устарели",
      market_data_unavailable: "Рыночные данные недоступны",
      market_data_incomplete: "Рыночные данные неполные",
      orderbook_unavailable: "Ликвидность стакана недоступна",
      ticker_bid_ask_unavailable: "Bid/ask тикера недоступны",
      spread_above_configured_max: "Spread выше заданного максимума",
      slippage_above_configured_max: "Ожидаемый slippage выше заданного максимума",
      price_moved_from_signal_entry: "Цена слишком далеко ушла от входа сигнала",
      orderbook_vwap_slippage_above_max: "Orderbook VWAP slippage выше заданного максимума",
      risk_limit_exceeded: "Риск на сделку выше скорректированного лимита",
      spot_position_size_exceeds_max: "Размер spot-позиции выше заданного максимума",
      orderbook_liquidity_unavailable: "Ликвидность стакана недоступна",
      orderbook_liquidity_empty: "Ликвидность стакана пуста на стороне входа",
      orderbook_liquidity_insufficient: "Ликвидности стакана недостаточно для рассчитанной позиции",
      orderbook_depth_cannot_fill: "Глубина стакана не может исполнить рассчитанную позицию",
      visible_orderbook_depth_half_consumed: "Позиция использует больше половины видимой глубины стакана",
      daily_loss_limit_exceeded: "Дневной лимит убытка будет превышен",
      max_open_risk_exceeded: "Лимит открытого риска будет превышен",
      max_correlated_risk_exceeded: "Лимит коррелированного риска будет превышен",
      signal_score_below_minimum: "Скор сигнала ниже минимального торгового порога",
      signal_virtual_only_real_blocked: "Сигнал virtual-only; real execution заблокирован",
      risk_protection_blocked: "Режим защиты риска блокирует новые входы",
      risk_protection_virtual_only: "Режим защиты риска разрешает только virtual trading",
      risk_protection_reduced: "Режим защиты риска снизил текущий множитель риска",
      signal_edge_unknown: "Edge сигнала неизвестен",
      signal_edge_insufficient_sample: "Недостаточный размер выборки для edge сигнала",
      signal_edge_negative: "Edge сигнала отрицательный",
      signal_expectancy_below_minimum: "Ожидание сигнала после издержек ниже минимума",
      leverage_above_max: "Запрошенное плечо выше максимального",
      liquidation_price_unavailable: "Цена ликвидации недоступна",
      liquidation_before_stop: "Ликвидация может произойти раньше stop-loss",
      liquidation_buffer_below_minimum: "Буфер ликвидации ниже заданного минимума",
      futures_risk_passed: "Проверки плеча и ликвидации пройдены",
      futures_risk_blocked: "Проверки futures-риска заблокировали сделку",
      futures_liquidation_buffer_required: "Требуется буфер ликвидации futures",
      futures_liquidation_before_stop: "Ликвидация futures может произойти раньше stop-loss",
      exchange_connection_required: "Для real execution нужно подключение к бирже",
      exchange_connection_forbidden: "Подключение к бирже принадлежит другому пользователю",
      exchange_connection_not_found: "Подключение к бирже не найдено",
      exchange_connection_exchange_mismatch: "Подключение к бирже не совпадает с биржей сигнала",
      exchange_connection_inactive: "Подключение к бирже не активно",
      exchange_credentials_unavailable: "Биржевые credentials недоступны",
      bybit_api_credentials_required: "Нужны Bybit API credentials",
      protective_stop_required: "Protective stop обязателен",
      order_placement_disabled: "Выставление ордеров выключено для этого подключения",
      order_placement_dry_run: "Режим выставления ордеров dry-run; ордер на биржу не будет отправлен",
      live_safety_pending: "Live-выставление ордеров ожидает backend safety-проверки",
      exchange_adapter_unsupported: "Live order placement не поддерживается для этой биржи",
      enable_live_trading_false: "Live trading выключен в backend-настройках",
      enable_bybit_live_order_placement_false: "Bybit live order placement выключен в backend-настройках",
      enable_bybit_mainnet_order_placement_false: "Bybit mainnet order placement выключен в backend-настройках",
      mainnet_connection_not_explicitly_enabled: "Для mainnet live order placement нужно явное подтверждение подключения",
      real_trading_mode_disabled: "Real trading rollout выключен",
      real_trading_dry_run_only: "Real trading rollout разрешает только dry-run order intents",
      real_trading_testnet_only: "Real trading rollout разрешает только testnet real orders",
      real_trading_mode_mismatch: "Режим подключения не совпадает с настроенным rollout",
      mainnet_protective_stop_required: "Для mainnet entry нужен protective stop",
      mainnet_kill_switch_not_healthy: "Для mainnet entry kill-switch должен быть healthy",
      mainnet_portfolio_risk_blocked: "Для mainnet entry portfolio risk должен пройти",
      mainnet_calibration_not_positive: "Для mainnet entry нужна positive calibration",
      mainnet_size_cap_exceeded: "Превышен mainnet small-size cap",
      account_snapshot_unavailable: "Нужен свежий снимок биржевого аккаунта",
      adapter_not_implemented: "Адаптер real execution не реализован",
      readiness_failed: "Readiness real execution не пройдена",
      execution_plan_validation_failed: "План исполнения не прошел валидацию",
      live_protective_stop_required: "Live-план должен включать protective stop до входа",
      live_take_profit_required: "Live-план должен включать take-profit ордера до входа",
      live_protective_guarantee_required: "Live-план должен использовать bracket/OCO/protective guarantee до входа",
      live_adapter_lacks_protective_guarantee: "Live-адаптер не дает bracket/OCO/protective guarantee",
      live_reduce_only_required: "Live-адаптер должен поддерживать reduce-only protective orders",
      real_execution_dry_run: "Dry-run план real execution построен",
      real_execution_submitted: "Адаптер real execution отправил план ордеров",
      real_execution_partially_filled: "Адаптер real execution вернул частичное исполнение",
      real_execution_failed: "Адаптер real execution вернул ошибку выставления ордера",
      real_pending_not_implemented: "Tick-driven real pending entry пока не реализован",
      pending_entry_signal_missing: "Сигнал ожидающего входа отсутствует",
      pending_entry_expired_before_touch: "Ожидающий вход истек до касания зоны входа",
      signal_terminal_at_trigger: "Сигнал стал terminal в момент trigger",
      signal_terminal: "Сигнал terminal",
      pending_entry_material_change_requires_review: "Ожидающий вход требует review из-за изменения плана",
      pending_entry_live_signal_changed_no_material_impact: "Live-сигнал изменился без material impact на план исполнения",
      trade_plan_reconfirmation_required: "План сделки изменился после принятия; нужно повторное подтверждение",
      entry_zone_shifted: "Зона входа изменилась после принятия",
      stop_loss_shifted: "Stop-loss изменился после принятия",
      take_profit_targets_shifted: "Take-profit цели изменились после принятия",
      risk_profile_restricted: "Профиль риска существенно изменился после принятия",
      triggered_pending_entry_missing_before_fill: "Triggered pending entry исчез до fill",
      pending_real_trigger_not_enabled: "Tick-driven pending real execution не включен",
      cancelled_by_user: "Отменено пользователем",
      pending_entry_reconfirmed: "Ожидающий вход подтвержден повторно",
      no_backend_reason: "Причина от backend отсутствует"
    }
  }
} as const satisfies Record<DictionaryLocale, TranslationTree>;

export type I18nKey = DotKeys<typeof typedDictionary.en>;
export type ReasonCode = keyof typeof typedDictionary.en.reasonCodes;
export const REASON_CODE_KEYS = Object.keys(typedDictionary.en.reasonCodes) as ReasonCode[];

const reasonCodeAliases: Record<string, ReasonCode> = {
  "accepted pending-entry request snapshot is invalid": "pending_entry_signal_missing",
  "account snapshot unavailable": "account_snapshot_unavailable",
  "bybit market data is stale": "market_data_stale",
  "bybit market data is unavailable": "market_data_unavailable",
  "bybit market data is incomplete": "market_data_incomplete",
  "calculated position would consume more than half of visible orderbook depth": "visible_orderbook_depth_half_consumed",
  "cancelled by user": "cancelled_by_user",
  "daily loss limit would be exceeded": "daily_loss_limit_exceeded",
  "exchange account equity is missing": "account_snapshot_unavailable",
  "exchange available balance is insufficient": "account_snapshot_unavailable",
  "exchange connection belongs to another user": "exchange_connection_forbidden",
  "exchange connection does not match the signal exchange": "exchange_connection_exchange_mismatch",
  "exchange connection is invalid": "exchange_connection_not_found",
  "exchange connection is not active": "exchange_connection_inactive",
  "exchange connection is not found": "exchange_connection_not_found",
  "exchange instrument rules are missing": "exchange_rules_missing",
  "exchange instrument rules are stale": "exchange_rules_stale",
  "expected slippage is above the configured maximum": "slippage_above_configured_max",
  "fresh account risk snapshot is required for real riskgate context": "account_snapshot_unavailable",
  "fresh exchange account snapshot is required before live entry": "account_snapshot_unavailable",
  "leverage exceeds exchange maximum leverage": "leverage_exceeds_exchange_max",
  "live adapter lacks bracket/oco/protective guarantee": "live_adapter_lacks_protective_guarantee",
  "live adapter must support reduce-only protective orders": "live_reduce_only_required",
  "live entry requires source=exchange account snapshot": "account_snapshot_unavailable",
  "live execution plan must include a protective stop before entry": "live_protective_stop_required",
  "live execution plan must include take-profit orders before entry": "live_take_profit_required",
  "live execution plan must use bracket/oco/protective guarantee before entry": "live_protective_guarantee_required",
  "market entry price moved far enough to invalidate r:r": "market_entry_price_moved_rr",
  "max correlated risk would be exceeded": "max_correlated_risk_exceeded",
  "max open risk would be exceeded": "max_open_risk_exceeded",
  "orderbook depth cannot fill calculated position size": "orderbook_depth_cannot_fill",
  "orderbook liquidity is empty for the entry side": "orderbook_liquidity_empty",
  "orderbook liquidity is insufficient for calculated position size": "orderbook_liquidity_insufficient",
  "orderbook liquidity is unavailable": "orderbook_liquidity_unavailable",
  "orderbook vwap slippage is above the configured maximum": "orderbook_vwap_slippage_above_max",
  "pending entry intent expired before entry touch": "pending_entry_expired_before_touch",
  "pending entry material change requires user review": "pending_entry_material_change_requires_review",
  "pending entry signal is missing": "pending_entry_signal_missing",
  "position notional is below exchange minimum notional": "position_notional_below_exchange_min",
  "position size is above exchange maximum order size": "position_size_above_exchange_max",
  "position size is below exchange minimum order size": "position_size_below_exchange_min",
  "price moved too far from the signal entry": "price_moved_from_signal_entry",
  "required margin exceeds available balance": "margin_exceeds_balance",
  "risk per trade exceeds the adjusted risk limit": "risk_limit_exceeded",
  "signal edge has insufficient sample size for real execution": "signal_edge_insufficient_sample",
  "signal edge is negative; real execution is blocked": "signal_edge_negative",
  "signal edge is unknown; real execution requires positive historical edge": "signal_edge_unknown",
  "signal expectancy after costs is below the configured minimum": "signal_expectancy_below_minimum",
  "signal score is below the minimum tradable threshold": "signal_score_below_minimum",
  "signal score is virtual-only; real execution is blocked": "signal_virtual_only_real_blocked",
  "spread is above the configured maximum": "spread_above_configured_max",
  "spot position size exceeds the configured maximum": "spot_position_size_exceeds_max",
  "take-profit plan is required": "take_profit_required",
  "ticker bid/ask is unavailable": "ticker_bid_ask_unavailable",
  "tick-driven pending real execution is not enabled in this virtual trigger service": "pending_real_trigger_not_enabled",
  "tick-driven real pending entry execution is not implemented": "real_pending_not_implemented",
  "trade plan changed after acceptance; reconfirmation required": "trade_plan_reconfirmation_required",
  "triggered pending entry intent disappeared before fill": "triggered_pending_entry_missing_before_fill"
};

const phrases: Record<string, TranslationMap> = Object.assign({
  "Account access": { ru: "Доступ к аккаунту", zh: "账户访问" },
  "Account drawdown": { ru: "Просадка аккаунта", zh: "账户回撤" },
  "Actions": { ru: "Действия", zh: "操作" },
  "Active": { ru: "Активные", zh: "活跃" },
  "Active Pending Entry": { ru: "Активное ожидание входа", zh: "活跃挂起入场" },
  "Active Signals": { ru: "Активные сигналы", zh: "活跃信号" },
  "Add": { ru: "Добавить", zh: "添加" },
  "Adjusted risk": { ru: "Скорректированный риск", zh: "调整后风险" },
  "Advanced": { ru: "Расширенный", zh: "高级" },
  "Aggressive": { ru: "Агрессивный", zh: "激进" },
  "All": { ru: "Все", zh: "全部" },
  "All market opportunities": { ru: "Все market opportunities", zh: "全部市场机会" },
  "All pairs": { ru: "Все пары", zh: "全部交易对" },
  "All pairs - quality filter on": { ru: "Все пары, фильтр качества включен", zh: "全部交易对，质量过滤已开启" },
  "All seeded pairs added": { ru: "Все загруженные пары добавлены", zh: "已添加全部预置交易对" },
  "All tiers": { ru: "Все tier", zh: "全部等级" },
  "Allowed": { ru: "Разрешён", zh: "允许" },
  "Available balance": { ru: "Доступный баланс", zh: "可用余额" },
  "Not realistic": { ru: "Нереалистично", zh: "不现实" },
  "Analytics": { ru: "Аналитика", zh: "分析" },
  "API key": { ru: "API-ключ", zh: "API 密钥" },
  "API passphrase": { ru: "API passphrase", zh: "API 口令" },
  "API secret": { ru: "API-секрет", zh: "API 私钥" },
  "Auto Entry": { ru: "Автовход", zh: "自动入场" },
  "Auto Paper": { ru: "Авто Paper", zh: "自动 Paper" },
  "Auto Paper Armed": { ru: "Auto Paper взведён", zh: "自动 Paper 已布置" },
  "Auto reduce after losses": { ru: "Снижать риск после убытков", zh: "亏损后自动降低风险" },
  "Accepted status": { ru: "Принятый статус", zh: "已接受状态" },
  "Automatic quality filter excludes bad instruments before strategy setup.": {
    ru: "Автоматический фильтр качества исключает слабые инструменты до проверки стратегии.",
    zh: "自动质量过滤会在策略 setup 前排除较差标的。"
  },
  "Balance": { ru: "Баланс", zh: "余额" },
  "Balanced": { ru: "Сбалансированный", zh: "均衡" },
  "Balanced is the default profile. Limits reduce risk exposure but cannot guarantee safety.": {
    ru: "Сбалансированный профиль используется по умолчанию. Лимиты снижают риск, но не гарантируют безопасность.",
    zh: "均衡是默认配置。限制会降低风险敞口，但不能保证安全。"
  },
  "BB squeeze %": { ru: "BB squeeze %", zh: "布林收缩 %" },
  "Bid / Ask": { ru: "Bid / Ask", zh: "买一 / 卖一" },
  "Billing": { ru: "Биллинг", zh: "账单" },
  "Book depth": { ru: "Глубина стакана", zh: "盘口深度" },
  "Breakout Entries": { ru: "Входы на breakout", zh: "突破入场" },
  "Breakeven": { ru: "Безубыток", zh: "保本" },
  "Browser": { ru: "Браузер", zh: "浏览器" },
  "Candles": { ru: "Свечи", zh: "K线" },
  "Candle history is still warming up": { ru: "История свечей ещё прогревается", zh: "K线历史仍在预热" },
  "candles analyzed": { ru: "свечей проанализировано", zh: "已分析K线" },
  "Can enter now": { ru: "Можно входить сейчас", zh: "现在可入场" },
  "Cancel waiting": { ru: "Отменить ожидание", zh: "取消等待" },
  "Chart": { ru: "График", zh: "图表" },
  "Checking": { ru: "Проверка", zh: "检查中" },
  "Checking session": { ru: "Проверяем сессию", zh: "正在检查会话" },
  "Checkout": { ru: "Оплатить", zh: "结账" },
  "Close": { ru: "Закрыть", zh: "关闭" },
  "Close market": { ru: "Закрыть по рынку", zh: "市价关闭" },
  "Close-only": { ru: "Только закрытие", zh: "仅平仓" },
  "Confidence": { ru: "Уверенность", zh: "置信度" },
  "Confidence Score": { ru: "Оценка уверенности", zh: "置信评分" },
  "Confirm volume x": { ru: "Объём подтверждения x", zh: "确认成交量 x" },
  "Connect": { ru: "Подключить", zh: "连接" },
  "Connection issue": { ru: "Проблема соединения", zh: "连接问题" },
  "Connection label": { ru: "Название подключения", zh: "连接名称" },
  "Conservative": { ru: "Консервативный", zh: "保守" },
  "Context TF": { ru: "Контекст TF", zh: "上下文周期" },
  "Correlated": { ru: "Корреляция", zh: "相关性" },
  "Correlated risk": { ru: "Коррелированный риск", zh: "相关风险" },
  "Current": { ru: "Текущая", zh: "当前" },
  "Custom": { ru: "Свои", zh: "自定义" },
  "Daily": { ru: "День", zh: "日" },
  "Daily risk": { ru: "Дневной риск", zh: "日风险" },
  "Daily Stop-Loss": { ru: "Дневной Stop-Loss", zh: "日止损" },
  "Data may be delayed": { ru: "Данные могут запаздывать", zh: "数据可能延迟" },
  "Decay 60s": { ru: "Затухание 60с", zh: "60秒衰减" },
  "Default": { ru: "По умолчанию", zh: "默认" },
  "Default profile": { ru: "Профиль по умолчанию", zh: "默认配置" },
  "Decision": { ru: "Решение", zh: "决策" },
  "Decision Snapshot": { ru: "Диагностика решения", zh: "决策快照" },
  "Depth, spread, slippage": { ru: "Глубина, spread, slippage", zh: "深度、价差、滑点" },
  "Delete": { ru: "Удалить", zh: "删除" },
  "Direction": { ru: "Направление", zh: "方向" },
  "Drawdown": { ru: "Просадка", zh: "回撤" },
  "Effective risk": { ru: "Фактический риск", zh: "有效风险" },
  "Edge Snapshot": { ru: "Статистика преимущества", zh: "优势快照" },
  "Email": { ru: "Email", zh: "邮箱" },
  "Enabled": { ru: "Включено", zh: "已启用" },
  "Entry": { ru: "Вход", zh: "入场" },
  "Entry candidate inside": { ru: "Кандидат на вход в зоне", zh: "入场候选位于" },
  "Entry is blocked by current checks": { ru: "Вход заблокирован текущими проверками", zh: "当前检查阻止入场" },
  "Entry is blocked by backend risk gate.": { ru: "Вход заблокирован backend risk gate.", zh: "入场被后端风控网关阻止。" },
  "Entry touched": { ru: "Вход задет", zh: "已触及入场" },
  "Entry touched, waiting for RiskGate permission": { ru: "Вход задет, ждём разрешение RiskGate", zh: "已触及入场，等待 RiskGate 许可" },
  "Entry type": { ru: "Тип входа", zh: "入场类型" },
  "Entry zone": { ru: "Зона входа", zh: "入场区间" },
  "Entry zone / price": { ru: "Зона / цена входа", zh: "入场区间 / 价格" },
  "Entry Zone": { ru: "Зона входа", zh: "入场区间" },
  "Equity": { ru: "Equity", zh: "权益" },
  "evaluated": { ru: "проверено", zh: "已评估" },
  "Exchange": { ru: "Биржа", zh: "交易所" },
  "Exchange rules": { ru: "Правила биржи", zh: "交易所规则" },
  "Exchanges": { ru: "Биржи", zh: "交易所" },
  "Exec": { ru: "Исполнение", zh: "执行" },
  "Execution": { ru: "Исполнение", zh: "执行" },
  "Execution-ready": { ru: "Готово к входу", zh: "执行就绪" },
  "Execution-ready only": { ru: "Только execution-ready", zh: "仅执行就绪" },
  "execution ready": { ru: "готово к входу", zh: "执行就绪" },
  "Execution quality": { ru: "Качество исполнения", zh: "执行质量" },
  "Execution looks realistic for this virtual size.": { ru: "Исполнение выглядит реалистично для этого virtual-размера.", zh: "该 virtual 规模的执行看起来现实。" },
  "Expected slippage": { ru: "Ожидаемое slippage", zh: "预期滑点" },
  "Expiry / TTL": { ru: "Истечение / TTL", zh: "过期 / TTL" },
  "Features": { ru: "Фичи", zh: "特征" },
  "Forming candle preview, wait for close": { ru: "Свеча ещё формируется, ждём закрытие", zh: "K线仍在形成，等待收盘" },
  "Fee source": { ru: "Источник комиссии", zh: "费用来源" },
  "Fees included": { ru: "Комиссии учтены", zh: "已计入手续费" },
  "Fill": { ru: "Исполнение", zh: "成交" },
  "Filter rows": { ru: "Фильтр строк", zh: "筛选行" },
  "Filter target": { ru: "Цель фильтра", zh: "过滤目标" },
  "Final RR": { ru: "Итоговый RR", zh: "最终 RR" },
  "Final target": { ru: "Финальная цель", zh: "最终目标" },
  "Fixed": { ru: "Фикс.", zh: "固定" },
  "Fixed %": { ru: "Фикс. %", zh: "固定 %" },
  "Fixed stop": { ru: "Фикс. стоп", zh: "固定止损" },
  "Futures max lev.": { ru: "Макс. плечо futures", zh: "合约最大杠杆" },
  "Futures open risk": { ru: "Открытый риск futures", zh: "合约持仓风险" },
  "Futures Protection": { ru: "Защита futures", zh: "合约保护" },
  "Futures protection": { ru: "Защита futures", zh: "合约保护" },
  "Futures risk": { ru: "Риск futures", zh: "合约风险" },
  "Futures risk budget": { ru: "Риск-бюджет futures", zh: "合约风险预算" },
  "Global": { ru: "Глобально", zh: "全局" },
  "Good": { ru: "Хорошо", zh: "良好" },
  "Guide": { ru: "Гайд", zh: "指南" },
  "Hide Chart": { ru: "Скрыть график", zh: "隐藏图表" },
  "Hide chart": { ru: "Скрыть график", zh: "隐藏图表" },
  "Hide low-RR cards": { ru: "Скрывать карточки с низким RR", zh: "隐藏低 RR 卡片" },
  "High": { ru: "Высокий", zh: "高" },
  "High Confidence": { ru: "Высокая уверенность", zh: "高置信" },
  "Ignore Signal": { ru: "Игнорировать сигнал", zh: "忽略信号" },
  "Impact": { ru: "Impact", zh: "冲击" },
  "Invalidation": { ru: "Инвалидация", zh: "失效" },
  "Journal": { ru: "Журнал", zh: "日志" },
  "Journal is empty": { ru: "Журнал пуст", zh: "日志为空" },
  "Keep stop loss": { ru: "Оставить stop loss", zh: "保留止损" },
  "Label": { ru: "Название", zh: "标签" },
  "Language": { ru: "Язык", zh: "语言" },
  "Last update": { ru: "Последнее обновление", zh: "最后更新" },
  "Level retests": { ru: "Ретесты уровня", zh: "水平重测" },
  "Limit": { ru: "Лимит", zh: "限价" },
  "Liq. buffer": { ru: "Буфер ликв.", zh: "强平缓冲" },
  "Liquidation buffer required": { ru: "Буфер ликвидации обязателен", zh: "需要强平缓冲" },
  "Liquidity": { ru: "Ликвидность", zh: "流动性" },
  "Liquidity Sweep": { ru: "Снятие ликвидности", zh: "流动性扫单" },
  "Live": { ru: "Live", zh: "在线" },
  "Live · Connected": { ru: "Online · Connected", zh: "在线 · 已连接" },
  "Live data delayed": { ru: "Live data delayed", zh: "实时数据延迟" },
  "Online · Connected": { ru: "Online · Connected", zh: "在线 · 已连接" },
  "Loading analytics...": { ru: "Загружаем аналитику...", zh: "正在加载分析..." },
  "Loading chart...": { ru: "Загружаем график...", zh: "正在加载图表..." },
  "Loading signals...": { ru: "Загружаем сигналы...", zh: "正在加载信号..." },
  "Loading table...": { ru: "Загружаем таблицу...", zh: "正在加载表格..." },
  "Loading watchlist": { ru: "Загружаем watchlist", zh: "正在加载观察列表" },
  "Low": { ru: "Низкий", zh: "低" },
  "Lower risk limits": { ru: "Более низкие лимиты риска", zh: "更低的风险限制" },
  "Manual limits": { ru: "Ручные лимиты", zh: "手动限制" },
  "Manual pair scope bypasses automatic quality exclusion.": {
    ru: "Ручной список пар обходит автоматическое исключение по качеству.",
    zh: "手动交易对范围会绕过自动质量排除。"
  },
  "Market / Limit": { ru: "Market / Limit", zh: "市价 / 限价" },
  "Market data": { ru: "Рыночные данные", zh: "市场数据" },
  "market data": { ru: "market data", zh: "市场数据" },
  "Market impact": { ru: "Влияние на рынок", zh: "市场冲击" },
  "Market opportunity": { ru: "Рыночная возможность", zh: "市场机会" },
  "Market opportunities": { ru: "Рыночные возможности", zh: "市场机会" },
  "Market order": { ru: "Market-ордер", zh: "市价单" },
  "Market quality": { ru: "Качество рынка", zh: "市场质量" },
  "Market regime": { ru: "Режим рынка", zh: "市场状态" },
  "trend_up": { ru: "Восходящий тренд", zh: "上升趋势" },
  "trend_down": { ru: "Нисходящий тренд", zh: "下降趋势" },
  "range": { ru: "Боковик", zh: "震荡" },
  "chop": { ru: "Пила", zh: "杂乱震荡" },
  "volatility_compression": { ru: "Сжатие волатильности", zh: "波动率压缩" },
  "volatility_expansion": { ru: "Расширение волатильности", zh: "波动率扩张" },
  "post_impulse": { ru: "После импульса", zh: "冲击后" },
  "liquidity_sweep_zone": { ru: "Зона снятия ликвидности", zh: "流动性扫单区域" },
  "news_pump": { ru: "Новостной памп", zh: "新闻拉升" },
  "liquidity_vacuum": { ru: "Вакуум ликвидности", zh: "流动性真空" },
  "market_wide_risk_off": { ru: "Общерыночный risk-off", zh: "全市场避险" },
  "news/pump mode": { ru: "Новостной/pump режим", zh: "新闻/拉升模式" },
  "liquidity vacuum": { ru: "Вакуум ликвидности", zh: "流动性真空" },
  "market-wide risk-off": { ru: "Общерыночный risk-off", zh: "全市场避险" },
  "Market setup exists, wait for entry trigger": { ru: "Сетап есть, ждём триггер входа", zh: "市场 setup 已形成，等待入场触发" },
  "Market Status": { ru: "Состояние рынка", zh: "市场状态" },
  "Mark price": { ru: "Mark price", zh: "标记价格" },
  "Max book use": { ru: "Макс. доля стакана", zh: "最大盘口占用" },
  "Max body ATR": { ru: "Макс. body ATR", zh: "最大实体 ATR" },
  "Max drawdown": { ru: "Макс. просадка", zh: "最大回撤" },
  "Max leverage": { ru: "Макс. плечо", zh: "最大杠杆" },
  "Max price drift": { ru: "Макс. уход цены", zh: "最大价格偏移" },
  "Max range ATR": { ru: "Макс. range ATR", zh: "最大区间 ATR" },
  "Max risk boost": { ru: "Макс. буст риска", zh: "最大风险提升" },
  "Max slippage": { ru: "Макс. slippage", zh: "最大滑点" },
  "Max spread": { ru: "Макс. spread", zh: "最大价差" },
  "Medium": { ru: "Средний", zh: "中" },
  "Min 24h volume": { ru: "Мин. объём 24ч", zh: "最小24小时成交量" },
  "Min history": { ru: "Мин. история", zh: "最小历史" },
  "Minimum RR": { ru: "Минимальный RR", zh: "最小 RR" },
  "Min R:R": { ru: "Мин. R:R", zh: "最小 R:R" },
  "Min RR": { ru: "Мин. RR", zh: "最小 RR" },
  "Min S/R ATR": { ru: "Мин. S/R ATR", zh: "最小支撑/阻力 ATR" },
  "Min wick": { ru: "Мин. фитиль", zh: "最小影线" },
  "Margin / leverage": { ru: "Маржа / плечо", zh: "保证金 / 杠杆" },
  "mixed": { ru: "смешанный", zh: "混合" },
  "Mode": { ru: "Режим", zh: "模式" },
  "Model": { ru: "Модель", zh: "模型" },
  "Move after": { ru: "Перенос после", zh: "达到后移动" },
  "MVP demo session": { ru: "MVP demo-сессия", zh: "MVP 演示会话" },
  "Nearest RR": { ru: "Ближайший RR", zh: "最近 RR" },
  "Nearest target": { ru: "Ближайшая цель", zh: "最近目标" },
  "Net PnL": { ru: "Чистый PnL", zh: "净 PnL" },
  "New signals, trade lifecycle events, and exchange issues will appear here.": {
    ru: "Новые сигналы, события сделок и проблемы бирж появятся здесь.",
    zh: "新信号、交易生命周期事件和交易所问题会显示在这里。"
  },
  "No active signals yet": { ru: "Активных сигналов пока нет", zh: "暂无活跃信号" },
  "No active blockers from current checks.": { ru: "Активных блокеров по текущим проверкам нет.", zh: "当前检查没有活跃阻断。" },
  "No active trades": { ru: "Активных сделок нет", zh: "暂无活跃交易" },
  "No alert rules": { ru: "Правил алертов нет", zh: "暂无提醒规则" },
  "No candle data for this trade": { ru: "Нет свечных данных для этой сделки", zh: "该交易暂无K线数据" },
  "No exchange connections": { ru: "Подключений бирж нет", zh: "暂无交易所连接" },
  "No historical signals yet": { ru: "Исторических сигналов пока нет", zh: "暂无历史信号" },
  "No notifications yet": { ru: "Уведомлений пока нет", zh: "暂无通知" },
  "No pairs": { ru: "Пар нет", zh: "暂无交易对" },
  "No pairs in watchlist": { ru: "В watchlist нет пар", zh: "观察列表暂无交易对" },
  "No plans": { ru: "Планов нет", zh: "暂无套餐" },
  "No renewal date": { ru: "Нет даты продления", zh: "无续订日期" },
  "No rows": { ru: "Строк нет", zh: "暂无行" },
  "No scanner series": { ru: "Серий сканера нет", zh: "暂无扫描序列" },
  "No signals": { ru: "Сигналов нет", zh: "暂无信号" },
  "No strategy configs": { ru: "Нет настроек стратегий", zh: "暂无策略配置" },
  "No trades": { ru: "Сделок нет", zh: "暂无交易" },
  "no expiry": { ru: "без срока", zh: "无过期时间" },
  "None": { ru: "Нет", zh: "无" },
  "Not recommended": { ru: "Не рекомендуется", zh: "不建议" },
  "not evaluated": { ru: "не проверено", zh: "未评估" },
  "not previewed": { ru: "не рассчитано", zh: "未预览" },
  "New signal": { ru: "Новый сигнал", zh: "新信号" },
  "Notifications": { ru: "Уведомления", zh: "通知" },
  "Offline": { ru: "Offline", zh: "离线" },
  "Offset": { ru: "Отступ", zh: "偏移" },
  "On": { ru: "On", zh: "开" },
  "Off": { ru: "Off", zh: "关" },
  "Online": { ru: "Online", zh: "在线" },
  "Open": { ru: "Открытые", zh: "开放" },
  "Open chart": { ru: "Открыть график", zh: "打开图表" },
  "Opened": { ru: "Открыт", zh: "已打开" },
  "Open Exchange": { ru: "Открыть биржу", zh: "打开交易所" },
  "Open exchange": { ru: "Открыть биржу", zh: "打开交易所" },
  "Open positions": { ru: "Открытые позиции", zh: "持仓" },
  "Open risk": { ru: "Открытый риск", zh: "持仓风险" },
  "Open risk cap": { ru: "Лимит открытого риска", zh: "持仓风险上限" },
  "Orderbook": { ru: "Стакан", zh: "订单簿" },
  "Order type": { ru: "Тип ордера", zh: "订单类型" },
  "Pair": { ru: "Пара", zh: "交易对" },
  "Pairs": { ru: "Пары", zh: "交易对" },
  "Paper Trade": { ru: "Виртуальная сделка", zh: "Paper 交易" },
  "Passphrase": { ru: "Passphrase", zh: "口令" },
  "Partial": { ru: "Частично", zh: "部分" },
  "Partial take-profit": { ru: "Частичный take-profit", zh: "部分止盈" },
  "Passive": { ru: "Пассивно", zh: "被动" },
  "Password": { ru: "Пароль", zh: "密码" },
  "Pending": { ru: "Ожидание", zh: "等待" },
  "planned retest": { ru: "запланированный retest", zh: "计划重测" },
  "Plans": { ru: "Планы", zh: "套餐" },
  "Portal": { ru: "Портал", zh: "门户" },
  "Position size": { ru: "Размер позиции", zh: "仓位规模" },
  "Post-impact": { ru: "После impact", zh: "冲击后" },
  "Preparing": { ru: "Подготовка", zh: "准备中" },
  "Preview error": { ru: "Ошибка preview", zh: "预览错误" },
  "Preview pending": { ru: "Preview ожидает", zh: "预览等待中" },
  "preview": { ru: "предпросмотр", zh: "预览" },
  "Price": { ru: "Цена", zh: "价格" },
  "Price above": { ru: "Цена выше", zh: "价格高于" },
  "Price below": { ru: "Цена ниже", zh: "价格低于" },
  "Price drift": { ru: "Уход цены", zh: "价格偏移" },
  "Price is testing previous swing high; waiting for liquidity sweep and rejection": {
    ru: "Цена тестирует предыдущий swing high; ждём liquidity sweep и rejection",
    zh: "价格正在测试前一个 swing high；等待 liquidity sweep 和 rejection"
  },
  "Price is testing previous swing low; waiting for liquidity sweep and reclaim": {
    ru: "Цена тестирует предыдущий swing low; ждём liquidity sweep и reclaim",
    zh: "价格正在测试前一个 swing low；等待 liquidity sweep 和 reclaim"
  },
  "Pro": { ru: "Pro", zh: "专业" },
  "Protection": { ru: "Защита", zh: "保护" },
  "Pullback Wait": { ru: "Ожидание pullback", zh: "等待回调" },
  "Queue, fees, liquidity": { ru: "Очередь, комиссии, ликвидность", zh: "队列、费用、流动性" },
  "Radar": { ru: "Радар", zh: "雷达" },
  "Radar settings": { ru: "Настройки радара", zh: "雷达设置" },
  "Read all": { ru: "Прочитать всё", zh: "全部已读" },
  "Real": { ru: "Real", zh: "实盘" },
  "Real wait entry": { ru: "Ждать реальный вход", zh: "真实等待入场" },
  "Realistic execution": { ru: "Реалистичное исполнение", zh: "真实执行模拟" },
  "Realtime events": { ru: "Realtime-события", zh: "实时事件" },
  "Realized PnL": { ru: "Реализованный PnL", zh: "已实现 PnL" },
  "Reality Check": { ru: "Проверка реальности", zh: "现实检查" },
  "Reconnecting...": { ru: "Переподключение...", zh: "重新连接..." },
  "Redirecting to sign in": { ru: "Переходим ко входу", zh: "正在跳转登录" },
  "Refresh": { ru: "Обновить", zh: "刷新" },
  "Replay, Monte Carlo": { ru: "Replay, Monte Carlo", zh: "回放，蒙特卡洛" },
  "Reconfirm plan": { ru: "Подтвердить план заново", zh: "重新确认计划" },
  "Reject / ignore": { ru: "Отклонить / игнорировать", zh: "拒绝 / 忽略" },
  "Requires reconfirmation": { ru: "Нужно подтверждение", zh: "需要重新确认" },
  "Risk": { ru: "Риск", zh: "风险" },
  "Risk / Reward": { ru: "Риск / прибыль", zh: "风险 / 收益" },
  "Risk / Reward Filter": { ru: "Фильтр Risk / Reward", zh: "风险收益过滤" },
  "Risk / Reward Guard": { ru: "Проверка RR", zh: "风险收益检查" },
  "Risk / trade": { ru: "Риск / сделка", zh: "单笔风险" },
  "Risk amount / %": { ru: "Сумма риска / %", zh: "风险金额 / %" },
  "Risk blockers / warnings": { ru: "Блокеры и предупреждения", zh: "风险阻断与警告" },
  "Risk budget": { ru: "Риск-бюджет", zh: "风险预算" },
  "Risk gate": { ru: "Risk gate", zh: "风控网关" },
  "Risk blocked": { ru: "Заблокировано риском", zh: "风险阻断" },
  "RiskGate blocks entry right now": { ru: "RiskGate сейчас блокирует вход", zh: "RiskGate 当前阻止入场" },
  "Risk management": { ru: "Risk management", zh: "风险管理" },
  "Risk Management": { ru: "Risk management", zh: "风险管理" },
  "Risk multiple": { ru: "Risk multiple", zh: "风险倍数" },
  "Risk Profile": { ru: "Профиль риска", zh: "风险配置" },
  "Risk size": { ru: "Размер риска", zh: "风险规模" },
  "Risk multiplier": { ru: "Множитель риска", zh: "风险倍数" },
  "Runner": { ru: "Остаток", zh: "奔跑仓位" },
  "Risky": { ru: "Рискованно", zh: "有风险" },
  "RR 1": { ru: "RR 1", zh: "RR 1" },
  "RR target": { ru: "RR-цель", zh: "RR 目标" },
  "Safe size": { ru: "Безопасный размер", zh: "安全规模" },
  "Save custom": { ru: "Сохранить свои", zh: "保存自定义" },
  "Scanner activity": { ru: "Активность сканера", zh: "扫描器活动" },
  "scanner": { ru: "сканер", zh: "扫描器" },
  "Scanner live": { ru: "Сканер Online", zh: "扫描器运行中" },
  "Scanner Online": { ru: "Сканер Online", zh: "扫描器运行中" },
  "Scanner connecting": { ru: "Подключается", zh: "扫描器连接中" },
  "Scanner data stale": { ru: "Данные устарели", zh: "扫描器数据已过期" },
  "Scanner error": { ru: "Ошибка сканера", zh: "扫描器错误" },
  "Scanner offline": { ru: "Сканер Offline", zh: "扫描器离线" },
  "Scanner status unknown": { ru: "Статус сканера неизвестен", zh: "扫描器状态未知" },
  "Scanner stopping": { ru: "Сканер останавливается", zh: "扫描器停止中" },
  "Score": { ru: "Скор", zh: "评分" },
  "Seeded candles": { ru: "Загружено свечей", zh: "预置K线" },
  "Selected RR": { ru: "Выбранный RR", zh: "选定 RR" },
  "Select pair": { ru: "Выбрать пару", zh: "选择交易对" },
  "Series": { ru: "Серия", zh: "序列" },
  "Settings": { ru: "Настройки", zh: "设置" },
  "Setup exists, wait for confirmation": { ru: "Setup есть, ждём подтверждение", zh: "Setup 已形成，等待确认" },
  "Show Chart": { ru: "Показать график", zh: "显示图表" },
  "Side": { ru: "Сторона", zh: "方向" },
  "Signal": { ru: "Сигнал", zh: "信号" },
  "Signal Details": { ru: "Детали сигнала", zh: "信号详情" },
  "Signal expired": { ru: "Сигнал истёк", zh: "信号已过期" },
  "Signal Feed": { ru: "Лента сигналов", zh: "信号流" },
  "Signal First Radar": { ru: "Радар сигналов", zh: "信号优先雷达" },
  "Signal generated": { ru: "Сигнал создан", zh: "信号生成" },
  "Signals found": { ru: "Найдено сигналов", zh: "发现信号" },
  "Signing in": { ru: "Входим", zh: "登录中" },
  "Sign in": { ru: "Войти", zh: "登录" },
  "Simple MVP stop": { ru: "Простой MVP-стоп", zh: "简单 MVP 止损" },
  "Simulation": { ru: "Симуляция", zh: "模拟" },
  "Slippage included": { ru: "Slippage учтено", zh: "已计入滑点" },
  "Sound": { ru: "Звук", zh: "声音" },
  "Speculative": { ru: "Спекулятивный", zh: "投机" },
  "Spot max size": { ru: "Макс. размер spot", zh: "现货最大规模" },
  "Spot risk": { ru: "Риск spot", zh: "现货风险" },
  "Spot stop required": { ru: "Spot stop обязателен", zh: "现货需要止损" },
  "Spread": { ru: "Spread", zh: "价差" },
  "Status": { ru: "Статус", zh: "状态" },
  "State": { ru: "Состояние", zh: "状态" },
  "Stop": { ru: "Стоп", zh: "止损" },
  "Stop Loss": { ru: "Stop Loss", zh: "止损" },
  "Stop required": { ru: "Стоп обязателен", zh: "需要止损" },
  "Stop scanner": { ru: "Остановить сканер", zh: "停止扫描器" },
  "Stop-loss": { ru: "Stop-loss", zh: "止损" },
  "Strategies": { ru: "Стратегии", zh: "策略" },
  "Strategy Checks": { ru: "Проверки стратегий", zh: "策略检查" },
  "Strategy invalidation": { ru: "Инвалидация стратегии", zh: "策略失效" },
  "Strategy Layers": { ru: "Слои стратегии", zh: "策略层" },
  "Strategy multipliers": { ru: "Множители стратегий", zh: "策略倍数" },
  "Strategy setup": { ru: "Strategy setup", zh: "策略 setup" },
  "Structure": { ru: "Структура", zh: "结构" },
  "Subscription": { ru: "Подписка", zh: "订阅" },
  "Sweep volume x": { ru: "Объём sweep x", zh: "扫单成交量 x" },
  "Sync": { ru: "Синхронизировать", zh: "同步" },
  "Taker fee": { ru: "Taker fee", zh: "Taker 手续费" },
  "Take Profit": { ru: "Take Profit", zh: "止盈" },
  "Take-profit": { ru: "Take-profit", zh: "止盈" },
  "Test": { ru: "Тест", zh: "测试" },
  "TF": { ru: "TF", zh: "周期" },
  "The scanner may still be building candle history, or the market has not produced a valid setup.": {
    ru: "Сканер может ещё собирать историю свечей, или рынок пока не дал валидный setup.",
    zh: "扫描器可能仍在构建K线历史，或市场尚未形成有效 setup。"
  },
  "Timeframes": { ru: "Таймфреймы", zh: "时间周期" },
  "Ticks": { ru: "Тики", zh: "Ticks" },
  "Total Trades": { ru: "Всего сделок", zh: "总交易数" },
  "Top MVP pairs": { ru: "Топ MVP-пары", zh: "MVP 热门交易对" },
  "Top blockers": { ru: "Главные блокеры", zh: "主要阻断" },
  "Trade Plan": { ru: "План сделки", zh: "交易计划" },
  "Trade Rules": { ru: "Правила сделок", zh: "交易规则" },
  "Trades": { ru: "Сделки", zh: "交易" },
  "Trades and journal": { ru: "Сделки и журнал", zh: "交易与日志" },
  "Trading actions disabled": { ru: "Торговые действия отключены", zh: "交易操作已禁用" },
  "Trading actions disabled until realtime data is current.": {
    ru: "Торговые действия отключены, пока realtime-данные не станут актуальными.",
    zh: "在实时数据恢复最新前，交易操作已禁用。"
  },
  "Trailing": { ru: "Trailing", zh: "追踪" },
  "Trailing stop": { ru: "Trailing stop", zh: "追踪止损" },
  "Trend": { ru: "Тренд", zh: "趋势" },
  "Trend pullback": { ru: "Trend pullback", zh: "趋势回调" },
  "Two-factor check": { ru: "Проверка 2FA", zh: "双因素验证" },
  "Updated": { ru: "Обновлено", zh: "更新时间" },
  "Use Auto Paper to wait for confirmation and enter automatically after the trigger candle.": {
    ru: "Используйте Auto Paper, чтобы дождаться подтверждения и войти автоматически после триггерной свечи.",
    zh: "使用 Auto Paper 等待确认，并在触发K线后自动入场。"
  },
  "Use smaller size": { ru: "Уменьшить размер", zh: "使用更小规模" },
  "Virtual": { ru: "Virtual", zh: "模拟" },
  "Virtual balance": { ru: "Virtual баланс", zh: "模拟余额" },
  "Virtual depth, spread, slippage": { ru: "Virtual глубина, spread, slippage", zh: "模拟深度、价差、滑点" },
  "Virtual execution": { ru: "Virtual исполнение", zh: "模拟执行" },
  "Virtual queue, fees, liquidity": { ru: "Virtual очередь, комиссии, ликвидность", zh: "模拟队列、费用、流动性" },
  "Virtual risk": { ru: "Virtual риск", zh: "模拟风险" },
  "Virtual risk budget": { ru: "Virtual риск-бюджет", zh: "模拟风险预算" },
  "Virtual entry locked": { ru: "Виртуальная сделка недоступна", zh: "模拟入场已锁定" },
  "Virtual entry now": { ru: "Виртуальная сделка", zh: "立即模拟入场" },
  "Virtual wait entry": { ru: "Ждать вход виртуально", zh: "模拟等待入场" },
  "Virtual Trading": { ru: "Virtual trading", zh: "模拟交易" },
  "Virtual Trades": { ru: "Virtual-сделки", zh: "模拟交易" },
  "Volatility": { ru: "Волатильность", zh: "波动率" },
  "Volume": { ru: "Объём", zh: "成交量" },
  "Volume x": { ru: "Объём x", zh: "成交量 x" },
  "Waiting": { ru: "Ожидание", zh: "等待" },
  "Waiting Entry": { ru: "Ждём вход", zh: "等待入场" },
  "Waiting entry": { ru: "Ждём вход", zh: "等待入场" },
  "forming allowed": { ru: "открытая свеча разрешена", zh: "允许形成中K线" },
  "forming candle": { ru: "свеча формируется", zh: "K线形成中" },
  "Waiting for market data": { ru: "Ждём рыночные данные", zh: "等待市场数据" },
  "Waiting for stream": { ru: "Ждём stream", zh: "等待数据流" },
  "Watch setup formation, no entry yet": { ru: "Наблюдать за формированием setup, входа пока нет", zh: "观察 setup 形成，暂不入场" },
  "Watchlist": { ru: "Список", zh: "观察列表" },
  "Weekly": { ru: "Неделя", zh: "周" },
  "Why this signal?": { ru: "Почему этот сигнал?", zh: "为什么是这个信号？" },
  "Win Rate": { ru: "Win Rate", zh: "胜率" },
}, {
  "Actionable entry follows the current strategy status; retest is the conservative alternative.": {
    ru: "Вход зависит от текущего статуса стратегии; ретест остается консервативной альтернативой.",
    zh: "入场跟随当前策略状态；回测区是保守替代方案。"
  },
  "Actionable entry is the retest zone while the breakout candle cools off.": {
    ru: "Рабочая зона входа сейчас находится на ретесте, пока breakout-свеча остывает.",
    zh: "突破K线冷却期间，可执行入场位于回测区。"
  },
  "ATR value is unavailable; using trailing percent fallback.": {
    ru: "ATR недоступен; используем резервный процентный трейлинг.",
    zh: "ATR 不可用；使用追踪百分比回退。"
  },
  "Bid / Ask": { ru: "Бид / аск", zh: "买价 / 卖价" },
  "Chart": { ru: "График", zh: "图表" },
  "Chart:": { ru: "График:", zh: "图表:" },
  "conservative_fallback": { ru: "консервативный резерв", zh: "保守回退" },
  "Confirm zone": { ru: "Зона подтверждения", zh: "确认区间" },
  "Confirmation": { ru: "Подтверждение", zh: "确认" },
  "Confirmation Checklist": { ru: "Чек-лист подтверждения", zh: "确认清单" },
  "context resistance": { ru: "Контекстное сопротивление", zh: "上下文阻力" },
  "context support": { ru: "Контекстная поддержка", zh: "上下文支撑" },
  "context timeframe": { ru: "Контекстный TF", zh: "上下文周期" },
  "ema200 chop": { ru: "EMA200 chop", zh: "EMA200 震荡" },
  "Execution": { ru: "Исполнение", zh: "执行" },
  "Execution:": { ru: "Исполнение:", zh: "执行:" },
  "Exit management": { ru: "Управление выходом", zh: "退出管理" },
  "Exit plan": { ru: "План выхода", zh: "退出计划" },
  "Entry is blocked by backend risk gate.": { ru: "Вход заблокирован серверным риск-гейтом.", zh: "入场被后端风控网关阻止。" },
  "Entry, SL and TP are calculated": { ru: "Вход, SL и TP рассчитаны", zh: "入场、SL 和 TP 已计算" },
  "Funding buffer": { ru: "Буфер funding", zh: "资金费缓冲" },
  "Futures guard": { ru: "Futures-защита", zh: "合约保护" },
  "Level touches": { ru: "Касания уровня", zh: "水平触碰" },
  "Margin": { ru: "Маржа", zh: "保证金" },
  "Mark price": { ru: "Маркировочная цена", zh: "标记价格" },
  "Measured move": { ru: "Цель measured move", zh: "量度目标" },
  "News/Event Risk": { ru: "Новостной/ивент-риск", zh: "新闻/事件风险" },
  "Overheat Penalty": { ru: "Штраф за перегрев", zh: "过热惩罚" },
  "Planned stop": { ru: "Плановый стоп", zh: "计划止损" },
  "Preview pending": { ru: "Ожидает расчёт", zh: "预览等待中" },
  "Recommended action": { ru: "Рекомендованное действие", zh: "建议操作" },
  "regime alignment": { ru: "Режим", zh: "市场状态" },
  "regime strength": { ru: "Сила режима", zh: "状态强度" },
  "reduced": { ru: "сниженная", zh: "降低" },
  "Retest zone": { ru: "Зона ретеста", zh: "回测区" },
  "Risks": { ru: "Риски", zh: "风险" },
  "Risk / Reward Filter": { ru: "Фильтр риска/прибыли", zh: "风险收益过滤" },
  "Risk gate": { ru: "Риск-гейт", zh: "风控网关" },
  "Risk/Reward is set": { ru: "RR указан", zh: "Risk/Reward 已设置" },
  "Risk/Reward": { ru: "Риск/прибыль", zh: "风险收益" },
  "Spread": { ru: "Спред", zh: "价差" },
  "Signal:": { ru: "Сигнал:", zh: "信号:" },
  "Stop Loss": { ru: "Стоп-лосс", zh: "止损" },
  "Strategy setup exists, but confirmation is incomplete": {
    ru: "Setup стратегии есть, но подтверждение неполное",
    zh: "策略 setup 已形成，但确认尚未完成"
  },
  "Strategy setup": { ru: "Сетап стратегии", zh: "策略 setup" },
  "Sweep is actionable only after reclaim, wick, volume and RR checks stay valid.": {
    ru: "Sweep можно отрабатывать только после reclaim, если фитиль, объём и RR остаются валидными.",
    zh: "只有在重新收复后，且影线、成交量和 RR 检查仍有效时，扫单才可执行。"
  },
  "Sweep is staged; wait for reclaim or a confirmation candle through micro structure.": {
    ru: "Sweep подготовлен; дождитесь reclaim или подтверждающей свечи через микроструктуру.",
    zh: "扫单已进入准备阶段；等待重新收复或穿越微结构的确认K线。"
  },
  "Swept level": { ru: "Снятый уровень", zh: "被扫水平" },
  "Take Profit": { ru: "Тейк-профит", zh: "止盈" },
  "Taker fee": { ru: "Taker-комиссия", zh: "吃单手续费" },
  "Trailing": { ru: "Трейлинг", zh: "追踪止损" },
  "Wait for pullback or retest": { ru: "Ждать pullback или ретест", zh: "等待回调或回测" },
  "Wick": { ru: "Фитиль", zh: "影线" },
  "active": { ru: "активен", zh: "活跃" },
  "actionable": { ru: "можно входить", zh: "可入场" },
  "all": { ru: "все", zh: "全部" },
  "blocked": { ru: "заблокировано", zh: "已阻止" },
  "closed": { ru: "закрыта", zh: "已关闭" },
  "confirmed": { ru: "подтверждён", zh: "已确认" },
  "entry touched": { ru: "вход задет", zh: "触及入场" },
  "expired": { ru: "истёк", zh: "已过期" },
  "failed": { ru: "ошибка", zh: "失败" },
  "final": { ru: "финальная", zh: "最终" },
  "Forming": { ru: "Формируется", zh: "形成中" },
  "fresh": { ru: "актуально", zh: "新鲜" },
  "good": { ru: "хороший", zh: "良好" },
  "history": { ru: "история", zh: "历史" },
  "invalidated": { ru: "сломана", zh: "已失效" },
  "low": { ru: "низкий", zh: "低" },
  "medium": { ru: "средний", zh: "中" },
  "nearest": { ru: "ближайшая", zh: "最近" },
  "new": { ru: "новый", zh: "新" },
  "none": { ru: "нет", zh: "无" },
  "open": { ru: "открытые", zh: "开放" },
  "open ideas": { ru: "открытые идеи", zh: "开放想法" },
  "passed": { ru: "пройдено", zh: "通过" },
  "pending": { ru: "ожидание", zh: "等待" },
  "poor": { ru: "слабое", zh: "差" },
  "ready": { ru: "готов", zh: "就绪" },
  "rejected": { ru: "отклонён", zh: "已拒绝" },
  "risky": { ru: "рискованное", zh: "有风险" },
  "short": { ru: "SHORT", zh: "SHORT" },
  "long": { ru: "LONG", zh: "LONG" },
  "strong": { ru: "сильный", zh: "强" },
  "stub": { ru: "заглушка", zh: "占位" },
  "unknown": { ru: "неизвестно", zh: "未知" },
  "virtual": { ru: "virtual", zh: "模拟" },
  "wait for pullback": { ru: "ждём pullback", zh: "等待回调" },
  "watchlist": { ru: "наблюдение", zh: "观察" },
  "warning": { ru: "предупреждение", zh: "警告" },
  "no": { ru: "нет", zh: "否" },
  "yes": { ru: "да", zh: "是" }
});

export function translatePhrase(value: string, locale: Locale): string {
  if (locale === "en") return phrases[value]?.en ?? value;
  return phrases[value]?.[locale] ?? value;
}

export function translateKey(key: I18nKey, locale: Locale, params: TranslationParams = {}): string {
  const text = lookupTypedTranslation(key, locale);
  return interpolate(text, params);
}

export function normalizeReasonCode(value: string | null | undefined): ReasonCode | null {
  if (value == null) return null;
  const text = String(value).trim();
  if (!text) return null;
  const canonical = text
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .replace(/[^A-Za-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .toLowerCase();
  if (canonical in typedDictionary.en.reasonCodes) return canonical as ReasonCode;
  const aliasKey = text
    .replace(/\s+/g, " ")
    .replace(/[.]+$/g, "")
    .trim()
    .toLowerCase();
  return reasonCodeAliases[aliasKey] ?? null;
}

export function translateReasonCode(value: string | null | undefined, locale: Locale, params: TranslationParams = {}): string {
  const reasonCode = normalizeReasonCode(value);
  if (reasonCode) {
    return translateKey(`reasonCodes.${reasonCode}` as I18nKey, locale, params);
  }
  const text = String(value ?? "").trim();
  if (!text) return translateKey("common.unknown", locale);
  const translated = translateText(text, locale);
  if (translated !== text) return translated;
  return humanizeReasonCode(text);
}

export function translateReasonCodes(values: Array<string | null | undefined>, locale: Locale): string[] {
  const translated: string[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    const text = translateReasonCode(value, locale);
    if (!text || seen.has(text)) continue;
    seen.add(text);
    translated.push(text);
  }
  return translated;
}

export function translateText(value: string, locale: Locale): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (!normalized) return value;

  const exact = translatePhrase(normalized, locale);
  if (exact !== normalized) return withOriginalWhitespace(value, exact);

  const dynamic = translateDynamicText(normalized, locale);
  if (dynamic !== normalized) return withOriginalWhitespace(value, dynamic);

  return value;
}

function withOriginalWhitespace(original: string, translated: string): string {
  const leading = original.match(/^\s*/)?.[0] ?? "";
  const trailing = original.match(/\s*$/)?.[0] ?? "";
  return `${leading}${translated}${trailing}`;
}

function lookupTypedTranslation(key: I18nKey, locale: Locale): string {
  const dictionaryLocale = locale === "ru" ? "ru" : "en";
  const localized = readTypedValue(typedDictionary[dictionaryLocale], key);
  if (localized) return localized;
  return readTypedValue(typedDictionary.en, key) ?? key;
}

function readTypedValue(tree: TranslationTree, key: string): string | null {
  let current: string | TranslationTree | undefined = tree;
  for (const part of key.split(".")) {
    if (!current || typeof current === "string") return null;
    current = current[part];
  }
  return typeof current === "string" ? current : null;
}

function interpolate(text: string, params: TranslationParams): string {
  return text.replace(/\{([A-Za-z0-9_]+)\}/g, (placeholder, key) => {
    const value = params[key];
    return value == null ? placeholder : String(value);
  });
}

function humanizeReasonCode(value: string): string {
  const normalized = value
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!normalized) return value;
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

function translateDynamicText(value: string, locale: Locale): string {
  const tradingText = translateTradingText(value, locale);
  if (tradingText !== value) return tradingText;

  const replacements: Array<[RegExp, (match: RegExpMatchArray) => string]> = [
    [/^Browser: (.+)$/u, (match) => `${translatePhrase("Browser", locale)}: ${translatePhrase(match[1] ?? "", locale)}`],
    [/^Current (.+)$/u, (match) => `${translatePhrase("Current", locale)} ${match[1] ?? ""}`],
    [/^Daily (.+)$/u, (match) => `${translatePhrase("Daily", locale)} ${match[1] ?? ""}`],
    [/^Drawdown (.+)$/u, (match) => `${translatePhrase("Drawdown", locale)} ${match[1] ?? ""}`],
    [/^Entry candidate inside (.+)$/u, (match) => `${translatePhrase("Entry candidate inside", locale)} ${match[1] ?? ""}`],
    [/^Execution-ready inside (.+)$/u, (match) => (locale === "zh" ? `执行就绪，区间 ${match[1] ?? ""}` : locale === "ru" ? `Готово к входу в зоне ${match[1] ?? ""}` : value)],
    [/^Features built: (.+)$/u, (match) => `${translatePhrase("Features", locale)}: ${match[1] ?? ""}`],
    [/^Last update: (.+)$/u, (match) => `${translatePhrase("Last update", locale)}: ${translateAge(match[1] ?? "", locale)}`],
    [/^Open (.+)$/u, (match) => `${translatePhrase("Open", locale)} ${translateAge(match[1] ?? "", locale)}`],
    [/^Opened (.+)$/u, (match) => `${translatePhrase("Opened", locale)} ${translateAge(match[1] ?? "", locale)}`],
    [/^Pairs: (.+)$/u, (match) => `${translatePhrase("Pairs", locale)}: ${match[1] ?? ""}`],
    [/^Protection: (.+)$/u, (match) => `${translatePhrase("Protection", locale)}: ${translatePhrase(match[1] ?? "", locale)}`],
    [/^Risk: (Low|Medium|High|Speculative) \| Opened (.+) \| Updated (.+)$/u, (match) => (
      `${translatePhrase("Risk", locale)}: ${translatePhrase(match[1] ?? "", locale)} | ${translatePhrase("Opened", locale)} ${translateAge(match[2] ?? "", locale)} | ${translatePhrase("Updated", locale)} ${translateAge(match[3] ?? "", locale)}`
    )],
    [/^Risk: (.+)$/u, (match) => `${translatePhrase("Risk", locale)}: ${translatePhrase(match[1] ?? "", locale)}`],
    [/^Seeded candles: (.+)$/u, (match) => `${translatePhrase("Seeded candles", locale)}: ${match[1] ?? ""}`],
    [/^Signal: (.+)$/u, (match) => `${translatePhrase("Signal", locale)}: ${translatePhrase(match[1] ?? "", locale)}`],
    [/^Chart: (.+)$/u, (match) => `${translatePhrase("Chart", locale)}: ${translatePhrase(match[1] ?? "", locale)}`],
    [/^Execution: (.+)$/u, (match) => `${translatePhrase("Execution", locale)}: ${translatePhrase(match[1] ?? "", locale)}`],
    [/^Signals found: (.+)$/u, (match) => `${translatePhrase("Signals found", locale)}: ${match[1] ?? ""}`],
    [/^Strategy status: (.+)$/u, (match) => `${translatePhrase("Status", locale)} стратегии: ${translatePhrase(match[1] ?? "", locale)}`],
    [/^Timeframes: (.+)$/u, (match) => `${translatePhrase("Timeframes", locale)}: ${match[1] ?? ""}`],
    [/^TTL expired$/u, () => (locale === "zh" ? "TTL 已过期" : locale === "ru" ? "TTL истёк" : "TTL expired")],
    [/^TTL n\/a$/u, () => (locale === "zh" ? "TTL 不可用" : locale === "ru" ? "TTL н/д" : "TTL n/a")],
    [/^TTL (.+)$/u, (match) => `TTL ${translateAge(match[1] ?? "", locale)}`],
    [/^Updated (.+)$/u, (match) => `${translatePhrase("Updated", locale)} ${translateAge(match[1] ?? "", locale)}`],
    [/^Weekly (.+)$/u, (match) => `${translatePhrase("Weekly", locale)} ${match[1] ?? ""}`],
    [/^(\d+) candles$/u, (match) => (locale === "zh" ? `${match[1]} 根K线` : locale === "ru" ? `${match[1]} свечей` : value)],
    [/^(\d+) rows$/u, (match) => (locale === "zh" ? `${match[1]} 行` : locale === "ru" ? `${match[1]} строк` : value)],
    [/^(\d+) selected pairs$/u, (match) => (locale === "zh" ? `已选交易对: ${match[1]}` : locale === "ru" ? `Выбрано пар: ${match[1]}` : value)],
    [/^Page size (.+)$/u, (match) => (locale === "zh" ? `每页 ${match[1]}` : locale === "ru" ? `Размер страницы ${match[1]}` : value)],
    [/^Risk (Low|Medium|High|Speculative)$/u, (match) => `${translatePhrase("Risk", locale)} ${translatePhrase(match[1] ?? "", locale)}`],
    [/^(Low|Medium|High) \/ (Low|Medium|High) impact$/u, (match) => (
      locale === "zh"
        ? `${translatePhrase(match[1] ?? "", locale)} / ${translatePhrase(match[2] ?? "", locale)} 冲击`
        : locale === "ru"
          ? `Качество: ${translateNeuterLevel(match[1] ?? "")} / влияние: ${translateNeuterLevel(match[2] ?? "")}`
          : value
    )],
    [/^(\d+)% Confidence$/u, (match) => (locale === "zh" ? `置信度 ${match[1]}%` : locale === "ru" ? `Уверенность ${match[1]}%` : value)],
    [/^(.+) Signal$/u, (match) => `${match[1] ?? ""} ${translatePhrase("Signal", locale)}`],
    [/^(\d+) Targets$/u, (match) => (locale === "zh" ? `${match[1]} 个目标` : locale === "ru" ? `${match[1]} цели` : value)]
  ];

  for (const [pattern, replacement] of replacements) {
    const match = value.match(pattern);
    if (match) return replacement(match);
  }

  return value;
}

function translateTradingText(value: string, locale: Locale): string {
  if (locale === "en") return value;

  const exact = tradeTextMap[value];
  if (exact) return exact[locale] ?? value;

  const riskReward = value.match(/^Risk\/reward passed: (nearest|final) target is ([\d.]+R), minimum ([\d.]+R)$/u);
  if (riskReward) {
    const target = riskReward[1] === "nearest"
      ? translatePhrase("nearest", locale)
      : translatePhrase("final", locale);
    if (locale === "zh") return `Risk/reward 已通过: ${target}目标 ${riskReward[2]}, 最小 ${riskReward[3]}`;
    return `Риск/прибыль пройдены: ${target} цель ${riskReward[2]}, минимум ${riskReward[3]}`;
  }

  const plannedRiskReward = value.match(/^Risk\/reward passed: planned (nearest|final) target is ([\d.]+R), minimum ([\d.]+R)$/u);
  if (plannedRiskReward) {
    const target = plannedRiskReward[1] === "nearest"
      ? translatePhrase("nearest", locale)
      : translatePhrase("final", locale);
    if (locale === "zh") return `Risk/reward 已通过: 计划${target}目标 ${plannedRiskReward[2]}, 最小 ${plannedRiskReward[3]}`;
    return `Риск/прибыль пройдены: плановая ${target} цель ${plannedRiskReward[2]}, минимум ${plannedRiskReward[3]}`;
  }

  if (locale === "zh") {
    const levelQualityZh = value.match(/^Level quality: (.+) from 20-50 candle structure$/u);
    if (levelQualityZh) return `水平质量: ${levelQualityZh[1]} 来自 20-50 根K线结构`;

    const sweptLevelZh = value.match(/^Swept liquidity level: (.+)$/u);
    if (sweptLevelZh) return `被扫流动性水平: ${sweptLevelZh[1]}`;

    if (/^context timeframe: Expected none context; using signal timeframe only$/u.test(value)) {
      return "上下文周期: 未设置上下文，仅使用信号周期";
    }

    const regimeAlignmentZh = value.match(/^regime alignment: (long|short) vs (bullish|bearish|range|unknown) context \((weak|normal|strong|unknown)\)$/u);
    if (regimeAlignmentZh) {
      const side = regimeAlignmentZh[1]?.toUpperCase() ?? "";
      const regime = translateMarketEnum(regimeAlignmentZh[2] ?? "", locale);
      const strength = translateMarketEnum(regimeAlignmentZh[3] ?? "", locale);
      return `市场状态: ${side} 对 ${regime} 上下文 (${strength})`;
    }

    const regimeStrengthZh = value.match(/^regime strength: Higher timeframe trend strength is (weak|normal|strong|unknown)$/u);
    if (regimeStrengthZh) {
      const strength = translateMarketEnum(regimeStrengthZh[1] ?? "", locale);
      return `状态强度: 高周期趋势强度为 ${strength}`;
    }

    const sizeConsumeZh = value.match(/^Your virtual size would consume (.+)\. The simulated entry could be worse by about (.+), and simulated stop execution could add about (.+) friction\.$/u);
    if (sizeConsumeZh) {
      return `你的 virtual 规模会消耗 ${translateLiquidityDepth(sizeConsumeZh[1] ?? "", locale)}。模拟入场可能恶化约 ${sizeConsumeZh[2]}，模拟止损执行可能额外增加约 ${sizeConsumeZh[3]} 摩擦。`;
    }

    const reduceRecommendationZh = value.match(/^Recommendation: reduce virtual size to about \$(.+), use a limit order, or treat this simulation as unrealistic\.$/u);
    if (reduceRecommendationZh) {
      return `建议: 将 virtual 规模降至约 $${reduceRecommendationZh[1]}，使用限价单，或将这次模拟视为不现实。`;
    }

    const skipRecommendationZh = value.match(/^Recommendation: use a much smaller virtual (.+) setup or treat this simulation as unrealistic\.$/u);
    if (skipRecommendationZh) {
      return `建议: 使用更小的 virtual ${skipRecommendationZh[1]} setup，或将这次模拟视为不现实。`;
    }

    const preferRecommendationZh = value.match(/^Recommendation: prefer (.+), reduce size if the book thins out, and avoid chasing a market order\.$/u);
    if (preferRecommendationZh) {
      return `建议: 优先使用 ${preferRecommendationZh[1]}，如果盘口变薄就降低规模，并避免追市价单。`;
    }
  }

  const levelQuality = value.match(/^Level quality: (.+) from 20-50 candle structure$/u);
  if (levelQuality) {
    if (locale === "zh") return `质量 уровня: ${levelQuality[1]} по структуре 20-50 свечей`;
    return `Качество уровня: ${levelQuality[1]} по структуре 20-50 свечей`;
  }

  const recentTouches = value.match(/^Level has (\d+) recent touches$/u);
  if (recentTouches) {
    if (locale === "zh") return `该水平最近有 ${recentTouches[1]} 次触碰`;
    return `У уровня ${recentTouches[1]} недавних касаний`;
  }

  const sweptLevel = value.match(/^Swept liquidity level: (.+)$/u);
  if (sweptLevel) {
    if (locale === "zh") return `Снят уровень ликвидности: ${sweptLevel[1]}`;
    return `Снят уровень ликвидности: ${sweptLevel[1]}`;
  }

  const status = value.match(/^Status: (.+)$/u);
  if (status) {
    const translatedStatus = translateTradingText(status[1] ?? "", locale);
    return `${translatePhrase("Status", locale)}: ${translatedStatus}`;
  }

  const contextTimeframe = value.match(/^context timeframe: Expected none context; using signal timeframe only$/u);
  if (contextTimeframe) {
    return locale === "zh"
      ? "Контекстный TF: контекст не задан, используется только TF сигнала"
      : "Контекстный TF: контекст не задан, используется только TF сигнала";
  }

  const regimeAlignment = value.match(/^regime alignment: (long|short) vs (bullish|bearish|range|unknown) context \((weak|normal|strong|unknown)\)$/u);
  if (regimeAlignment) {
    const side = regimeAlignment[1]?.toUpperCase() ?? "";
    const regime = translateMarketEnum(regimeAlignment[2] ?? "", locale);
    const strength = translateMarketEnum(regimeAlignment[3] ?? "", locale);
    return locale === "zh"
      ? `市场状态: ${side} 对上下文 ${regime} (${strength})`
      : `Режим: ${side} против контекста: ${regime} (${strength})`;
  }

  const regimeStrength = value.match(/^regime strength: Higher timeframe trend strength is (weak|normal|strong|unknown)$/u);
  if (regimeStrength) {
    const strength = translateMarketEnum(regimeStrength[1] ?? "", locale);
    return locale === "zh"
      ? `Сила режима: тренд старшего TF ${strength}`
      : `Сила режима: тренд старшего TF ${strength}`;
  }

  const sizeConsume = value.match(/^Your virtual size would consume (.+)\. The simulated entry could be worse by about (.+), and simulated stop execution could add about (.+) friction\.$/u);
  if (sizeConsume) {
    if (locale === "zh") {
      return `Ваш virtual-размер занял бы ${translateLiquidityDepth(sizeConsume[1] ?? "", locale)}. Симулированный вход может быть хуже примерно на ${sizeConsume[2]}, а симулированный стоп может добавить около ${sizeConsume[3]} трения.`;
    }
    return `Ваш virtual-размер занял бы ${translateLiquidityDepth(sizeConsume[1] ?? "", locale)}. Симулированный вход может быть хуже примерно на ${sizeConsume[2]}, а симулированный стоп может добавить около ${sizeConsume[3]} трения.`;
  }

  const reduceRecommendation = value.match(/^Recommendation: reduce virtual size to about \$(.+), use a limit order, or treat this simulation as unrealistic\.$/u);
  if (reduceRecommendation) {
    if (locale === "zh") return `Рекомендация: уменьшить virtual-размер примерно до $${reduceRecommendation[1]}, использовать limit-ордер или считать эту симуляцию нереалистичной.`;
    return `Рекомендация: уменьшить virtual-размер примерно до $${reduceRecommendation[1]}, использовать limit-ордер или считать эту симуляцию нереалистичной.`;
  }

  const skipRecommendation = value.match(/^Recommendation: use a much smaller virtual (.+) setup or treat this simulation as unrealistic\.$/u);
  if (skipRecommendation) {
    if (locale === "zh") return `Рекомендация: использовать намного меньший virtual ${skipRecommendation[1]} setup или считать эту симуляцию нереалистичной.`;
    return `Рекомендация: использовать намного меньший virtual ${skipRecommendation[1]} setup или считать эту симуляцию нереалистичной.`;
  }

  const preferRecommendation = value.match(/^Recommendation: prefer (.+), reduce size if the book thins out, and avoid chasing a market order\.$/u);
  if (preferRecommendation) {
    if (locale === "zh") return `Рекомендация: предпочесть ${preferRecommendation[1]}, уменьшить размер при истончении стакана и не догонять market-ордер.`;
    return `Рекомендация: предпочесть ${preferRecommendation[1]}, уменьшить размер при истончении стакана и не догонять market-ордер.`;
  }

  const realisticSize = value.match(/^The requested size fits current liquidity with expected entry slippage around (.+)\.$/u);
  if (realisticSize) {
    if (locale === "zh") return `请求规模符合当前流动性，预期入场滑点约 ${realisticSize[1]}。`;
    return `Запрошенный размер помещается в текущую ликвидность; ожидаемое slippage входа около ${realisticSize[1]}.`;
  }

  const sensitiveSetup = value.match(/^The virtual fill is usable, but execution is sensitive: expected entry slippage is (.+) and impact risk is (.+)\.$/u);
  if (sensitiveSetup) {
    const impact = translatePhrase(sensitiveSetup[2] ?? "", locale);
    if (locale === "zh") return `Virtual fill 可用，但执行较敏感：预期入场滑点 ${sensitiveSetup[1]}，impact 风险 ${impact}。`;
    return `Virtual fill usable, но исполнение чувствительно: ожидаемое slippage входа ${sensitiveSetup[1]}, impact-риск ${impact}.`;
  }

  const rejectionWick = value.match(/^Rejection wick ratio is (.+)$/u);
  if (rejectionWick) {
    if (locale === "zh") return `拒绝影线比例为 ${rejectionWick[1]}`;
    return `Доля rejection-фитиля ${rejectionWick[1]}`;
  }

  const wickRatioThreshold = value.match(/^Wick ratio (.+) is below the sweep threshold$/u);
  if (wickRatioThreshold) {
    if (locale === "zh") return `影线比例 ${wickRatioThreshold[1]} 低于 sweep 阈值`;
    return `Доля фитиля ${wickRatioThreshold[1]} ниже порога sweep`;
  }

  const priceEma = value.match(/^Price is (above|below) EMA(\d+)$/u);
  if (priceEma) {
    if (locale === "zh") return `价格${translateAboveBelow(priceEma[1] ?? "", locale)} EMA${priceEma[2]}`;
    return `Цена ${translateAboveBelow(priceEma[1] ?? "", locale)} EMA${priceEma[2]}`;
  }

  const emaRelation = value.match(/^(EMA\d+) is (above|below) (EMA\d+)$/u);
  if (emaRelation) {
    if (locale === "zh") return `${emaRelation[1]} ${translateAboveBelow(emaRelation[2] ?? "", locale)} ${emaRelation[3]}`;
    return `${emaRelation[1]} ${translateAboveBelow(emaRelation[2] ?? "", locale)} ${emaRelation[3]}`;
  }

  const adxConfirm = value.match(/^ADX ([\d.]+) confirms trend strength$/u);
  if (adxConfirm) {
    if (locale === "zh") return `ADX ${adxConfirm[1]} 确认趋势强度`;
    return `ADX ${adxConfirm[1]} подтверждает силу тренда`;
  }

  const rsiOutside = value.match(/^RSI ([\d.]+) is outside the healthy pullback zone$/u);
  if (rsiOutside) {
    if (locale === "zh") return `RSI ${rsiOutside[1]} 不在健康回调区间内`;
    return `RSI ${rsiOutside[1]} вне здоровой зоны pullback`;
  }

  const triggerMissing = value.match(/^Trigger is still missing: wait for previous high\/low break with ([\d.]+x) volume$/u);
  if (triggerMissing) {
    if (locale === "zh") return `触发器仍缺失: 等待前高/前低突破并伴随 ${triggerMissing[1]} 成交量`;
    return `Триггера ещё нет: ждём пробой предыдущего high/low с объёмом ${triggerMissing[1]}`;
  }

  const entryLate = value.match(/^Entry is late: distance from EMA(\d+) is above ([\d.]+ ATR)$/u);
  if (entryLate) {
    if (locale === "zh") return `入场偏晚: 距 EMA${entryLate[1]} 超过 ${entryLate[2]}`;
    return `Вход запаздывает: расстояние от EMA${entryLate[1]} больше ${entryLate[2]}`;
  }

  const closeEma = value.match(/^Close (above|below) EMA(\d+)$/u);
  if (closeEma) {
    if (locale === "zh") return `收盘${translateAboveBelow(closeEma[1] ?? "", locale)} EMA${closeEma[2]}`;
    return `Закрытие ${translateAboveBelow(closeEma[1] ?? "", locale)} EMA${closeEma[2]}`;
  }

  const breakSwing = value.match(/^Break (above|below) last swing (high|low)$/u);
  if (breakSwing) {
    const side = breakSwing[2] === "high" ? "high" : "low";
    if (locale === "zh") return `突破最近 swing ${side}`;
    return `Пробой последнего swing ${side}`;
  }

  const rsiReclaims = value.match(/^RSI reclaims the ([\d.]+) zone$/u);
  if (rsiReclaims) {
    if (locale === "zh") return `RSI 重新收复 ${rsiReclaims[1]} 区域`;
    return `RSI возвращает зону ${rsiReclaims[1]}`;
  }

  const regimeAlignmentWithTf = value.match(/^regime alignment: (long|short) vs (bullish|bearish|range|unknown) ([\w]+) \((weak|normal|strong|unknown)\)$/u);
  if (regimeAlignmentWithTf) {
    const side = regimeAlignmentWithTf[1]?.toUpperCase() ?? "";
    const regime = translateMarketEnum(regimeAlignmentWithTf[2] ?? "", locale);
    const timeframe = regimeAlignmentWithTf[3] ?? "";
    const strength = translateMarketEnum(regimeAlignmentWithTf[4] ?? "", locale);
    if (locale === "zh") return `市场状态: ${side} 对 ${timeframe} ${regime} (${strength})`;
    return `Режим: ${side} против ${timeframe} ${regime} (${strength})`;
  }

  const emaChop = value.match(/^ema200 chop: EMA200 chop score ([\d.]+): (\d+) crosses in (\d+) candles, near-ratio ([\d.]+%), slope ([\d.]+ ATR)$/u);
  if (emaChop) {
    if (locale === "zh") return `EMA200 chop: 评分 ${emaChop[1]}, ${emaChop[2]} 次穿越 / ${emaChop[3]} 根K线, 接近比例 ${emaChop[4]}, 斜率 ${emaChop[5]}`;
    return `EMA200 chop: скор ${emaChop[1]}, ${emaChop[2]} пересечений за ${emaChop[3]} свечей, близость ${emaChop[4]}, наклон ${emaChop[5]}`;
  }

  const contextLevel = value.match(/^context (support|resistance): (.+) S\/R (support|resistance) (.+) is (.+ ATR) from entry; strength (\d+), retests (\d+), age (\d+) candles, volume x([\d.]+)$/u);
  if (contextLevel) {
    const levelType = translateSupportResistance(contextLevel[1] ?? "", locale);
    const srType = translateSupportResistance(contextLevel[3] ?? "", locale);
    if (locale === "zh") {
      return `上下文${levelType}: ${contextLevel[2]} S/R ${srType} ${contextLevel[4]} 距入场 ${contextLevel[5]}；强度 ${contextLevel[6]}，回测 ${contextLevel[7]}，年龄 ${contextLevel[8]} 根K线，成交量 x${contextLevel[9]}`;
    }
    return `Контекстная ${levelType}: ${contextLevel[2]} S/R ${srType} ${contextLevel[4]} в ${contextLevel[5]} от входа; сила ${contextLevel[6]}, ретестов ${contextLevel[7]}, возраст ${contextLevel[8]} свечей, объём x${contextLevel[9]}`;
  }

  const regimeAlignmentReason = value.match(/^(long|short) vs (bullish|bearish|range|unknown) ([\w]+) \((weak|normal|strong|unknown)\)$/u);
  if (regimeAlignmentReason) {
    const side = regimeAlignmentReason[1]?.toUpperCase() ?? "";
    const regime = translateMarketEnum(regimeAlignmentReason[2] ?? "", locale);
    const timeframe = regimeAlignmentReason[3] ?? "";
    const strength = translateMarketEnum(regimeAlignmentReason[4] ?? "", locale);
    if (timeframe === "context") {
      if (locale === "zh") return `${side} 对上下文 ${regime} (${strength})`;
      return `${side} против контекста: ${regime} (${strength})`;
    }
    if (locale === "zh") return `${side} 对 ${timeframe} ${regime} (${strength})`;
    return `${side} против ${timeframe} ${regime} (${strength})`;
  }

  const emaChopReason = value.match(/^EMA200 chop score ([\d.]+): (\d+) crosses in (\d+) candles, near-ratio ([\d.]+%), slope ([\d.]+ ATR)$/u);
  if (emaChopReason) {
    if (locale === "zh") return `评分 ${emaChopReason[1]}, ${emaChopReason[2]} 次穿越 / ${emaChopReason[3]} 根K线, 接近比例 ${emaChopReason[4]}, 斜率 ${emaChopReason[5]}`;
    return `скор ${emaChopReason[1]}, ${emaChopReason[2]} пересечений за ${emaChopReason[3]} свечей, близость ${emaChopReason[4]}, наклон ${emaChopReason[5]}`;
  }

  const contextLevelReason = value.match(/^(.+) S\/R (support|resistance) (.+) is (.+ ATR) from entry; strength (\d+), retests (\d+), age (\d+) candles, volume x([\d.]+)$/u);
  if (contextLevelReason) {
    const srType = translateSupportResistance(contextLevelReason[2] ?? "", locale);
    if (locale === "zh") {
      return `${contextLevelReason[1]} S/R ${srType} ${contextLevelReason[3]} 距入场 ${contextLevelReason[4]}；强度 ${contextLevelReason[5]}，回测 ${contextLevelReason[6]}，年龄 ${contextLevelReason[7]} 根K线，成交量 x${contextLevelReason[8]}`;
    }
    return `${contextLevelReason[1]} S/R ${srType} ${contextLevelReason[3]} в ${contextLevelReason[4]} от входа; сила ${contextLevelReason[5]}, ретестов ${contextLevelReason[6]}, возраст ${contextLevelReason[7]} свечей, объём x${contextLevelReason[8]}`;
  }

  if (value === "Expected none context; using signal timeframe only") {
    return locale === "zh"
      ? "未设置上下文，仅使用信号周期"
      : "контекст не задан, используется только TF сигнала";
  }

  const regimeStrengthReason = value.match(/^Higher timeframe trend strength is (weak|normal|strong|unknown)$/u);
  if (regimeStrengthReason) {
    const strength = translateMarketEnum(regimeStrengthReason[1] ?? "", locale);
    if (locale === "zh") return `高周期趋势强度为 ${strength}`;
    return `тренд старшего TF ${strength}`;
  }

  const donchianWait = value.match(/^Volatility is compressed and price is near the (upper|lower) Donchian boundary; waiting for breakout volume and a candle close outside the range$/u);
  if (donchianWait) {
    const boundary = donchianWait[1] === "upper"
      ? locale === "zh" ? "上" : "верхней"
      : locale === "zh" ? "下" : "нижней";
    if (locale === "zh") return `波动率被压缩，价格接近 Donchian ${boundary}边界；等待突破成交量和区间外收盘`;
    return `Волатильность сжата, цена рядом с ${boundary} границей Donchian; ждём breakout-объём и закрытие свечи вне диапазона`;
  }

  const bbWidth = value.match(/^BB width percentile is compressed below ([\d.]+)$/u);
  if (bbWidth) {
    if (locale === "zh") return `BB 宽度百分位压缩到 ${bbWidth[1]} 以下`;
    return `Перцентиль ширины BB сжат ниже ${bbWidth[1]}`;
  }

  const measuredMove = value.match(/^Measured move target: (.+)$/u);
  if (measuredMove) {
    if (locale === "zh") return `量度目标: ${measuredMove[1]}`;
    return `Цель measured move: ${measuredMove[1]}`;
  }

  const squeezeRange = value.match(/^Squeeze range uses ([\d.]+ ATR); wider ranges are less clean$/u);
  if (squeezeRange) {
    if (locale === "zh") return `Squeeze 区间占用 ${squeezeRange[1]}；更宽的区间不够干净`;
    return `Squeeze-диапазон занимает ${squeezeRange[1]}; более широкие диапазоны менее чистые`;
  }

  const closeDonchian = value.match(/^Close finished outside the Donchian (range high|range low)$/u);
  if (closeDonchian) {
    const level = closeDonchian[1] === "range high" ? "range high" : "range low";
    if (locale === "zh") return `收盘在 Donchian ${level} 之外`;
    return `Закрытие вышло за Donchian ${level}`;
  }

  const breakoutVolume = value.match(/^Breakout volume is ([\d.]+x) average$/u);
  if (breakoutVolume) {
    if (locale === "zh") return `Breakout 成交量为平均值的 ${breakoutVolume[1]}`;
    return `Breakout-объём ${breakoutVolume[1]} от среднего`;
  }

  const strongClose = value.match(/^Close is in the directional part of the candle: (.+)$/u);
  if (strongClose) {
    if (locale === "zh") return `收盘位于K线方向性区域: ${strongClose[1]}`;
    return `Закрытие в направленной части свечи: ${strongClose[1]}`;
  }

  const breakoutBody = value.match(/^Breakout candle body is ([\d.]+ ATR)$/u);
  if (breakoutBody) {
    if (locale === "zh") return `Breakout K线实体为 ${breakoutBody[1]}`;
    return `Тело breakout-свечи ${breakoutBody[1]}`;
  }

  const rejectionWickRange = value.match(/^Rejection wick is (.+) of the candle range$/u);
  if (rejectionWickRange) {
    if (locale === "zh") return `拒绝影线占K线区间的 ${rejectionWickRange[1]}`;
    return `Rejection-фитиль занимает ${rejectionWickRange[1]} диапазона свечи`;
  }

  const rsiMomentum = value.match(/^RSI ([\d.]+) supports (upside|downside) momentum without extreme heat$/u);
  if (rsiMomentum) {
    const direction = rsiMomentum[2] === "upside"
      ? locale === "zh" ? "上行" : "вверх"
      : locale === "zh" ? "下行" : "вниз";
    if (locale === "zh") return `RSI ${rsiMomentum[1]} 支持${direction}动能，且没有极端过热`;
    return `RSI ${rsiMomentum[1]} поддерживает импульс ${direction} без экстремального перегрева`;
  }

  const enumLike = translateEnumLike(value, locale);
  if (enumLike !== value) return enumLike;

  return value;
}

const tradeTextMap: Record<string, Partial<Record<Locale, string>>> = {
  "ATR value is unavailable; using trailing percent fallback.": {
    ru: "ATR недоступен; используем резервный процентный трейлинг.",
    zh: "ATR 不可用；使用追踪百分比回退。"
  },
  "ADX/context is not a strong local trend against the reversal": {
    ru: "ADX/контекст не показывает сильный локальный тренд против разворота",
    zh: "ADX/上下文未显示反转方向上的强局部趋势"
  },
  "Close settled beyond the swept level; this may be a real breakout": {
    ru: "Закрытие закрепилось за снятым уровнем; это может быть настоящий breakout",
    zh: "收盘站上被扫水平之外；这可能是真突破"
  },
  "Close returns below swept low": {
    ru: "Закрытие возвращается ниже снятого low",
    zh: "收盘回到被扫低点下方"
  },
  "Level has equal-high/low style retests": {
    ru: "У уровня есть ретесты в стиле equal-high/low",
    zh: "该水平有 equal-high/low 类型的回测"
  },
  "Next candles fail to hold reclaim": {
    ru: "Следующие свечи не удерживают reclaim",
    zh: "后续K线未能守住重新收复位"
  },
  "Position notional is below exchange minimum notional.": {
    ru: "Номинал позиции ниже минимального значения биржи.",
    zh: "仓位名义价值低于交易所最小名义金额。"
  },
  "Position size is below exchange minimum order size.": {
    ru: "Размер позиции ниже минимального размера ордера на бирже.",
    zh: "仓位规模低于交易所最小下单量。"
  },
  "Price has not pulled back into the EMA20/EMA50 zone yet": {
    ru: "Цена ещё не откатилась в зону EMA20/EMA50",
    zh: "价格尚未回调到 EMA20/EMA50 区域"
  },
  "Price is chopping around EMA200; trend-continuation setups are less reliable": {
    ru: "Цена пилит вокруг EMA200; trend-continuation setup менее надёжен",
    zh: "价格围绕 EMA200 震荡；趋势延续 setup 可靠性较低"
  },
  "Price swept visible liquidity": {
    ru: "Цена сняла видимую ликвидность",
    zh: "价格扫过可见流动性"
  },
  "Pullback volume is at or below average": {
    ru: "Объём на pullback на уровне среднего или ниже",
    zh: "回调成交量等于或低于平均值"
  },
  "Signal is too close to higher-timeframe support/resistance": {
    ru: "Сигнал слишком близко к поддержке/сопротивлению старшего TF",
    zh: "信号离高周期支撑/阻力太近"
  },
  "Signal is against a strong higher-timeframe regime": {
    ru: "Сигнал против сильного режима старшего TF",
    zh: "信号逆着强高周期状态"
  },
  "Signal score is below the minimum tradable threshold.": {
    ru: "Скор сигнала ниже минимального торгового порога.",
    zh: "信号评分低于最小可交易阈值。"
  },
  "Strategy setup exists, but confirmation is incomplete": {
    ru: "Setup стратегии есть, но подтверждение неполное",
    zh: "策略 setup 已形成，但确认尚未完成"
  },
  "Sweep candle also broke micro structure toward reversal": {
    ru: "Sweep-свеча также пробила микроструктуру в сторону разворота",
    zh: "扫单K线也朝反转方向突破了微结构"
  },
  "Sweep has not reclaimed the level yet": {
    ru: "Sweep ещё не вернул уровень",
    zh: "扫单尚未重新收复该水平"
  },
  "Sweep lacks strong volume confirmation": {
    ru: "Sweep без сильного подтверждения объёмом",
    zh: "扫单缺少强成交量确认"
  },
  "Sweep low is broken again": {
    ru: "Sweep low снова пробит",
    zh: "扫低点再次被跌破"
  },
  "Swept level was reclaimed with a strong wick, close and volume": {
    ru: "Снятый уровень вернули сильным фитилем, закрытием и объёмом",
    zh: "被扫水平通过强影线、收盘和成交量重新收复"
  },
  "Swept level was reclaimed; waiting for stronger wick, volume or confirmation candle": {
    ru: "Снятый уровень вернули; ждём более сильный фитиль, объём или подтверждающую свечу",
    zh: "被扫水平已收复；等待更强影线、成交量或确认K线"
  },
  "Volume disappears after reclaim": {
    ru: "Объём исчезает после reclaim",
    zh: "重新收复后成交量消失"
  },
  "20-candle range is below its recent average": {
    ru: "Диапазон 20 свечей ниже своего недавнего среднего",
    zh: "20 根K线区间低于近期均值"
  },
  "ATR has not started expanding yet": {
    ru: "ATR ещё не начал расширяться",
    zh: "ATR 尚未开始扩张"
  },
  "ATR is below its 50-candle average": {
    ru: "ATR ниже среднего за 50 свечей",
    zh: "ATR 低于 50 根K线均值"
  },
  "ATR is expanding after compression": {
    ru: "ATR расширяется после сжатия",
    zh: "ATR 在压缩后开始扩张"
  },
  "Breakdown candle is fully retraced": {
    ru: "Breakdown-свеча полностью отретрейсилась",
    zh: "Breakdown K线被完全回撤"
  },
  "Breakout volume is below the configured confirmation multiplier": {
    ru: "Breakout-объём ниже заданного множителя подтверждения",
    zh: "Breakout 成交量低于配置的确认倍数"
  },
  "Close is not strong enough inside the breakout candle": {
    ru: "Закрытие недостаточно сильное внутри breakout-свечи",
    zh: "Breakout K线内的收盘不够强"
  },
  "Close returns inside the previous Donchian range": {
    ru: "Закрытие возвращается внутрь предыдущего диапазона Donchian",
    zh: "收盘回到前一个 Donchian 区间内"
  },
  "Price is pressing the Donchian boundary before confirmation": {
    ru: "Цена давит на границу Donchian до подтверждения",
    zh: "确认前价格压向 Donchian 边界"
  },
  "Price pierced the range but closed back inside": {
    ru: "Цена проколола диапазон, но закрылась обратно внутри",
    zh: "价格刺穿区间但收回内部"
  },
  "RSI above 75: late long breakout risk": {
    ru: "RSI выше 75: риск позднего LONG breakout",
    zh: "RSI 高于 75：LONG breakout 偏晚风险"
  },
  "RSI below 25: late short breakdown risk": {
    ru: "RSI ниже 25: риск позднего SHORT breakdown",
    zh: "RSI 低于 25：SHORT breakdown 偏晚风险"
  },
  "Volume disappears after breakdown": {
    ru: "Объём исчезает после breakdown",
    zh: "Breakdown 后成交量消失"
  }
};

function translateLiquidityDepth(value: string, locale: Locale): string {
  if (value === "current depth") return locale === "zh" ? "当前深度" : "текущую глубину";
  const match = value.match(/^(.+) of liquidity inside 1%$/u);
  if (!match) return value;
  return locale === "zh" ? `1% 内流动性的 ${match[1]}` : `${match[1]} ликвидности внутри 1%`;
}

function translateAboveBelow(value: string, locale: Locale): string {
  if (value === "above") return locale === "zh" ? "高于" : "выше";
  if (value === "below") return locale === "zh" ? "低于" : "ниже";
  return value;
}

function translateSupportResistance(value: string, locale: Locale): string {
  if (value === "support") return locale === "zh" ? "支撑" : "поддержка";
  if (value === "resistance") return locale === "zh" ? "阻力" : "сопротивление";
  return value;
}

function translateEnumLike(value: string, locale: Locale): string {
  const targets = value.match(/^(\d+) targets$/iu);
  if (targets) return locale === "zh" ? `${targets[1]} 个目标` : `${targets[1]} цели`;

  if (!/[A-Za-z]/.test(value)) return value;
  const separators = value.includes(" / ") ? " / " : value.includes(" vs ") ? " vs " : null;
  if (!separators) return value;

  const parts = value.split(separators);
  const translatedParts = parts.map((part) => translateMarketEnum(part, locale));
  if (translatedParts.every((part, index) => part === parts[index])) return value;
  return translatedParts.join(separators);
}

function translateNeuterLevel(value: string): string {
  const map: Record<string, string> = {
    High: "высокое",
    Low: "низкое",
    Medium: "среднее"
  };
  return map[value] ?? value.toLowerCase();
}

function translateMarketEnum(value: string, locale: Locale): string {
  const normalized = value.trim().toLowerCase().replaceAll("_", " ");
  const map: Record<string, Partial<Record<Locale, string>>> = {
    against: { ru: "против", zh: "逆向" },
    aligned: { ru: "по тренду", zh: "同向" },
    bearish: { ru: "медвежий", zh: "看跌" },
    bullish: { ru: "бычий", zh: "看涨" },
    confirmed: { ru: "подтверждён", zh: "已确认" },
    forming: { ru: "формируется", zh: "形成中" },
    major: { ru: "мажор", zh: "主流" },
    "mid alt": { ru: "средний альт", zh: "中型山寨" },
    mixed: { ru: "смешанный", zh: "混合" },
    normal: { ru: "нормальный", zh: "正常" },
    pending: { ru: "ожидание", zh: "等待" },
    range: { ru: "боковик", zh: "震荡" },
    ready: { ru: "готов", zh: "就绪" },
    strong: { ru: "сильный", zh: "强" },
    "trend up": { ru: "восходящий тренд", zh: "上升趋势" },
    "trend down": { ru: "нисходящий тренд", zh: "下降趋势" },
    chop: { ru: "пила", zh: "杂乱震荡" },
    "volatility compression": { ru: "сжатие волатильности", zh: "波动率压缩" },
    "volatility expansion": { ru: "расширение волатильности", zh: "波动率扩张" },
    "post impulse": { ru: "после импульса", zh: "冲击后" },
    "liquidity sweep zone": { ru: "зона снятия ликвидности", zh: "流动性扫单区域" },
    "news pump": { ru: "новостной памп", zh: "新闻拉升" },
    "liquidity vacuum": { ru: "вакуум ликвидности", zh: "流动性真空" },
    "market wide risk off": { ru: "общерыночный risk-off", zh: "全市场避险" },
    "market-wide risk-off": { ru: "общерыночный risk-off", zh: "全市场避险" },
    "news/pump mode": { ru: "новостной/pump режим", zh: "新闻/拉升模式" },
    unknown: { ru: "неизвестно", zh: "未知" },
    weak: { ru: "слабый", zh: "弱" }
  };
  return map[normalized]?.[locale] ?? value;
}

function translateAge(value: string, locale: Locale): string {
  if (locale === "en") return value;
  if (value === "waiting for data") return locale === "zh" ? "等待数据" : "ожидаем данные";
  if (value === "just now") return locale === "zh" ? "刚刚" : "только что";

  const unitMatch = value.match(/^(\d+)(ms|s|m|h)(?: ago)?$/u);
  if (!unitMatch) return value;

  const amount = unitMatch[1];
  const unit = unitMatch[2];
  if (locale === "zh") {
    const unitText = unit === "ms" ? "毫秒前" : unit === "s" ? "秒前" : unit === "m" ? "分钟前" : "小时前";
    return `${amount}${unitText}`;
  }
  const unitText = unit === "ms" ? "мс назад" : unit === "s" ? "с назад" : unit === "m" ? "м назад" : "ч назад";
  return `${amount}${unitText}`;
}
