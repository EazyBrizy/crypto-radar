"use client";

import dynamic from "next/dynamic";
import { useState } from "react";
import { BarChart3, FileCheck2, ShieldAlert, XCircle } from "lucide-react";

import { Badge } from "./Badge";
import type { AccountRiskSnapshot, ExchangeConnection } from "@/features/server-state/types";
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
    loading: () => <div className="chart-panel chart-panel-loading">Loading chart...</div>,
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
  const [chartOpen, setChartOpen] = useState(false);
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);
  const [realConfirmationOpen, setRealConfirmationOpen] = useState(false);

  if (!signal) {
    return (
      <section className="details-empty">
        <FileCheck2 size={32} />
        <h2>{missingSignalId ? "Signal is no longer visible" : "Р’С‹Р±РµСЂРё СЃРёРіРЅР°Р»"}</h2>
        <p>{missingSignalId ? "selected signal is no longer visible." : "Backend signal details will appear here."}</p>
        {missingSignalId ? (
          <button className="secondary-action" disabled={!onSelectLatestSignal} onClick={onSelectLatestSignal} type="button">
            <FileCheck2 size={17} /> РІС‹Р±СЂР°С‚СЊ РїРѕСЃР»РµРґРЅРёР№ СЃРёРіРЅР°Р»
          </button>
        ) : null}
      </section>
    );
  }

  const viewModel = buildSignalDetailsViewModel(signal, pendingEntry, { actionState: actionState ?? null });
  const activePendingEntry = viewModel.activePendingEntry;
  const terminalPendingEntry = viewModel.terminalPendingEntry;
  const backendDisabledReason = actionStateDisabledReason(actionState ?? null);
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
          <span className="muted">Signal Details</span>
          <h2>{signal.symbol}</h2>
        </div>
        <div className="details-badges">
          <Badge tone={viewModel.side === "long" ? "green" : "red"}>{viewModel.side.toUpperCase()}</Badge>
          <Badge tone="yellow">Risk {viewModel.riskSummary.label}</Badge>
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

      <ActivePendingEntryCompact
        pendingEntry={activePendingEntry}
        onReconfirmPendingEntry={onReconfirmPendingEntry}
        busy={busy || tradingActionsDisabled}
        canReconfirm={actionState?.can_reconfirm}
      />

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
        realExecutionEnvironment={realActionState?.environment ?? realTradeContext?.connection?.environment ?? "No exchange connection"}
        rejectDisabled={rejectDisabled}
        setRealConfirmationOpen={setRealConfirmationOpen}
        tradingActionsDisabled={tradingActionsDisabled}
        backendDisabledReason={backendDisabledReason}
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
  return (
    <div className="decision-block decision-card">
      <div className="section-title compact-section-title">
        <FileCheck2 size={18} />
        <h3>Decision</h3>
        <Badge tone={viewModel.primaryStatusTone}>{viewModel.primaryStatusLabel}</Badge>
      </div>
      <div className="compact-metric-grid decision-card-grid">
        <MetricLine label="Recommended action" value={primaryActionLabel} />
        <MetricLine label="Can enter now" value={canEnterNowLabel(canEnterNow)} />
      </div>
      <p>{recommendedActionText}</p>
      <div className="top-blocker-list">
        <strong>Top blockers</strong>
        {topBlockers.length ? (
          <ul className="risk-blocker-list compact-risk-blockers">
            {topBlockers.map((blocker) => (
              <li key={blockerKey(blocker)}>{blocker.userMessage}</li>
            ))}
          </ul>
        ) : (
          <p className="compact-empty">No active blockers from backend action-state.</p>
        )}
      </div>
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
  if (!pendingEntry) return null;
  const view = pendingEntry.view;
  return (
    <div className="auto-entry-block active-pending-compact">
      <div className="section-title">
        <FileCheck2 size={18} />
        <h3>Active Pending Entry</h3>
        <Badge tone={view?.status_tone ?? pendingEntryTone(pendingEntry.status)}>{view?.status_label ?? pendingEntry.status.replaceAll("_", " ")}</Badge>
      </div>
      <div className="compact-metric-grid">
        <MetricLine label="State" value={view?.status_label ?? pendingEntry.status.replaceAll("_", " ")} />
        <MetricLine label="Entry zone" value={view?.entry_zone ?? `${formatPrice(pendingEntry.entry_min)} - ${formatPrice(pendingEntry.entry_max)}`} />
        <MetricLine label="Stop" value={formatPrice(pendingEntry.stop_loss)} />
        <MetricLine label="Reason code" value={view?.reason_code ?? pendingEntry.reason_code ?? "-"} />
        <MetricLine label="Expiry / TTL" value={formatPendingEntryExpiry(pendingEntry)} />
      </div>
      <p>{view?.reason ?? pendingEntry.failure_reason ?? "No backend reason."}</p>
      {pendingEntry.status === "requires_reconfirmation" && onReconfirmPendingEntry ? (
        <div className="detail-actions compact-card-actions">
          <button className="secondary-action" disabled={busy || canReconfirm === false} onClick={() => onReconfirmPendingEntry(pendingEntry)} type="button">
            <FileCheck2 size={17} /> Reconfirm plan
          </button>
        </div>
      ) : null}
    </div>
  );
}

