"use client";

import dynamic from "next/dynamic";
import { useState } from "react";
import { BarChart3, FileCheck2, ShieldAlert, XCircle } from "lucide-react";

import { Badge } from "./Badge";
import type { AccountRiskSnapshot, ExchangeConnection } from "@/features/server-state/types";
import { useI18n, type I18nKey } from "@/i18n";
import type {
  PendingEntryIntent,
  RadarSignal,
  RiskStateResponse,
  SignalActionState,
  SignalTradePlanView,
  ViewTone,
  VirtualExecutionReport
} from "../types";
import { buildSignalDetailsViewModel, type SignalDetailsViewModel, type UiBlocker } from "./signal-details-view-model";
import { formatPrice } from "../utils";

const LazySignalDetailsChart = dynamic(
  () => import("@/components/charts/SignalDetailsChart").then((module) => module.SignalDetailsChart),
  {
    loading: SignalDetailsChartLoading,
    ssr: false
  }
);

interface SignalDetailsProps {
  signal: RadarSignal | null;
  onPaperTrade: (signal: RadarSignal) => void;
  onConfirmRealTrade?: (signal: RadarSignal) => void | Promise<unknown>;
  onAcceptPendingEntry?: (signal: RadarSignal) => void;
  onCancelPendingEntry?: (intent: PendingEntryIntent) => void;
  onReconfirmPendingEntry?: (intent: PendingEntryIntent) => void;
  onReject: (signal: RadarSignal) => void;
  busy: boolean;
  pendingEntry?: PendingEntryIntent | null;
  pendingEntryLoading?: boolean;
  executionPreview: VirtualExecutionReport | null;
  executionPreviewError?: string | null;
  executionPreviewLoading?: boolean;
  actionState?: SignalActionState | null;
  actionStateLoading?: boolean;
  realActionState?: SignalActionState | null;
  tradingActionsDisabled?: boolean;
  realTradeContext?: RealTradeContext;
  realTradeBusy?: boolean;
  missingSignalId?: string | null;
  onSelectLatestSignal?: () => void;
}

export interface RealTradeContext {
  userId: string | null;
  connection: ExchangeConnection | null;
  accountSnapshot: AccountRiskSnapshot | null;
  riskState: RiskStateResponse | null;
  realExecutionEnabled: boolean;
  loading?: boolean;
}

type I18nParams = Record<string, string | number | boolean | null | undefined>;
type TKey = (key: I18nKey, params?: I18nParams) => string;
type TReason = (code: string | null | undefined, params?: I18nParams) => string;

function SignalDetailsChartLoading() {
  const { tKey } = useI18n();
  return <div className="chart-panel chart-panel-loading">{tKey("trades.loadingChart")}</div>;
}

