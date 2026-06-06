"use client";

import { FileCheck2, Filter, RadioTower, RefreshCw, XCircle } from "lucide-react";

import { Metric } from "@/components/Metric";
import { SignalDetails, type RealTradeContext } from "@/components/SignalDetails";
import { SignalFeed } from "@/components/SignalFeed";
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
  pendingEntryActionStates?: Record<string, SignalActionState | null>;
  pendingEntryActionStatesLoading?: Record<string, boolean>;
  signalIds: string[];
  signals: RadarSignal[];
  actionError?: string | null;
  executionPreview?: VirtualExecutionReport | null;
  executionPreviewError?: string | null;
  executionPreviewLoading?: boolean;
  actionState?: SignalActionState | null;
  actionStateLoading?: boolean;
  realActionState?: SignalActionState | null;
  pendingEntryLoading?: boolean;
  realTradeContext?: RealTradeContext;
  realTradeBusy?: boolean;
  tradingActionsDisabled?: boolean;
}

export function RadarPage(props: RadarPageProps) {
  const { t, tKey } = useI18n();
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
          actionStates={props.pendingEntryActionStates ?? {}}
          actionStatesLoading={props.pendingEntryActionStatesLoading ?? {}}
          busy={props.busy || Boolean(props.tradingActionsDisabled)}
          historyEntries={props.pendingEntryHistory}
          loading={props.pendingEntriesLoading ?? false}
          onCancelPendingEntry={props.onCancelPendingEntry}
          onReconfirmPendingEntry={props.onReconfirmPendingEntry}
          onSelectPendingEntrySignal={props.onSelectPendingEntrySignal}
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
            { labelKey: "radar.allIdeasFilter", value: "all_market_opportunities" },
            { labelKey: "radar.watchlistFilter", value: "watchlist" },
            { labelKey: "radar.readyToExecuteFilter", value: "execution_ready" },
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
        {props.radarDisplayMode === "blocked" ? (
          <div className="warning-banner">{tKey("radar.blockedDiagnosticsWarning")}</div>
        ) : null}
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
        actionState={props.actionState}
        actionStateLoading={props.actionStateLoading ?? false}
        realActionState={props.realActionState}
        realTradeContext={props.realTradeContext}
        realTradeBusy={props.realTradeBusy ?? false}
        tradingActionsDisabled={props.tradingActionsDisabled}
        missingSignalId={props.missingSelectedSignalId ?? null}
        onSelectLatestSignal={props.onSelectLatestSignal}
      />
    </div>
  );
}

function PendingEntriesQueue({
  activeEntries,
  actionStates,
  actionStatesLoading,
  busy,
  historyEntries,
  loading,
  onCancelPendingEntry,
  onReconfirmPendingEntry,
  onSelectPendingEntrySignal,
  selectedSignalId
}: {
  activeEntries: PendingEntryIntent[];
  actionStates: Record<string, SignalActionState | null>;
  actionStatesLoading: Record<string, boolean>;
  busy: boolean;
  historyEntries: PendingEntryIntent[];
  loading: boolean;
  onCancelPendingEntry: (intent: PendingEntryIntent) => void;
  onReconfirmPendingEntry: (intent: PendingEntryIntent) => void;
  onSelectPendingEntrySignal: (intent: PendingEntryIntent) => void;
  selectedSignalId: string | null;
}) {
  const { tKey } = useI18n();
  const active = activeEntries.filter((intent) => isActivePendingEntryStatus(intent.status));
  const history = historyEntries.filter((intent) => isTerminalPendingEntryStatus(intent.status));

  return (
    <section className="pending-entries-panel">
      <div className="pending-entries-head">
        <div>
          <span className="muted">{tKey("pendingEntry.queueEyebrow")}</span>
          <h3>{tKey("pendingEntry.selectedEntries")}</h3>
        </div>
        <span className="badge badge-blue">{tKey("pendingEntry.activeCount", { count: active.length })}</span>
      </div>
      {loading && !active.length ? (
        <div className="empty-state compact-empty">{tKey("pendingEntry.loading")}</div>
      ) : active.length ? (
        <div className="pending-entry-list">
          {active.map((intent) => (
            <PendingEntryQueueItem
              actionState={actionStates[intent.id] ?? null}
              actionStateLoading={Boolean(actionStatesLoading[intent.id])}
              busy={busy}
              intent={intent}
              key={intent.id}
              onCancelPendingEntry={onCancelPendingEntry}
              onReconfirmPendingEntry={onReconfirmPendingEntry}
              onSelectPendingEntrySignal={onSelectPendingEntrySignal}
              selected={selectedSignalId === intent.signal_id}
            />
          ))}
        </div>
      ) : (
        <div className="empty-state compact-empty">{tKey("pendingEntry.noActive")}</div>
      )}
      <details className="pending-entry-history-queue">
        <summary>
          <span>{tKey("pendingEntry.history")}</span>
          <span className="badge">{history.length}</span>
        </summary>
        {history.length ? (
          <div className="pending-entry-list history">
            {history.map((intent) => (
              <PendingEntryQueueItem
                actionState={actionStates[intent.id] ?? null}
                actionStateLoading={Boolean(actionStatesLoading[intent.id])}
                busy={busy}
                intent={intent}
                key={intent.id}
                onCancelPendingEntry={onCancelPendingEntry}
                onReconfirmPendingEntry={onReconfirmPendingEntry}
                onSelectPendingEntrySignal={onSelectPendingEntrySignal}
                selected={selectedSignalId === intent.signal_id}
              />
            ))}
          </div>
        ) : (
          <div className="empty-state compact-empty">{tKey("pendingEntry.noHistory")}</div>
        )}
      </details>
    </section>
  );
}