function TradePlanCompact({ tradePlan }: { tradePlan: SignalTradePlanView }) {
  return (
    <div className="risk-reward-detail-block trade-plan-compact">
      <div className="section-title">
        <ShieldAlert size={18} />
        <h3>Trade Plan</h3>
        <Badge tone={tradePlan.has_trade_plan ? "blue" : "neutral"}>{tradePlan.entry_type}</Badge>
      </div>
      <div className="compact-metric-grid trade-plan-compact-grid">
        <MetricLine label="Entry type" value={tradePlan.entry_type} />
        <MetricLine label="Entry zone / price" value={`${tradePlan.entry_zone} / ${formatPrice(tradePlan.entry_price)}`} />
        <MetricLine label="Stop-loss" value={formatPrice(tradePlan.stop_loss)} />
        <MetricLine label="TP1" value={formatCompactTarget(tradePlan, 0)} />
        <MetricLine label="TP2" value={formatCompactTarget(tradePlan, 1)} />
        <MetricLine label="Runner" value={formatCompactRunnerTarget(tradePlan)} />
        <MetricLine label="Selected RR" value={formatRMultiple(tradePlan.selected_rr)} />
        <MetricLine label="Invalidation" value={tradePlan.invalidation} />
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
  const riskCheck = execution?.risk_check ?? execution?.risk_decision?.risk_check ?? null;
  const sizing = execution?.position_sizing ?? execution?.risk_decision?.checked_position_sizing ?? null;
  return (
    <div className="risk-reward-detail-block risk-compact">
      <div className="section-title">
        <ShieldAlert size={18} />
        <h3>Risk</h3>
        <Badge tone={riskGateTone(riskCheck?.status ?? execution?.risk_decision?.status ?? null)}>
          {riskCheck?.status ?? execution?.risk_decision?.status ?? (loading ? "checking" : "not previewed")}
        </Badge>
      </div>
      <div className="compact-metric-grid risk-compact-grid">
        <MetricLine label="Risk amount / %" value={`${formatCurrencyAmount(riskCheck?.effective_risk_amount ?? sizing?.risk_amount)} / ${formatPercentValue(riskCheck?.adjusted_risk_percent ?? sizing?.risk_per_trade_percent)}`} />
        <MetricLine label="Margin / leverage" value={`${formatCurrencyAmount(riskCheck?.required_margin ?? sizing?.required_margin)} / ${sizing?.leverage == null ? "-" : `${sizing.leverage}x`}`} />
        <MetricLine label="Execution quality" value={execution ? `${execution.quality_gate.status} / ${execution.liquidity.impact_risk} impact` : error ? "Preview error" : loading ? "Checking" : "not previewed"} />
      </div>
    </div>
  );
}

function WhyThisSignal({ reasons }: { reasons: string[] }) {
  return (
    <div className="explanation-block why-signal-block">
      <h3>Why this signal?</h3>
      <ul>{reasons.map((reason) => <li key={reason}><span>{reason}</span></li>)}</ul>
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
  canEnterNow: boolean | null;
}) {
  return (
    <div className="actions-block">
      <div className="section-title">
        <FileCheck2 size={18} />
        <h3>Actions</h3>
        <Badge tone={canEnterNow === true ? "green" : canEnterNow === false ? "red" : "yellow"}>
          {canEnterNowLabel(canEnterNow)}
        </Badge>
      </div>
      <p className="compact-action-note">Execution environment: {realExecutionEnvironment}</p>
      <div className="detail-actions compact-actions">
        <button className="secondary-action" onClick={onAcceptPendingEntry} disabled={acceptPendingDisabled} type="button">
          <FileCheck2 size={17} /> Virtual wait entry
        </button>
        <button className="real-action" onClick={() => setRealConfirmationOpen(true)} disabled={realActionDisabled} type="button">
          <ShieldAlert size={17} /> Real wait entry
        </button>
        <button className="primary-action" onClick={onPaperTrade} disabled={entryActionDisabled} type="button">
          <FileCheck2 size={17} /> {canEnterNow === true ? "Virtual entry now" : "Virtual entry locked"}
        </button>
        {activePendingEntry ? (
          <button className="secondary-action" onClick={onCancelPendingEntry} disabled={cancelPendingDisabled} type="button">
            <XCircle size={17} /> Cancel waiting
          </button>
        ) : null}
        <button className="secondary-action" onClick={onToggleChart} type="button">
          <BarChart3 size={17} /> {chartOpen ? "Hide chart" : "Open chart"}
        </button>
        <button className="danger-action" onClick={onReject} disabled={rejectDisabled} type="button">
          <XCircle size={17} /> Reject / ignore
        </button>
      </div>
      {tradingActionsDisabled ? (
        <p className="compact-action-note">Trading actions disabled until realtime data is current.</p>
      ) : backendDisabledReason ? (
        <p className="compact-action-note">{backendDisabledReason}</p>
      ) : null}
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
          <span>Р”РёР°РіРЅРѕСЃС‚РёРєР°</span>
        </span>
        <Badge tone={open ? "blue" : "neutral"}>{open ? "open" : "collapsed"}</Badge>
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
  return (
    <div className="risk-reward-detail-block">
      <div className="section-title">
        <ShieldAlert size={18} />
        <h3>Backend Action State</h3>
        <Badge tone={viewModel.primaryStatusTone}>{viewModel.primaryStatusLabel}</Badge>
      </div>
      <div className="risk-reward-detail-grid">
        <MetricLine label="Signal status" value={signal.status.replaceAll("_", " ")} />
        <MetricLine label="Primary action" value={actionState?.primary_action ?? "-"} />
        <MetricLine label="Can enter" value={canEnterNowLabel(actionState?.can_enter_now ?? null)} />
        <MetricLine label="Can arm pending" value={formatBool(actionState?.can_arm_pending)} />
        <MetricLine label="Can cancel" value={formatBool(actionState?.can_cancel)} />
        <MetricLine label="Environment" value={actionState?.environment ?? "-"} />
      </div>
      {[...viewModel.topBlockers, ...viewModel.warnings].length ? (
        <ul className="risk-blocker-list">
          {[...viewModel.topBlockers, ...viewModel.warnings].map((blocker) => (
            <li key={blockerKey(blocker)}>{blocker.userMessage}</li>
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
  if (!pendingEntry) return null;
  return (
    <div className="auto-entry-block">
      <div className="section-title">
        <FileCheck2 size={18} />
        <h3>Pending Entry</h3>
        <Badge tone={pendingEntry.view?.status_tone ?? pendingEntryTone(pendingEntry.status)}>
          {pendingEntry.view?.status_label ?? pendingEntry.status.replaceAll("_", " ")}
        </Badge>
      </div>
      <p>{pendingEntry.view?.reason ?? pendingEntry.failure_reason ?? "No backend reason."}</p>
      <div className="risk-reward-detail-grid">
        <MetricLine label="Entry zone" value={pendingEntry.view?.entry_zone ?? `${formatPrice(pendingEntry.entry_min)} - ${formatPrice(pendingEntry.entry_max)}`} />
        <MetricLine label="Stop" value={formatPrice(pendingEntry.stop_loss)} />
        <MetricLine label="Mode" value={pendingEntry.mode} />
        <MetricLine label="Accepted status" value={pendingEntry.accepted_signal_status.replaceAll("_", " ")} />
      </div>
      {pendingEntry.status === "requires_reconfirmation" && onReconfirmPendingEntry ? (
        <div className="detail-actions">
          <button className="secondary-action" disabled={busy} onClick={() => onReconfirmPendingEntry(pendingEntry)} type="button">
            <FileCheck2 size={17} /> Reconfirm plan
          </button>
        </div>
      ) : null}
    </div>
  );
}

function PendingEntryHistoryCollapsed({ pendingEntry }: { pendingEntry: PendingEntryIntent | null }) {
  if (!pendingEntry) return null;
  return (
    <details className="risk-reward-detail-block pending-entry-history-block">
      <summary className="pending-entry-history-summary">
        <span className="section-title">
          <FileCheck2 size={18} />
          <h3>РСЃС‚РѕСЂРёСЏ РѕР¶РёРґР°РЅРёСЏ РІС…РѕРґР°</h3>
        </span>
        <Badge tone={pendingEntry.view?.status_tone ?? pendingEntryTone(pendingEntry.status)}>
          {pendingEntry.view?.status_label ?? pendingEntry.status.replaceAll("_", " ")}
        </Badge>
      </summary>
      <div className="risk-reward-detail-grid">
        <MetricLine label="Status" value={pendingEntry.status.replaceAll("_", " ")} />
        <MetricLine label="Reason" value={pendingEntry.view?.reason ?? pendingEntry.failure_reason ?? "-"} />
        <MetricLine label="Updated" value={formatPendingEntryTimestamp(pendingEntry.updated_at)} />
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
  return (
    <div className="execution-quality-block">
      <div className="section-title">
        <ShieldAlert size={18} />
        <h3>Backend Execution Preview</h3>
        <Badge tone={execution ? riskGateTone(execution.risk_check?.status ?? execution.risk_decision?.status ?? null) : loading ? "yellow" : "neutral"}>
          {execution?.risk_check?.status ?? execution?.risk_decision?.status ?? (loading ? "checking" : "not previewed")}
        </Badge>
      </div>
      {execution ? (
        <div className="execution-quality-grid">
          <MetricLine label="Quality gate" value={execution.quality_gate.status} />
          <MetricLine label="Impact risk" value={execution.liquidity.impact_risk} />
          <MetricLine label="Requested size" value={formatCurrencyAmount(execution.requested_size_usd)} />
          <MetricLine label="Filled size" value={formatCurrencyAmount(execution.filled_size_usd)} />
          <MetricLine label="Entry slippage" value={formatBps(execution.entry_slippage_bps)} />
          <MetricLine label="Reason" value={execution.reason_code ?? "-"} />
        </div>
      ) : (
        <p>{error ?? (loading ? "Backend execution preview is loading." : "No execution preview requested.")}</p>
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
            <span className="muted">Real execution</span>
            <h3 id="real-trade-confirm-title">РџРѕРґС‚РІРµСЂР¶РґРµРЅРёРµ СЂРµР°Р»СЊРЅРѕРіРѕ РІС…РѕРґР°</h3>
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
          <span>Real execution availability is backend-owned. Confirm only sends the selected intent.</span>
        </div>

        <div className="real-trade-metric-grid">
          <RealTradeMetric label="Exchange" value={context?.connection ? `${context.connection.exchange_name || context.connection.exchange_code} В· ${context.connection.label}` : signal.exchange} />
          <RealTradeMetric label="Account equity" value={formatCurrencyAmount(context?.accountSnapshot?.account_equity)} />
          <RealTradeMetric label="Available balance" value={formatCurrencyAmount(riskCheck?.available_balance)} />
          <RealTradeMetric label="Symbol / side" value={`${signal.symbol} / ${signal.direction.toUpperCase()}`} />
          <RealTradeMetric label="Entry zone" value={tradePlan?.entry_zone ?? "-"} />
          <RealTradeMetric label="Stop-loss" value={formatPrice(tradePlan?.stop_loss)} />
          <RealTradeMetric label="Selected RR" value={formatRMultiple(tradePlan?.selected_rr ?? null)} />
          <RealTradeMetric label="RiskGate" value={riskCheck?.status ?? execution?.risk_decision?.status ?? "-"} />
        </div>

        <div className="real-trade-blockers">
          <strong>Backend blockers / warnings</strong>
          {blockers.length ? (
            <ul className="risk-blocker-list">
              {blockers.map((blocker) => (
                <li key={blocker.code}>{blocker.display_label ?? blocker.message ?? blocker.code}</li>
              ))}
            </ul>
          ) : (
            <p>Р‘Р»РѕРєРµСЂРѕРІ РЅРµС‚.</p>
          )}
          {warnings.length ? (
            <div className="real-trade-warning-list">
              {warnings.map((warning) => (
                <span key={warning.code}>{warning.display_label ?? warning.message ?? warning.code}</span>
              ))}
            </div>
          ) : null}
        </div>

        <div className="real-trade-modal-actions">
          <button className="secondary-action" onClick={onCancel} type="button">РћС‚РјРµРЅР°</button>
          <button className="real-action" disabled={confirmDisabled} onClick={onConfirm} type="button">
            <ShieldAlert size={17} /> РџРѕРґС‚РІРµСЂРґРёС‚СЊ СЂРµР°Р»СЊРЅС‹Р№ РІС…РѕРґ
          </button>
        </div>
      </div>
    </div>
  );
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

function canEnterNowLabel(value: boolean | null): string {
  if (value == null) return "not evaluated";
  return value ? "yes" : "no";
}

function formatBool(value: boolean | undefined): string {
  if (value == null) return "not evaluated";
  return value ? "yes" : "no";
}

function formatPendingEntryExpiry(pendingEntry: PendingEntryIntent): string {
  if (!pendingEntry.expires_at) return "no expiry";
  return `${formatPendingEntryTimestamp(pendingEntry.expires_at)} / ${formatPendingEntryTtl(pendingEntry.expires_at)}`;
}

function formatPendingEntryTtl(value: string): string {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return "TTL unknown";
  const diffMs = timestamp - Date.now();
  if (diffMs <= 0) return "expired";
  const diffMinutes = Math.ceil(diffMs / 60_000);
  if (diffMinutes < 60) return `${diffMinutes}m left`;
  return `${Math.ceil(diffMinutes / 60)}h left`;
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

function actionStateDisabledReason(state: SignalActionState | null): string | null {
  if (!state) return null;
  const blocker = state.blockers[0] ?? null;
  return state.display_labels.disabled_reason
    ?? blocker?.display_label
    ?? blocker?.message
    ?? state.disabled_reason_code
    ?? null;
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

function formatBps(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "slippage -";
  return `slippage ${value.toFixed(1)} bps`;
}

function blockerKey(blocker: UiBlocker): string {
  return `${blocker.code}:${blocker.userMessage}`;
}
