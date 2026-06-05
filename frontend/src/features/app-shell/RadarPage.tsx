import { FileCheck2, Filter, RadioTower, RefreshCw, XCircle } from "lucide-react";

import { Metric } from "@/components/Metric";
import { SignalDetails, type RealTradeContext } from "@/components/SignalDetails";
import { SignalFeed } from "@/components/SignalFeed";
import { RADAR_STATUS_FILTERS } from "@/domain/signal-status";
import type { RadarDisplayMode } from "@/features/server-state/types";
import { isActivePendingEntryStatus, isTerminalPendingEntryStatus } from "@/domain/pending-entry-status";
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
  const summary = props.radarSummary;
  const scannerPairCount = props.radarStatus?.scanner_pairs_count ?? props.health?.scanner_pairs_count ?? props.radarStatus?.symbols.length ?? 0;
  const scannerUniverse = props.radarStatus?.scanner_universe_source ?? props.health?.scanner_universe_source ?? "default";
  const estimatedEvaluations = props.radarStatus?.estimated_strategy_checks ?? props.health?.estimated_strategy_checks ?? 0;
  const scannerWarning = props.radarStatus?.scanner_universe_warning ?? props.health?.scanner_universe_warning ?? null;
  const latestSeries = Object.entries(props.radarStatus?.candle_history ?? {})
    .sort(([, left], [, right]) => right - left)
    .slice(0, 6);

  return (
    <div className="page-grid">
      {props.actionError ? <div className="error-banner">{props.actionError}</div> : null}
      <section className="feed-panel">
        <div className="page-head">
          <div>
            <span className="muted">Signal First Radar</span>
            <h1>Market opportunities</h1>
          </div>
          <button className="icon-button" onClick={props.onRefresh} type="button" title="Refresh">
            <RefreshCw size={18} />
          </button>
        </div>

        <div className="metrics-grid">
          <Metric label="Market Status" value={props.health?.scanner_running ? "Online" : "Offline"} hint="scanner" />
          <Metric label="Execution Ready" value={String(summary?.execution_ready_signals ?? 0)} hint="RiskGate" />
          <Metric label="High Confidence" value={String(summary?.high_confidence_signals ?? 0)} hint="score 80+" />
          <Metric label="Positive Edge" value={String(summary?.positive_edge_signals ?? 0)} hint="EV gate" />
          <Metric label="Blocked Ideas" value={String(summary?.blocked_ideas ?? 0)} hint="backend" />
          <Metric label="Ticks" value={String(props.radarStatus?.ticks_processed ?? props.health?.ticks_processed ?? 0)} hint="market data" />
          <Metric label="Strategy Checks" value={String(props.radarStatus?.strategy_evaluations ?? props.health?.strategy_evaluations ?? 0)} hint="evaluated" />
          <Metric label="Features" value={String(props.radarStatus?.features_built ?? props.health?.features_built ?? 0)} hint="candles analyzed" />
        </div>

        <div className="scanner-panel">
          <div>
            <span className="muted">Scanner activity</span>
            <strong>
              {props.radarStatus?.last_symbol
                ? `${props.radarStatus.last_exchange ?? ""} ${props.radarStatus.last_symbol} ${props.radarStatus.last_price ?? ""}`
                : "Waiting for market data"}
            </strong>
          </div>
          <div className="scanner-stats">
            <span>Signals found: {props.radarStatus?.signals_found ?? props.health?.signals_found ?? 0}</span>
            <span>Seeded candles: {props.radarStatus?.candles_seeded ?? props.health?.candles_seeded ?? 0}</span>
            <span>Pairs: {scannerPairCount}</span>
            <span>Universe: {scannerUniverse}</span>
            <span>Estimated evaluations: {estimatedEvaluations}</span>
            <span>Timeframes: {props.radarStatus?.timeframes.join(", ") ?? "1m, 5m, 15m, 1h, 4h, 1d"}</span>
            {scannerWarning ? <span>Warning: {scannerWarning}</span> : null}
          </div>
          <div className="history-grid">
            {latestSeries.length ? latestSeries.map(([series, candles]) => (
              <span key={series}>{series}: {candles} candles</span>
            )) : <span>Candle history is still warming up</span>}
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
              {item === "open" ? "open ideas" : "history"}
            </button>
          ))}
        </div>
        <div className="filter-row">
          {([
            { label: "all market opportunities", value: "all_market_opportunities" },
            { label: "execution ready", value: "execution_ready" }
          ] as const).map((item) => (
            <button
              className={props.radarDisplayMode === item.value ? "filter-chip active" : "filter-chip"}
              key={item.value}
              onClick={() => props.onRadarDisplayModeChange(item.value)}
              type="button"
            >
              {item.label}
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
              {item}
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
              {item.replaceAll("_", " ")}
            </button>
          ))}
        </div>

        <SignalFeed
          emptyState={
            <div className="empty-state">
              <RadioTower size={26} />
              <strong>{props.signalView === "history" ? "No historical signals yet" : "No market opportunities yet"}</strong>
              <span>
                {props.signalView === "history"
                  ? "Invalidated and expired ideas will appear here after lifecycle transitions."
                  : "The scanner may still be building candle history, or the market has not produced a valid setup."}
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
  const active = activeEntries.filter((intent) => isActivePendingEntryStatus(intent.status));
  const history = historyEntries.filter((intent) => isTerminalPendingEntryStatus(intent.status));

  return (
    <section className="pending-entries-panel">
      <div className="pending-entries-head">
        <div>
          <span className="muted">Pending Entries Queue</span>
          <h3>Selected entries</h3>
        </div>
        <span className="badge badge-blue">{active.length} active</span>
      </div>
      {loading && !active.length ? (
        <div className="empty-state compact-empty">Loading pending entries</div>
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
        <div className="empty-state compact-empty">No active pending entries</div>
      )}
      <details className="pending-entry-history-queue">
        <summary>
          <span>History</span>
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
          <div className="empty-state compact-empty">No pending entry history</div>
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
  const reasonCode = intent.view?.reason_code ?? intent.reason_code ?? null;
  const reason = intent.view?.reason ?? intent.failure_reason ?? reasonCode?.replaceAll("_", " ") ?? "No reason from backend";
  const currentPrice = intent.view?.current_price == null ? formatPrice(intent.current_price) : formatPrice(intent.view.current_price);

  return (
    <article className={selected ? "pending-entry-item selected" : "pending-entry-item"}>
      <div className="pending-entry-main">
        <div>
          <strong>{intent.symbol}</strong>
          <span>{intent.exchange} / {intent.side.toUpperCase()}</span>
        </div>
        <div className="pending-entry-badges">
          <span className={`badge badge-${pendingEntryTone(intent.status)}`}>{intent.status.replaceAll("_", " ")}</span>
          <span className="badge badge-purple">{intent.mode}</span>
        </div>
      </div>
      <div className="pending-entry-metrics">
        <MetricLine label="Entry zone" value={intent.view?.entry_zone ?? `${formatPrice(intent.entry_min)} - ${formatPrice(intent.entry_max)}`} />
        <MetricLine label="Current price" value={currentPrice} />
        <MetricLine label="Expires" value={formatPendingEntryTtl(intent.expires_at)} />
        <MetricLine label="Reason code" value={reasonCode ?? "-"} />
      </div>
      <p className="pending-entry-reason">{reason}</p>
      <div className="pending-entry-actions">
        <button className="secondary-action compact-action" onClick={() => onSelectPendingEntrySignal(intent)} type="button">
          <FileCheck2 size={15} /> Select signal
        </button>
        <button
          className="secondary-action compact-action"
          disabled={busy || actionStateLoading || !actionState?.can_reconfirm}
          onClick={() => onReconfirmPendingEntry(intent)}
          type="button"
        >
          <RefreshCw size={15} /> Reconfirm
        </button>
        <button
          className="secondary-action compact-action"
          disabled={busy || actionStateLoading || !actionState?.can_cancel}
          onClick={() => onCancelPendingEntry(intent)}
          type="button"
        >
          <XCircle size={15} /> Cancel
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

function formatPendingEntryTtl(value: string | null): string {
  if (!value) return "no expiry";
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return "unknown";
  const diffMs = timestamp - Date.now();
  if (diffMs <= 0) return "expired";
  const diffMinutes = Math.ceil(diffMs / 60_000);
  if (diffMinutes < 60) return `${diffMinutes}m left`;
  return `${Math.ceil(diffMinutes / 60)}h left`;
}
