"use client";

import { useCallback, useMemo, useState, type KeyboardEvent, type MouseEvent } from "react";
import { ChevronDown, ChevronRight, EyeOff, FileCheck2, Filter, RadioTower, RefreshCw, ShieldAlert, XCircle } from "lucide-react";

import { Metric } from "@/components/Metric";
import { SignalDetails, type RealTradeContext } from "@/components/SignalDetails";
import { SignalFeed } from "@/components/SignalFeed";
import type { RealExecutionResultDto } from "@/api/generated/schemas";
import { RADAR_STATUS_FILTERS } from "@/domain/signal-status";
import type { RadarDisplayMode } from "@/features/server-state/types";
import { isActivePendingEntryStatus, isTerminalPendingEntryStatus } from "@/domain/pending-entry-status";
import { useI18n, type I18nKey } from "@/i18n";
import type { HealthStatus, PendingEntryIntent, RadarSignal, RadarStatus, RadarSummary, SignalActionState, SignalStatus, VirtualExecutionReport } from "@/types";
import { formatPrice } from "@/utils";

interface RadarPageProps {
  busy: boolean;
  filter: "all" | "long" | "short";
  radarDisplayMode: RadarDisplayMode;
  signalView: "open" | "history";
  statusFilter: "all" | SignalStatus;
  health: HealthStatus | null;
  loading: boolean;
  onFilterChange: (filter: "all" | "long" | "short") => void;
  onAcceptPendingEntry: (signal: RadarSignal) => void;
  onCancelPendingEntry: (intent: PendingEntryIntent) => void;
  onReconfirmPendingEntry: (intent: PendingEntryIntent) => void;
  onRadarDisplayModeChange: (mode: RadarDisplayMode) => void;
  onSignalViewChange: (view: "open" | "history") => void;
  onStatusFilterChange: (filter: "all" | SignalStatus) => void;
  onConfirmRealTrade: (signal: RadarSignal) => void;
  onPaperTrade: (signal: RadarSignal) => void;
  onRefresh: () => void;
  onReject: (signal: RadarSignal) => void;
  onSelectSignal: (signal: RadarSignal) => void;
  onSelectPendingEntrySignal: (intent: PendingEntryIntent) => void;
  onSelectLatestSignal: () => void;
  radarStatus: RadarStatus | null;
  radarSummary?: RadarSummary | null;
  selectedSignal: RadarSignal | null;
  selectedSignalId: string | null;
  missingSelectedSignalId?: string | null;
  selectedPendingEntry?: PendingEntryIntent | null;
  pendingEntries: PendingEntryIntent[];
  pendingEntryHistory: PendingEntryIntent[];
  pendingEntriesLoading?: boolean;
  signalIds: string[];
  signals: RadarSignal[];
  actionError?: string | null;
  executionPreview?: VirtualExecutionReport | null;
  executionPreviewError?: string | null;
  executionPreviewLoading?: boolean;
  realExecutionPreview?: RealExecutionResultDto | null;
  realExecutionPreviewError?: string | null;
  realExecutionPreviewLoading?: boolean;
  actionState?: SignalActionState | null;
  actionStateLoading?: boolean;
  realActionState?: SignalActionState | null;
  pendingEntryLoading?: boolean;
  realTradeContext?: RealTradeContext;
  realTradeBusy?: boolean;
  tradingActionsDisabled?: boolean;
  selectedPendingEntryId?: string | null;
}

