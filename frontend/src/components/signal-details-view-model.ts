import { isActivePendingEntryStatus, isTerminalPendingEntryStatus } from "@/domain/pending-entry-status";
import { terminalStatusDetailLabel } from "@/domain/signal-status";
import type {
  PendingEntryIntent,
  RadarSignal,
  SignalActionState,
  SignalDetailsBlockerView,
  SignalDetailsPrimaryStatus,
  SignalTradePlanView,
  ViewTone
} from "@/types";

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
  label: string;
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
  riskCheckStatus: string | null;
  riskDecisionStatus: string | null;
  canEnter: boolean | null;
  qualityGateStatus: string | null;
  impactRisk: string | null;
  statusAllowsTrade: boolean;
}

export interface SignalDetailsDiagnostics {
  signalStatus: RadarSignal["status"];
  riskGateStatus: RadarSignal["risk_gate_status"] | null;
  canEnter: RadarSignal["can_enter"] | null;
  pendingEntryStatus: PendingEntryIntent["status"] | null;
  actionState: SignalActionState | null;
  rawBlockers: UiBlocker[];
  rawWarnings: UiBlocker[];
}

export interface SignalDetailsViewModel {
  title: string;
  side: RadarSignal["direction"];
  primaryStatus: SignalDetailsPrimaryStatus;
  primaryStatusLabel: string;
  primaryStatusTone: ViewTone;
  primaryActionLabel: string;
  recommendedActionText: string;
  canEnterNow: boolean | null;
  activePendingEntry: PendingEntryIntent | null;
  terminalPendingEntry: PendingEntryIntent | null;
  tradePlanSummary: SignalTradePlanView;
  riskSummary: SignalDetailsRiskSummary;
  executionSummary: SignalDetailsExecutionSummary;
  topReasons: string[];
  topBlockers: UiBlocker[];
  warnings: UiBlocker[];
  diagnostics: SignalDetailsDiagnostics;
  contractError: string | null;
}

export interface BuildSignalDetailsViewModelOptions {
  actionState?: SignalActionState | null;
}

const EMPTY_TRADE_PLAN: SignalTradePlanView = {
  has_trade_plan: false,
  entry_type: "API contract error",
  entry_zone: "-",
  entry_price: null,
  stop_loss: null,
  targets: [],
  selected_rr: null,
  selected_rr_target: null,
  min_rr: null,
  trade_plan_complete: null,
  fallback_used: false,
  missing: [],
  invalidation: "-"
};

