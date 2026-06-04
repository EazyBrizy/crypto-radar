import { isActivePendingEntryStatus, isTerminalPendingEntryStatus } from "@/domain/pending-entry-status";
import {
  canShowEnterButton,
  isEntryTouched,
  isFormingCandleSignal,
  isMarketOpportunity,
  isOpenCandleActionableAllowed,
  isWaitingEntry
} from "@/domain/signal-status";
import type {
  DecisionReason,
  PendingEntryIntent,
  RadarSignal,
  RiskCheckResult,
  RiskDecision,
  VirtualExecutionReport
} from "@/types";
import {
  entryZone,
  formingCandleReason,
  isRiskRewardBlocked,
  riskLabel,
  riskRewardBlockReason,
  riskRewardWarningReason,
  signalTradePlanSummary,
  type SignalTradePlanSummary
} from "@/utils";

export type SignalDetailsPrimaryStatus =
  | "execution_ready"
  | "waiting_entry"
  | "requires_reconfirmation"
  | "blocked"
  | "watchlist"
  | "cancelled"
  | "expired"
  | "unknown";

export type UiBlockerSeverity = "blocker" | "warning" | "info";
export type UiBlockerCategory = "entry" | "risk" | "market_data" | "liquidity" | "execution" | "technical";

export interface UiBlocker {
  code: string;
  severity: UiBlockerSeverity;
  category: UiBlockerCategory;
  userMessage: string;
  debugMessages: string[];
}

export interface SignalDetailsRiskSummary {
  label: ReturnType<typeof riskLabel>;
  riskFailed: boolean;
  riskRewardBlocked: boolean;
  riskRewardWarning: string | null;
  formingCandle: boolean;
  openCandleAllowed: boolean;
  formingReason: string | null;
  statusAllowsTrade: boolean;
  tradePlanComplete: boolean;
  riskRewardOk: boolean;
  isMarketOpportunity: boolean;
}

export interface SignalDetailsExecutionSummary {
  previewAvailable: boolean;
  riskCheckStatus: RiskCheckResult["status"] | null;
  riskDecisionStatus: RiskDecision["status"] | null;
  canEnter: boolean | null;
  qualityGateStatus: VirtualExecutionReport["quality_gate"]["status"] | null;
  impactRisk: VirtualExecutionReport["liquidity"]["impact_risk"] | null;
  statusAllowsTrade: boolean;
}

export interface SignalDetailsDiagnostics {
  signalStatus: RadarSignal["status"];
  riskGateStatus: RadarSignal["risk_gate_status"] | null;
  canEnter: RadarSignal["can_enter"] | null;
  pendingEntryStatus: PendingEntryIntent["status"] | null;
  legacyAutoEntryStatus: NonNullable<RadarSignal["auto_entry"]>["status"] | null;
  decision: RadarSignal["decision"] | null;
  noTrade: RadarSignal["no_trade_filter"] | null;
  riskDecision: RiskDecision | null;
  riskCheck: RiskCheckResult | null;
  rrBlockReason: string | null;
  rrWarningReason: string | null;
  rawBlockers: UiBlocker[];
  rawWarnings: UiBlocker[];
}

export interface SignalDetailsViewModel {
  title: string;
  side: RadarSignal["direction"];
  primaryStatus: SignalDetailsPrimaryStatus;
  primaryActionLabel: string;
  recommendedActionText: string;
  canEnterNow: boolean | null;
  activePendingEntry: PendingEntryIntent | null;
  terminalPendingEntry: PendingEntryIntent | null;
  activeLegacyAutoEntry: RadarSignal["auto_entry"];
  terminalLegacyAutoEntry: RadarSignal["auto_entry"];
  shouldShowLegacyAutoEntryInDefault: boolean;
  tradePlanSummary: SignalTradePlanSummary;
  riskSummary: SignalDetailsRiskSummary;
  executionSummary: SignalDetailsExecutionSummary;
  topReasons: string[];
  topBlockers: UiBlocker[];
  warnings: UiBlocker[];
  diagnostics: SignalDetailsDiagnostics;
}

export interface BuildSignalDetailsViewModelOptions {
  executionPreview?: VirtualExecutionReport | null;
}

interface CollectedUiBlocker extends UiBlocker {
  order: number;
}

interface BlockerSource {
  code?: string;
  severity: UiBlockerSeverity;
  category?: UiBlockerCategory;
  userMessage: string | null | undefined;
  debugMessages?: string[];
}