export function RadarPage(props: RadarPageProps) {
  const { t, tKey } = useI18n();
  const [pendingEntriesCollapsed, setPendingEntriesCollapsed] = useState(false);
  const [hiddenHistoryEntryIds, setHiddenHistoryEntryIds] = useState(() => readHiddenPendingEntryIds());
  const summary = props.radarSummary;
  const scannerPairCount = props.radarStatus?.scanner_pairs_count ?? props.health?.scanner_pairs_count ?? props.radarStatus?.symbols.length ?? 0;
  const scannerUniverse = props.radarStatus?.scanner_universe_source ?? props.health?.scanner_universe_source ?? "default";
  const estimatedEvaluations = props.radarStatus?.estimated_strategy_checks ?? props.health?.estimated_strategy_checks ?? 0;
  const scannerWarning = props.radarStatus?.scanner_universe_warning ?? props.health?.scanner_universe_warning ?? null;
  const scannerRuntime = props.radarStatus ?? props.health;
  const scannerMarketLabel = tKey(scannerMarketStatusLabelKey(scannerRuntime));
  const warmupTotal = scannerRuntime?.warmup_total ?? 0;
  const warmupCompleted = scannerRuntime?.warmup_completed ?? 0;
  const warmupFailed = scannerRuntime?.warmup_failed ?? 0;
  const lastTickAge = formatLastTickAge(scannerRuntime?.last_tick_age_seconds, tKey);
  const lastError = scannerRuntime?.last_error ?? null;
  const latestSeries = Object.entries(props.radarStatus?.candle_history ?? {})
    .sort(([, left], [, right]) => right - left)
    .slice(0, 6);
  const visiblePendingEntryHistory = useMemo(
    () => props.pendingEntryHistory.filter((intent) => !hiddenHistoryEntryIds.has(intent.id)),
    [hiddenHistoryEntryIds, props.pendingEntryHistory]
  );
  const handleDismissPendingEntryHistory = useCallback((intent: PendingEntryIntent) => {
    setHiddenHistoryEntryIds((current) => {
      const next = new Set(current);
      next.add(intent.id);
      writeHiddenPendingEntryIds(next);
      return next;
    });
  }, []);

  return (
    <div className="page-grid">
      {props.actionError ? <div className="error-banner">{props.actionError}</div> : null}
      <section className="feed-panel">
        <div className="page-head">
          <div>
            <span className="muted">{tKey("radar.eyebrow")}</span>
            <h1>{tKey("radar.title")}</h1>
          </div>
          <button className="icon-button" onClick={props.onRefresh} type="button" title={tKey("common.refresh")}>
            <RefreshCw size={18} />
          </button>
        </div>

        <div className="metrics-grid">
          <Metric label={tKey("radar.marketStatus")} value={scannerMarketLabel} hint={tKey("radar.scanner")} />
          <Metric label={tKey("radar.executionReady")} value={String(summary?.execution_ready_signals ?? 0)} hint={tKey("radar.riskGate")} />
          <Metric label={tKey("radar.highConfidence")} value={String(summary?.high_confidence_signals ?? 0)} hint={tKey("radar.score80")} />
          <Metric label={tKey("radar.positiveEdge")} value={String(summary?.positive_edge_signals ?? 0)} hint={tKey("radar.evGate")} />
          <Metric label={tKey("radar.blockedIdeas")} value={String(summary?.blocked_ideas ?? 0)} hint={tKey("radar.backend")} />
          <Metric label={tKey("radar.ticks")} value={String(props.radarStatus?.ticks_processed ?? props.health?.ticks_processed ?? 0)} hint={tKey("radar.marketData")} />
          <Metric label={tKey("radar.strategyChecks")} value={String(props.radarStatus?.strategy_evaluations ?? props.health?.strategy_evaluations ?? 0)} hint={tKey("radar.evaluated")} />
          <Metric label={tKey("radar.features")} value={String(props.radarStatus?.features_built ?? props.health?.features_built ?? 0)} hint={tKey("radar.candlesAnalyzed")} />
        </div>

        <div className="scanner-panel">
          <div>
            <span className="muted">{tKey("radar.scannerActivity")}</span>
            <strong>
              {props.radarStatus?.last_symbol
                ? `${props.radarStatus.last_exchange ?? ""} ${props.radarStatus.last_symbol} ${props.radarStatus.last_price ?? ""}`
                : scannerMarketLabel}
            </strong>
          </div>
          <div className="scanner-stats">
            <span>{tKey("radar.warmupProgress", { completed: warmupCompleted, total: warmupTotal, failed: warmupFailed })}</span>
            <span>{tKey("radar.lastTickAge", { age: lastTickAge })}</span>
            <span>{tKey("radar.signalsFound", { count: props.radarStatus?.signals_found ?? props.health?.signals_found ?? 0 })}</span>
            <span>{tKey("radar.seededCandles", { count: props.radarStatus?.candles_seeded ?? props.health?.candles_seeded ?? 0 })}</span>
            <span>{tKey("radar.pairs", { count: scannerPairCount })}</span>
            <span>{tKey("radar.universe", { universe: scannerUniverse })}</span>
            <span>{tKey("radar.estimatedEvaluations", { count: estimatedEvaluations })}</span>
            <span>{tKey("radar.timeframes", { timeframes: props.radarStatus?.timeframes.join(", ") ?? "1m, 5m, 15m, 1h, 4h, 1d" })}</span>
            {scannerWarning ? <span>{tKey("radar.warning", { warning: scannerWarning })}</span> : null}
            {lastError ? <span className="error-pill" title={lastError}>{tKey("radar.lastError", { error: lastError })}</span> : null}
          </div>
          <div className="history-grid">
            {latestSeries.length ? latestSeries.map(([series, candles]) => (
              <span key={series}>{series}: {tKey("radar.candles", { count: candles })}</span>
            )) : <span>{tKey("radar.candleHistoryWarming")}</span>}
          </div>
        </div>

        <PendingEntriesQueue
          activeEntries={props.pendingEntries}
          busy={props.busy || Boolean(props.tradingActionsDisabled)}
          collapsed={pendingEntriesCollapsed}
          hiddenHistoryEntryIds={hiddenHistoryEntryIds}
          historyEntries={visiblePendingEntryHistory}
          loading={props.pendingEntriesLoading ?? false}
          onCancelPendingEntry={props.onCancelPendingEntry}
          onDismissHistoryEntry={handleDismissPendingEntryHistory}
          onReconfirmPendingEntry={props.onReconfirmPendingEntry}
          onSelectPendingEntrySignal={props.onSelectPendingEntrySignal}
          onToggleCollapsed={() => setPendingEntriesCollapsed((collapsed) => !collapsed)}
          selectedPendingEntryId={props.selectedPendingEntryId ?? null}
          selectedSignalId={props.selectedSignalId}
        />

        <div className="filter-row">
          <Filter size={16} />
          {(["open", "history"] as const).map((item) => (
            <button
              className={props.signalView === item ? "filter-chip active" : "filter-chip"}
              key={item}
              onClick={() => props.onSignalViewChange(item)}
              type="button"
            >
              {item === "open" ? tKey("radar.openIdeas") : tKey("radar.history")}
            </button>
          ))}
        </div>
        <div className="filter-row">
          {([
            { labelKey: "radar.hotFilter", value: "execution_ready" },
            { labelKey: "radar.watchlistFilter", value: "watchlist" },
            { labelKey: "radar.diagnosticsFilter", value: "all_market_opportunities" },
            { labelKey: "radar.blockedFilter", value: "blocked" }
          ] as const).map((item) => (
            <button
              className={props.radarDisplayMode === item.value ? "filter-chip active" : "filter-chip"}
              key={item.value}
              onClick={() => props.onRadarDisplayModeChange(item.value)}
              type="button"
            >
              {tKey(item.labelKey)}
            </button>
          ))}
        </div>
        <div className="filter-row">
          {(["all", "long", "short"] as const).map((item) => (
            <button
              className={props.filter === item ? "filter-chip active" : "filter-chip"}
              key={item}
              onClick={() => props.onFilterChange(item)}
              type="button"
            >
              {tKey(radarDirectionFilterKey(item))}
            </button>
          ))}
        </div>
        <div className="filter-row status-filter-row">
          {RADAR_STATUS_FILTERS.map((item) => (
            <button
              className={props.statusFilter === item ? "filter-chip active" : "filter-chip"}
              key={item}
              onClick={() => props.onStatusFilterChange(item)}
              type="button"
            >
              {t(item.replaceAll("_", " "))}
            </button>
          ))}
        </div>

        <SignalFeed
          emptyState={
            <div className="empty-state">
              <RadioTower size={26} />
              <strong>{props.signalView === "history" ? tKey("radar.noHistoricalSignals") : tKey("radar.noMarketOpportunities")}</strong>
              <span>
                {props.signalView === "history"
                  ? tKey("radar.historicalSignalsEmpty")
                  : tKey("radar.marketOpportunitiesEmpty")}
              </span>
            </div>
          }
          loading={props.loading}
          signalIds={props.signalIds}
          signals={props.signals}
          selectedSignalId={props.selectedSignalId}
          onSelectSignal={props.onSelectSignal}
        />
      </section>

      {props.selectedSignal || !props.selectedPendingEntry ? (
        <SignalDetails
          signal={props.selectedSignal}
          onPaperTrade={props.onPaperTrade}
          onConfirmRealTrade={props.onConfirmRealTrade}
          onAcceptPendingEntry={props.onAcceptPendingEntry}
          onCancelPendingEntry={props.onCancelPendingEntry}
          onReconfirmPendingEntry={props.onReconfirmPendingEntry}
          onReject={props.onReject}
          busy={props.busy}
          pendingEntry={props.selectedPendingEntry ?? null}
          pendingEntryLoading={props.pendingEntryLoading ?? false}
          executionPreview={props.executionPreview ?? null}
          executionPreviewError={props.executionPreviewError ?? null}
          executionPreviewLoading={props.executionPreviewLoading ?? false}
          realExecutionPreview={props.realExecutionPreview ?? null}
          realExecutionPreviewError={props.realExecutionPreviewError ?? null}
          realExecutionPreviewLoading={props.realExecutionPreviewLoading ?? false}
          actionState={props.actionState}
          actionStateLoading={props.actionStateLoading ?? false}
          realActionState={props.realActionState}
          realTradeContext={props.realTradeContext}
          realTradeBusy={props.realTradeBusy ?? false}
          tradingActionsDisabled={props.tradingActionsDisabled}
          missingSignalId={props.missingSelectedSignalId ?? null}
          onSelectLatestSignal={props.onSelectLatestSignal}
        />
      ) : (
        <PendingEntryDetailsPanel
          busy={props.busy || Boolean(props.tradingActionsDisabled)}
          missingSignalId={props.missingSelectedSignalId ?? null}
          onCancelPendingEntry={props.onCancelPendingEntry}
          onReconfirmPendingEntry={props.onReconfirmPendingEntry}
          pendingEntry={props.selectedPendingEntry}
        />
      )}
    </div>
  );
}