export function SignalDetails({
  signal,
  onPaperTrade,
  onConfirmRealTrade,
  onAcceptPendingEntry,
  onCancelPendingEntry,
  onReconfirmPendingEntry,
  onReject,
  busy,
  pendingEntry = null,
  pendingEntryLoading = false,
  executionPreview,
  executionPreviewError = null,
  executionPreviewLoading = false,
  actionState,
  actionStateLoading = false,
  realActionState,
  tradingActionsDisabled = false,
  realTradeContext,
  realTradeBusy = false,
  missingSignalId = null,
  onSelectLatestSignal
}: SignalDetailsProps) {
  const { t, tKey, tReason } = useI18n();
  const [chartOpen, setChartOpen] = useState(false);
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);
  const [realConfirmationOpen, setRealConfirmationOpen] = useState(false);

  if (!signal) {
    return (
      <section className="details-empty">
        <FileCheck2 size={32} />
        <h2>{missingSignalId ? tKey("signalDetails.missingTitle") : tKey("signalDetails.emptyTitle")}</h2>
        <p>{missingSignalId ? tKey("signalDetails.missingBody") : tKey("signalDetails.emptyBody")}</p>
        {missingSignalId ? (
          <button className="secondary-action" disabled={!onSelectLatestSignal} onClick={onSelectLatestSignal} type="button">
            <FileCheck2 size={17} /> {tKey("signalDetails.selectLatestSignal")}
          </button>
        ) : null}
      </section>
    );
  }

  const viewModel = buildSignalDetailsViewModel(signal, pendingEntry, { actionState: actionState ?? null });
  const activePendingEntry = viewModel.activePendingEntry;
  const terminalPendingEntry = viewModel.terminalPendingEntry;
  const backendDisabledReason = actionStateDisabledReason(actionState ?? null, tReason);
  const entryDisabledReason = enterNowDisabledReason(signal, actionState ?? null, tKey, tReason);
  const pendingDisabledReason = pendingEntryDisabledReason(signal, actionState ?? null, tKey, tReason);
  const entryActionDisabled = busy || tradingActionsDisabled || actionStateLoading || actionState?.can_enter_now !== true;
  const acceptPendingDisabled = busy || tradingActionsDisabled || actionStateLoading || pendingEntryLoading || actionState?.can_arm_pending !== true;
  const cancelPendingDisabled = busy || tradingActionsDisabled || actionStateLoading || actionState?.can_cancel !== true;
  const realActionAvailable = Boolean(realActionState?.can_enter_now || realActionState?.can_arm_pending);
  const realActionDisabled = busy || tradingActionsDisabled || !realActionAvailable || !onConfirmRealTrade;
  const rejectDisabled = busy || tradingActionsDisabled || signal.details_view?.primary_status === "cancelled" || signal.details_view?.primary_status === "expired";

  return (
    <section className="details-panel">
      <div className="details-header">
        <div>
          <span className="muted">{tKey("signalDetails.title")}</span>
          <h2>{signal.symbol}</h2>
        </div>
        <div className="details-badges">
          <Badge tone={viewModel.side === "long" ? "green" : "red"}>{viewModel.side.toUpperCase()}</Badge>
          <Badge tone="yellow">{tKey("signalDetails.risk")} {t(viewModel.riskSummary.label)}</Badge>
          <Badge tone={viewModel.primaryStatusTone}>{viewModel.primaryStatusLabel}</Badge>
          {signal.card_view?.badges.map((badge) => (
            <Badge key={`${badge.code}:${badge.label}`} tone={badge.tone}>{badge.label}</Badge>
          ))}
        </div>
      </div>

      {viewModel.contractError ? <div className="error-banner">{viewModel.contractError}</div> : null}

      <DecisionCard
        canEnterNow={viewModel.canEnterNow}
        primaryActionLabel={viewModel.primaryActionLabel}
        recommendedActionText={backendDisabledReason ?? viewModel.recommendedActionText}
        viewModel={viewModel}
        topBlockers={viewModel.topBlockers.slice(0, 3)}
      />

      <TriggerCompact signal={signal} />
      <ExecutionEvidenceCompact signal={signal} />
      <ActivePendingEntryCompact
        pendingEntry={activePendingEntry}
        onReconfirmPendingEntry={onReconfirmPendingEntry}
        busy={busy || tradingActionsDisabled}
        canReconfirm={actionState?.can_reconfirm}
      />
      <TerminalPendingEntryCompact pendingEntry={terminalPendingEntry} />

      <TradePlanCompact tradePlan={viewModel.tradePlanSummary} />
      <RiskCompact execution={executionPreview} error={executionPreviewError} loading={executionPreviewLoading} />
      <WhyThisSignal reasons={viewModel.topReasons.slice(0, 6)} />

      <ActionsBlock
        acceptPendingDisabled={acceptPendingDisabled}
        activePendingEntry={activePendingEntry}
        cancelPendingDisabled={cancelPendingDisabled}
        chartOpen={chartOpen}
        entryActionDisabled={entryActionDisabled}
        onAcceptPendingEntry={() => onAcceptPendingEntry?.(signal)}
        onCancelPendingEntry={() => activePendingEntry ? onCancelPendingEntry?.(activePendingEntry) : undefined}
        onPaperTrade={() => onPaperTrade(signal)}
        onReject={() => onReject(signal)}
        onToggleChart={() => setChartOpen((open) => !open)}
        realActionDisabled={realActionDisabled}
        realExecutionEnvironment={realActionState?.environment ?? realTradeContext?.connection?.environment ?? tKey("signalDetails.noExchangeConnection")}
        rejectDisabled={rejectDisabled}
        setRealConfirmationOpen={setRealConfirmationOpen}
        tradingActionsDisabled={tradingActionsDisabled}
        backendDisabledReason={backendDisabledReason}
        entryDisabledReason={entryActionDisabled ? entryDisabledReason : null}
        pendingDisabledReason={acceptPendingDisabled ? pendingDisabledReason : null}
        canEnterNow={viewModel.canEnterNow}
      />

      {chartOpen ? <LazySignalDetailsChart signal={signal} /> : null}

      <DiagnosticsPanel
        actionState={actionState ?? null}
        busy={busy || tradingActionsDisabled}
        execution={executionPreview}
        executionError={executionPreviewError}
        executionLoading={executionPreviewLoading}
        open={diagnosticsOpen}
        onReconfirmPendingEntry={onReconfirmPendingEntry}
        onToggle={() => setDiagnosticsOpen((open) => !open)}
        pendingEntry={activePendingEntry}
        signal={signal}
        terminalPendingEntry={terminalPendingEntry}
        viewModel={viewModel}
      />

      {realConfirmationOpen ? (
        <RealTradeConfirmationModal
          actionState={realActionState ?? null}
          busy={realTradeBusy}
          context={realTradeContext}
          execution={executionPreview}
          onCancel={() => setRealConfirmationOpen(false)}
          onConfirm={() => {
            if (!onConfirmRealTrade) return;
            void Promise.resolve(onConfirmRealTrade(signal)).then(() => setRealConfirmationOpen(false));
          }}
          signal={signal}
        />
      ) : null}
    </section>
  );
}

function DecisionCard({
  canEnterNow,
  primaryActionLabel,
  recommendedActionText,
  viewModel,
  topBlockers
}: {
  canEnterNow: boolean | null;
  primaryActionLabel: string;
  recommendedActionText: string;
  viewModel: SignalDetailsViewModel;
  topBlockers: UiBlocker[];
}) {
  const { t, tKey, tReason } = useI18n();
  return (
    <div className="decision-block decision-card">
      <div className="section-title compact-section-title">
        <FileCheck2 size={18} />
        <h3>{tKey("signalDetails.decision")}</h3>
        <Badge tone={viewModel.primaryStatusTone}>{t(viewModel.primaryStatusLabel)}</Badge>
      </div>
      <div className="compact-metric-grid decision-card-grid">
        <MetricLine label={tKey("signalDetails.recommendedAction")} value={t(primaryActionLabel)} />
        <MetricLine label={tKey("signalDetails.canEnterNow")} value={canEnterNowLabel(canEnterNow, tKey)} />
      </div>
      <p>{t(recommendedActionText)}</p>
      <div className="top-blocker-list">
        <strong>{tKey("signalDetails.topBlockers")}</strong>
        {topBlockers.length ? (
          <ul className="risk-blocker-list compact-risk-blockers">
            {topBlockers.map((blocker) => (
              <li key={blockerKey(blocker)}>{tReason(blocker.code ?? blocker.userMessage)}</li>
            ))}
          </ul>
        ) : (
          <p className="compact-empty">{tKey("signalDetails.noActiveBlockers")}</p>
        )}
      </div>
    </div>
  );
}