const FORMING_CANDLE_MESSAGE = "Свеча ещё формируется. Вход будет доступен после закрытия свечи.";
const LIQUIDATION_MISSING_FIELDS_MESSAGE = "Для liquidation guard не хватает обязательных данных. Проверьте рыночные данные и фьючерсный профиль.";
const TRADE_PLAN_INCOMPLETE_MESSAGE = "Trade plan неполный. Вход заблокирован до пересчёта entry, stop-loss и целей.";
const LOW_LIQUIDITY_MESSAGE = "Ликвидность слишком низкая для входа. Нужен более плотный стакан или меньший размер.";

export function buildSignalDetailsViewModel(
  signal: RadarSignal,
  pendingEntry: PendingEntryIntent | null | undefined,
  options: BuildSignalDetailsViewModelOptions = {}
): SignalDetailsViewModel {
  const execution = options.executionPreview ?? null;
  const tradePlanSummary = signalTradePlanSummary(signal);
  const riskDecision = execution?.risk_decision ?? null;
  const riskCheck = execution?.risk_check ?? null;
  const activePendingEntry = pendingEntry && isActivePendingEntryStatus(pendingEntry.status) ? pendingEntry : null;
  const terminalPendingEntry = pendingEntry && isTerminalPendingEntryStatus(pendingEntry.status) ? pendingEntry : null;
  const hasPendingEntryIntent = pendingEntry != null;
  const activeLegacyAutoEntry = !hasPendingEntryIntent && signal.auto_entry && isActivePendingEntryStatus(signal.auto_entry.status)
    ? signal.auto_entry
    : null;
  const terminalLegacyAutoEntry = !hasPendingEntryIntent && signal.auto_entry && isTerminalPendingEntryStatus(signal.auto_entry.status)
    ? signal.auto_entry
    : null;
  const activePendingStatus = activePendingEntry?.status ?? activeLegacyAutoEntry?.status ?? null;
  const hasActivePendingStatus = activePendingStatus != null;
  const rrBlockReason = riskRewardBlockReason(signal);
  const rrWarningReason = riskRewardWarningReason(signal);
  const collected = collectUiBlockers(signal, execution, rrBlockReason, rrWarningReason);
  const normalized = normalizeUiBlockers(collected);
  const topBlockers = normalized.filter((item) => item.severity === "blocker");
  const warnings = normalized.filter((item) => item.severity !== "blocker");
  const formingCandle = isFormingCandleSignal(signal);
  const openCandleAllowed = isOpenCandleActionableAllowed(signal);
  const formingReason = formingCandleReason(signal);
  const statusAllowsTrade = canShowEnterButton(signal) && (!formingCandle || openCandleAllowed);
  const riskFailed = riskCheck?.status === "failed" || riskDecision?.status === "failed";
  const riskRewardBlocked = isRiskRewardBlocked(signal);
  const canEnterNow = deriveCanEnterNow({
    hasActivePendingStatus,
    riskFailed,
    riskRewardBlocked,
    signal,
    statusAllowsTrade
  });
  const primaryStatus = derivePrimaryStatus({
    activePendingStatus,
    canEnterNow,
    riskFailed,
    signal,
    topBlockers
  });
  const riskRewardOk = tradePlanSummary.selectedRr != null || signal.risk_reward != null;
  const tradePlanComplete = tradePlanSummary.entryPrice != null && tradePlanSummary.stopLoss != null && tradePlanSummary.targets.length > 0;

  return {
    title: `${signal.symbol} ${signal.direction.toUpperCase()} Signal`,
    side: signal.direction,
    primaryStatus,
    primaryActionLabel: primaryActionLabel(signal, primaryStatus),
    recommendedActionText: recommendedActionText(signal, topBlockers, warnings),
    canEnterNow,
    activePendingEntry,
    terminalPendingEntry,
    activeLegacyAutoEntry,
    terminalLegacyAutoEntry,
    shouldShowLegacyAutoEntryInDefault: activeLegacyAutoEntry != null || terminalLegacyAutoEntry != null,
    tradePlanSummary,
    riskSummary: {
      label: riskLabel(signal),
      riskFailed,
      riskRewardBlocked,
      riskRewardWarning: rrWarningReason,
      formingCandle,
      openCandleAllowed,
      formingReason,
      statusAllowsTrade,
      tradePlanComplete,
      riskRewardOk,
      isMarketOpportunity: isMarketOpportunity(signal.status)
    },
    executionSummary: {
      previewAvailable: execution != null,
      riskCheckStatus: riskCheck?.status ?? null,
      riskDecisionStatus: riskDecision?.status ?? null,
      canEnter: riskDecision?.can_enter ?? signal.can_enter ?? null,
      qualityGateStatus: execution?.quality_gate.status ?? null,
      impactRisk: execution?.liquidity.impact_risk ?? null,
      statusAllowsTrade
    },
    topReasons: topReasons(signal, formingReason),
    topBlockers,
    warnings,
    diagnostics: {
      signalStatus: signal.status,
      riskGateStatus: signal.risk_gate_status ?? null,
      canEnter: signal.can_enter ?? null,
      pendingEntryStatus: pendingEntry?.status ?? null,
      legacyAutoEntryStatus: signal.auto_entry?.status ?? null,
      decision: signal.decision ?? null,
      noTrade: signal.no_trade_filter ?? null,
      riskDecision,
      riskCheck,
      rrBlockReason,
      rrWarningReason,
      rawBlockers: stripInternalOrder(collected.filter((item) => item.severity === "blocker")),
      rawWarnings: stripInternalOrder(collected.filter((item) => item.severity !== "blocker"))
    }
  };
}