function PendingEntriesQueue({
  activeEntries,
  busy,
  collapsed,
  hiddenHistoryEntryIds,
  historyEntries,
  loading,
  onCancelPendingEntry,
  onDismissHistoryEntry,
  onReconfirmPendingEntry,
  onSelectPendingEntrySignal,
  onToggleCollapsed,
  selectedPendingEntryId,
  selectedSignalId
}: {
  activeEntries: PendingEntryIntent[];
  busy: boolean;
  collapsed: boolean;
  hiddenHistoryEntryIds: Set<string>;
  historyEntries: PendingEntryIntent[];
  loading: boolean;
  onCancelPendingEntry: (intent: PendingEntryIntent) => void;
  onDismissHistoryEntry: (intent: PendingEntryIntent) => void;
  onReconfirmPendingEntry: (intent: PendingEntryIntent) => void;
  onSelectPendingEntrySignal: (intent: PendingEntryIntent) => void;
  onToggleCollapsed: () => void;
  selectedPendingEntryId: string | null;
  selectedSignalId: string | null;
}) {
  const { tKey } = useI18n();
  const active = activeEntries.filter((intent) => intent.mode !== "real" && isActivePendingEntryStatus(intent.status));
  const unsupportedReal = activeEntries.filter((intent) => intent.mode === "real" && isActivePendingEntryStatus(intent.status));
  const history = historyEntries.filter((intent) => isTerminalPendingEntryStatus(intent.status));
  const hiddenCount = hiddenHistoryEntryIds.size;
  const collapseLabel = collapsed ? tKey("pendingEntry.expandQueue") : tKey("pendingEntry.collapseQueue");

  return (
    <section className="pending-entries-panel">
      <div className="pending-entries-head">
        <div>
          <span className="muted">{tKey("pendingEntry.queueEyebrow")}</span>
          <h3>{tKey("pendingEntry.selectedEntries")}</h3>
        </div>
        <div className="pending-entries-head-actions">
          <span className="badge badge-blue">{tKey("pendingEntry.activeCount", { count: active.length })}</span>
          {hiddenCount ? <span className="badge">{tKey("pendingEntry.hiddenCount", { count: hiddenCount })}</span> : null}
          <button
            aria-expanded={!collapsed}
            aria-label={collapseLabel}
            className="icon-button compact-icon-button"
            onClick={onToggleCollapsed}
            title={collapseLabel}
            type="button"
          >
            {collapsed ? <ChevronRight size={17} /> : <ChevronDown size={17} />}
          </button>
        </div>
      </div>
      {collapsed ? null : (
        <>
          {loading && !active.length ? (
            <div className="empty-state compact-empty">{tKey("pendingEntry.loading")}</div>
          ) : active.length ? (
            <div className="pending-entry-list">
              {active.map((intent) => (
                <PendingEntryQueueItem
                  busy={busy}
                  intent={intent}
                  key={intent.id}
                  onCancelPendingEntry={onCancelPendingEntry}
                  onReconfirmPendingEntry={onReconfirmPendingEntry}
                  onSelectPendingEntrySignal={onSelectPendingEntrySignal}
                  selected={isPendingEntrySelected(intent, selectedPendingEntryId, selectedSignalId)}
                />
              ))}
            </div>
          ) : (
            <div className="empty-state compact-empty">{tKey("pendingEntry.noActive")}</div>
          )}
          {unsupportedReal.length ? (
            <div className="pending-entry-list unsupported-real-pending-list">
              <div className="section-title compact-section-title">
                <ShieldAlert size={18} />
                <h3>{tKey("pendingEntry.unsupportedRealPending")}</h3>
                <span className="badge badge-yellow">{tKey("pendingEntry.diagnosticOnly")}</span>
              </div>
              <p className="compact-action-note">{tKey("pendingEntry.realPendingUnavailable")}</p>
              {unsupportedReal.map((intent) => (
                <PendingEntryQueueItem
                  busy={busy}
                  diagnosticOnly
                  intent={intent}
                  key={intent.id}
                  onCancelPendingEntry={onCancelPendingEntry}
                  onReconfirmPendingEntry={onReconfirmPendingEntry}
                  onSelectPendingEntrySignal={onSelectPendingEntrySignal}
                  selected={isPendingEntrySelected(intent, selectedPendingEntryId, selectedSignalId)}
                />
              ))}
            </div>
          ) : null}
          <details className="pending-entry-history-queue">
            <summary>
              <span>{tKey("pendingEntry.history")}</span>
              <span className="badge">{history.length}</span>
            </summary>
            {history.length ? (
              <div className="pending-entry-list history">
                {history.map((intent) => (
                  <PendingEntryQueueItem
                    busy={busy}
                    intent={intent}
                    key={intent.id}
                    onCancelPendingEntry={onCancelPendingEntry}
                    onDismissHistoryEntry={onDismissHistoryEntry}
                    onReconfirmPendingEntry={onReconfirmPendingEntry}
                    onSelectPendingEntrySignal={onSelectPendingEntrySignal}
                    selected={isPendingEntrySelected(intent, selectedPendingEntryId, selectedSignalId)}
                  />
                ))}
              </div>
            ) : (
              <div className="empty-state compact-empty">{tKey("pendingEntry.noHistory")}</div>
            )}
          </details>
        </>
      )}
    </section>
  );
}

