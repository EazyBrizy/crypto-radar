import { Filter, RadioTower, RefreshCw } from "lucide-react";

import { Metric } from "@/components/Metric";
import { SignalDetails } from "@/components/SignalDetails";
import { SignalFeed } from "@/components/SignalFeed";
import { canShowEnterButton } from "@/domain/signal-status";
import type { RadarDisplayMode } from "@/features/server-state/types";
import type { HealthStatus, PendingEntryIntent, RadarSignal, RadarStatus, SignalStatus, VirtualExecutionReport } from "@/types";
import { isRiskRewardBlocked } from "@/utils";

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
  onPaperTrade: (signal: RadarSignal) => void;
  onRefresh: () => void;
  onReject: (signal: RadarSignal) => void;
  onSelectSignal: (signal: RadarSignal) => void;
  radarStatus: RadarStatus | null;
  selectedSignal: RadarSignal | null;
  selectedSignalId: string | null;
  selectedPendingEntry?: PendingEntryIntent | null;
  signalIds: string[];
  signals: RadarSignal[];
  actionError?: string | null;
  executionPreview?: VirtualExecutionReport | null;
  executionPreviewError?: string | null;
  executionPreviewLoading?: boolean;
  pendingEntryLoading?: boolean;
  tradingActionsDisabled?: boolean;
}

export function RadarPage(props: RadarPageProps) {
  const executionReadySignals = props.signals.filter(canShowEnterButton).length;
  const highConfidence = props.signals.filter((signal) => signal.score >= 80).length;
  const positiveEdge = props.signals.filter((signal) => signal.edge?.status === "positive").length;
  const blockedIdeas = props.signals.filter((signal) => isRiskRewardBlocked(signal) || signal.no_trade_filter?.blocked || signal.risk_gate_status === "failed" || signal.can_enter === false).length;
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
          <Metric label="Execution Ready" value={String(executionReadySignals)} hint="RiskGate" />
          <Metric label="High Confidence" value={String(highConfidence)} hint="score 80+" />
          <Metric label="Positive Edge" value={String(positiveEdge)} hint="EV gate" />
          <Metric label="Blocked Ideas" value={String(blockedIdeas)} hint="RR/no-trade" />
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
            <span>Pairs: {props.radarStatus?.symbols.length ?? 0}</span>
            <span>Timeframes: {props.radarStatus?.timeframes.join(", ") ?? "1m, 5m, 15m, 1h, 4h, 1d"}</span>
          </div>
          <div className="history-grid">
            {latestSeries.length ? latestSeries.map(([series, candles]) => (
              <span key={series}>{series}: {candles} candles</span>
            )) : <span>Candle history is still warming up</span>}
          </div>
        </div>

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
          {(["all", "watchlist", "ready", "actionable", "wait_for_pullback", "invalidated", "expired"] as const).map((item) => (
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
        tradingActionsDisabled={props.tradingActionsDisabled}
      />
    </div>
  );
}