function collectUiBlockers(
  signal: RadarSignal,
  execution: VirtualExecutionReport | null,
  rrBlockReason: string | null,
  rrWarningReason: string | null
): CollectedUiBlocker[] {
  const collected: CollectedUiBlocker[] = [];
  let order = 0;
  const add = (source: BlockerSource) => {
    const message = normalizeMessageValue(source.userMessage);
    if (!message) return;
    const code = source.code ?? inferCode(message);
    const category = source.category ?? inferCategory(code, message);
    collected.push({
      code,
      severity: source.severity,
      category,
      userMessage: message,
      debugMessages: source.debugMessages ?? [],
      order
    });
    order += 1;
  };

  if (rrBlockReason) {
    add({
      code: "risk_reward_guard",
      severity: "blocker",
      category: "risk",
      userMessage: rrBlockReason,
      debugMessages: ["rr:block_reason"]
    });
  } else if (rrWarningReason) {
    add({
      code: "risk_reward_guard",
      severity: "warning",
      category: "risk",
      userMessage: rrWarningReason,
      debugMessages: ["rr:warning_reason"]
    });
  }

  if (signal.display_reason) {
    add({
      code: signal.risk_gate_status ? `risk_gate_${signal.risk_gate_status}` : "display_reason",
      severity: signal.risk_gate_status === "failed" || signal.can_enter === false
        ? "blocker"
        : signal.risk_gate_status === "warning"
          ? "warning"
          : "info",
      category: "risk",
      userMessage: signal.display_reason,
      debugMessages: ["signal.display_reason"]
    });
  }

  const candleReason = formingCandleReason(signal);
  if (candleReason) {
    add({
      code: "forming_candle",
      severity: "blocker",
      category: "entry",
      userMessage: candleReason,
      debugMessages: ["signal.forming_candle"]
    });
  }

  for (const blocker of signal.no_trade_filter?.blockers ?? []) {
    add({
      severity: "blocker",
      userMessage: blocker,
      debugMessages: ["no_trade.blockers"]
    });
  }
  for (const warning of signal.no_trade_filter?.warnings ?? []) {
    add({
      severity: "warning",
      userMessage: warning,
      debugMessages: ["no_trade.warnings"]
    });
  }

  for (const reason of signal.decision?.blockers ?? []) {
    add(decisionReasonToBlocker(reason));
  }
  for (const reason of signal.decision?.warnings ?? []) {
    add(decisionReasonToBlocker(reason));
  }

  const riskDecision = execution?.risk_decision ?? null;
  const riskCheck = execution?.risk_check ?? null;
  for (const blocker of riskDecision?.blockers ?? []) {
    add({
      severity: "blocker",
      category: "risk",
      userMessage: blocker,
      debugMessages: ["riskDecision.blockers"]
    });
  }
  for (const warning of riskDecision?.warnings ?? []) {
    add({
      severity: "warning",
      category: "risk",
      userMessage: warning,
      debugMessages: ["riskDecision.warnings"]
    });
  }
  for (const blocker of riskCheck?.blockers ?? []) {
    add({
      severity: "blocker",
      category: "risk",
      userMessage: blocker,
      debugMessages: ["riskCheck.blockers"]
    });
  }
  for (const warning of riskCheck?.warnings ?? []) {
    add({
      severity: "warning",
      category: "risk",
      userMessage: warning,
      debugMessages: ["riskCheck.warnings"]
    });
  }

  for (const risk of signal.risks) {
    add({
      severity: isFormingCandleMessage(risk) ? "blocker" : "warning",
      userMessage: risk,
      debugMessages: ["signal.risks"]
    });
  }

  if (tradePlanLooksIncomplete(signal)) {
    add({
      code: "trade_plan_incomplete",
      severity: "blocker",
      category: "entry",
      userMessage: signal.status_reason ?? "Trade plan incomplete.",
      debugMessages: ["trade_plan.completeness"]
    });
  }

  return collected;
}