function PendingEntryDetailsPanel({
  busy,
  missingSignalId,
  onCancelPendingEntry,
  onReconfirmPendingEntry,
  pendingEntry
}: {
  busy: boolean;
  missingSignalId: string | null;
  onCancelPendingEntry: (intent: PendingEntryIntent) => void;
  onReconfirmPendingEntry: (intent: PendingEntryIntent) => void;
  pendingEntry: PendingEntryIntent;
}) {
  const { t, tKey, tReason } = useI18n();
  const reasonCode = pendingEntry.view?.reason_code ?? pendingEntry.reason_code ?? null;
  const reason = reasonCode
    ? tReason(reasonCode)
    : tReason(pendingEntry.view?.reason ?? pendingEntry.failure_reason ?? tKey("pendingEntry.noBackendReason"));
  const unsupportedReal = pendingEntry.mode === "real";
  const canCancel = isActivePendingEntryStatus(pendingEntry.status) && !unsupportedReal;
  const canReconfirm = pendingEntry.status === "requires_reconfirmation" && !unsupportedReal;

  return (
    <section className="details-panel pending-entry-details-panel">
      <div className="details-header">
        <div>
          <span className="muted">{tKey("pendingEntry.detailsTitle")}</span>
          <h2>{pendingEntry.symbol}</h2>
        </div>
        <div className="details-badges">
          <span className={`badge badge-${pendingEntryTone(pendingEntry.status)}`}>{t(pendingEntry.status.replaceAll("_", " "))}</span>
          <span className="badge badge-purple">{pendingEntry.mode}</span>
        </div>
      </div>

      {missingSignalId ? <div className="warning-banner">{tKey("pendingEntry.originalSignalMissing")}</div> : null}
      {unsupportedReal ? <div className="warning-banner">{tKey("pendingEntry.realPendingDiagnostic")}</div> : null}

      <div className="pending-entry-block">
        <div className="section-title">
          <FileCheck2 size={18} />
          <h3>{tKey("pendingEntry.acceptedSnapshot")}</h3>
        </div>
        <p>{reason}</p>
        <div className="risk-reward-detail-grid">
          <MetricLine label={tKey("pendingEntry.entryZone")} value={pendingEntry.view?.entry_zone ?? `${formatPrice(pendingEntry.entry_min)} - ${formatPrice(pendingEntry.entry_max)}`} />
          <MetricLine label={tKey("pendingEntry.stop")} value={formatPrice(pendingEntry.stop_loss)} />
          <MetricLine label={tKey("pendingEntry.reasonCode")} value={reasonCode ?? "-"} />
          <MetricLine label={tKey("pendingEntry.currentPrice")} value={formatPrice(pendingEntry.view?.current_price ?? pendingEntry.current_price ?? null)} />
          <MetricLine label={tKey("pendingEntry.expires")} value={formatPendingEntryTtl(pendingEntry.expires_at, tKey)} />
          <MetricLine label={tKey("pendingEntry.acceptedStatus")} value={t(pendingEntry.accepted_signal_status.replaceAll("_", " "))} />
          <MetricLine label={tKey("pendingEntry.targets")} value={formatPendingEntryTargets(pendingEntry.targets_snapshot)} />
          <MetricLine label={tKey("pendingEntry.updated")} value={formatPendingEntryTimestamp(pendingEntry.updated_at)} />
        </div>
      </div>

      <div className="detail-actions">
        {canReconfirm ? (
          <button className="secondary-action" disabled={busy} onClick={() => onReconfirmPendingEntry(pendingEntry)} type="button">
            <RefreshCw size={17} /> {tKey("pendingEntry.reconfirmPlan")}
          </button>
        ) : (
          null
        )}
        {canCancel ? (
          <button className="secondary-action" disabled={busy} onClick={() => onCancelPendingEntry(pendingEntry)} type="button">
            <XCircle size={17} /> {tKey("pendingEntry.cancel")}
          </button>
        ) : null}
      </div>
    </section>
  );
}