export function buildSignalDetailsViewModel(
  signal: RadarSignal,
  pendingEntry: PendingEntryIntent | null | undefined,
  options: BuildSignalDetailsViewModelOptions = {}
): SignalDetailsViewModel {
  const details = signal.details_view ?? null;
  const actionState = options.actionState ?? null;
  const activePendingEntry = pendingEntry && isActivePendingEntryStatus(pendingEntry.status) ? pendingEntry : null;
  const terminalPendingEntry = pendingEntry && isTerminalPendingEntryStatus(pendingEntry.status) ? pendingEntry : null;
  const contractError = details ? null : "API contract error: SignalDetailsView is missing";
  const terminalSignalLabel = terminalStatusDetailLabel(signal.status);
  const topBlockers = mergeActionBlockers(
    actionState,
    details?.top_blockers ?? [],
    "blocker"
  );
  const warnings = mergeActionBlockers(
    actionState,
    details?.warnings ?? [],
    "warning"
  );

  return {
    title: details?.title ?? signal.symbol,
    side: details?.side ?? signal.direction,
    primaryStatus: details?.primary_status ?? "unknown",
    primaryStatusLabel: terminalSignalLabel ?? details?.primary_status_label ?? "unknown",
    primaryStatusTone: terminalSignalLabel ? "red" : details?.primary_status_tone ?? "neutral",
    primaryActionLabel: actionState?.display_labels.primary_action ?? details?.primary_action_label ?? "Action state unavailable",
    recommendedActionText: actionStateDisabledReason(actionState) ?? details?.recommended_action_text ?? contractError ?? "Backend returned no recommendation.",
    canEnterNow: actionState?.can_enter_now ?? details?.can_enter_now ?? null,
    activePendingEntry,
    terminalPendingEntry,
    tradePlanSummary: details?.trade_plan ?? EMPTY_TRADE_PLAN,
    riskSummary: {
      label: details?.risk_summary.label ?? "-",
      riskFailed: details?.risk_summary.risk_failed ?? false,
      riskRewardBlocked: details?.risk_summary.risk_reward_blocked ?? false,
      riskRewardWarning: details?.risk_summary.risk_reward_warning ?? null,
      formingCandle: details?.risk_summary.forming_candle ?? false,
      openCandleAllowed: details?.risk_summary.open_candle_allowed ?? false,
      formingReason: details?.risk_summary.forming_reason ?? null,
      statusAllowsTrade: details?.risk_summary.status_allows_trade ?? false,
      tradePlanComplete: details?.risk_summary.trade_plan_complete ?? false,
      riskRewardOk: details?.risk_summary.risk_reward_ok ?? false,
      isMarketOpportunity: details?.risk_summary.is_market_opportunity ?? false
    },
    executionSummary: {
      previewAvailable: details?.execution_summary.preview_available ?? false,
      riskCheckStatus: details?.execution_summary.risk_check_status ?? null,
      riskDecisionStatus: details?.execution_summary.risk_decision_status ?? null,
      canEnter: details?.execution_summary.can_enter ?? null,
      qualityGateStatus: details?.execution_summary.quality_gate_status ?? null,
      impactRisk: details?.execution_summary.impact_risk ?? null,
      statusAllowsTrade: details?.execution_summary.status_allows_trade ?? false
    },
    topReasons: details?.top_reasons.length ? details.top_reasons : [contractError ?? "Backend returned no signal reasons."],
    topBlockers,
    warnings,
    diagnostics: {
      signalStatus: signal.status,
      riskGateStatus: signal.risk_gate_status ?? null,
      canEnter: signal.can_enter ?? null,
      pendingEntryStatus: pendingEntry?.status ?? null,
      actionState,
      rawBlockers: topBlockers,
      rawWarnings: warnings
    },
    contractError
  };
}

function mergeActionBlockers(
  actionState: SignalActionState | null,
  viewBlockers: SignalDetailsBlockerView[],
  severity: "blocker" | "warning"
): UiBlocker[] {
  const actionItems = actionState
    ? (severity === "blocker" ? actionState.blockers : actionState.warnings).map((blocker) => ({
        code: blocker.code,
        severity: blocker.severity,
        category: categoryFromCode(blocker.code),
        userMessage: blocker.display_label ?? blocker.message ?? blocker.code,
        debugMessages: [blocker.code]
      }))
    : [];
  return dedupeBlockers([
    ...actionItems,
    ...viewBlockers.map(viewBlockerToUiBlocker)
  ]);
}

function viewBlockerToUiBlocker(blocker: SignalDetailsBlockerView): UiBlocker {
  return {
    code: blocker.code,
    severity: blocker.severity,
    category: blocker.category,
    userMessage: blocker.user_message,
    debugMessages: blocker.debug_messages
  };
}

function actionStateDisabledReason(state: SignalActionState | null): string | null {
  if (!state) return null;
  const blocker = state.blockers[0] ?? null;
  return state.display_labels.disabled_reason
    ?? blocker?.display_label
    ?? blocker?.message
    ?? state.disabled_reason_code
    ?? null;
}

function categoryFromCode(code: string): UiBlockerCategory {
  const normalized = code.toLowerCase();
  if (normalized.includes("liquidity") || normalized.includes("spread")) return "liquidity";
  if (normalized.includes("risk") || normalized.includes("rr")) return "risk";
  if (normalized.includes("execution") || normalized.includes("order") || normalized.includes("fill")) return "execution";
  if (normalized.includes("market") || normalized.includes("price") || normalized.includes("candle")) return "market_data";
  if (normalized.includes("entry") || normalized.includes("signal")) return "entry";
  return "technical";
}

function dedupeBlockers(items: UiBlocker[]): UiBlocker[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    const key = `${item.code}:${item.userMessage}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