function decisionReasonToBlocker(reason: DecisionReason): BlockerSource {
  return {
    code: reason.code,
    severity: reason.severity,
    category: categoryFromDecisionSource(reason.source),
    userMessage: reason.message,
    debugMessages: [`decision.${reason.severity}.${reason.source}.${reason.scope}.${reason.code}`]
  };
}

function normalizeUiBlockers(items: CollectedUiBlocker[]): UiBlocker[] {
  const grouped = groupKnownBlockers(items);
  const deduped = new Map<string, CollectedUiBlocker>();
  for (const item of grouped) {
    const key = dedupeKey(item);
    const existing = deduped.get(key);
    if (!existing) {
      deduped.set(key, { ...item });
      continue;
    }
    existing.severity = strongerSeverity(existing.severity, item.severity);
    existing.category = existing.category === item.category ? existing.category : strongerCategory(existing.category, item.category);
    existing.debugMessages = dedupeStrings([
      ...existing.debugMessages,
      ...item.debugMessages,
      item.userMessage
    ]);
    existing.order = Math.min(existing.order, item.order);
  }
  return stripInternalOrder(Array.from(deduped.values()).sort((left, right) => left.order - right.order));
}

function groupKnownBlockers(items: CollectedUiBlocker[]): CollectedUiBlocker[] {
  const consumed = new Set<number>();
  const grouped: CollectedUiBlocker[] = [];
  const addGroup = (
    predicate: (item: CollectedUiBlocker) => boolean,
    replacement: Omit<UiBlocker, "debugMessages"> & { debugMessages?: string[] },
    forceSeverity?: UiBlockerSeverity,
    minimumSize = 1,
    minimumDistinctMessages = 1
  ) => {
    const matches = items.filter((item, index) => !consumed.has(index) && predicate(item));
    if (matches.length < minimumSize) return;
    if (new Set(matches.map((item) => normalizeForMatch(item.userMessage))).size < minimumDistinctMessages) return;
    for (const match of matches) consumed.add(items.indexOf(match));
    grouped.push({
      ...replacement,
      severity: forceSeverity ?? strongestSeverity(matches.map((item) => item.severity)),
      debugMessages: dedupeStrings([
        ...(replacement.debugMessages ?? []),
        ...matches.flatMap((item) => [item.userMessage, ...item.debugMessages])
      ]),
      order: Math.min(...matches.map((item) => item.order))
    });
  };

  addGroup(
    (item) => isFormingCandleMessage(item.code) || isFormingCandleMessage(item.userMessage),
    {
      code: "forming_candle",
      severity: "blocker",
      category: "entry",
      userMessage: FORMING_CANDLE_MESSAGE
    },
    "blocker"
  );
  addGroup(
    (item) => isLiquidationMissingFieldsMessage(item.code) || isLiquidationMissingFieldsMessage(item.userMessage),
    {
      code: "liquidation_missing_fields",
      severity: "warning",
      category: "technical",
      userMessage: LIQUIDATION_MISSING_FIELDS_MESSAGE
    }
  );
  addGroup(
    (item) => isTradePlanIncompleteMessage(item.code) || isTradePlanIncompleteMessage(item.userMessage),
    {
      code: "trade_plan_incomplete",
      severity: "blocker",
      category: "entry",
      userMessage: TRADE_PLAN_INCOMPLETE_MESSAGE
    },
    "blocker"
  );
  addGroup(
    (item) => isLowLiquidityMessage(item.code) || isLowLiquidityMessage(item.userMessage),
    {
      code: "low_liquidity",
      severity: "blocker",
      category: "liquidity",
      userMessage: LOW_LIQUIDITY_MESSAGE
    },
    undefined,
    2,
    2
  );

  return [
    ...grouped,
    ...items.filter((_, index) => !consumed.has(index))
  ].sort((left, right) => left.order - right.order);
}