function PendingEntryQueueItem({
  busy,
  diagnosticOnly = false,
  intent,
  onCancelPendingEntry,
  onDismissHistoryEntry,
  onReconfirmPendingEntry,
  onSelectPendingEntrySignal,
  selected
}: {
  busy: boolean;
  diagnosticOnly?: boolean;
  intent: PendingEntryIntent;
  onCancelPendingEntry: (intent: PendingEntryIntent) => void;
  onDismissHistoryEntry?: (intent: PendingEntryIntent) => void;
  onReconfirmPendingEntry: (intent: PendingEntryIntent) => void;
  onSelectPendingEntrySignal: (intent: PendingEntryIntent) => void;
  selected: boolean;
}) {
  const { t, tKey, tReason } = useI18n();
  const reasonCode = intent.view?.reason_code ?? intent.reason_code ?? null;
  const reason = reasonCode
    ? tReason(reasonCode)
    : tReason(intent.view?.reason ?? intent.failure_reason ?? tKey("pendingEntry.noReasonFromBackend"));
  const currentPrice = intent.view?.current_price == null ? formatPrice(intent.current_price) : formatPrice(intent.view.current_price);
  const active = isActivePendingEntryStatus(intent.status);
  const terminal = isTerminalPendingEntryStatus(intent.status);
  const canCancel = active;
  const canReconfirm = intent.status === "requires_reconfirmation";
  const openLabel = tKey("pendingEntry.openQueueItem", { id: intent.id, symbol: intent.symbol });
  const handleSelect = () => onSelectPendingEntrySignal(intent);
  const handleKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.target instanceof Element) {
      const nestedControl = event.target.closest("button,a,input,select,textarea,[role='button'],[tabindex]");
      if (nestedControl && nestedControl !== event.currentTarget) return;
    }
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    handleSelect();
  };
  const handleActionClick = (event: MouseEvent<HTMLButtonElement>, action: () => void) => {
    event.stopPropagation();
    action();
  };

  return (
    <article
      aria-label={openLabel}
      className={selected ? "pending-entry-item selected" : "pending-entry-item"}
      onClick={handleSelect}
      onKeyDown={handleKeyDown}
      role="button"
      tabIndex={0}
    >
      <div className="pending-entry-main">
        <div>
          <strong>{intent.symbol}</strong>
          <span>{intent.exchange} / {intent.side.toUpperCase()}</span>
        </div>
        <div className="pending-entry-badges">
          <span className={`badge badge-${pendingEntryTone(intent.status)}`}>{t(intent.status.replaceAll("_", " "))}</span>
          <span className="badge badge-purple">{intent.mode}</span>
        </div>
      </div>
      <div className="pending-entry-metrics">
        <MetricLine label={tKey("pendingEntry.entryZone")} value={intent.view?.entry_zone ?? `${formatPrice(intent.entry_min)} - ${formatPrice(intent.entry_max)}`} />
        <MetricLine label={tKey("pendingEntry.currentPrice")} value={currentPrice} />
        <MetricLine label={tKey("pendingEntry.expires")} value={formatPendingEntryTtl(intent.expires_at, tKey)} />
        <MetricLine label={tKey("pendingEntry.reasonCode")} value={reasonCode ?? "-"} />
      </div>
      <p className="pending-entry-reason">{reason}</p>
      <div className="pending-entry-actions">
        <button className="secondary-action compact-action" onClick={(event) => handleActionClick(event, handleSelect)} type="button">
          <FileCheck2 size={15} /> {tKey("pendingEntry.selectSignal")}
        </button>
        {diagnosticOnly ? (
          <span className="badge badge-yellow">{tKey("pendingEntry.diagnosticOnly")}</span>
        ) : active ? (
          <>
            <button
              className="secondary-action compact-action"
              disabled={busy || !canReconfirm}
              onClick={(event) => handleActionClick(event, () => onReconfirmPendingEntry(intent))}
              type="button"
            >
              <RefreshCw size={15} /> {tKey("pendingEntry.reconfirm")}
            </button>
            <button
              className="secondary-action compact-action"
              disabled={busy || !canCancel}
              onClick={(event) => handleActionClick(event, () => onCancelPendingEntry(intent))}
              type="button"
            >
              <XCircle size={15} /> {tKey("pendingEntry.cancel")}
            </button>
          </>
        ) : null}
        {terminal && onDismissHistoryEntry ? (
          <button
            aria-label={tKey("pendingEntry.hideQueueItem", { id: intent.id })}
            className="secondary-action compact-action"
            onClick={(event) => handleActionClick(event, () => onDismissHistoryEntry(intent))}
            type="button"
          >
            <EyeOff size={15} /> {tKey("pendingEntry.hide")}
          </button>
        ) : null}
      </div>
    </article>
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

function isPendingEntrySelected(
  intent: PendingEntryIntent,
  selectedPendingEntryId: string | null,
  selectedSignalId: string | null
): boolean {
  return selectedPendingEntryId ? selectedPendingEntryId === intent.id : selectedSignalId === intent.signal_id;
}

function formatPendingEntryTargets(targets: PendingEntryIntent["targets_snapshot"]): string {
  if (Array.isArray(targets)) return String(targets.length);
  const values = Object.values(targets);
  return values.length ? String(values.length) : "-";
}

function pendingEntryTone(status: PendingEntryIntent["status"]): "green" | "red" | "yellow" | "blue" | "purple" | "neutral" {
  if (status === "pending") return "blue";
  if (status === "requires_reconfirmation") return "yellow";
  if (status === "triggered" || status === "filling" || status === "filled") return "green";
  if (status === "failed" || status === "cancelled" || status === "expired") return "red";
  return "neutral";
}

function formatPendingEntryTtl(value: string | null, tKey: (key: I18nKey, params?: Record<string, string | number | boolean | null | undefined>) => string): string {
  if (!value) return tKey("pendingEntry.noExpiry");
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return tKey("common.unknown");
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

const HIDDEN_PENDING_ENTRY_HISTORY_KEY = "crypto-radar:hidden-pending-entry-history";

function readHiddenPendingEntryIds(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = window.localStorage.getItem(HIDDEN_PENDING_ENTRY_HISTORY_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((value): value is string => typeof value === "string" && value.trim().length > 0));
  } catch {
    return new Set();
  }
}

function writeHiddenPendingEntryIds(values: Set<string>): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(HIDDEN_PENDING_ENTRY_HISTORY_KEY, JSON.stringify([...values]));
}

