"use client";

import dynamic from "next/dynamic";
import { useState } from "react";
import { BarChart3, CheckCircle2, Circle, ExternalLink, FileCheck2, ShieldAlert, XCircle } from "lucide-react";

import { Badge } from "./Badge";
import type { ExecutionGateStatus, ImpactRisk, RadarSignal, VirtualExecutionReport } from "../types";
import { entryZone, formatPrice, riskLabel } from "../utils";

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
  onReject: (signal: RadarSignal) => void;
  busy: boolean;
  executionPreview: VirtualExecutionReport | null;
  executionPreviewLoading?: boolean;
  tradingActionsDisabled?: boolean;
}

export function SignalDetails({
  signal,
  onPaperTrade,
  onReject,
  busy,
  executionPreview,
  executionPreviewLoading = false,
  tradingActionsDisabled = false
}: SignalDetailsProps) {
  const [chartOpen, setChartOpen] = useState(false);

  if (!signal) {
    return (
      <section className="details-empty">
        <FileCheck2 size={32} />
        <h2>Выбери сигнал</h2>
        <p>Здесь появится торговый план, причины, риск и действия для Manual Confirm.</p>
      </section>
    );
  }

  const isLong = signal.direction === "long";
  const actionsDisabled = busy || tradingActionsDisabled;
  const breakdown = signal.score_breakdown;
  const reasons = signal.explanation.length ? signal.explanation : ["Стратегия сформировала сигнал по текущему market context."];

  return (
    <section className="details-panel">
      <div className="details-header">
        <div>
          <span className="muted">Signal Details</span>
          <h2>{signal.symbol} {signal.direction.toUpperCase()} Signal</h2>
        </div>
        <div className="details-badges">
          <Badge tone={isLong ? "green" : "red"}>{signal.direction.toUpperCase()}</Badge>
          <Badge tone="yellow">Risk {riskLabel(signal)}</Badge>
          <Badge tone="blue">{signal.status}</Badge>
        </div>
      </div>

      <div className="decision-block">
        <span>Recommended action</span>
        <strong>Ждать вход внутри зоны {entryZone(signal)}</strong>
        <p>Решение должно опираться на entry, invalidation и риск, а не только на направление.</p>
      </div>

      <div className="trade-setup">
        <div><span>Entry Zone</span><strong>{entryZone(signal)}</strong></div>
        <div><span>Stop Loss</span><strong>{formatPrice(signal.stop_loss)}</strong></div>
        <div><span>Take Profit</span><strong>{formatPrice(signal.take_profit_1)} / {formatPrice(signal.take_profit_2)}</strong></div>
        <div><span>Risk / Reward</span><strong>1 : {signal.risk_reward?.toFixed(2) ?? "-"}</strong></div>
      </div>

      <ExecutionQualityBlock
        signal={signal}
        execution={executionPreview}
        loading={executionPreviewLoading}
      />

      <div className="detail-actions">
        <button className="secondary-action" onClick={() => setChartOpen((open) => !open)} type="button">
          <BarChart3 size={17} /> {chartOpen ? "Hide Chart" : "Show Chart"}
        </button>
      </div>

      {chartOpen ? <LazySignalDetailsChart signal={signal} /> : null}

      <div className="confidence-breakdown">
        <div className="section-title">
          <ShieldAlert size={18} />
          <h3>Confidence Score</h3>
        </div>
        <ScoreLine label="Trend" value={breakdown.trend_score} max={100} />
        <ScoreLine label="Volume" value={breakdown.volume_score} max={100} />
        <ScoreLine label="Liquidity" value={breakdown.liquidity_score} max={100} />
        <ScoreLine label="Orderbook" value={breakdown.orderbook_score} max={100} />
        <ScoreLine label="Risk/Reward" value={breakdown.risk_reward_score} max={100} />
        <ScoreLine label="Volatility" value={breakdown.volatility_score} max={100} />
        <ScoreLine label="Overheat Penalty" value={breakdown.overheat_penalty} max={100} />
        <ScoreLine label="News/Event Risk" value={breakdown.news_event_risk_penalty} max={100} />
      </div>

      <div className="explanation-block">
        <h3>Why this signal?</h3>
        <ul>
          {reasons.map((reason) => (
            <li key={reason}><CheckCircle2 size={16} /><span>{reason}</span></li>
          ))}
        </ul>
      </div>

      <div className="checklist-block">
        <h3>Confirmation Checklist</h3>
        <CheckRow done text="Сетап соответствует стратегии" />
        <CheckRow done text="Entry, SL и TP рассчитаны" />
        <CheckRow done text="Risk/Reward указан" />
        <CheckRow text={signal.score >= 70 ? "Сигнал actionable" : "Сигнал в watchlist"} />
      </div>

      {signal.risks.length ? (
        <div className="risk-block">
          <h3>Risks</h3>
          {signal.risks.map((risk) => <p key={risk}>{risk}</p>)}
        </div>
      ) : null}

      <div className="detail-actions">
        <button className="primary-action" onClick={() => onPaperTrade(signal)} disabled={actionsDisabled} type="button">
          <FileCheck2 size={17} /> Paper Trade
        </button>
        <button className="secondary-action" type="button" disabled>
          <ExternalLink size={17} /> Open Exchange
        </button>
        <button className="danger-action" onClick={() => onReject(signal)} disabled={actionsDisabled} type="button">
          <XCircle size={17} /> Ignore Signal
        </button>
      </div>
      {tradingActionsDisabled ? (
        <p className="form-description">Trading actions disabled until realtime data is current.</p>
      ) : null}
    </section>
  );
}