function deriveCanEnterNow({
  hasActivePendingStatus,
  riskFailed,
  riskRewardBlocked,
  signal,
  statusAllowsTrade
}: {
  hasActivePendingStatus: boolean;
  riskFailed: boolean;
  riskRewardBlocked: boolean;
  signal: RadarSignal;
  statusAllowsTrade: boolean;
}): boolean | null {
  if (hasActivePendingStatus || riskFailed || riskRewardBlocked) return false;
  if (signal.can_enter === false || signal.risk_gate_status === "failed") return false;
  if (signal.can_enter === true) return statusAllowsTrade;
  if (signal.decision) return statusAllowsTrade;
  if (signal.risk_gate_status != null) return statusAllowsTrade;
  if (signal.status === "entry_touched" || signal.status === "actionable") return null;
  return false;
}

function derivePrimaryStatus({
  activePendingStatus,
  canEnterNow,
  riskFailed,
  signal,
  topBlockers
}: {
  activePendingStatus: PendingEntryIntent["status"] | null;
  canEnterNow: boolean | null;
  riskFailed: boolean;
  signal: RadarSignal;
  topBlockers: UiBlocker[];
}): SignalDetailsPrimaryStatus {
  if (activePendingStatus === "requires_reconfirmation") return "requires_reconfirmation";
  if (activePendingStatus) return "waiting_entry";
  if (signal.status === "expired") return "expired";
  if (signal.status === "invalidated" || signal.status === "rejected" || signal.status === "closed") return "cancelled";
  if (canEnterNow === true) return "execution_ready";
  if (topBlockers.length || riskFailed || signal.can_enter === false || signal.risk_gate_status === "failed") return "blocked";
  if (signal.status === "watchlist") return "watchlist";
  if (isWaitingEntry(signal.status) || isEntryTouched(signal.status)) return "waiting_entry";
  return "unknown";
}

function primaryActionLabel(signal: RadarSignal, status: SignalDetailsPrimaryStatus): string {
  if (status === "requires_reconfirmation") return "Requires reconfirmation";
  if (status === "execution_ready") return `Execution-ready inside ${entryZone(signal)}`;
  if (status === "blocked") {
    if (formingCandleReason(signal)) return "Forming candle preview, wait for close";
    if (signal.risk_gate_status === "failed" || signal.can_enter === false) return "RiskGate blocks entry right now";
    return "Entry is blocked by current checks";
  }
  if (status === "waiting_entry") {
    if (isEntryTouched(signal.status)) return "Entry touched, waiting for RiskGate permission";
    if (signal.status === "wait_for_pullback") return "Wait for pullback or retest";
    return "Market setup exists, wait for entry trigger";
  }
  if (status === "watchlist") return "Watch setup formation, no entry yet";
  if (status === "expired") return "Signal expired";
  if (status === "cancelled") return "Idea is no longer active";
  return `Monitor status ${signal.status.replaceAll("_", " ")}`;
}

function recommendedActionText(signal: RadarSignal, blockers: UiBlocker[], warnings: UiBlocker[]): string {
  return blockers[0]?.userMessage
    ?? signal.status_reason
    ?? warnings[0]?.userMessage
    ?? "Decision must use setup status, invalidation and risk context, not direction alone.";
}

function topReasons(signal: RadarSignal, formingReason: string | null): string[] {
  return dedupeStrings([
    ...(formingReason ? [formingReason] : []),
    ...(signal.explanation.length ? signal.explanation : ["Strategy formed a signal from the current market context."])
  ]);
}

function tradePlanLooksIncomplete(signal: RadarSignal): boolean {
  const plan = signalTradePlanSummary(signal);
  if (plan.tradePlanComplete === false) return true;
  if (signal.decision?.trade_plan_valid === false) return true;
  return Boolean(signal.status_reason && isTradePlanIncompleteMessage(signal.status_reason));
}

function categoryFromDecisionSource(source: DecisionReason["source"]): UiBlockerCategory {
  if (source === "rr" || source === "risk") return "risk";
  if (source === "execution") return "execution";
  if (source === "market_quality" || source === "data") return "market_data";
  if (source === "setup") return "entry";
  return "technical";
}