type ScannerRuntimeStatus = Pick<HealthStatus | RadarStatus, "market_data_status" | "stage">;

export function scannerMarketStatusLabelKey(status: ScannerRuntimeStatus | null | undefined): I18nKey {
  if (!status) return "common.unknown";
  if (status.market_data_status === "online") return "radar.online";
  if (status.market_data_status === "error") return "radar.scannerError";
  if (status.market_data_status === "stale") return "radar.dataStale";
  if (status.market_data_status === "waiting") {
    return status.stage === "starting" || status.stage === "warming_up"
      ? "radar.scannerConnecting"
      : "radar.waitingMarketData";
  }
  return "radar.offline";
}

function formatLastTickAge(
  value: number | null | undefined,
  tKey: (key: I18nKey, params?: Record<string, string | number | boolean | null | undefined>) => string
): string {
  if (value == null) return tKey("radar.noTicksYet");
  if (value < 1) return tKey("radar.justNow");
  if (value < 60) return `${Math.round(value)}s`;
  if (value < 3600) return `${Math.round(value / 60)}m`;
  return `${Math.round(value / 3600)}h`;
}

function radarDirectionFilterKey(value: "all" | "long" | "short"): I18nKey {
  if (value === "long") return "radar.longFilter";
  if (value === "short") return "radar.shortFilter";
  return "radar.allFilter";
}