function TriggerCompact({ signal }: { signal: RadarSignal }) {
  const { tKey, tReason } = useI18n();
  const trigger = signal.trigger ?? null;
  const triggerBlocker = signal.execution_gate?.reasons.find((reason) => reason.code === "trigger_not_confirmed") ?? null;
  if (!trigger && !triggerBlocker) return null;
  const passed = trigger?.passed ?? false;
  const reason = trigger?.reason ?? triggerBlocker?.message ?? null;
  return (
    <div className="risk-reward-detail-block trigger-compact">
      <div className="section-title">
        <FileCheck2 size={18} />
        <h3>{tKey("signalDetails.trigger")}</h3>
        <Badge tone={passed ? "green" : "red"}>{passed ? "Confirmed" : "Not confirmed"}</Badge>
      </div>
      <div className="compact-metric-grid">
        <MetricLine label="Type" value={formatOptionalText(trigger?.trigger_type)} />
        <MetricLine label="Candle" value={formatOptionalText(trigger?.candle_state)} />
        <MetricLine label="Price" value={formatPrice(trigger?.price ?? null)} />
        <MetricLine label="Reason" value={triggerBlocker?.code ? tReason(triggerBlocker.code) : reason ?? "-"} />
      </div>
      {reason ? <p>{reason}</p> : null}
    </div>
  );
}

function ExecutionEvidenceCompact({ signal }: { signal: RadarSignal }) {
  const { tKey } = useI18n();
  const eligibility = strategyEligibility(signal);
  const dedup = dedupSnapshot(signal);
  if (!eligibility && !dedup) return null;
  return (
    <div className="risk-reward-detail-block execution-evidence-compact">
      {eligibility ? (
        <div className="execution-evidence-section">
          <div className="section-title compact-section-title">
            <ShieldAlert size={18} />
            <h3>{tKey("signalDetails.strategyEligibility")}</h3>
            <Badge tone={eligibility.eligible === true ? "green" : "red"}>
              {eligibility.eligible === true ? "Eligible" : "Blocked"}
            </Badge>
          </div>
          <p>{eligibility.reason}</p>
          {eligibility.source || eligibility.runIds.length ? (
            <div className="compact-metric-grid">
              {eligibility.source ? <MetricLine label="Edge source" value={eligibility.source} /> : null}
              {eligibility.runIds.length ? <MetricLine label="Calibration run" value={eligibility.runIds.map(shortId).join(", ")} /> : null}
            </div>
          ) : null}
        </div>
      ) : null}
      {dedup ? (
        <div className="execution-evidence-section">
          <div className="section-title compact-section-title">
            <FileCheck2 size={18} />
            <h3>{tKey("signalDetails.deduplication")}</h3>
            <Badge tone={dedup.status === "active" ? "green" : "neutral"}>{dedup.status}</Badge>
          </div>
          <p>{dedup.reason}</p>
        </div>
      ) : null}
    </div>
  );
}

function TerminalPendingEntryCompact({ pendingEntry }: { pendingEntry: PendingEntryIntent | null }) {
  const { t, tKey, tReason } = useI18n();
  if (!pendingEntry) return null;
  const reasonCode = pendingEntry.view?.reason_code ?? pendingEntry.reason_code ?? null;
  const reason = reasonCode
    ? tReason(reasonCode)
    : tReason(pendingEntry.view?.reason ?? pendingEntry.failure_reason ?? null);
  return (
    <div className="pending-entry-block terminal-pending-compact">
      <div className="section-title">
        <FileCheck2 size={18} />
        <h3>{tKey("signalDetails.latestPendingEntryOutcome")}</h3>
        <Badge tone={pendingEntry.view?.status_tone ?? pendingEntryTone(pendingEntry.status)}>
          {t(pendingEntry.view?.status_label ?? pendingEntry.status.replaceAll("_", " "))}
        </Badge>
      </div>
      <div className="compact-metric-grid">
        <MetricLine label="Status" value={t(pendingEntry.status.replaceAll("_", " "))} />
        <MetricLine label="Reason code" value={reasonCode ?? "-"} />
        <MetricLine label="Updated" value={formatPendingEntryTimestamp(pendingEntry.updated_at)} />
      </div>
      <p>{reason}</p>
    </div>
  );
}

function ActivePendingEntryCompact({
  pendingEntry,
  onReconfirmPendingEntry,
  busy,
  canReconfirm
}: {
  pendingEntry: PendingEntryIntent | null;
  onReconfirmPendingEntry?: (intent: PendingEntryIntent) => void;
  busy: boolean;
  canReconfirm?: boolean;
}) {
  const { t, tKey, tReason } = useI18n();
  if (!pendingEntry) return null;
  const view = pendingEntry.view;
  const reasonCode = view?.reason_code ?? pendingEntry.reason_code ?? null;
  return (
    <div className="pending-entry-block active-pending-compact">
      <div className="section-title">
        <FileCheck2 size={18} />
        <h3>{tKey("pendingEntry.activePendingEntry")}</h3>
        <Badge tone={view?.status_tone ?? pendingEntryTone(pendingEntry.status)}>{view?.status_label ? t(view.status_label) : t(pendingEntry.status.replaceAll("_", " "))}</Badge>
      </div>
      <div className="compact-metric-grid">
        <MetricLine label={tKey("pendingEntry.state")} value={view?.status_label ? t(view.status_label) : t(pendingEntry.status.replaceAll("_", " "))} />
        <MetricLine label={tKey("pendingEntry.entryZone")} value={view?.entry_zone ?? `${formatPrice(pendingEntry.entry_min)} - ${formatPrice(pendingEntry.entry_max)}`} />
        <MetricLine label={tKey("pendingEntry.stop")} value={formatPrice(pendingEntry.stop_loss)} />
        <MetricLine label={tKey("pendingEntry.reasonCode")} value={reasonCode ?? "-"} />
        <MetricLine label={tKey("pendingEntry.expiryTtl")} value={formatPendingEntryExpiry(pendingEntry, tKey)} />
      </div>
      <p>{reasonCode ? tReason(reasonCode) : tReason(view?.reason ?? pendingEntry.failure_reason ?? tKey("pendingEntry.noBackendReason"))}</p>
      {pendingEntry.status === "requires_reconfirmation" && onReconfirmPendingEntry ? (
        <div className="detail-actions compact-card-actions">
          <button className="secondary-action" disabled={busy || canReconfirm === false} onClick={() => onReconfirmPendingEntry(pendingEntry)} type="button">
            <FileCheck2 size={17} /> {tKey("pendingEntry.reconfirmPlan")}
          </button>
        </div>
      ) : null}
    </div>
  );
}