function inferCategory(code: string, message: string, fallback: UiBlockerCategory = "technical"): UiBlockerCategory {
  if (isFormingCandleMessage(code) || isFormingCandleMessage(message) || isTradePlanIncompleteMessage(code) || isTradePlanIncompleteMessage(message)) {
    return "entry";
  }
  if (isLowLiquidityMessage(code) || isLowLiquidityMessage(message)) return "liquidity";
  if (isLiquidationMissingFieldsMessage(code) || isLiquidationMissingFieldsMessage(message)) return "technical";
  const normalized = normalizeForMatch(`${code} ${message}`);
  if (normalized.includes("risk") || normalized.includes("rr") || normalized.includes("reward") || normalized.includes("drawdown")) return "risk";
  if (normalized.includes("order") || normalized.includes("fill") || normalized.includes("execution") || normalized.includes("slippage")) return "execution";
  if (normalized.includes("market data") || normalized.includes("candle") || normalized.includes("price") || normalized.includes("spread")) return "market_data";
  return fallback;
}

function inferCode(message: string): string {
  const normalized = message.trim();
  if (/^[a-z][a-z0-9_:.:-]{1,80}$/u.test(normalized)) return normalized.replaceAll(":", "_");
  if (isFormingCandleMessage(normalized)) return "forming_candle";
  if (isLiquidationMissingFieldsMessage(normalized)) return "liquidation_missing_fields";
  if (isTradePlanIncompleteMessage(normalized)) return "trade_plan_incomplete";
  if (isLowLiquidityMessage(normalized)) return "low_liquidity";
  return "raw_reason";
}

function normalizeMessageValue(value: string | null | undefined): string | null {
  const normalized = value?.trim();
  return normalized ? normalized : null;
}

function isFormingCandleMessage(value: string): boolean {
  const normalized = normalizeForMatch(value);
  return normalized.includes("forming candle")
    || normalized.includes("forming_candle")
    || (normalized.includes("open candle") && normalized.includes("close"));
}

function isLiquidationMissingFieldsMessage(value: string): boolean {
  const normalized = normalizeForMatch(value);
  return normalized.includes("liquidation")
    && (
      normalized.includes("missing")
      || normalized.includes("unavailable")
      || normalized.includes("not available")
      || normalized.includes("required")
      || normalized.includes("none")
      || normalized.includes("null")
    );
}

function isTradePlanIncompleteMessage(value: string): boolean {
  const normalized = normalizeForMatch(value);
  return (
    normalized.includes("trade plan")
    || normalized.includes("trade_plan")
  ) && (
    normalized.includes("incomplete")
    || normalized.includes("missing")
    || normalized.includes("invalid")
    || normalized.includes("blocked")
  );
}

function isLowLiquidityMessage(value: string): boolean {
  const normalized = normalizeForMatch(value);
  return normalized.includes("low liquidity")
    || normalized.includes("low_liquidity")
    || normalized.includes("high_spread")
    || normalized.includes("high spread")
    || normalized.includes("insufficient liquidity")
    || normalized.includes("liquidity is unavailable")
    || normalized.includes("orderbook liquidity")
    || normalized.includes("orderbook depth")
    || normalized.includes("visible orderbook depth");
}

function dedupeKey(item: UiBlocker): string {
  const message = normalizeForMatch(item.userMessage);
  return message || normalizeForMatch(item.code);
}

function normalizeForMatch(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .replace(/[^\p{L}\p{N}\s.%:/]+/gu, " ")
    .replace(/\s+/gu, " ")
    .trim();
}

function strongestSeverity(values: UiBlockerSeverity[]): UiBlockerSeverity {
  return values.reduce(strongerSeverity, "info");
}

function strongerSeverity(left: UiBlockerSeverity, right: UiBlockerSeverity): UiBlockerSeverity {
  const rank: Record<UiBlockerSeverity, number> = { blocker: 3, warning: 2, info: 1 };
  return rank[left] >= rank[right] ? left : right;
}

function strongerCategory(left: UiBlockerCategory, right: UiBlockerCategory): UiBlockerCategory {
  if (left === "risk" || right === "risk") return "risk";
  if (left === "execution" || right === "execution") return "execution";
  if (left === "liquidity" || right === "liquidity") return "liquidity";
  if (left === "market_data" || right === "market_data") return "market_data";
  if (left === "entry" || right === "entry") return "entry";
  return "technical";
}

function dedupeStrings(values: string[]): string[] {
  return Array.from(new Set(values.filter(Boolean)));
}

function stripInternalOrder(items: CollectedUiBlocker[]): UiBlocker[] {
  return items.map((item) => ({
    code: item.code,
    severity: item.severity,
    category: item.category,
    userMessage: item.userMessage,
    debugMessages: item.debugMessages
  }));
}
