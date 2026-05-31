import { Bell, BookOpen, Gauge, KeyRound, Radio, RefreshCw, Send, Shield, SlidersHorizontal, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/Badge";
import type {
  AlertRule,
  AlertRuleDraft,
  ExchangeConnection,
  ExchangeConnectionDraft,
  MarketPairOption,
  RiskManagementSettings,
  RiskProfileName,
  StopLossMode,
  StrategyConfig,
  StrategyConfigPatch,
  TrailingMode,
  VirtualFeeModel,
  VirtualRiskMode,
  VirtualSlippageModel,
  UserProfile,
  UserSettingsPatch,
  VirtualSimulationLevel
} from "@/features/server-state/types";
import type { RadarConfig, RiskProtectionMode, RiskStateResponse } from "@/types";

interface SettingsPageProps {
  config: RadarConfig | null;
  availablePairs: MarketPairOption[];
  strategyConfigs: StrategyConfig[];
  alertRules: AlertRule[];
  exchangeConnections: ExchangeConnection[];
  userProfile: UserProfile | null;
  riskState: RiskStateResponse | null;
  busy: boolean;
  onCreateAlert: (draft: AlertRuleDraft) => Promise<unknown>;
  onToggleAlert: (alertId: string, isEnabled: boolean) => Promise<unknown>;
  onDeleteAlert: (alertId: string) => Promise<unknown>;
  onTestAlert: (alertId: string) => Promise<unknown>;
  onCreateExchangeConnection: (draft: ExchangeConnectionDraft) => Promise<unknown>;
  onToggleExchangeConnection: (connectionId: string, isActive: boolean) => Promise<unknown>;
  onDeleteExchangeConnection: (connectionId: string) => Promise<unknown>;
  onTestExchangeConnection: (connectionId: string) => Promise<unknown>;
  onSyncExchangeConnection: (connectionId: string) => Promise<unknown>;
  onSelectSimulationLevel: (simulationLevel: VirtualSimulationLevel) => Promise<unknown>;
  onUpdateStrategyConfig: (configId: string, patch: StrategyConfigPatch) => Promise<unknown>;
  onUpdateRiskManagement: (patch: UserSettingsPatch) => Promise<unknown>;
}

const SIMULATION_LEVELS: Array<{
  value: VirtualSimulationLevel;
  label: string;
  caption: string;
  status: "active" | "stub";
}> = [
  {
    value: "mvp",
    label: "MVP",
    caption: "Depth, spread, slippage",
    status: "active"
  },
  {
    value: "advanced",
    label: "Advanced",
    caption: "Queue, fees, liquidity",
    status: "stub"
  },
  {
    value: "pro",
    label: "Pro",
    caption: "Replay, Monte Carlo",
    status: "stub"
  }
];

const RISK_PROFILES: Array<{
  value: RiskProfileName;
  label: string;
  caption: string;
}> = [
  { value: "conservative", label: "Conservative", caption: "Lower risk limits" },
  { value: "balanced", label: "Balanced", caption: "Default profile" },
  { value: "aggressive", label: "Aggressive", caption: "Wider risk budget" },
  { value: "custom", label: "Custom", caption: "Manual limits" }
];

const STRATEGY_TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"];
const MAX_BODY_ATR_DEFAULTS: Record<string, number> = {
  trend_pullback_continuation: 2.0,
  volatility_squeeze_breakout: 2.5,
  liquidity_sweep_reversal: 2.0
};
const MAX_RANGE_ATR_DEFAULTS: Record<string, number> = {
  trend_pullback_continuation: 3.0,
  volatility_squeeze_breakout: 3.5,
  liquidity_sweep_reversal: 3.8
};
const RR_TARGET_DEFAULTS: Record<string, "final" | "nearest"> = {
  trend_pullback_continuation: "final",
  volatility_squeeze_breakout: "final",
  liquidity_sweep_reversal: "nearest"
};
const SQUEEZE_BREAKOUT_FIELD_LABELS: Array<{
  key: string;
  label: string;
  step: string;
  min: string;
  max?: string;
  defaultValue: number;
}> = [
  { key: "bb_width_percentile_threshold", label: "BB squeeze %", step: "1", min: "0", max: "100", defaultValue: 20 },
  { key: "volume_spike_multiplier", label: "Volume x", step: "0.1", min: "0", defaultValue: 1.5 },
  { key: "min_close_position", label: "Close strength", step: "0.05", min: "0", max: "1", defaultValue: 0.7 },
  { key: "max_breakout_wick_ratio", label: "Max wick", step: "0.05", min: "0", max: "1", defaultValue: 0.35 },
  { key: "max_squeeze_range_atr", label: "Range ATR", step: "0.1", min: "1", defaultValue: 5 }
];

const LIQUIDITY_SWEEP_FIELD_LABELS: Array<{
  key: string;
  label: string;
  step: string;
  min: string;
  max?: string;
  defaultValue: number;
}> = [
  { key: "min_sweep_wick_ratio", label: "Min wick", step: "0.05", min: "0", max: "1", defaultValue: 0.45 },
  { key: "sweep_volume_spike_multiplier", label: "Sweep volume x", step: "0.1", min: "0", defaultValue: 1.3 },
  { key: "confirmation_volume_spike", label: "Confirm volume x", step: "0.1", min: "0", defaultValue: 1.1 },
  { key: "sweep_aggressive_close_position", label: "Close strength", step: "0.05", min: "0", max: "1", defaultValue: 0.6 },
  { key: "sweep_stop_atr", label: "Stop ATR", step: "0.1", min: "0", defaultValue: 0.3 },
  { key: "min_level_retests", label: "Level retests", step: "1", min: "0", defaultValue: 2 },
  { key: "sweep_level_confluence_atr", label: "HTF level ATR", step: "0.1", min: "0", defaultValue: 0.5 }
];

type RiskNumericField =
  | "risk_per_trade_percent"
  | "min_rr_ratio"
  | "max_daily_loss_percent"
  | "max_weekly_loss_percent"
  | "max_account_drawdown_percent"
  | "max_open_risk_percent"
  | "max_correlated_risk_percent"
  | "max_spread_bps"
  | "max_slippage_bps"
  | "max_price_deviation_bps"
  | "max_orderbook_liquidity_ratio"
  | "default_stop_loss_percent"
  | "atr_period"
  | "atr_multiplier"
  | "tp1_r_multiple"
  | "tp2_r_multiple"
  | "tp3_r_multiple"
  | "tp1_close_percent"
  | "tp2_close_percent"
  | "tp3_close_percent"
  | "move_sl_to_breakeven_after_r"
  | "breakeven_offset_percent"
  | "trailing_atr_multiplier"
  | "trailing_stop_percent"
  | "max_leverage"
  | "min_liquidation_buffer_percent"
  | "spot_risk_per_trade_percent"
  | "spot_max_position_size_percent"
  | "futures_risk_per_trade_percent"
  | "futures_max_leverage"
  | "futures_max_open_risk_percent"
  | "virtual_risk_per_trade_percent"
  | "virtual_starting_balance"
  | "max_risk_boost";

const RISK_PROFILE_FIELD_LABELS: Array<{
  key: RiskNumericField;
  label: string;
  suffix: string;
  step: string;
}> = [
  { key: "risk_per_trade_percent", label: "Risk / trade", suffix: "%", step: "0.05" },
  { key: "max_daily_loss_percent", label: "Daily Stop-Loss", suffix: "%", step: "0.1" },
  { key: "max_weekly_loss_percent", label: "Weekly Stop-Loss", suffix: "%", step: "0.5" },
  { key: "max_account_drawdown_percent", label: "Max drawdown", suffix: "%", step: "0.5" },
  { key: "max_open_risk_percent", label: "Open risk cap", suffix: "%", step: "0.1" },
  { key: "max_correlated_risk_percent", label: "Correlated risk", suffix: "%", step: "0.1" }
];

const TRADE_RULE_FIELD_LABELS: Array<{
  key: RiskNumericField;
  label: string;
  suffix: string;
  step: string;
}> = [
  { key: "min_rr_ratio", label: "Min R:R", suffix: "R", step: "0.1" },
  { key: "max_spread_bps", label: "Max spread", suffix: "bps", step: "1" },
  { key: "max_slippage_bps", label: "Max slippage", suffix: "bps", step: "5" },
  { key: "max_price_deviation_bps", label: "Max price drift", suffix: "bps", step: "5" },
  { key: "max_orderbook_liquidity_ratio", label: "Max book use", suffix: "x", step: "0.05" }
];

const STOP_LOSS_MODES: Array<{
  value: StopLossMode;
  label: string;
  caption: string;
}> = [
  { value: "fixed_percent", label: "Fixed %", caption: "Simple MVP stop" },
  { value: "atr", label: "ATR", caption: "Volatility-based" },
  { value: "structure", label: "Structure", caption: "Signal invalidation" }
];

const STOP_LOSS_FIELD_LABELS: Array<{
  key: RiskNumericField;
  label: string;
  suffix: string;
  step: string;
}> = [
  { key: "default_stop_loss_percent", label: "Fixed stop", suffix: "%", step: "0.1" },
  { key: "atr_period", label: "ATR period", suffix: "", step: "1" },
  { key: "atr_multiplier", label: "ATR multiplier", suffix: "x", step: "0.25" }
];

const TAKE_PROFIT_FIELD_LABELS: Array<{
  key: RiskNumericField;
  label: string;
  suffix: string;
  step: string;
}> = [
  { key: "tp1_r_multiple", label: "TP1", suffix: "R", step: "0.25" },
  { key: "tp2_r_multiple", label: "TP2", suffix: "R", step: "0.25" },
  { key: "tp3_r_multiple", label: "TP3", suffix: "R", step: "0.25" }
];

const PARTIAL_TAKE_PROFIT_FIELD_LABELS: Array<{
  key: RiskNumericField;
  label: string;
  suffix: string;
  step: string;
}> = [
  { key: "tp1_close_percent", label: "TP1 close", suffix: "%", step: "5" },
  { key: "tp2_close_percent", label: "TP2 close", suffix: "%", step: "5" },
  { key: "tp3_close_percent", label: "TP3 close", suffix: "%", step: "5" }
];

const BREAKEVEN_FIELD_LABELS: Array<{
  key: RiskNumericField;
  label: string;
  suffix: string;
  step: string;
}> = [
  { key: "move_sl_to_breakeven_after_r", label: "Move after", suffix: "R", step: "0.25" },
  { key: "breakeven_offset_percent", label: "Offset", suffix: "%", step: "0.01" }
];

const TRAILING_MODES: Array<{
  value: TrailingMode;
  label: string;
  caption: string;
}> = [
  { value: "atr", label: "ATR", caption: "Swing-friendly trailing" },
  { value: "percent", label: "Percent", caption: "Scalping trailing" },
  { value: "structure", label: "Structure", caption: "Trail behind market structure" }
];

const TRAILING_FIELD_LABELS: Array<{
  key: RiskNumericField;
  label: string;
  suffix: string;
  step: string;
}> = [
  { key: "trailing_atr_multiplier", label: "ATR trail", suffix: "x", step: "0.25" },
  { key: "trailing_stop_percent", label: "Percent trail", suffix: "%", step: "0.1" }
];

const FUTURES_FIELD_LABELS: Array<{
  key: RiskNumericField;
  label: string;
  suffix: string;
  step: string;
}> = [
  { key: "max_leverage", label: "Max leverage", suffix: "x", step: "1" },
  { key: "min_liquidation_buffer_percent", label: "Liq. buffer", suffix: "%", step: "0.25" }
];

const TRADE_TYPE_FIELD_LABELS: Array<{
  key: RiskNumericField;
  label: string;
  suffix: string;
  step: string;
}> = [
  { key: "spot_risk_per_trade_percent", label: "Spot risk", suffix: "%", step: "0.05" },
  { key: "spot_max_position_size_percent", label: "Spot max size", suffix: "%", step: "0.5" },
  { key: "futures_risk_per_trade_percent", label: "Futures risk", suffix: "%", step: "0.05" },
  { key: "futures_max_leverage", label: "Futures max lev.", suffix: "x", step: "1" },
  { key: "futures_max_open_risk_percent", label: "Futures open risk", suffix: "%", step: "0.1" },
  { key: "virtual_risk_per_trade_percent", label: "Virtual risk", suffix: "%", step: "0.05" },
  { key: "virtual_starting_balance", label: "Virtual balance", suffix: "USDT", step: "100" }
];

const SPOT_TRADE_TYPE_FIELD_LABELS = TRADE_TYPE_FIELD_LABELS.filter((field) =>
  field.key === "spot_risk_per_trade_percent" || field.key === "spot_max_position_size_percent"
);

const FUTURES_TRADE_TYPE_FIELD_LABELS = TRADE_TYPE_FIELD_LABELS.filter((field) =>
  field.key === "futures_risk_per_trade_percent" ||
  field.key === "futures_max_leverage" ||
  field.key === "futures_max_open_risk_percent"
);

const VIRTUAL_TRADE_TYPE_FIELD_LABELS = TRADE_TYPE_FIELD_LABELS.filter((field) =>
  field.key === "virtual_risk_per_trade_percent" || field.key === "virtual_starting_balance"
);

const VIRTUAL_RISK_MODES: Array<{ value: VirtualRiskMode; label: string }> = [
  { value: "same_as_real", label: "Same as real" },
  { value: "custom", label: "Separate" }
];

const VIRTUAL_SLIPPAGE_MODELS: Array<{ value: VirtualSlippageModel; label: string }> = [
  { value: "none", label: "None" },
  { value: "fixed_percent", label: "Fixed" },
  { value: "spread_based", label: "Spread" },
  { value: "orderbook_based", label: "Orderbook" },
  { value: "volatility_based", label: "Volatility" }
];

const VIRTUAL_FEE_MODELS: Array<{ value: VirtualFeeModel; label: string }> = [
  { value: "exchange_based", label: "Exchange" },
  { value: "manual", label: "Manual" }
];

type RiskSettingsTab = "profile" | "rules" | "futures" | "virtual" | "guide";

const RISK_SETTINGS_TABS: Array<{ value: RiskSettingsTab; label: string }> = [
  { value: "profile", label: "Risk Profile" },
  { value: "rules", label: "Trade Rules" },
  { value: "futures", label: "Futures Protection" },
  { value: "virtual", label: "Virtual Trading" },
  { value: "guide", label: "Guide" }
];

const STRATEGY_MULTIPLIER_LABELS: Record<string, string> = {
  trend_following: "Trend-following",
  trend_pullback_continuation: "Trend pullback",
  breakout: "Breakout",
  scalping: "Scalping",
  mean_reversion: "Mean reversion",
  smart_money_setup: "Smart Money",
  news_event_trade: "News/Event"
};

interface RiskGuideItem {
  title: string;
  body: string;
  tip?: string;
}

interface RiskGuideSection {
  title: string;
  intro: string;
  items: RiskGuideItem[];
}

const RISK_BLOCKER_GUIDE: RiskGuideItem[] = [
  {
    title: "Open risk cap",
    body: "Сумма риска по уже открытым позициям плюс новый риск выше лимита. Часто это причина, когда в virtual уже накопились позиции.",
    tip: "Закройте старые virtual-позиции, снизьте Risk / trade или поднимите Open risk cap только для тестового профиля."
  },
  {
    title: "Correlated risk",
    body: "Новая сделка усиливает тот же кластер: например несколько L1 long или majors short. Это не отдельный риск, а один directional risk.",
    tip: "Для обучения можно поднять Correlated risk, но в real лучше оставлять его ниже Open risk cap."
  },
  {
    title: "Min R:R",
    body: "Backend пересчитывает R:R от реальной цены входа, стопа, комиссий и проскальзывания. Если цена ушла, бумажный 2R может стать 1.3R.",
    tip: "Для MVP-тестов допустимо временно поставить 1.5R, но для real 2R остается более дисциплинированным уровнем."
  },
  {
    title: "Spread, slippage, price drift",
    body: "Если bid/ask, ожидаемое исполнение или уход цены от сигнала ломают план сделки, risk-gate блокирует вход.",
    tip: "Расширяйте эти лимиты осторожно: они напрямую увеличивают фактический убыток при стопе."
  },
  {
    title: "Futures liquidation guard",
    body: "Для futures сделка должна иметь стоп раньше ликвидации и достаточный буфер. Плечо уменьшает маржу, но не уменьшает риск сделки.",
    tip: "Снижайте leverage или увеличивайте дистанцию до стопа, если liquidation guard не проходит."
  }
];

const RISK_GUIDE_SECTIONS: RiskGuideSection[] = [
  {
    title: "1. Risk Profile",
    intro: "Главный блок отвечает за размер риска и общие лимиты аккаунта. Здесь система решает, сколько можно потерять, а не сколько купить.",
    items: [
      {
        title: "Conservative / Balanced / Aggressive / Custom",
        body: "Пресеты быстро задают набор лимитов. Conservative сужает риск, Balanced является базовым профилем, Aggressive дает больше свободы, Custom открывает ручное редактирование всех полей.",
        tip: "Если нужно понять, почему сделки не проходят, переключайтесь в Custom и меняйте по одному лимиту."
      },
      {
        title: "Risk / trade",
        body: "Процент equity, который пользователь готов потерять при срабатывании стопа. Это не размер позиции. Backend считает position size от этого риска, стопа, комиссий и проскальзывания.",
        tip: "Если позиции слишком большие или быстро забивается Open risk cap, уменьшайте это значение."
      },
      {
        title: "Daily Stop-Loss",
        body: "Дневной лимит убытка. После достижения лимита real entries должны переходить в close-only, чтобы можно было только закрывать или уменьшать риск.",
        tip: "Значение 0 выключает именно этот лимит. Для real лучше выключать только осознанно."
      },
      {
        title: "Weekly Stop-Loss",
        body: "Недельный лимит убытка. Защищает от серии плохих дней, когда дневной стоп несколько раз подряд уже был достигнут.",
        tip: "Значение 0 выключает недельную блокировку."
      },
      {
        title: "Max drawdown",
        body: "Максимальная просадка от peak equity. Если лимит достигнут, protection state может снизить риск, включить virtual-only или заблокировать новые входы.",
        tip: "Значение 0 выключает лимит просадки, но peak equity все равно сохраняется."
      },
      {
        title: "Open risk cap",
        body: "Максимальный суммарный риск всех открытых позиций. Если уже открыто несколько сделок по 1%, новая сделка добавляет еще риск к общей корзине.",
        tip: "Значение 0 выключает этот лимит. Если сейчас не открывается ни одна сделка, первым делом проверьте Open risk."
      },
      {
        title: "Correlated risk",
        body: "Лимит по связанным активам и направлению: majors, L1, L2, meme, DeFi, AI и другие группы. BTC long, ETH long и SOL long не считаются полностью независимыми.",
        tip: "Значение 0 выключает кластерный лимит. Для real лучше держать его ниже общего Open risk cap."
      },
      {
        title: "Fees included / Slippage included",
        body: "Комиссии и проскальзывание входят в effective risk per unit. Это уменьшает разрешенный position size, зато не дает превысить риск при реальном исполнении.",
        tip: "В MVP для новичков эти флаги намеренно включены как защитный стандарт."
      },
      {
        title: "Stop required / TP required",
        body: "Без стопа risk-gate не может посчитать position size. Take-profit нужен для проверки минимального Risk/Reward.",
        tip: "Если стратегия еще не умеет давать стоп или TP, такая сделка должна оставаться только аналитическим сигналом."
      },
      {
        title: "Spot risk",
        body: "Отдельный риск на spot-сделку. Spot не имеет liquidation price, но все равно учитывает стоп, комиссии, проскальзывание и максимальный размер позиции.",
        tip: "Spot max size ограничивает долю депозита, которую можно занять одной spot-позицией."
      },
      {
        title: "Adaptive risk",
        body: "Автоматическое снижение риска после серии убытков или просадки. Adaptive multiplier умножает финальный риск до расчета позиции.",
        tip: "Risk increase после прибыли лучше держать выключенным для MVP и новичков."
      }
    ]
  },
  {
    title: "2. Trade Rules",
    intro: "Эти настройки проверяют качество сделки перед входом: достаточно ли прибыли к риску и не испортилось ли исполнение.",
    items: [
      {
        title: "Min R:R",
        body: "Минимальное качество сделки по соотношению цели и стопа. Backend пересматривает это качество по актуальной цене входа.",
        tip: "Значение 0 выключает эту проверку. Если рынок ушел от entry, backend все равно покажет изменившийся риск в карточке."
      },
      {
        title: "Max spread",
        body: "Максимально допустимая ширина bid/ask. Широкий spread означает дорогой вход и выход.",
        tip: "Значение 0 выключает spread-блокировку. Для low-cap лучше тестировать отдельно в virtual."
      },
      {
        title: "Max slippage",
        body: "Ожидаемое ухудшение цены исполнения. Оно добавляется к effective risk, поэтому влияет на position size и блокировки.",
        tip: "Значение 0 выключает slippage-блокировку. Если часто блокирует slippage, проверьте orderbook depth и размер позиции."
      },
      {
        title: "Max price drift",
        body: "Максимальное отклонение текущей цены от сигнальной цены. Защищает от входа после того, как сигнал уже устарел.",
        tip: "Значение 0 выключает блокировку по уходу цены от сигнала."
      },
      {
        title: "Max book use",
        body: "Доля видимой ликвидности стакана, которую может потребить расчетный размер позиции. Чем выше доля, тем больше market impact.",
        tip: "Значение 0 выключает лимит использования стакана, но отсутствие стакана для real все равно остается риском."
      },
      {
        title: "Stop-loss mode",
        body: "Fixed % ставит простой стоп от entry. ATR учитывает волатильность монеты. Structure берет стоп из структуры сигнала: swing, support/resistance, liquidity zone.",
        tip: "Для MVP проще Fixed %, для крипты на разных монетах чаще лучше ATR или Structure."
      },
      {
        title: "Fixed stop / ATR period / ATR multiplier",
        body: "Fixed stop задает дистанцию стопа в процентах. ATR period задает период расчета волатильности. ATR multiplier умножает ATR и получает стоп-дистанцию.",
        tip: "Чем дальше стоп, тем меньше position size при том же Risk / trade."
      },
      {
        title: "TP1 / TP2 / TP3",
        body: "Цели выхода по уровням риска. Они помогают заранее описать план фиксации прибыли.",
        tip: "Средняя цель обычно используется как базовая проверка качества сделки."
      },
      {
        title: "Partial take-profit",
        body: "Разрешает закрывать позицию частями: например TP1 30%, TP2 40%, TP3 30%. Это превращает сигнал в полный exit plan.",
        tip: "Сумма процентов должна логически давать 100%, иначе план выхода будет неоднозначным."
      },
      {
        title: "Breakeven",
        body: "Move after задает, после какого R переносить стоп в безубыток. Offset добавляет небольшой запас, чтобы покрыть комиссии.",
        tip: "Небольшой offset нужен, чтобы безубыток не съедали комиссии."
      },
      {
        title: "Trailing stop",
        body: "Трейлинг двигает защитный стоп вслед за ценой. ATR подходит для swing, percent для скальпинга, structure для Price Action.",
        tip: "Включайте трейлинг только если стратегия действительно предполагает удержание позиции после TP1/TP2."
      },
      {
        title: "Strategy multipliers",
        body: "Множители снижают или оставляют базовый риск в зависимости от стратегии. Scalping может быть 0.5x, breakout 0.75x, trend-following 1.0x.",
        tip: "Чем рискованнее стратегия, тем ниже должен быть ее множитель."
      }
    ]
  },
  {
    title: "3. Futures Protection",
    intro: "Futures требуют отдельной защиты, потому что liquidation price может наступить раньше стоп-лосса.",
    items: [
      {
        title: "Max leverage",
        body: "Максимальное плечо, которое разрешает приложение. Плечо уменьшает required margin, но не уменьшает риск до стопа.",
        tip: "Для MVP дефолт 3x. Новым пользователям не стоит давать больше 5x без явного подтверждения."
      },
      {
        title: "Liq. buffer",
        body: "Минимальная дистанция между stop-loss и liquidation price. Для long ликвидация должна быть ниже стопа, для short выше стопа.",
        tip: "Значение 0 выключает минимальный буфер, но проверка ликвидации раньше стопа остается защитой."
      },
      {
        title: "Liquidation buffer required",
        body: "Если включено, risk-gate не должен считать futures-сделку безопасной без проверки ликвидации.",
        tip: "Для production real trading это обязательная защита."
      },
      {
        title: "Futures risk",
        body: "Отдельный риск на futures-сделку. Обычно ниже общего Risk / trade, потому что добавляются ликвидация, funding и резкие движения.",
        tip: "Если real/virtual futures слишком часто блокируются, начинайте с Futures open risk и Open risk cap, а не с leverage."
      },
      {
        title: "Futures open risk",
        body: "Отдельный лимит открытого риска для futures. Он может быть жестче общего лимита аккаунта.",
        tip: "Значение 0 выключает futures open risk cap."
      }
    ]
  },
  {
    title: "4. Virtual Trading",
    intro: "Virtual должен имитировать реальную торговлю, но может иметь отдельный учебный профиль риска.",
    items: [
      {
        title: "Same as real / Separate",
        body: "Same as real использует реальные риск-настройки. Separate позволяет тестировать мягче или агрессивнее без изменения real-профиля.",
        tip: "Если сейчас все блокируется в paper trading, временно выберите Separate и настройте virtual-лимиты отдельно."
      },
      {
        title: "Virtual risk",
        body: "Риск на одну virtual-сделку. Работает только в Separate mode.",
        tip: "Для обучения можно поставить 0.5-1%, а не 10%, чтобы Open risk cap не забивался за одну-две сделки."
      },
      {
        title: "Virtual balance",
        body: "Стартовый баланс virtual-аккаунта. От него считаются risk amount, margin, daily/open risk и размер позиции.",
        tip: "Если баланс маленький, даже небольшие старые позиции могут выглядеть как огромный open risk."
      },
      {
        title: "Slippage model",
        body: "None не добавляет проскальзывание, Fixed добавляет постоянный буфер, Spread использует bid/ask, Orderbook оценивает глубину, Volatility учитывает волатильность.",
        tip: "Для MVP лучший учебный режим: spread-based плюс фиксированный буфер."
      },
      {
        title: "Fee model",
        body: "Exchange берет комиссии из Bybit fee cache. Manual использует ручной fallback.",
        tip: "Если fee cache недоступен, backend использует conservative fallback и показывает warning."
      },
      {
        title: "Realistic execution",
        body: "Virtual учитывает spread, fee, slippage, depth и fill ratio. Это делает paper trading ближе к real flow.",
        tip: "Для проверки стратегии лучше оставлять включенным, даже если из-за этого часть сделок блокируется."
      }
    ]
  }
];

export function SettingsPage({
  config,
  availablePairs,
  strategyConfigs,
  alertRules,
  exchangeConnections,
  userProfile,
  riskState,
  busy,
  onCreateAlert,
  onToggleAlert,
  onDeleteAlert,
  onTestAlert,
  onCreateExchangeConnection,
  onToggleExchangeConnection,
  onDeleteExchangeConnection,
  onTestExchangeConnection,
  onSyncExchangeConnection,
  onSelectSimulationLevel,
  onUpdateStrategyConfig,
  onUpdateRiskManagement
}: SettingsPageProps) {
  const [pairId, setPairId] = useState("");
  const [conditionType, setConditionType] = useState("price_above");
  const [targetPrice, setTargetPrice] = useState("");
  const supportedExchanges = useMemo(
    () => config?.exchanges?.length ? config.exchanges : ["bybit"],
    [config]
  );
  const [exchangeCode, setExchangeCode] = useState(supportedExchanges[0] ?? "bybit");
  const [connectionLabel, setConnectionLabel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [apiPassphrase, setApiPassphrase] = useState("");
  const [riskTab, setRiskTab] = useState<RiskSettingsTab>("profile");
  const selectedPair = useMemo(
    () => availablePairs.find((pair) => pair.id === pairId) ?? availablePairs[0] ?? null,
    [availablePairs, pairId]
  );
  const availableStrategyExchanges = useMemo(
    () => dedupeStrings([
      ...supportedExchanges,
      ...availablePairs.map((pair) => pair.exchange)
    ]),
    [availablePairs, supportedExchanges]
  );
  const simulationLevel = userProfile?.settings.virtual_trading.simulation_level ?? "mvp";
  const riskManagement = userProfile?.settings.risk_management ?? defaultRiskManagement();
  const riskManagementKey = [
    riskManagement.risk_profile,
    riskManagement.risk_per_trade_percent,
    riskManagement.min_rr_ratio,
    riskManagement.max_daily_loss_percent,
    riskManagement.max_weekly_loss_percent,
    riskManagement.max_account_drawdown_percent,
    riskManagement.max_open_risk_percent,
    riskManagement.max_correlated_risk_percent,
    riskManagement.max_spread_bps,
    riskManagement.max_slippage_bps,
    riskManagement.max_price_deviation_bps,
    riskManagement.max_orderbook_liquidity_ratio,
    riskManagement.stop_loss_required,
    riskManagement.take_profit_required,
    riskManagement.stop_loss_mode,
    riskManagement.default_stop_loss_percent,
    riskManagement.atr_period,
    riskManagement.atr_multiplier,
    riskManagement.take_profit_mode,
    riskManagement.tp1_r_multiple,
    riskManagement.tp2_r_multiple,
    riskManagement.tp3_r_multiple,
    riskManagement.partial_take_profit_enabled,
    riskManagement.tp1_close_percent,
    riskManagement.tp2_close_percent,
    riskManagement.tp3_close_percent,
    riskManagement.move_sl_to_breakeven_after_r,
    riskManagement.breakeven_offset_percent,
    riskManagement.trailing_stop_enabled,
    riskManagement.trailing_mode,
    riskManagement.trailing_atr_multiplier,
    riskManagement.trailing_stop_percent,
    riskManagement.max_leverage,
    riskManagement.min_liquidation_buffer_percent,
    riskManagement.liquidation_buffer_required,
    riskManagement.spot_risk_per_trade_percent,
    riskManagement.spot_max_position_size_percent,
    riskManagement.spot_stop_required,
    riskManagement.futures_risk_per_trade_percent,
    riskManagement.futures_max_leverage,
    riskManagement.futures_max_open_risk_percent,
    riskManagement.futures_liquidation_buffer_required,
    riskManagement.virtual_risk_mode,
    riskManagement.virtual_risk_per_trade_percent,
    riskManagement.virtual_starting_balance,
    riskManagement.virtual_slippage_model,
    riskManagement.virtual_fee_model,
    riskManagement.virtual_trading_uses_realistic_execution,
    JSON.stringify(riskManagement.strategy_risk_multipliers),
    riskManagement.auto_reduce_risk_after_losses,
    riskManagement.allow_risk_increase_after_profit,
    riskManagement.increase_risk_after_profit_streak,
    riskManagement.max_risk_boost
  ].join(":");
  const [riskDraftState, setRiskDraftState] = useState<{
    key: string;
    value: RiskManagementSettings;
  } | null>(null);
  const riskDraft = riskDraftState?.key === riskManagementKey ? riskDraftState.value : riskManagement;
  const customRiskEnabled = riskManagement.risk_profile === "custom";

  function updateRiskDraft(values: Partial<RiskManagementSettings>) {
    setRiskDraftState({
      key: riskManagementKey,
      value: {
        ...riskDraft,
        ...values,
        risk_profile: "custom"
      }
    });
  }

  function updateStrategyRiskMultiplier(strategy: string, multiplier: number) {
    updateRiskDraft({
      strategy_risk_multipliers: {
        ...riskDraft.strategy_risk_multipliers,
        [strategy]: multiplier
      }
    });
  }

  async function handleCreateAlert() {
    if (!selectedPair || !targetPrice) return;
    await onCreateAlert({
      pair_id: selectedPair.id,
      condition_type: conditionType,
      condition_body: { price: Number(targetPrice) },
      channels: ["websocket"],
      is_enabled: true
    });
    setTargetPrice("");
  }

  async function handleCreateExchangeConnection() {
    if (!exchangeCode || !connectionLabel || !apiKey || !apiSecret) return;
    await onCreateExchangeConnection({
      exchange_code: exchangeCode,
      label: connectionLabel,
      account_type: "spot",
      api_key: apiKey,
      api_secret: apiSecret,
      api_passphrase: apiPassphrase || null,
      permissions: { read: true, trade: false }
    });
    setConnectionLabel("");
    setApiKey("");
    setApiSecret("");
    setApiPassphrase("");
  }

  async function handleToggleStrategyPair(configItem: StrategyConfig, pair: MarketPairOption, checked: boolean) {
    const pairScope = { exchange: pair.exchange, symbol: pair.symbol };
    const nextPairs = checked
      ? [...configItem.pairs, pairScope]
      : configItem.pairs.filter((item) => !(item.exchange === pair.exchange && item.symbol === pair.symbol));
    await onUpdateStrategyConfig(configItem.id, { pairs: dedupeStrategyPairs(nextPairs) });
  }

  async function handleToggleStrategyExchange(configItem: StrategyConfig, exchange: string, checked: boolean) {
    const nextExchanges = checked
      ? [...configItem.exchanges, exchange]
      : configItem.exchanges.filter((item) => item !== exchange);
    if (!checked && nextExchanges.length === 0) return;
    await onUpdateStrategyConfig(configItem.id, { exchanges: dedupeStrings(nextExchanges) });
  }

  async function handleToggleStrategyTimeframe(configItem: StrategyConfig, timeframe: string, checked: boolean) {
    const nextTimeframes = checked
      ? [...configItem.timeframes, timeframe]
      : configItem.timeframes.filter((item) => item !== timeframe);
    if (!checked && nextTimeframes.length === 0) return;
    await onUpdateStrategyConfig(configItem.id, { timeframes: dedupeStrings(nextTimeframes) });
  }

  async function handleStrategyContextTimeframe(configItem: StrategyConfig, signalTimeframe: string, contextTimeframe: string) {
    const nextMap = { ...getContextTimeframeMap(configItem.params) };
    if (contextTimeframe) {
      nextMap[signalTimeframe] = contextTimeframe;
    } else {
      delete nextMap[signalTimeframe];
    }
    await onUpdateStrategyConfig(configItem.id, { params: { context_timeframe_map: nextMap } });
  }

  async function handleUseAllPairs(configItem: StrategyConfig) {
    await onUpdateStrategyConfig(configItem.id, { pairs: [] });
  }

  async function handleStrategyParamBlur(configItem: StrategyConfig, key: string, rawValue: string) {
    const value = Number(rawValue);
    if (!Number.isFinite(value) || value < 0) return;
    if (Number(configItem.params[key] ?? 0) === value) return;
    await onUpdateStrategyConfig(configItem.id, { params: { [key]: value } });
  }

  async function handleStrategyRiskNumberBlur(configItem: StrategyConfig, key: string, rawValue: string) {
    const value = Number(rawValue);
    if (!Number.isFinite(value) || value < 0) return;
    if (Number(configItem.risk_settings[key] ?? 0) === value) return;
    await onUpdateStrategyConfig(configItem.id, { risk_settings: { [key]: value } });
  }

  async function handleStrategyRiskValue(configItem: StrategyConfig, key: string, value: string | boolean) {
    if (configItem.risk_settings[key] === value) return;
    await onUpdateStrategyConfig(configItem.id, { risk_settings: { [key]: value } });
  }

  async function handleSelectRiskProfile(profile: RiskProfileName) {
    await onUpdateRiskManagement({ risk_profile: profile });
  }

  async function handleSaveCustomRisk() {
    await onUpdateRiskManagement({
      risk_profile: "custom",
      risk_management: {
        risk_profile: "custom",
        risk_per_trade_percent: riskDraft.risk_per_trade_percent,
        min_rr_ratio: riskDraft.min_rr_ratio,
        max_daily_loss_percent: riskDraft.max_daily_loss_percent,
        max_weekly_loss_percent: riskDraft.max_weekly_loss_percent,
        max_account_drawdown_percent: riskDraft.max_account_drawdown_percent,
        max_open_risk_percent: riskDraft.max_open_risk_percent,
        max_correlated_risk_percent: riskDraft.max_correlated_risk_percent,
        max_spread_bps: riskDraft.max_spread_bps,
        max_slippage_bps: riskDraft.max_slippage_bps,
        max_price_deviation_bps: riskDraft.max_price_deviation_bps,
        max_orderbook_liquidity_ratio: riskDraft.max_orderbook_liquidity_ratio,
        stop_loss_required: riskDraft.stop_loss_required,
        take_profit_required: riskDraft.take_profit_required,
        stop_loss_mode: riskDraft.stop_loss_mode,
        default_stop_loss_percent: riskDraft.default_stop_loss_percent,
        atr_period: riskDraft.atr_period,
        atr_multiplier: riskDraft.atr_multiplier,
        take_profit_mode: riskDraft.take_profit_mode,
        tp1_r_multiple: riskDraft.tp1_r_multiple,
        tp2_r_multiple: riskDraft.tp2_r_multiple,
        tp3_r_multiple: riskDraft.tp3_r_multiple,
        partial_take_profit_enabled: riskDraft.partial_take_profit_enabled,
        tp1_close_percent: riskDraft.tp1_close_percent,
        tp2_close_percent: riskDraft.tp2_close_percent,
        tp3_close_percent: riskDraft.tp3_close_percent,
        move_sl_to_breakeven_after_r: riskDraft.move_sl_to_breakeven_after_r,
        breakeven_offset_percent: riskDraft.breakeven_offset_percent,
        trailing_stop_enabled: riskDraft.trailing_stop_enabled,
        trailing_mode: riskDraft.trailing_mode,
        trailing_atr_multiplier: riskDraft.trailing_atr_multiplier,
        trailing_stop_percent: riskDraft.trailing_stop_percent,
        max_leverage: riskDraft.max_leverage,
        min_liquidation_buffer_percent: riskDraft.min_liquidation_buffer_percent,
        liquidation_buffer_required: riskDraft.liquidation_buffer_required,
        spot_risk_per_trade_percent: riskDraft.spot_risk_per_trade_percent,
        spot_max_position_size_percent: riskDraft.spot_max_position_size_percent,
        spot_stop_required: riskDraft.spot_stop_required,
        futures_risk_per_trade_percent: riskDraft.futures_risk_per_trade_percent,
        futures_max_leverage: riskDraft.futures_max_leverage,
        futures_max_open_risk_percent: riskDraft.futures_max_open_risk_percent,
        futures_liquidation_buffer_required: riskDraft.futures_liquidation_buffer_required,
        virtual_risk_mode: riskDraft.virtual_risk_mode,
        virtual_risk_per_trade_percent: riskDraft.virtual_risk_per_trade_percent,
        virtual_starting_balance: riskDraft.virtual_starting_balance,
        virtual_slippage_model: riskDraft.virtual_slippage_model,
        virtual_fee_model: riskDraft.virtual_fee_model,
        virtual_trading_uses_realistic_execution: riskDraft.virtual_trading_uses_realistic_execution,
        strategy_risk_multipliers: riskDraft.strategy_risk_multipliers,
        auto_reduce_risk_after_losses: riskDraft.auto_reduce_risk_after_losses,
        allow_risk_increase_after_profit: riskDraft.allow_risk_increase_after_profit,
        increase_risk_after_profit_streak: riskDraft.increase_risk_after_profit_streak,
        max_risk_boost: riskDraft.max_risk_boost
      }
    });
  }

  return (
    <section className="wide-panel">
      <div className="page-head">
        <div>
          <span className="muted">Settings</span>
          <h1>Radar settings</h1>
        </div>
      </div>

      <div className="settings-grid">
        <div className="settings-section">
          <div className="section-title"><Radio size={18} /><h3>Exchanges</h3></div>
          <div className="inline-form stacked">
            <select
              aria-label="Exchange"
              disabled={busy}
              onChange={(event) => setExchangeCode(event.target.value)}
              value={exchangeCode}
            >
              {supportedExchanges.map((exchange) => (
                <option key={exchange} value={exchange}>{exchange}</option>
              ))}
            </select>
            <input
              aria-label="Connection label"
              disabled={busy}
              onChange={(event) => setConnectionLabel(event.target.value)}
              placeholder="Label"
              value={connectionLabel}
            />
            <input
              aria-label="API key"
              disabled={busy}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder="API key"
              value={apiKey}
            />
            <input
              aria-label="API secret"
              disabled={busy}
              onChange={(event) => setApiSecret(event.target.value)}
              placeholder="API secret"
              type="password"
              value={apiSecret}
            />
            <input
              aria-label="API passphrase"
              disabled={busy}
              onChange={(event) => setApiPassphrase(event.target.value)}
              placeholder="Passphrase"
              type="password"
              value={apiPassphrase}
            />
            <button
              className="primary-action"
              disabled={busy || !connectionLabel || !apiKey || !apiSecret}
              onClick={handleCreateExchangeConnection}
              type="button"
            >
              <KeyRound size={16} />
              Connect
            </button>
          </div>
          <div className="connection-list">
            {exchangeConnections.length === 0 ? <div className="empty-state compact-empty">No exchange connections</div> : null}
            {exchangeConnections.map((connection) => (
              <div className="connection-row" key={connection.id}>
                <div>
                  <strong>{connection.label}</strong>
                  <span>{connection.exchange_code}:{connection.account_type}</span>
                  <code>{shortKeyRef(connection.key_ref)}</code>
                </div>
                <Badge tone={connection.status === "active" ? "green" : "red"}>{connection.status}</Badge>
                <label className="toggle-row compact-toggle">
                  <input
                    checked={connection.status === "active"}
                    disabled={busy}
                    onChange={(event) => onToggleExchangeConnection(connection.id, event.target.checked)}
                    type="checkbox"
                  />
                  <span>{connection.status === "active" ? "On" : "Off"}</span>
                </label>
                <button className="icon-button compact" disabled={busy} onClick={() => onTestExchangeConnection(connection.id)} title="Test" type="button">
                  <Send size={15} />
                </button>
                <button className="icon-button compact" disabled={busy} onClick={() => onSyncExchangeConnection(connection.id)} title="Sync" type="button">
                  <RefreshCw size={15} />
                </button>
                <button className="icon-button compact" disabled={busy} onClick={() => onDeleteExchangeConnection(connection.id)} title="Delete" type="button">
                  <Trash2 size={15} />
                </button>
              </div>
            ))}
          </div>
        </div>

        <div className="settings-section strategy-settings-section">
          <div className="section-title"><SlidersHorizontal size={18} /><h3>Strategies</h3></div>
          <div className="strategy-config-list">
            {strategyConfigs.length === 0 ? <div className="empty-state compact-empty">No strategy configs</div> : null}
            {strategyConfigs.map((strategyConfig) => {
              const strategyExchangeOptions = dedupeStrings([
                ...availableStrategyExchanges,
                ...strategyConfig.exchanges
              ]);
              const contextTimeframeMap = getContextTimeframeMap(strategyConfig.params);
              return (
                <div className="strategy-config-row" key={strategyConfig.id}>
                <div className="strategy-config-header">
                  <div>
                    <strong>{strategyConfig.strategy_name}</strong>
                    <span>
                      {strategyConfig.pairs.length ? `${strategyConfig.pairs.length} selected pairs` : "All pairs - quality filter on"}
                      {" · "}
                      {strategyConfig.exchanges.join(", ")}
                      {" · "}
                      {strategyConfig.timeframes.join(", ")}
                    </span>
                  </div>
                  <label className="toggle-row compact-toggle">
                    <input
                      checked={strategyConfig.is_enabled}
                      disabled={busy}
                      onChange={(event) => onUpdateStrategyConfig(strategyConfig.id, { is_enabled: event.target.checked })}
                      type="checkbox"
                    />
                    <span>{strategyConfig.is_enabled ? "On" : "Off"}</span>
                  </label>
                </div>

                <div className="strategy-scope-grid">
                  <div>
                    <span>Exchanges</span>
                    <div className="strategy-chip-row">
                      {strategyExchangeOptions.map((exchange) => {
                        const checked = strategyConfig.exchanges.includes(exchange);
                        return (
                          <label className="strategy-scope-chip" key={`${strategyConfig.id}:exchange:${exchange}`}>
                            <input
                              checked={checked}
                              disabled={busy || (checked && strategyConfig.exchanges.length <= 1)}
                              onChange={(event) => handleToggleStrategyExchange(strategyConfig, exchange, event.target.checked)}
                              type="checkbox"
                            />
                            <span>{exchange}</span>
                          </label>
                        );
                      })}
                    </div>
                  </div>
                  <div>
                    <span>Timeframes</span>
                    <div className="strategy-chip-row">
                      {STRATEGY_TIMEFRAMES.map((timeframe) => {
                        const checked = strategyConfig.timeframes.includes(timeframe);
                        return (
                          <label className="strategy-scope-chip" key={`${strategyConfig.id}:timeframe:${timeframe}`}>
                            <input
                              checked={checked}
                              disabled={busy || (checked && strategyConfig.timeframes.length <= 1)}
                              onChange={(event) => handleToggleStrategyTimeframe(strategyConfig, timeframe, event.target.checked)}
                              type="checkbox"
                            />
                            <span>{timeframe}</span>
                          </label>
                        );
                      })}
                    </div>
                  </div>
                  <div className="strategy-context-grid">
                    <span>Context TF</span>
                    <div className="strategy-context-row">
                      {strategyConfig.timeframes.map((timeframe) => (
                        <label className="strategy-context-select" key={`${strategyConfig.id}:context:${timeframe}`}>
                          <span>{timeframe}</span>
                          <select
                            disabled={busy}
                            onChange={(event) => handleStrategyContextTimeframe(strategyConfig, timeframe, event.target.value)}
                            value={contextTimeframeMap[timeframe] ?? ""}
                          >
                            <option value="">Default</option>
                            {contextTimeframeOptions(timeframe).map((option) => (
                              <option key={option} value={option}>{option}</option>
                            ))}
                          </select>
                        </label>
                      ))}
                    </div>
                  </div>
                </div>

                <div className="strategy-quality-grid">
                  <label>
                    <span>Min 24h volume</span>
                    <input
                      defaultValue={String(Number(strategyConfig.params.min_24h_volume_quote ?? 10_000_000))}
                      disabled={busy}
                      inputMode="decimal"
                      key={`${strategyConfig.id}:min_24h_volume_quote:${String(strategyConfig.params.min_24h_volume_quote ?? "")}`}
                      onBlur={(event) => handleStrategyParamBlur(strategyConfig, "min_24h_volume_quote", event.target.value)}
                      type="number"
                    />
                  </label>
                  <label>
                    <span>Max spread bps</span>
                    <input
                      defaultValue={String(Number(strategyConfig.params.max_spread_bps ?? 25))}
                      disabled={busy}
                      inputMode="decimal"
                      key={`${strategyConfig.id}:max_spread_bps:${String(strategyConfig.params.max_spread_bps ?? "")}`}
                      onBlur={(event) => handleStrategyParamBlur(strategyConfig, "max_spread_bps", event.target.value)}
                      type="number"
                    />
                  </label>
                  <label>
                    <span>Min history</span>
                    <input
                      defaultValue={String(Number(strategyConfig.params.min_history ?? 50))}
                      disabled={busy}
                      inputMode="numeric"
                      key={`${strategyConfig.id}:min_history:${String(strategyConfig.params.min_history ?? "")}`}
                      onBlur={(event) => handleStrategyParamBlur(strategyConfig, "min_history", event.target.value)}
                      type="number"
                    />
                  </label>
                  <label>
                    <span>Min S/R ATR</span>
                    <input
                      defaultValue={String(Number(strategyConfig.params.context_obstacle_min_atr ?? 1))}
                      disabled={busy}
                      inputMode="decimal"
                      key={`${strategyConfig.id}:context_obstacle_min_atr:${String(strategyConfig.params.context_obstacle_min_atr ?? "")}`}
                      min="0"
                      onBlur={(event) => handleStrategyParamBlur(strategyConfig, "context_obstacle_min_atr", event.target.value)}
                      step="0.1"
                      type="number"
                    />
                  </label>
                  <label>
                    <span>S/R strength</span>
                    <input
                      defaultValue={String(Number(strategyConfig.params.context_level_min_strength ?? 25))}
                      disabled={busy}
                      inputMode="decimal"
                      key={`${strategyConfig.id}:context_level_min_strength:${String(strategyConfig.params.context_level_min_strength ?? "")}`}
                      max="100"
                      min="0"
                      onBlur={(event) => handleStrategyParamBlur(strategyConfig, "context_level_min_strength", event.target.value)}
                      step="1"
                      type="number"
                    />
                  </label>
                  <label>
                    <span>Max body ATR</span>
                    <input
                      defaultValue={String(Number(strategyConfig.params.max_body_atr ?? defaultMaxBodyAtr(strategyConfig.strategy_code)))}
                      disabled={busy}
                      inputMode="decimal"
                      key={`${strategyConfig.id}:max_body_atr:${String(strategyConfig.params.max_body_atr ?? "")}`}
                      min="0.5"
                      onBlur={(event) => handleStrategyParamBlur(strategyConfig, "max_body_atr", event.target.value)}
                      step="0.1"
                      type="number"
                    />
                  </label>
                  <label>
                    <span>Max range ATR</span>
                    <input
                      defaultValue={String(Number(strategyConfig.params.max_range_atr ?? defaultMaxRangeAtr(strategyConfig.strategy_code)))}
                      disabled={busy}
                      inputMode="decimal"
                      key={`${strategyConfig.id}:max_range_atr:${String(strategyConfig.params.max_range_atr ?? "")}`}
                      min="1"
                      onBlur={(event) => handleStrategyParamBlur(strategyConfig, "max_range_atr", event.target.value)}
                      step="0.1"
                      type="number"
                    />
                  </label>
                  {strategyConfig.strategy_code === "volatility_squeeze_breakout"
                    ? SQUEEZE_BREAKOUT_FIELD_LABELS.map((field) => (
                        <label key={`${strategyConfig.id}:${field.key}`}>
                          <span>{field.label}</span>
                          <input
                            defaultValue={String(Number(strategyConfig.params[field.key] ?? field.defaultValue))}
                            disabled={busy}
                            inputMode="decimal"
                            key={`${strategyConfig.id}:${field.key}:${String(strategyConfig.params[field.key] ?? "")}`}
                            max={field.max}
                            min={field.min}
                            onBlur={(event) => handleStrategyParamBlur(strategyConfig, field.key, event.target.value)}
                            step={field.step}
                            type="number"
                          />
                        </label>
                      ))
                    : null}
                  {strategyConfig.strategy_code === "liquidity_sweep_reversal"
                    ? LIQUIDITY_SWEEP_FIELD_LABELS.map((field) => (
                        <label key={`${strategyConfig.id}:${field.key}`}>
                          <span>{field.label}</span>
                          <input
                            defaultValue={String(Number(strategyConfig.params[field.key] ?? field.defaultValue))}
                            disabled={busy}
                            inputMode="decimal"
                            key={`${strategyConfig.id}:${field.key}:${String(strategyConfig.params[field.key] ?? "")}`}
                            max={field.max}
                            min={field.min}
                            onBlur={(event) => handleStrategyParamBlur(strategyConfig, field.key, event.target.value)}
                            step={field.step}
                            type="number"
                          />
                        </label>
                      ))
                    : null}
                  <label>
                    <span>Min RR</span>
                    <input
                      defaultValue={String(Number(strategyConfig.risk_settings.min_rr_ratio ?? riskManagement.min_rr_ratio ?? 2))}
                      disabled={busy}
                      inputMode="decimal"
                      key={`${strategyConfig.id}:min_rr_ratio:${String(strategyConfig.risk_settings.min_rr_ratio ?? riskManagement.min_rr_ratio ?? "")}`}
                      min="0"
                      onBlur={(event) => handleStrategyRiskNumberBlur(strategyConfig, "min_rr_ratio", event.target.value)}
                      step="0.1"
                      type="number"
                    />
                  </label>
                  <label>
                    <span>RR target</span>
                    <select
                      disabled={busy}
                      onChange={(event) => handleStrategyRiskValue(strategyConfig, "rr_target", event.target.value)}
                      value={String(strategyConfig.risk_settings.rr_target ?? defaultRrTarget(strategyConfig.strategy_code))}
                    >
                      <option value="final">Final target</option>
                      <option value="nearest">Nearest target</option>
                    </select>
                  </label>
                  <label className="strategy-risk-toggle">
                    <span>Hide low-RR cards</span>
                    <input
                      checked={Boolean(strategyConfig.risk_settings.hide_failed_rr_signals)}
                      disabled={busy}
                      onChange={(event) => handleStrategyRiskValue(strategyConfig, "hide_failed_rr_signals", event.target.checked)}
                      type="checkbox"
                    />
                  </label>
                </div>

                <div className="strategy-pair-toolbar">
                  <button className="secondary-action compact-action" disabled={busy || strategyConfig.pairs.length === 0} onClick={() => handleUseAllPairs(strategyConfig)} type="button">
                    All pairs
                  </button>
                  <span>{strategyConfig.pairs.length ? "Manual pair scope bypasses automatic quality exclusion." : "Automatic quality filter excludes bad instruments before strategy setup."}</span>
                </div>

                <div className="strategy-pair-grid">
                  {availablePairs.map((pair) => {
                    const checked = strategyConfig.pairs.some((item) => item.exchange === pair.exchange && item.symbol === pair.symbol);
                    const active = pair.status === "active";
                    return (
                      <label className="strategy-pair-option" key={`${strategyConfig.id}:${pair.id}`}>
                        <input
                          checked={checked}
                          disabled={busy || !active}
                          onChange={(event) => handleToggleStrategyPair(strategyConfig, pair, event.target.checked)}
                          type="checkbox"
                        />
                        <span>{pair.exchange}:{pair.symbol}</span>
                        {!active ? <Badge tone="yellow">{pair.status}</Badge> : null}
                      </label>
                    );
                  })}
                </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="settings-section risk-management-section">
          <div className="section-title"><Shield size={18} /><h3>Risk management</h3></div>
          <div className="risk-settings-tabs" role="tablist" aria-label="Risk management sections">
            {RISK_SETTINGS_TABS.map((tab) => (
              <button
                aria-selected={riskTab === tab.value}
                className={riskTab === tab.value ? "active" : ""}
                key={tab.value}
                onClick={() => setRiskTab(tab.value)}
                role="tab"
                type="button"
              >
                {tab.label}
              </button>
            ))}
          </div>
          {riskState ? (
            <div className="risk-state-strip">
              <Badge tone={riskProtectionTone(riskState.protection_state)}>
                Protection: {riskState.protection_state}
              </Badge>
              {riskState.close_only ? <Badge tone="yellow">Close-only</Badge> : null}
              <span>Daily {formatRiskUsageValue(riskState.daily_loss_percent, riskDraft.max_daily_loss_percent)}</span>
              <span>Weekly {formatRiskUsageValue(riskState.weekly_loss_percent, riskDraft.max_weekly_loss_percent)}</span>
              <span>Drawdown {formatRiskUsageValue(riskState.account_drawdown_percent, riskState.max_account_drawdown_percent)}</span>
              <span>Open {formatRiskUsageValue(riskState.open_risk_percent, riskState.max_open_risk_percent)}</span>
              <span>Correlated {formatRiskUsageValue(riskState.correlated_risk_percent, riskState.max_correlated_risk_percent)}</span>
              <span>Rules {riskState.exchange_rule_status}</span>
              <span>Adaptive x{riskState.adaptive_multiplier.toFixed(2)}</span>
            </div>
          ) : null}

          {riskTab === "profile" ? (
            <>
              <div className="segmented">
                {RISK_PROFILES.map((profile) => (
                  <button
                    className={riskManagement.risk_profile === profile.value ? "active" : ""}
                    disabled={busy}
                    key={profile.value}
                    onClick={() => handleSelectRiskProfile(profile.value)}
                    title={profile.caption}
                    type="button"
                  >
                    {profile.label}
                  </button>
                ))}
              </div>
              <div className="risk-settings-grid">
                {RISK_PROFILE_FIELD_LABELS.map((field) => (
                  <label className="risk-setting-field" key={field.key}>
                    <span>{field.label}</span>
                    <div>
                      <input
                        aria-label={field.label}
                        disabled={busy || !customRiskEnabled}
                        inputMode="decimal"
                        min="0"
                        onChange={(event) => updateRiskDraft({ [field.key]: Number(event.target.value) })}
                        step={field.step}
                        type="number"
                        value={riskDraft[field.key]}
                      />
                      <small>{field.suffix}</small>
                    </div>
                  </label>
                ))}
              </div>
              <div className="risk-inclusion-strip">
                <Badge tone="blue">Fees included</Badge>
                <Badge tone="blue">Slippage included</Badge>
                <Badge tone={riskDraft.stop_loss_required ? "green" : "yellow"}>Stop required</Badge>
                <Badge tone={riskDraft.take_profit_required ? "green" : "yellow"}>TP required</Badge>
              </div>
              <div className="risk-plan-block">
                <div className="risk-plan-heading">
                  <strong>Spot risk</strong>
                </div>
                <div className="risk-settings-grid">
                  {SPOT_TRADE_TYPE_FIELD_LABELS.map((field) => (
                    <label className="risk-setting-field" key={field.key}>
                      <span>{field.label}</span>
                      <div>
                        <input
                          aria-label={field.label}
                          disabled={busy || !customRiskEnabled}
                          inputMode="decimal"
                          min="0"
                          onChange={(event) => updateRiskDraft({ [field.key]: Number(event.target.value) })}
                          step={field.step}
                          type="number"
                          value={riskDraft[field.key]}
                        />
                        <small>{field.suffix}</small>
                      </div>
                    </label>
                  ))}
                </div>
                <label className="risk-checkbox-row">
                  <input
                    checked={riskDraft.spot_stop_required}
                    disabled={busy || !customRiskEnabled}
                    onChange={(event) => updateRiskDraft({ spot_stop_required: event.target.checked })}
                    type="checkbox"
                  />
                  <span>Spot stop required</span>
                </label>
              </div>
              <div className="risk-plan-block">
                <div className="risk-plan-heading">
                  <strong>Adaptive risk</strong>
                </div>
                <label className="risk-checkbox-row">
                  <input
                    checked={riskDraft.auto_reduce_risk_after_losses}
                    disabled={busy || !customRiskEnabled}
                    onChange={(event) => updateRiskDraft({ auto_reduce_risk_after_losses: event.target.checked })}
                    type="checkbox"
                  />
                  <span>Auto reduce after losses</span>
                </label>
                <label className="risk-checkbox-row">
                  <input
                    checked={riskDraft.allow_risk_increase_after_profit}
                    disabled={busy || !customRiskEnabled}
                    onChange={(event) => updateRiskDraft({ allow_risk_increase_after_profit: event.target.checked })}
                    type="checkbox"
                  />
                  <span>Allow risk increase</span>
                </label>
                <div className="risk-settings-grid">
                  <label className="risk-setting-field">
                    <span>Max risk boost</span>
                    <div>
                      <input
                        aria-label="Max risk boost"
                        disabled={busy || !customRiskEnabled || !riskDraft.allow_risk_increase_after_profit}
                        inputMode="decimal"
                        min="1"
                        onChange={(event) => updateRiskDraft({ max_risk_boost: Number(event.target.value) })}
                        step="0.05"
                        type="number"
                        value={riskDraft.max_risk_boost}
                      />
                      <small>x</small>
                    </div>
                  </label>
                </div>
              </div>
            </>
          ) : null}

          {riskTab === "rules" ? (
            <>
              <div className="risk-settings-grid compact-risk-grid">
                {TRADE_RULE_FIELD_LABELS.map((field) => (
                  <label className="risk-setting-field" key={field.key}>
                    <span>{field.label}</span>
                    <div>
                      <input
                        aria-label={field.label}
                        disabled={busy || !customRiskEnabled}
                        inputMode="decimal"
                        min="0"
                        onChange={(event) => updateRiskDraft({ [field.key]: Number(event.target.value) })}
                        step={field.step}
                        type="number"
                        value={riskDraft[field.key]}
                      />
                      <small>{field.suffix}</small>
                    </div>
                  </label>
                ))}
              </div>
              <div className="risk-plan-block">
                <div className="risk-plan-heading">
                  <strong>Stop-loss</strong>
                </div>
                <div className="risk-mode-grid">
                  {STOP_LOSS_MODES.map((mode) => (
                    <button
                      className={riskDraft.stop_loss_mode === mode.value ? "active" : ""}
                      disabled={busy || !customRiskEnabled}
                      key={mode.value}
                      onClick={() => updateRiskDraft({ stop_loss_mode: mode.value })}
                      title={mode.caption}
                      type="button"
                    >
                      {mode.label}
                    </button>
                  ))}
                </div>
                <div className="risk-settings-grid compact-risk-grid">
                  {STOP_LOSS_FIELD_LABELS.map((field) => {
                    const atrField = field.key === "atr_period" || field.key === "atr_multiplier";
                    return (
                      <label className="risk-setting-field" key={field.key}>
                        <span>{field.label}</span>
                        <div>
                          <input
                            aria-label={field.label}
                            disabled={busy || !customRiskEnabled || (atrField && riskDraft.stop_loss_mode !== "atr")}
                            inputMode="decimal"
                            min="0"
                            onChange={(event) => updateRiskDraft({ [field.key]: Number(event.target.value) })}
                            step={field.step}
                            type="number"
                            value={riskDraft[field.key]}
                          />
                          <small>{field.suffix}</small>
                        </div>
                      </label>
                    );
                  })}
                </div>
              </div>
              <div className="risk-plan-block">
                <div className="risk-plan-heading">
                  <strong>Take-profit</strong>
                  <Badge tone="purple">Risk multiple</Badge>
                </div>
                <div className="risk-settings-grid">
                  {TAKE_PROFIT_FIELD_LABELS.map((field) => (
                    <label className="risk-setting-field" key={field.key}>
                      <span>{field.label}</span>
                      <div>
                        <input
                          aria-label={field.label}
                          disabled={busy || !customRiskEnabled}
                          inputMode="decimal"
                          min="0"
                          onChange={(event) => updateRiskDraft({ [field.key]: Number(event.target.value) })}
                          step={field.step}
                          type="number"
                          value={riskDraft[field.key]}
                        />
                        <small>{field.suffix}</small>
                      </div>
                    </label>
                  ))}
                </div>
                <label className="risk-checkbox-row">
                  <input
                    checked={riskDraft.partial_take_profit_enabled}
                    disabled={busy || !customRiskEnabled}
                    onChange={(event) => updateRiskDraft({ partial_take_profit_enabled: event.target.checked })}
                    type="checkbox"
                  />
                  <span>Partial take-profit</span>
                </label>
                <div className="risk-settings-grid">
                  {PARTIAL_TAKE_PROFIT_FIELD_LABELS.map((field) => (
                    <label className="risk-setting-field" key={field.key}>
                      <span>{field.label}</span>
                      <div>
                        <input
                          aria-label={field.label}
                          disabled={busy || !customRiskEnabled || !riskDraft.partial_take_profit_enabled}
                          inputMode="decimal"
                          min="0"
                          onChange={(event) => updateRiskDraft({ [field.key]: Number(event.target.value) })}
                          step={field.step}
                          type="number"
                          value={riskDraft[field.key]}
                        />
                        <small>{field.suffix}</small>
                      </div>
                    </label>
                  ))}
                </div>
              </div>
              <div className="risk-plan-block">
                <div className="risk-plan-heading">
                  <strong>Breakeven</strong>
                </div>
                <div className="risk-settings-grid">
                  {BREAKEVEN_FIELD_LABELS.map((field) => (
                    <label className="risk-setting-field" key={field.key}>
                      <span>{field.label}</span>
                      <div>
                        <input
                          aria-label={field.label}
                          disabled={busy || !customRiskEnabled}
                          inputMode="decimal"
                          min="0"
                          onChange={(event) => updateRiskDraft({ [field.key]: Number(event.target.value) })}
                          step={field.step}
                          type="number"
                          value={riskDraft[field.key]}
                        />
                        <small>{field.suffix}</small>
                      </div>
                    </label>
                  ))}
                </div>
              </div>
              <div className="risk-plan-block">
                <div className="risk-plan-heading">
                  <strong>Trailing stop</strong>
                </div>
                <label className="risk-checkbox-row">
                  <input
                    checked={riskDraft.trailing_stop_enabled}
                    disabled={busy || !customRiskEnabled}
                    onChange={(event) => updateRiskDraft({ trailing_stop_enabled: event.target.checked })}
                    type="checkbox"
                  />
                  <span>Enabled</span>
                </label>
                <div className="risk-mode-grid">
                  {TRAILING_MODES.map((mode) => (
                    <button
                      className={riskDraft.trailing_mode === mode.value ? "active" : ""}
                      disabled={busy || !customRiskEnabled || !riskDraft.trailing_stop_enabled}
                      key={mode.value}
                      onClick={() => updateRiskDraft({ trailing_mode: mode.value })}
                      title={mode.caption}
                      type="button"
                    >
                      {mode.label}
                    </button>
                  ))}
                </div>
                <div className="risk-settings-grid">
                  {TRAILING_FIELD_LABELS.map((field) => {
                    const atrField = field.key === "trailing_atr_multiplier";
                    const percentField = field.key === "trailing_stop_percent";
                    return (
                      <label className="risk-setting-field" key={field.key}>
                        <span>{field.label}</span>
                        <div>
                          <input
                            aria-label={field.label}
                            disabled={
                              busy ||
                              !customRiskEnabled ||
                              !riskDraft.trailing_stop_enabled ||
                              (atrField && riskDraft.trailing_mode !== "atr") ||
                              (percentField && riskDraft.trailing_mode === "atr")
                            }
                            inputMode="decimal"
                            min="0"
                            onChange={(event) => updateRiskDraft({ [field.key]: Number(event.target.value) })}
                            step={field.step}
                            type="number"
                            value={riskDraft[field.key]}
                          />
                          <small>{field.suffix}</small>
                        </div>
                      </label>
                    );
                  })}
                </div>
              </div>
              <div className="risk-plan-block">
                <div className="risk-plan-heading">
                  <strong>Strategy multipliers</strong>
                  <Badge tone="blue">Risk multiplier</Badge>
                </div>
                <div className="strategy-multiplier-grid">
                  {Object.entries(riskDraft.strategy_risk_multipliers).map(([strategy, multiplier]) => (
                    <label className="strategy-multiplier-field" key={strategy}>
                      <span>{STRATEGY_MULTIPLIER_LABELS[strategy] ?? strategy.replaceAll("_", " ")}</span>
                      <input
                        aria-label={`${STRATEGY_MULTIPLIER_LABELS[strategy] ?? strategy} multiplier`}
                        disabled={busy || !customRiskEnabled}
                        inputMode="decimal"
                        min="0"
                        onChange={(event) => updateStrategyRiskMultiplier(strategy, Number(event.target.value))}
                        step="0.05"
                        type="number"
                        value={Number(multiplier)}
                      />
                    </label>
                  ))}
                </div>
              </div>
            </>
          ) : null}

          {riskTab === "futures" ? (
            <>
              <div className="risk-plan-block">
                <div className="risk-plan-heading">
                  <strong>Futures protection</strong>
                </div>
                <label className="risk-checkbox-row">
                  <input
                    checked={riskDraft.liquidation_buffer_required}
                    disabled={busy || !customRiskEnabled}
                    onChange={(event) => updateRiskDraft({ liquidation_buffer_required: event.target.checked })}
                    type="checkbox"
                  />
                  <span>Liquidation buffer required</span>
                </label>
                <div className="risk-settings-grid">
                  {FUTURES_FIELD_LABELS.map((field) => (
                    <label className="risk-setting-field" key={field.key}>
                      <span>{field.label}</span>
                      <div>
                        <input
                          aria-label={field.label}
                          disabled={busy || !customRiskEnabled}
                          inputMode="decimal"
                          min="0"
                          onChange={(event) => updateRiskDraft({ [field.key]: Number(event.target.value) })}
                          step={field.step}
                          type="number"
                          value={riskDraft[field.key]}
                        />
                        <small>{field.suffix}</small>
                      </div>
                    </label>
                  ))}
                </div>
              </div>
              <div className="risk-plan-block">
                <div className="risk-plan-heading">
                  <strong>Futures risk budget</strong>
                </div>
                <div className="risk-settings-grid">
                  {FUTURES_TRADE_TYPE_FIELD_LABELS.map((field) => (
                    <label className="risk-setting-field" key={field.key}>
                      <span>{field.label}</span>
                      <div>
                        <input
                          aria-label={field.label}
                          disabled={busy || !customRiskEnabled}
                          inputMode="decimal"
                          min="0"
                          onChange={(event) => updateRiskDraft({ [field.key]: Number(event.target.value) })}
                          step={field.step}
                          type="number"
                          value={riskDraft[field.key]}
                        />
                        <small>{field.suffix}</small>
                      </div>
                    </label>
                  ))}
                </div>
                <label className="risk-checkbox-row">
                  <input
                    checked={riskDraft.futures_liquidation_buffer_required}
                    disabled={busy || !customRiskEnabled}
                    onChange={(event) => updateRiskDraft({ futures_liquidation_buffer_required: event.target.checked })}
                    type="checkbox"
                  />
                  <span>Futures liquidation buffer required</span>
                </label>
              </div>
            </>
          ) : null}

          {riskTab === "virtual" ? (
            <>
              <div className="risk-plan-block">
                <div className="risk-plan-heading">
                  <strong>Virtual risk budget</strong>
                </div>
                <div className="risk-mode-grid two-option-grid">
                  {VIRTUAL_RISK_MODES.map((mode) => (
                    <button
                      className={riskDraft.virtual_risk_mode === mode.value ? "active" : ""}
                      disabled={busy || !customRiskEnabled}
                      key={mode.value}
                      onClick={() => updateRiskDraft({ virtual_risk_mode: mode.value })}
                      type="button"
                    >
                      {mode.label}
                    </button>
                  ))}
                </div>
                <div className="risk-settings-grid">
                  {VIRTUAL_TRADE_TYPE_FIELD_LABELS.map((field) => {
                    const virtualRisk = field.key === "virtual_risk_per_trade_percent";
                    return (
                      <label className="risk-setting-field" key={field.key}>
                        <span>{field.label}</span>
                        <div>
                          <input
                            aria-label={field.label}
                            disabled={busy || !customRiskEnabled || (virtualRisk && riskDraft.virtual_risk_mode !== "custom")}
                            inputMode="decimal"
                            min="0"
                            onChange={(event) => updateRiskDraft({ [field.key]: Number(event.target.value) })}
                            step={field.step}
                            type="number"
                            value={riskDraft[field.key]}
                          />
                          <small>{field.suffix}</small>
                        </div>
                      </label>
                    );
                  })}
                </div>
              </div>
              <div className="risk-plan-block">
                <div className="risk-plan-heading">
                  <strong>Virtual execution</strong>
                </div>
                <div className="risk-mode-grid">
                  {VIRTUAL_SLIPPAGE_MODELS.map((model) => (
                    <button
                      className={riskDraft.virtual_slippage_model === model.value ? "active" : ""}
                      disabled={busy || !customRiskEnabled}
                      key={model.value}
                      onClick={() => updateRiskDraft({ virtual_slippage_model: model.value })}
                      type="button"
                    >
                      {model.label}
                    </button>
                  ))}
                </div>
                <div className="risk-mode-grid two-option-grid">
                  {VIRTUAL_FEE_MODELS.map((model) => (
                    <button
                      className={riskDraft.virtual_fee_model === model.value ? "active" : ""}
                      disabled={busy || !customRiskEnabled}
                      key={model.value}
                      onClick={() => updateRiskDraft({ virtual_fee_model: model.value })}
                      type="button"
                    >
                      {model.label}
                    </button>
                  ))}
                </div>
                <label className="risk-checkbox-row">
                  <input
                    checked={riskDraft.virtual_trading_uses_realistic_execution}
                    disabled={busy || !customRiskEnabled}
                    onChange={(event) => updateRiskDraft({ virtual_trading_uses_realistic_execution: event.target.checked })}
                    type="checkbox"
                  />
                  <span>Realistic execution</span>
                </label>
              </div>
            </>
          ) : null}

          {riskTab === "guide" ? (
            <RiskManagementGuide riskDraft={riskDraft} riskState={riskState} />
          ) : null}

          <div className="risk-profile-footer">
            <span>Balanced is the default profile. Limits reduce risk exposure but cannot guarantee safety.</span>
            <button
              className="secondary-action"
              disabled={busy || !customRiskEnabled}
              onClick={handleSaveCustomRisk}
              type="button"
            >
              Save custom
            </button>
          </div>
        </div>

        <div className="settings-section">
          <div className="section-title"><Gauge size={18} /><h3>Simulation</h3></div>
          <div className="simulation-mode-grid">
            {SIMULATION_LEVELS.map((level) => (
              <button
                className={`simulation-mode-option ${simulationLevel === level.value ? "active" : ""}`}
                disabled={busy}
                key={level.value}
                onClick={() => onSelectSimulationLevel(level.value)}
                type="button"
              >
                <span>
                  <strong>{level.label}</strong>
                  <small>{level.caption}</small>
                </span>
                <Badge tone={level.status === "active" ? "green" : "yellow"}>{level.status}</Badge>
              </button>
            ))}
          </div>
        </div>

        <div className="settings-section alerts-section">
          <div className="section-title"><Bell size={18} /><h3>Alerts</h3></div>
          <div className="inline-form stacked">
            <select
              aria-label="Alert pair"
              disabled={busy || availablePairs.length === 0}
              onChange={(event) => setPairId(event.target.value)}
              value={pairId}
            >
              <option value="">{availablePairs.length ? "Select pair" : "No pairs"}</option>
              {availablePairs.map((pair) => (
                <option key={pair.id} value={pair.id}>{pair.exchange}:{pair.symbol}</option>
              ))}
            </select>
            <select
              aria-label="Alert condition"
              disabled={busy}
              onChange={(event) => setConditionType(event.target.value)}
              value={conditionType}
            >
              <option value="price_above">Price above</option>
              <option value="price_below">Price below</option>
              <option value="signal_generated">Signal generated</option>
            </select>
            <input
              aria-label="Alert price"
              disabled={busy}
              inputMode="decimal"
              onChange={(event) => setTargetPrice(event.target.value)}
              placeholder="Price"
              type="number"
              value={targetPrice}
            />
            <button className="primary-action" disabled={busy || !selectedPair || !targetPrice} onClick={handleCreateAlert} type="button">
              <Bell size={16} />
              Add
            </button>
          </div>

          <div className="alert-list">
            {alertRules.length === 0 ? <div className="empty-state compact-empty">No alert rules</div> : null}
            {alertRules.map((alert) => (
              <div className="alert-row" key={alert.id}>
                <div>
                  <strong>{alert.pair?.symbol ?? "Global"}</strong>
                  <span>{alert.condition_type} {formatCondition(alert.condition_body)}</span>
                </div>
                <label className="toggle-row compact-toggle">
                  <input
                    checked={alert.is_enabled}
                    disabled={busy}
                    onChange={(event) => onToggleAlert(alert.id, event.target.checked)}
                    type="checkbox"
                  />
                  <span>{alert.is_enabled ? "On" : "Off"}</span>
                </label>
                <button className="icon-button compact" disabled={busy} onClick={() => onTestAlert(alert.id)} title="Test" type="button">
                  <Send size={15} />
                </button>
                <button className="icon-button compact" disabled={busy} onClick={() => onDeleteAlert(alert.id)} title="Delete" type="button">
                  <Trash2 size={15} />
                </button>
              </div>
            ))}
          </div>
        </div>

        <div className="settings-section">
          <h3>Timeframes</h3>
          <div className="chip-cloud">
            {(config?.timeframes ?? ["1m", "5m", "15m", "1h", "4h", "1d"]).map((timeframe) => (
              <Badge tone="purple" key={timeframe}>{timeframe}</Badge>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function RiskManagementGuide({
  riskDraft,
  riskState
}: {
  riskDraft: RiskManagementSettings;
  riskState: RiskStateResponse | null;
}) {
  return (
    <div className="risk-guide">
      <div className="risk-guide-intro">
        <div className="risk-guide-title">
          <BookOpen size={18} />
          <div>
            <strong>Как настраивать risk management</strong>
            <span>Backend проверяет допустимый риск, размер позиции, маржу и причины блокировки перед входом.</span>
          </div>
        </div>
      </div>

      <div className="risk-guide-snapshot">
        <div>
          <span>Текущий профиль</span>
          <strong>{riskDraft.risk_profile}</strong>
        </div>
        <div>
          <span>Risk / trade</span>
          <strong>{formatPercentValue(riskDraft.risk_per_trade_percent)}</strong>
        </div>
        <div>
          <span>Open risk</span>
          <strong>
            {riskState
              ? formatRiskUsageValue(riskState.open_risk_percent, riskState.max_open_risk_percent)
              : "-"}
          </strong>
        </div>
        <div>
          <span>Correlated</span>
          <strong>
            {riskState
              ? formatRiskUsageValue(riskState.correlated_risk_percent, riskState.max_correlated_risk_percent)
              : "-"}
          </strong>
        </div>
        <div>
          <span>Drawdown</span>
          <strong>
            {riskState
              ? formatRiskUsageValue(riskState.account_drawdown_percent, riskState.max_account_drawdown_percent)
              : "-"}
          </strong>
        </div>
        <div>
          <span>Protection</span>
          <strong>{riskState?.protection_state ?? "-"}</strong>
        </div>
      </div>

      <div className="risk-guide-playbook">
        <div className="risk-guide-block">
          <h4>Если не открывается ни одна сделка</h4>
          <ol>
            <li>Проверьте Open risk в строке состояния. Если он выше лимита, закройте старые virtual-позиции или временно увеличьте Open risk cap в Custom.</li>
            <li>Проверьте Correlated risk. Несколько сделок в одном кластере и направлении могут блокировать новый вход раньше общего лимита.</li>
            <li>Для paper trading включите Virtual Trading &gt; Separate и задайте отдельный virtual risk, balance и лимиты.</li>
            <li>Чтобы выключить конкретный лимит, поставьте 0. В интерфейсе такой лимит будет показан как Off.</li>
            <li>Если блокирует R:R или price drift, значит цена ушла от сигнала. Лучше дождаться нового сигнала, а не расширять все лимиты сразу.</li>
            <li>Меняйте только одно поле за раз и смотрите на risk card в Radar: backend должен показать passed, warning или failed и точную причину.</li>
          </ol>
        </div>
        <div className="risk-guide-block">
          <h4>Что можно ослабить для обучения</h4>
          <ul>
            <li>Min R:R: временно 1.5R вместо 2R для virtual.</li>
            <li>Open risk cap: выше, если на virtual много параллельных тестов.</li>
            <li>Correlated risk: выше, если вы сознательно тестируете один сектор.</li>
            <li>Virtual balance: ближе к реальному размеру учебного депозита.</li>
          </ul>
        </div>
      </div>

      <div className="risk-guide-blocker-grid">
        {RISK_BLOCKER_GUIDE.map((item) => (
          <article className="risk-guide-mini" key={item.title}>
            <h4>{item.title}</h4>
            <p>{item.body}</p>
            {item.tip ? <small>{item.tip}</small> : null}
          </article>
        ))}
      </div>

      <div className="risk-guide-sections">
        {RISK_GUIDE_SECTIONS.map((section) => (
          <section className="risk-guide-section" key={section.title}>
            <h4>{section.title}</h4>
            <p>{section.intro}</p>
            <div className="risk-guide-item-list">
              {section.items.map((item) => (
                <article className="risk-guide-item" key={item.title}>
                  <strong>{item.title}</strong>
                  <span>{item.body}</span>
                  {item.tip ? <small>{item.tip}</small> : null}
                </article>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

function formatCondition(condition: Record<string, unknown>): string {
  const price = condition.price;
  if (typeof price === "number" || typeof price === "string") return String(price);
  return "";
}

function shortKeyRef(keyRef: string): string {
  const parts = keyRef.split("/");
  const suffix = parts[parts.length - 1] ?? keyRef;
  return `key_ref:${suffix.slice(0, 8)}`;
}

function dedupeStrategyPairs(pairs: Array<{ exchange: string; symbol: string }>) {
  const seen = new Set<string>();
  return pairs.filter((pair) => {
    const key = `${pair.exchange.toLowerCase()}:${pair.symbol.toUpperCase()}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function dedupeStrings(values: string[]): string[] {
  return Array.from(new Set(values.map((value) => value.trim().toLowerCase()).filter(Boolean)));
}

function getContextTimeframeMap(params: Record<string, unknown>): Record<string, string> {
  const rawMap = params.context_timeframe_map;
  if (!rawMap || typeof rawMap !== "object" || Array.isArray(rawMap)) return {};
  return Object.fromEntries(
    Object.entries(rawMap)
      .map(([signalTimeframe, contextTimeframe]) => [
        signalTimeframe.trim().toLowerCase(),
        String(contextTimeframe).trim().toLowerCase()
      ])
      .filter(([signalTimeframe, contextTimeframe]) => signalTimeframe && contextTimeframe && contextTimeframe !== "default")
  );
}

function contextTimeframeOptions(signalTimeframe: string): string[] {
  const index = STRATEGY_TIMEFRAMES.indexOf(signalTimeframe);
  if (index < 0) return STRATEGY_TIMEFRAMES;
  return STRATEGY_TIMEFRAMES.slice(index + 1);
}

function defaultMaxBodyAtr(strategyCode: string): number {
  return MAX_BODY_ATR_DEFAULTS[strategyCode] ?? 2.5;
}

function defaultMaxRangeAtr(strategyCode: string): number {
  return MAX_RANGE_ATR_DEFAULTS[strategyCode] ?? 3.5;
}

function defaultRrTarget(strategyCode: string): "final" | "nearest" {
  return RR_TARGET_DEFAULTS[strategyCode] ?? "final";
}

function riskProtectionTone(mode: RiskProtectionMode): "green" | "red" | "yellow" | "blue" {
  if (mode === "blocked") return "red";
  if (mode === "virtual_only" || mode === "reduced") return "yellow";
  return "green";
}

function formatPercentValue(value: number): string {
  return `${value.toFixed(2)}%`;
}

function formatRiskUsageValue(used: number, limit: number): string {
  return `${formatPercentValue(used)} / ${limit <= 0 ? "Off" : formatPercentValue(limit)}`;
}

function defaultRiskManagement(): RiskManagementSettings {
  return {
    risk_profile: "balanced",
    risk_per_trade_percent: 1,
    min_rr_ratio: 2,
    max_daily_loss_percent: 3,
    max_weekly_loss_percent: 7,
    max_account_drawdown_percent: 10,
    max_open_risk_percent: 5,
    max_correlated_risk_percent: 3,
    max_spread_bps: 50,
    max_slippage_bps: 150,
    max_price_deviation_bps: 100,
    max_orderbook_liquidity_ratio: 1,
    include_fees_in_risk: true,
    include_slippage_in_risk: true,
    stop_loss_required: true,
    take_profit_required: true,
    stop_loss_mode: "fixed_percent",
    default_stop_loss_percent: 1.5,
    atr_period: 14,
    atr_multiplier: 2,
    take_profit_mode: "risk_multiple",
    tp1_r_multiple: 1,
    tp2_r_multiple: 2,
    tp3_r_multiple: 3,
    partial_take_profit_enabled: true,
    tp1_close_percent: 30,
    tp2_close_percent: 40,
    tp3_close_percent: 30,
    move_sl_to_breakeven_after_r: 1,
    breakeven_offset_percent: 0.05,
    trailing_stop_enabled: true,
    trailing_mode: "atr",
    trailing_atr_multiplier: 1.5,
    trailing_stop_percent: 0.5,
    max_leverage: 3,
    min_liquidation_buffer_percent: 2,
    liquidation_buffer_required: true,
    spot_risk_per_trade_percent: 1,
    spot_max_position_size_percent: 20,
    spot_stop_required: true,
    futures_risk_per_trade_percent: 0.5,
    futures_max_leverage: 3,
    futures_max_open_risk_percent: 3,
    futures_liquidation_buffer_required: true,
    virtual_risk_mode: "same_as_real",
    virtual_risk_per_trade_percent: 1,
    virtual_starting_balance: 10000,
    virtual_slippage_model: "spread_based",
    virtual_fee_model: "exchange_based",
    virtual_trading_uses_realistic_execution: true,
    strategy_risk_multipliers: {
      trend_following: 1,
      trend_pullback_continuation: 1,
      breakout: 0.75,
      scalping: 0.5,
      mean_reversion: 0.75,
      smart_money_setup: 1,
      news_event_trade: 0.25
    },
    auto_reduce_risk_after_losses: true,
    allow_risk_increase_after_profit: false,
    increase_risk_after_profit_streak: false,
    max_risk_boost: 1.25
  };
}