function TradePlanCompact({ tradePlan }: { tradePlan: SignalTradePlanView }) {
  const { t, tKey } = useI18n();
  return (
    <div className="risk-reward-detail-block trade-plan-compact">
      <div className="section-title">
        <ShieldAlert size={18} />
        <h3>{tKey("signalDetails.tradePlan")}</h3>
        <Badge tone={tradePlan.has_trade_plan ? "blue" : "neutral"}>{t(tradePlan.entry_type)}</Badge>
      </div>
      <div className="compact-metric-grid trade-plan-compact-grid">
        <MetricLine label={tKey("signalDetails.entryType")} value={t(tradePlan.entry_type)} />
        <MetricLine label={tKey("signalDetails.entryZonePrice")} value={`${tradePlan.entry_zone} / ${formatPrice(tradePlan.entry_price)}`} />
        <MetricLine label={tKey("signalDetails.stopLoss")} value={formatPrice(tradePlan.stop_loss)} />
        <MetricLine label="TP1" value={formatCompactTarget(tradePlan, 0)} />
        <MetricLine label="TP2" value={formatCompactTarget(tradePlan, 1)} />
        <MetricLine label={tKey("signalDetails.runner")} value={formatCompactRunnerTarget(tradePlan)} />
        <MetricLine label={tKey("signalDetails.selectedRr")} value={formatRMultiple(tradePlan.selected_rr)} />
        <MetricLine label={tKey("signalDetails.invalidation")} value={t(tradePlan.invalidation)} />
      </div>
    </div>
  );
}

function RiskCompact({
  execution,
  error,
  loading
}: {
  execution: VirtualExecutionReport | null;
  error: string | null;
  loading: boolean;
}) {
  const { t, tKey } = useI18n();
  const riskCheck = execution?.risk_check ?? execution?.risk_decision?.risk_check ?? null;
  const sizing = execution?.position_sizing ?? execution?.risk_decision?.checked_position_sizing ?? null;
  return (
    <div className="risk-reward-detail-block risk-compact">
      <div className="section-title">
        <ShieldAlert size={18} />
        <h3>{tKey("signalDetails.risk")}</h3>
        <Badge tone={riskGateTone(riskCheck?.status ?? execution?.risk_decision?.status ?? null)}>
          {t(riskCheck?.status ?? execution?.risk_decision?.status ?? (loading ? "checking" : "not previewed"))}
        </Badge>
      </div>
      <div className="compact-metric-grid risk-compact-grid">
        <MetricLine label={tKey("signalDetails.riskAmountPercent")} value={`${formatCurrencyAmount(riskCheck?.effective_risk_amount ?? sizing?.risk_amount)} / ${formatPercentValue(riskCheck?.adjusted_risk_percent ?? sizing?.risk_per_trade_percent)}`} />
        <MetricLine label={tKey("signalDetails.marginLeverage")} value={`${formatCurrencyAmount(riskCheck?.required_margin ?? sizing?.required_margin)} / ${sizing?.leverage == null ? "-" : `${sizing.leverage}x`}`} />
        <MetricLine label={tKey("signalDetails.executionQuality")} value={execution ? `${t(execution.quality_gate.status)} / ${t(execution.liquidity.impact_risk)} ${tKey("signalDetails.impactRisk").toLowerCase()}` : error ? tKey("signalDetails.previewError") : loading ? tKey("common.checking") : tKey("signalDetails.notPreviewed")} />
      </div>
    </div>
  );
}

function WhyThisSignal({ reasons }: { reasons: string[] }) {
  const { t, tKey } = useI18n();
  return (
    <div className="explanation-block why-signal-block">
      <h3>{tKey("signalDetails.whyThisSignal")}</h3>
      <ul>{reasons.map((reason) => <li key={reason}><span>{t(reason)}</span></li>)}</ul>
    </div>
  );
}