function PendingEntryQueueItem({
  actionState,
  actionStateLoading,
  busy,
  intent,
  onCancelPendingEntry,
  onReconfirmPendingEntry,
  onSelectPendingEntrySignal,
  selected
}: {
  actionState: SignalActionState | null;
  actionStateLoading: boolean;
  busy: boolean;
  intent: PendingEntryIntent;
  onCancelPendingEntry: (intent: PendingEntryIntent) => void;
  onReconfirmPendingEntry: (intent: PendingEntryIntent) => void;
  onSelectPendingEntrySignal: (intent: PendingEntryIntent) => void;
  selected: boolean;
}) {
  const { t, tKey, tReason } = useI18n();
  const reasonCode = intent.view?.reason_code ?? intent.reason_code ?? pendingEntryFallbackReasonCode(intent.status);
  const reason = intent.view?.reason
    ? tReason(intent.view.reason)
    : intent.failure_reason
      ? tReason(intent.failure_reason)
      : reasonCode
        ? tReason(reasonCode)
        : t(intent.status.replaceAll("_", " "));
  const currentPrice = intent.view?.current_price == null ? formatPrice(intent.current_price) : formatPrice(intent.view.current_price);

  return (
    <article className={selected ? "pending-entry-item selected" : "pending-entry-item"}>
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
        <button className="secondary-action compact-action" onClick={() => onSelectPendingEntrySignal(intent)} type="button">
          <FileCheck2 size={15} /> {tKey("pendingEntry.selectSignal")}
        </button>
        <button
          className="secondary-action compact-action"
          disabled={busy || actionStateLoading || !actionState?.can_reconfirm}
          onClick={() => onReconfirmPendingEntry(intent)}
          type="button"
        >
          <RefreshCw size={15} /> {tKey("pendingEntry.reconfirm")}
        </button>
        <button
          className="secondary-action compact-action"
          disabled={busy || actionStateLoading || !actionState?.can_cancel}
          onClick={() => onCancelPendingEntry(intent)}
          type="button"
        >
          <XCircle size={15} /> {tKey("pendingEntry.cancel")}
        </button>
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

function pendingEntryTone(status: PendingEntryIntent["status"]): "green" | "red" | "yellow" | "blue" | "purple" | "neutral" {
  if (status === "pending") return "blue";
  if (status === "requires_reconfirmation") return "yellow";
  if (status === "triggered" || status === "filling" || status === "filled") return "green";
  if (status === "failed" || status === "cancelled" || status === "expired") return "red";
  return "neutral";
}

function pendingEntryFallbackReasonCode(status: PendingEntryIntent["status"]): string | null {
  if (status === "expired") return "pending_entry_expired_before_touch";
  if (status === "cancelled") return "cancelled";
  if (status === "failed") return "execution_failed";
  if (status === "requires_reconfirmation") return "trade_plan_reconfirmation_required";
  return null;
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
