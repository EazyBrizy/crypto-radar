import { Filter, RadioTower, RefreshCw } from "lucide-react";

import { Metric } from "../components/Metric";
import { SignalCard } from "../components/SignalCard";
import { SignalDetails } from "../components/SignalDetails";
import type { HealthStatus, RadarSignal } from "../types";

interface RadarPageProps {
  signals: RadarSignal[];
  selectedSignal: RadarSignal | null;
  health: HealthStatus | null;
  loading: boolean;
  busy: boolean;
  filter: "all" | "long" | "short";
  onFilterChange: (filter: "all" | "long" | "short") => void;
  onRefresh: () => void;
  onSelectSignal: (signal: RadarSignal) => void;
  onPaperTrade: (signal: RadarSignal) => void;
  onReject: (signal: RadarSignal) => void;
}

export function RadarPage(props: RadarPageProps) {
  const activeSignals = props.signals.filter((signal) => signal.status === "active").length;
  const highConfidence = props.signals.filter((signal) => signal.score >= 80).length;

  return (
    <div className="page-grid">
      <section className="feed-panel">
        <div className="page-head">
          <div>
            <span className="muted">Signal First Radar</span>
            <h1>Лучшие возможности рынка</h1>
          </div>
          <button className="icon-button" onClick={props.onRefresh} type="button" title="Обновить">
            <RefreshCw size={18} />
          </button>
        </div>

        <div className="metrics-grid">
          <Metric label="Market Status" value={props.health?.scanner_running ? "Live" : "Offline"} hint="scanner" />
          <Metric label="Active Signals" value={String(activeSignals)} hint="actionable" />
          <Metric label="High Confidence" value={String(highConfidence)} hint="score 80+" />
        </div>

        <div className="filter-row">
          <Filter size={16} />
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

        <div className="signal-feed">
          {props.loading ? <div className="empty-state">Загружаем сигналы...</div> : null}
          {!props.loading && !props.signals.length ? (
            <div className="empty-state">
              <RadioTower size={26} />
              <strong>Пока нет активных сигналов</strong>
              <span>Scanner может копить свечную историю или рынок не дал подходящий сетап.</span>
            </div>
          ) : null}
          {props.signals.map((signal) => (
            <SignalCard
              key={signal.id}
              signal={signal}
              selected={props.selectedSignal?.id === signal.id}
              onSelect={props.onSelectSignal}
            />
          ))}
        </div>
      </section>

      <SignalDetails
        signal={props.selectedSignal}
        onPaperTrade={props.onPaperTrade}
        onReject={props.onReject}
        busy={props.busy}
      />
    </div>
  );
}