function ActionsBlock({
  acceptPendingDisabled,
  activePendingEntry,
  cancelPendingDisabled,
  chartOpen,
  entryActionDisabled,
  onAcceptPendingEntry,
  onCancelPendingEntry,
  onPaperTrade,
  onReject,
  onToggleChart,
  realActionDisabled,
  realExecutionEnvironment,
  rejectDisabled,
  setRealConfirmationOpen,
  tradingActionsDisabled,
  backendDisabledReason,
  entryDisabledReason,
  pendingDisabledReason,
  canEnterNow
}: {
  acceptPendingDisabled: boolean;
  activePendingEntry: PendingEntryIntent | null;
  cancelPendingDisabled: boolean;
  chartOpen: boolean;
  entryActionDisabled: boolean;
  onAcceptPendingEntry: () => void;
  onCancelPendingEntry: () => void;
  onPaperTrade: () => void;
  onReject: () => void;
  onToggleChart: () => void;
  realActionDisabled: boolean;
  realExecutionEnvironment: string;
  rejectDisabled: boolean;
  setRealConfirmationOpen: (open: boolean) => void;
  tradingActionsDisabled: boolean;
  backendDisabledReason: string | null;
  entryDisabledReason: string | null;
  pendingDisabledReason: string | null;
  canEnterNow: boolean | null;
}) {
  const { tKey } = useI18n();
  return (
    <div className="actions-block">
      <div className="section-title">
        <FileCheck2 size={18} />
        <h3>{tKey("signalDetails.actions")}</h3>
        <Badge tone={canEnterNow === true ? "green" : canEnterNow === false ? "red" : "yellow"}>
          {canEnterNowLabel(canEnterNow, tKey)}
        </Badge>
      </div>
      <p className="compact-action-note">{tKey("signalDetails.executionEnvironment", { environment: realExecutionEnvironment })}</p>
      <div className="detail-actions compact-actions">
        <button className="secondary-action" onClick={onAcceptPendingEntry} disabled={acceptPendingDisabled} type="button">
          <FileCheck2 size={17} /> {tKey("signalDetails.virtualWaitEntry")}
        </button>
        <button className="real-action" onClick={() => setRealConfirmationOpen(true)} disabled={realActionDisabled} type="button">
          <ShieldAlert size={17} /> {tKey("signalDetails.realWaitEntry")}
        </button>
        <button className="primary-action" onClick={onPaperTrade} disabled={entryActionDisabled} type="button">
          <FileCheck2 size={17} /> {canEnterNow === true ? tKey("signalDetails.virtualEntryNow") : tKey("signalDetails.virtualEntryLocked")}
        </button>
        {activePendingEntry ? (
          <button className="secondary-action" onClick={onCancelPendingEntry} disabled={cancelPendingDisabled} type="button">
            <XCircle size={17} /> {tKey("signalDetails.cancelWaiting")}
          </button>
        ) : null}
        <button className="secondary-action" onClick={onToggleChart} type="button">
          <BarChart3 size={17} /> {chartOpen ? tKey("signalDetails.hideChart") : tKey("signalDetails.openChart")}
        </button>
        <button className="danger-action" onClick={onReject} disabled={rejectDisabled} type="button">
          <XCircle size={17} /> {tKey("signalDetails.rejectIgnore")}
        </button>
      </div>
      {tradingActionsDisabled ? (
        <p className="compact-action-note">{tKey("signalDetails.tradingDisabled")}</p>
      ) : (
        <>
          {entryDisabledReason ? <p className="compact-action-note">{entryDisabledReason}</p> : null}
          {pendingDisabledReason ? <p className="compact-action-note">{pendingDisabledReason}</p> : null}
          {!entryDisabledReason && !pendingDisabledReason && backendDisabledReason ? (
            <p className="compact-action-note">{backendDisabledReason}</p>
          ) : null}
        </>
      )}
    </div>
  );
}

function DiagnosticsPanel({
  actionState,
  busy,
  execution,
  executionError,
  executionLoading,
  open,
  onReconfirmPendingEntry,
  onToggle,
  pendingEntry,
  signal,
  terminalPendingEntry,
  viewModel
}: {
  actionState: SignalActionState | null;
  busy: boolean;
  execution: VirtualExecutionReport | null;
  executionError: string | null;
  executionLoading: boolean;
  open: boolean;
  onReconfirmPendingEntry?: (intent: PendingEntryIntent) => void;
  onToggle: () => void;
  pendingEntry: PendingEntryIntent | null;
  signal: RadarSignal;
  terminalPendingEntry: PendingEntryIntent | null;
  viewModel: SignalDetailsViewModel;
}) {
  const { tKey } = useI18n();
  return (
    <div className="diagnostics-panel">
      <button
        aria-controls="signal-diagnostics-content"
        aria-expanded={open}
        className="diagnostics-toggle"
        onClick={onToggle}
        type="button"
      >
        <span className="section-title">
          <ShieldAlert size={18} />
          <span>{tKey("signalDetails.diagnostics")}</span>
        </span>
        <Badge tone={open ? "blue" : "neutral"}>{open ? tKey("common.openLower") : tKey("common.collapsed")}</Badge>
      </button>
      {open ? (
        <div className="diagnostics-content" id="signal-diagnostics-content">
          <BackendViewBlock signal={signal} actionState={actionState} viewModel={viewModel} />
          <PendingEntryBlock pendingEntry={pendingEntry} onReconfirmPendingEntry={onReconfirmPendingEntry} busy={busy} />
          <PendingEntryHistoryCollapsed pendingEntry={terminalPendingEntry} />
          <ExecutionPreviewBlock execution={execution} error={executionError} loading={executionLoading} />
        </div>
      ) : null}
    </div>
  );
}