function ExecutionQualityBlock({
  signal,
  execution,
  loading
}: {
  signal: RadarSignal;
  execution: VirtualExecutionReport | null;
  loading: boolean;
}) {
  const gateStatus = execution?.quality_gate.status ?? scoreGateStatus(signal);
  const impactRisk = execution?.liquidity.impact_risk ?? scoreImpactRisk(signal);
  const tone = gateTone(gateStatus, impactRisk);
  const executionLabel = loading && !execution ? "Checking" : executionQualityLabel(gateStatus, impactRisk);
  const marketOrder = gateStatus === "blocked" || impactRisk === "high"
    ? "Not recommended"
    : gateStatus === "warning"
      ? "Use smaller size"
      : "Allowed";
  const orderType = gateStatus === "blocked" || impactRisk === "high" ? "Limit" : "Market / Limit";
  const safeSize = execution?.quality_gate.suggested_max_size_usd
    ?? (execution && execution.quality_gate.status !== "blocked" ? execution.filled_size_usd : null);
  const simulatedPath = execution?.simulated_path ?? null;

  return (
    <div className="execution-quality-block">
      <div className="section-title">
        <ShieldAlert size={18} />
        <h3>Execution Quality</h3>
        <Badge tone={tone}>{executionLabel}</Badge>
      </div>
      <div className="execution-quality-grid">
        <MetricLine label="Expected slippage" value={execution ? `${(execution.entry_slippage_bps / 100).toFixed(2)}%` : "Preview pending"} />
        <MetricLine label="Market impact" value={impactRiskLabel(impactRisk)} />
        <MetricLine label="Safe size" value={safeSize == null ? "-" : `$${safeSize.toFixed(0)}`} />
        <MetricLine label="Order type" value={orderType} />
        <MetricLine label="Market order" value={marketOrder} />
        <MetricLine label="Fill" value={execution ? `${Math.round(execution.fill_ratio * 100)}%` : "-"} />
        <MetricLine label="Post-impact" value={simulatedPath ? formatExecutionPrice(simulatedPath.post_trade_price) : "-"} />
        <MetricLine label="Decay 60s" value={simulatedPath ? formatExecutionPrice(simulatedPath.simulated_candle.close) : "-"} />
      </div>
      {execution?.quality_gate.message ? (
        <p className="execution-quality-message">{execution.quality_gate.message}</p>
      ) : null}
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

function formatExecutionPrice(price: number): string {
  if (Math.abs(price) >= 1000) return price.toFixed(0);
  if (Math.abs(price) >= 1) return price.toFixed(2);
  return price.toPrecision(4);
}

function ScoreLine({ label, value, max }: { label: string; value: number; max: number }) {
  return (
    <div className="score-line">
      <span>{label}</span>
      <progress value={value} max={max} />
      <strong>{Math.round(value)}/{max}</strong>
    </div>
  );
}

function scoreGateStatus(signal: RadarSignal): ExecutionGateStatus {
  const liquidity = signal.score_breakdown.liquidity_score;
  const orderbook = signal.score_breakdown.orderbook_score;
  if (liquidity < 25 || orderbook < 20) return "blocked";
  if (liquidity < 45 || orderbook < 40) return "warning";
  return "passed";
}

function scoreImpactRisk(signal: RadarSignal): ImpactRisk {
  const liquidity = signal.score_breakdown.liquidity_score;
  const orderbook = signal.score_breakdown.orderbook_score;
  if (liquidity < 35 || orderbook < 30) return "high";
  if (liquidity < 60 || orderbook < 50) return "medium";
  return "low";
}

function executionQualityLabel(status: ExecutionGateStatus, impactRisk: ImpactRisk): string {
  if (status === "blocked") return "Low";
  if (status === "warning" || impactRisk !== "low") return "Medium";
  return "High";
}

function impactRiskLabel(risk: ImpactRisk): string {
  if (risk === "high") return "High";
  if (risk === "medium") return "Medium";
  return "Low";
}

function gateTone(status: ExecutionGateStatus, risk: ImpactRisk): "green" | "red" | "yellow" {
  if (status === "blocked" || risk === "high") return "red";
  if (status === "warning" || risk === "medium") return "yellow";
  return "green";
}

function CheckRow({ done = false, text }: { done?: boolean; text: string }) {
  return (
    <div className="check-row">
      {done ? <CheckCircle2 size={16} /> : <Circle size={16} />}
      <span>{text}</span>
    </div>
  );
}