function BackendViewBlock({
  signal,
  actionState,
  viewModel
}: {
  signal: RadarSignal;
  actionState: SignalActionState | null;
  viewModel: SignalDetailsViewModel;
}) {
  const { t, tKey, tReason } = useI18n();
  return (
    <div className="risk-reward-detail-block">
      <div className="section-title">
        <ShieldAlert size={18} />
        <h3>{tKey("signalDetails.backendActionState")}</h3>
        <Badge tone={viewModel.primaryStatusTone}>{t(viewModel.primaryStatusLabel)}</Badge>
      </div>
      <div className="risk-reward-detail-grid">
        <MetricLine label={tKey("signalDetails.signalStatus")} value={t(signal.status.replaceAll("_", " "))} />
        <MetricLine label={tKey("signalDetails.primaryAction")} value={actionState?.primary_action ?? "-"} />
        <MetricLine label={tKey("signalDetails.canEnter")} value={canEnterNowLabel(actionState?.can_enter_now ?? null, tKey)} />
        <MetricLine label={tKey("signalDetails.canArmPending")} value={formatBool(actionState?.can_arm_pending, tKey)} />
        <MetricLine label={tKey("signalDetails.canCancel")} value={formatBool(actionState?.can_cancel, tKey)} />
        <MetricLine label={tKey("signalDetails.environment")} value={actionState?.environment ?? "-"} />
      </div>
      {[...viewModel.topBlockers, ...viewModel.warnings].length ? (
        <ul className="risk-blocker-list">
          {[...viewModel.topBlockers, ...viewModel.warnings].map((blocker) => (
            <li key={blockerKey(blocker)}>{tReason(blocker.code)}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function PendingEntryBlock({
  pendingEntry,
  onReconfirmPendingEntry,
  busy
}: {
  pendingEntry: PendingEntryIntent | null;
  onReconfirmPendingEntry?: (intent: PendingEntryIntent) => void;
  busy: boolean;
}) {
  const { t, tKey, tReason } = useI18n();
  if (!pendingEntry) return null;
  const reasonCode = pendingEntry.view?.reason_code ?? pendingEntry.reason_code ?? null;
  const reason = reasonCode
    ? tReason(reasonCode)
    : tReason(pendingEntry.view?.reason ?? pendingEntry.failure_reason ?? tKey("pendingEntry.noBackendReason"));
  return (
    <div className="pending-entry-block">
      <div className="section-title">
        <FileCheck2 size={18} />
        <h3>{tKey("pendingEntry.pendingEntry")}</h3>
        <Badge tone={pendingEntry.view?.status_tone ?? pendingEntryTone(pendingEntry.status)}>
          {t(pendingEntry.view?.status_label ?? pendingEntry.status.replaceAll("_", " "))}
        </Badge>
      </div>
      <p>{reason}</p>
      <div className="risk-reward-detail-grid">
        <MetricLine label={tKey("pendingEntry.entryZone")} value={pendingEntry.view?.entry_zone ?? `${formatPrice(pendingEntry.entry_min)} - ${formatPrice(pendingEntry.entry_max)}`} />
        <MetricLine label={tKey("pendingEntry.stop")} value={formatPrice(pendingEntry.stop_loss)} />
        <MetricLine label={tKey("pendingEntry.mode")} value={pendingEntry.mode} />
        <MetricLine label={tKey("pendingEntry.acceptedStatus")} value={t(pendingEntry.accepted_signal_status.replaceAll("_", " "))} />
      </div>
      {pendingEntry.status === "requires_reconfirmation" && onReconfirmPendingEntry ? (
        <div className="detail-actions">
          <button className="secondary-action" disabled={busy} onClick={() => onReconfirmPendingEntry(pendingEntry)} type="button">
            <FileCheck2 size={17} /> {tKey("pendingEntry.reconfirmPlan")}
          </button>
        </div>
      ) : null}
    </div>
  );
}

function PendingEntryHistoryCollapsed({ pendingEntry }: { pendingEntry: PendingEntryIntent | null }) {
  const { t, tKey, tReason } = useI18n();
  if (!pendingEntry) return null;
  const reasonCode = pendingEntry.view?.reason_code ?? pendingEntry.reason_code ?? null;
  const reason = reasonCode ? tReason(reasonCode) : tReason(pendingEntry.view?.reason ?? pendingEntry.failure_reason ?? null);
  return (
    <details className="risk-reward-detail-block pending-entry-history-block">
      <summary className="pending-entry-history-summary">
        <span className="section-title">
          <FileCheck2 size={18} />
          <h3>{tKey("pendingEntry.historyTitle")}</h3>
        </span>
        <Badge tone={pendingEntry.view?.status_tone ?? pendingEntryTone(pendingEntry.status)}>
          {t(pendingEntry.view?.status_label ?? pendingEntry.status.replaceAll("_", " "))}
        </Badge>
      </summary>
      <div className="risk-reward-detail-grid">
        <MetricLine label={tKey("pendingEntry.status")} value={t(pendingEntry.status.replaceAll("_", " "))} />
        <MetricLine label={tKey("pendingEntry.reason")} value={reason} />
        <MetricLine label={tKey("pendingEntry.updated")} value={formatPendingEntryTimestamp(pendingEntry.updated_at)} />
      </div>
    </details>
  );
}

function ExecutionPreviewBlock({
  execution,
  error,
  loading
}: {
  execution: VirtualExecutionReport | null;
  error: string | null;
  loading: boolean;
}) {
  const { t, tKey, tReason } = useI18n();
  return (
    <div className="execution-quality-block">
      <div className="section-title">
        <ShieldAlert size={18} />
        <h3>{tKey("signalDetails.backendExecutionPreview")}</h3>
        <Badge tone={execution ? riskGateTone(execution.risk_check?.status ?? execution.risk_decision?.status ?? null) : loading ? "yellow" : "neutral"}>
          {t(execution?.risk_check?.status ?? execution?.risk_decision?.status ?? (loading ? tKey("common.checking") : tKey("signalDetails.notPreviewed")))}
        </Badge>
      </div>
      {execution ? (
        <div className="execution-quality-grid">
          <MetricLine label={tKey("signalDetails.qualityGate")} value={t(execution.quality_gate.status)} />
          <MetricLine label={tKey("signalDetails.impactRisk")} value={t(execution.liquidity.impact_risk)} />
          <MetricLine label={tKey("signalDetails.requestedSize")} value={formatCurrencyAmount(execution.requested_size_usd)} />
          <MetricLine label={tKey("signalDetails.filledSize")} value={formatCurrencyAmount(execution.filled_size_usd)} />
          <MetricLine label={tKey("signalDetails.entrySlippage")} value={formatBps(execution.entry_slippage_bps, tKey)} />
          <MetricLine label={tKey("signalDetails.reason")} value={execution.reason_code ? tReason(execution.reason_code) : "-"} />
        </div>
      ) : (
        <p>{error ?? (loading ? tKey("signalDetails.previewLoading") : tKey("signalDetails.previewNotRequested"))}</p>
      )}
    </div>
  );
}

function RealTradeConfirmationModal({
  signal,
  context,
  execution,
  actionState,
  busy,
  onCancel,
  onConfirm
}: {
  signal: RadarSignal;
  context?: RealTradeContext;
  execution: VirtualExecutionReport | null;
  actionState: SignalActionState | null;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const { t, tKey, tReason } = useI18n();
  const confirmDisabled = busy || !(actionState?.can_enter_now || actionState?.can_arm_pending);
  const blockers = actionState?.blockers ?? [];
  const warnings = actionState?.warnings ?? [];
  const riskCheck = execution?.risk_check ?? execution?.risk_decision?.risk_check ?? null;
  const tradePlan = signal.details_view?.trade_plan;
  return (
    <div className="real-trade-modal-backdrop">
      <div aria-labelledby="real-trade-confirm-title" aria-modal="true" className="real-trade-modal" role="dialog">
        <div className="real-trade-modal-header">
          <div>
            <span className="muted">{tKey("execution.real")}</span>
            <h3 id="real-trade-confirm-title">{tKey("execution.confirmRealEntry")}</h3>
          </div>
          <div className="details-badges">
            <Badge tone={actionState?.environment === "mainnet" ? "red" : actionState?.environment === "testnet" ? "blue" : "yellow"}>
              {actionState?.environment ?? "real_unresolved"}
            </Badge>
            <Badge tone={context?.accountSnapshot?.status === "fresh" ? "green" : context?.accountSnapshot?.status === "stale" ? "yellow" : "red"}>
              {context?.accountSnapshot?.status ?? "missing"}
            </Badge>
          </div>
        </div>

        <div className="real-trade-warning">
          <ShieldAlert size={18} />
          <span>{tKey("execution.availabilityBackendOwned")}</span>
        </div>

        <div className="real-trade-metric-grid">
          <RealTradeMetric label={tKey("common.exchange")} value={context?.connection ? `${context.connection.exchange_name || context.connection.exchange_code} / ${context.connection.label}` : signal.exchange} />
          <RealTradeMetric label={tKey("execution.accountEquity")} value={formatCurrencyAmount(context?.accountSnapshot?.account_equity)} />
          <RealTradeMetric label={tKey("execution.availableBalance")} value={formatCurrencyAmount(riskCheck?.available_balance)} />
          <RealTradeMetric label={tKey("execution.symbolSide")} value={`${signal.symbol} / ${signal.direction.toUpperCase()}`} />
          <RealTradeMetric label={tKey("pendingEntry.entryZone")} value={tradePlan?.entry_zone ?? "-"} />
          <RealTradeMetric label={tKey("signalDetails.stopLoss")} value={formatPrice(tradePlan?.stop_loss)} />
          <RealTradeMetric label={tKey("signalDetails.selectedRr")} value={formatRMultiple(tradePlan?.selected_rr ?? null)} />
          <RealTradeMetric label={tKey("execution.riskGate")} value={t(riskCheck?.status ?? execution?.risk_decision?.status ?? "-")} />
        </div>

        <div className="real-trade-blockers">
          <strong>{tKey("execution.backendBlockersWarnings")}</strong>
          {blockers.length ? (
            <ul className="risk-blocker-list">
              {blockers.map((blocker) => (
                <li key={blocker.code}>{tReason(blocker.code)}</li>
              ))}
            </ul>
          ) : (
            <p>{tKey("execution.noBlockers")}</p>
          )}
          {warnings.length ? (
            <div className="real-trade-warning-list">
              {warnings.map((warning) => (
                <span key={warning.code}>{tReason(warning.code)}</span>
              ))}
            </div>
          ) : null}
        </div>

        <div className="real-trade-modal-actions">
          <button className="secondary-action" onClick={onCancel} type="button">{tKey("execution.cancel")}</button>
          <button className="real-action" disabled={confirmDisabled} onClick={onConfirm} type="button">
            <ShieldAlert size={17} /> {tKey("execution.confirmReal")}
          </button>
        </div>
      </div>
    </div>
  );
}

function strategyEligibility(signal: RadarSignal): { eligible: boolean | null; reason: string; runIds: string[]; source: string | null } | null {
  const raw = recordValue(signal.edge?.metadata.strategy_eligibility)
    ?? recordValue(signal.execution_gate?.metadata.strategy_eligibility);
  if (!raw) return null;
  const edgeMetadata = recordValue(signal.edge?.metadata) ?? {};
  return {
    eligible: typeof raw.eligible === "boolean" ? raw.eligible : null,
    reason: stringValue(raw.reason) ?? stringValue(raw.reason_code) ?? "-",
    runIds: stringList(edgeMetadata.run_ids ?? raw.run_ids),
    source: stringValue(edgeMetadata.profile_source) ?? stringValue(raw.source)
  };
}

function dedupSnapshot(signal: RadarSignal): { status: string; reason: string } | null {
  const raw = recordValue(signal.execution_gate?.metadata.dedup)
    ?? recordValue(signal.edge?.metadata.dedup);
  if (!raw) return null;
  return {
    status: stringValue(raw.status) ?? "dedup",
    reason: stringValue(raw.reason) ?? stringValue(raw.reason_code) ?? "-"
  };
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item)).filter(Boolean);
}

function shortId(value: string): string {
  return value.length > 8 ? value.slice(0, 8) : value;
}

function formatOptionalText(value: string | null | undefined): string {
  return value && value.trim() ? value : "-";
}

function MetricLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="execution-quality-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function RealTradeMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="real-trade-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function formatCompactTarget(tradePlan: SignalTradePlanView, index: number): string {
  const target = tradePlan.targets[index];
  if (!target) return "-";
  const rr = target.r_multiple == null ? "" : ` / ${formatRMultiple(target.r_multiple)}`;
  return `${target.label} ${formatPrice(target.price)}${rr}`;
}

function formatCompactRunnerTarget(tradePlan: SignalTradePlanView): string {
  const runner = tradePlan.targets[2] ?? tradePlan.targets.find((target) => target.action?.includes("runner")) ?? null;
  if (!runner) return "-";
  const rr = runner.r_multiple == null ? "" : ` / ${formatRMultiple(runner.r_multiple)}`;
  return `${runner.label} ${formatPrice(runner.price)}${rr}`;
}

function formatRMultiple(value: number | null): string {
  return value == null ? "-" : `${value.toFixed(2)}R`;
}

function canEnterNowLabel(value: boolean | null, tKey: TKey): string {
  if (value == null) return tKey("signalDetails.notEvaluated");
  return value ? tKey("signalDetails.yes") : tKey("signalDetails.no");
}

function formatBool(value: boolean | undefined, tKey: TKey): string {
  if (value == null) return tKey("signalDetails.notEvaluated");
  return value ? tKey("signalDetails.yes") : tKey("signalDetails.no");
}

function formatPendingEntryExpiry(pendingEntry: PendingEntryIntent, tKey: TKey): string {
  if (!pendingEntry.expires_at) return tKey("pendingEntry.noExpiry");
  return `${formatPendingEntryTimestamp(pendingEntry.expires_at)} / ${formatPendingEntryTtl(pendingEntry.expires_at, tKey)}`;
}

function formatPendingEntryTtl(value: string, tKey: TKey): string {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return tKey("pendingEntry.ttlUnknown");
  const diffMs = timestamp - Date.now();
  if (diffMs <= 0) return tKey("pendingEntry.expired");
  const diffMinutes = Math.ceil(diffMs / 60_000);
  if (diffMinutes < 60) return tKey("pendingEntry.minutesLeft", { count: diffMinutes });
  return tKey("pendingEntry.hoursLeft", { count: Math.ceil(diffMinutes / 60) });
}

function formatPendingEntryTimestamp(value: string | null | undefined): string {
  if (!value) return "-";
  return value.replace("T", " ").replace(".000Z", "Z");
}

function pendingEntryTone(status: PendingEntryIntent["status"]): ViewTone {
  if (status === "pending") return "blue";
  if (status === "requires_reconfirmation") return "yellow";
  if (status === "triggered" || status === "filling" || status === "filled") return "green";
  if (status === "failed" || status === "cancelled" || status === "expired") return "red";
  return "neutral";
}

function riskGateTone(status: string | null | undefined): ViewTone {
  if (status === "passed") return "green";
  if (status === "failed") return "red";
  if (status === "warning") return "yellow";
  return "neutral";
}

function actionStateDisabledReason(state: SignalActionState | null, tReason: TReason): string | null {
  if (!state) return null;
  const blocker = state.blockers[0] ?? null;
  const reasonCode = state.disabled_reason_code ?? blocker?.code ?? null;
  if (reasonCode) return tReason(reasonCode);
  const fallback = state.display_labels.disabled_reason ?? blocker?.display_label ?? blocker?.message ?? null;
  return fallback ? tReason(fallback) : null;
}

function enterNowDisabledReason(
  signal: RadarSignal,
  state: SignalActionState | null,
  tKey: TKey,
  tReason: TReason
): string | null {
  if (state?.can_enter_now === true) return null;
  const reason = actionStateReason(signal, state, tReason);
  return reason ? tKey("signalDetails.actionUnavailable", { reason }) : null;
}

function pendingEntryDisabledReason(
  signal: RadarSignal,
  state: SignalActionState | null,
  tKey: TKey,
  tReason: TReason
): string | null {
  if (state?.can_arm_pending === true) return null;
  const reason = actionStateReason(signal, state, tReason);
  return reason ? tKey("signalDetails.actionUnavailable", { reason }) : null;
}

function actionStateReason(signal: RadarSignal, state: SignalActionState | null, tReason: TReason): string | null {
  const actionReason = actionStateDisabledReason(state, tReason);
  const gateBlocker = signal.execution_gate?.reasons.find((reason) => reason.severity === "blocker")
    ?? signal.execution_gate?.reasons[0]
    ?? null;
  return actionReason ?? gateBlocker?.message ?? null;
}

function formatCurrencyAmount(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "-";
  return value.toLocaleString("en-US", {
    currency: "USD",
    maximumFractionDigits: value >= 1000 ? 2 : 6,
    minimumFractionDigits: value >= 1000 ? 2 : 0,
    style: "currency"
  });
}

function formatPercentValue(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "-";
  if (value > 0 && value < 0.01) return "<0.01%";
  return `${value.toFixed(value >= 10 ? 1 : 2)}%`;
}

function formatBps(value: number | null | undefined, tKey: TKey): string {
  if (value == null || !Number.isFinite(value)) return tKey("signalDetails.slippageUnavailable");
  return tKey("signalDetails.slippageBps", { value: value.toFixed(1) });
}

function blockerKey(blocker: UiBlocker): string {
  return `${blocker.code}:${blocker.userMessage}`;
}
