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
  executionPreviewError?: string | null;
  executionPreviewLoading?: boolean;
  tradingActionsDisabled?: boolean;
}

export function SignalDetails({
  signal,
  onPaperTrade,
  onReject,
  busy,
  executionPreview,
  executionPreviewError = null,
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
  const riskFailed = executionPreview?.risk_check?.status === "failed";
  const statusAllowsTrade = signal.status === "actionable" || signal.status === "active" || signal.status === "entry_touched";
  const actionsDisabled = busy || tradingActionsDisabled || riskFailed || !statusAllowsTrade;
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
        <strong>{recommendedAction(signal)}</strong>
        <p>{signal.status_reason ?? "Decision must use setup status, invalidation and risk context, not direction alone."}</p>
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
        error={executionPreviewError}
        loading={executionPreviewLoading}
      />

      <StrategyLayersBlock signal={signal} />

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
        <CheckRow done={statusAllowsTrade} text={`Strategy status: ${signal.status.replaceAll("_", " ")}`} />
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
      {riskFailed ? (
        <p className="form-description">Entry is blocked by backend risk gate.</p>
      ) : null}
      {!statusAllowsTrade ? (
        <p className="form-description">Entry actions are available only for actionable strategy signals.</p>
      ) : null}
    </section>
  );
}

function recommendedAction(signal: RadarSignal): string {
  if (signal.status === "watchlist") return "Watch setup formation, no entry yet";
  if (signal.status === "ready") return "Setup exists, wait for confirmation";
  if (signal.status === "wait_for_pullback") return "Wait for pullback or retest";
  if (signal.status === "invalidated") return "Idea is invalidated";
  if (signal.status === "actionable" || signal.status === "active" || signal.status === "entry_touched") {
    return `Entry candidate inside ${entryZone(signal)}`;
  }
  return `Monitor status ${signal.status.replaceAll("_", " ")}`;
}

function StrategyLayersBlock({ signal }: { signal: RadarSignal }) {
  const regimeChecks = signal.regime?.checks.filter((check) => check.status !== "passed").slice(0, 4) ?? [];
  const layers = [
    {
      label: "Market quality",
      value: signal.quality ? `${signal.quality.tier.replace("_", " ")} / ${signal.quality.score}` : "-"
    },
    {
      label: "Market regime",
      value: signal.regime ? `${signal.regime.direction} / ${signal.regime.alignment}` : "-"
    },
    {
      label: "Strategy setup",
      value: signal.setup ? signal.setup.stage : "-"
    },
    {
      label: "Confirmation",
      value: signal.confirmation ? (signal.confirmation.passed ? "passed" : "pending") : "-"
    },
    {
      label: "Invalidation",
      value: signal.invalidation?.price == null ? "-" : formatPrice(signal.invalidation.price)
    },
    {
      label: "Exit management",
      value: signal.exit_plan?.targets.length ? `${signal.exit_plan.targets.length} targets` : "-"
    }
  ];

  return (
    <div className="strategy-layers-block">
      <div className="section-title">
        <ShieldAlert size={18} />
        <h3>Strategy Layers</h3>
      </div>
      <div className="strategy-layer-grid">
        {layers.map((layer) => (
          <div className="strategy-layer-metric" key={layer.label}>
            <span>{layer.label}</span>
            <strong>{layer.value}</strong>
          </div>
        ))}
      </div>
      {signal.invalidation?.conditions.length ? (
        <div className="invalidation-list">
          {signal.invalidation.conditions.slice(0, 3).map((condition) => (
            <span key={condition}>{condition}</span>
          ))}
        </div>
      ) : null}
      {regimeChecks.length ? (
        <div className="layer-check-list">
          {regimeChecks.map((check) => (
            <span className={`layer-check-${check.status}`} key={`${check.name}:${check.reason ?? ""}`}>
              {formatLayerCheckName(check.name)}: {check.reason ?? check.status}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function formatLayerCheckName(value: string): string {
  return value.replaceAll("_", " ");
}

function ExecutionQualityBlock({
  signal,
  execution,
  error,
  loading
}: {
  signal: RadarSignal;
  execution: VirtualExecutionReport | null;
  error: string | null;
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
  const positionSizing = execution?.position_sizing ?? null;
  const stopLossPlan = execution?.stop_loss_plan ?? null;
  const takeProfitPlan = execution?.take_profit_plan ?? null;
  const breakevenPlan = execution?.breakeven_plan ?? null;
  const trailingStopPlan = execution?.trailing_stop_plan ?? null;
  const futuresRiskPlan = execution?.futures_risk_plan ?? null;
  const riskAdjustmentPlan = execution?.risk_adjustment_plan ?? null;
  const riskCheck = execution?.risk_check ?? null;
  const riskDecision = execution?.risk_decision ?? null;

  return (
    <div className="execution-quality-block">
      <div className="section-title">
        <ShieldAlert size={18} />
        <h3>Reality Check</h3>
        <Badge tone={tone}>{executionLabel}</Badge>
      </div>
      <div className="reality-check-summary">
        <span>Signal: {signal.score >= 70 ? "good" : "watchlist"}</span>
        <span>Chart: {signal.score >= 80 ? "strong" : "mixed"}</span>
        <span>Execution: {executionQualityText(gateStatus, impactRisk).toLowerCase()}</span>
      </div>
      <div className="execution-quality-grid">
        <MetricLine label="Expected slippage" value={execution ? formatCompactPercent(execution.entry_slippage_bps / 100) : error ? "Preview error" : "Preview pending"} />
        <MetricLine label="Market impact" value={impactRiskLabel(impactRisk)} />
        <MetricLine label="Safe size" value={safeSize == null ? "-" : `$${safeSize.toFixed(0)}`} />
        <MetricLine label="Risk budget" value={positionSizing ? `$${positionSizing.risk_amount.toFixed(2)}` : "-"} />
        <MetricLine label="Adjusted risk" value={riskAdjustmentPlan ? `${riskAdjustmentPlan.adjusted_risk_percent.toFixed(3)}%` : "-"} />
        <MetricLine label="Risk gate" value={riskDecision ? riskDecision.status : riskCheck ? riskCheck.status : "-"} />
        <MetricLine label="Risk size" value={positionSizing ? `$${positionSizing.notional.toFixed(0)}` : "-"} />
        <MetricLine label="Margin" value={positionSizing ? `$${positionSizing.required_margin.toFixed(0)} @ ${positionSizing.leverage}x` : "-"} />
        <MetricLine label="Effective risk" value={riskCheck ? `$${riskCheck.effective_risk_amount.toFixed(2)}` : "-"} />
        <MetricLine label="Daily risk" value={formatRiskUsage(riskCheck?.daily_risk_used_percent, riskCheck?.max_daily_loss_percent)} />
        <MetricLine label="Account drawdown" value={formatRiskUsage(riskCheck?.account_drawdown_percent, riskCheck?.max_account_drawdown_percent)} />
        <MetricLine label="Open risk" value={formatRiskUsage(riskCheck?.open_risk_used_percent, riskCheck?.max_open_risk_percent)} />
        <MetricLine label="Correlated risk" value={formatRiskUsage(riskCheck?.correlated_risk_used_percent, riskCheck?.max_correlated_risk_percent)} />
        <MetricLine label="Exchange rules" value={riskCheck ? riskCheck.exchange_rule_status : "-"} />
        <MetricLine label="Market data" value={riskCheck ? riskCheck.market_data_status : "-"} />
        <MetricLine label="Bid / Ask" value={riskCheck?.best_bid && riskCheck?.best_ask ? `${formatExecutionPrice(riskCheck.best_bid)} / ${formatExecutionPrice(riskCheck.best_ask)}` : "-"} />
        <MetricLine label="Mark price" value={riskCheck?.mark_price ? formatExecutionPrice(riskCheck.mark_price) : "-"} />
        <MetricLine label="Spread" value={riskCheck?.spread_bps == null ? "-" : `${riskCheck.spread_bps.toFixed(1)} bps`} />
        <MetricLine label="Price drift" value={riskCheck?.price_deviation_bps == null ? "-" : `${riskCheck.price_deviation_bps.toFixed(1)} bps`} />
        <MetricLine label="Book depth" value={riskCheck?.orderbook_depth_usd == null ? "-" : `$${riskCheck.orderbook_depth_usd.toFixed(0)}`} />
        <MetricLine label="Fee source" value={riskCheck?.fee_rate_source ?? "-"} />
        <MetricLine label="Taker fee" value={riskCheck?.taker_fee_rate == null ? "-" : `${(riskCheck.taker_fee_rate * 100).toFixed(3)}%`} />
        <MetricLine label="Funding buffer" value={riskCheck ? `$${riskCheck.funding_buffer_amount.toFixed(2)}` : "-"} />
        <MetricLine label="Close-only" value={riskCheck?.close_only ? "yes" : "no"} />
        <MetricLine label="Protection" value={riskCheck ? riskCheck.protection_state.replace("_", " ") : "-"} />
        <MetricLine label="Planned stop" value={stopLossPlan ? formatExecutionPrice(stopLossPlan.stop_loss_price) : formatPrice(signal.stop_loss)} />
        <MetricLine label="Exit plan" value={takeProfitPlan ? takeProfitPlan.targets.map((target) => `${target.label} ${target.r_multiple}R`).join(" / ") : "-"} />
        <MetricLine label="Breakeven" value={breakevenPlan ? `${formatExecutionPrice(breakevenPlan.trigger_price)} -> ${formatExecutionPrice(breakevenPlan.breakeven_stop_price)}` : "-"} />
        <MetricLine label="Trailing" value={trailingStopPlan?.enabled ? trailingStopPlan.mode.toUpperCase() : "Off"} />
        <MetricLine label="Futures guard" value={futuresRiskPlan ? futuresRiskPlan.status : "-"} />
        <MetricLine label="Order type" value={orderType} />
        <MetricLine label="Market order" value={marketOrder} />
        <MetricLine label="Fill" value={execution ? `${Math.round(execution.fill_ratio * 100)}%` : "-"} />
        <MetricLine label="Post-impact" value={simulatedPath ? formatExecutionPrice(simulatedPath.post_trade_price) : "-"} />
        <MetricLine label="Decay 60s" value={simulatedPath ? formatExecutionPrice(simulatedPath.simulated_candle.close) : "-"} />
        <MetricLine label="Model" value={execution ? execution.simulation_tier.toUpperCase() : "MVP"} />
      </div>
      {execution?.quality_gate.message ? (
        <p className="execution-quality-message">{execution.quality_gate.message}</p>
      ) : null}
      {riskCheck?.blockers.length ? (
        <ul className="risk-blocker-list">
          {riskCheck.blockers.map((blocker) => (
            <li key={blocker}>{blocker}</li>
          ))}
        </ul>
      ) : null}
      {error && !execution ? (
        <p className="execution-quality-message">Risk preview unavailable: {error}</p>
      ) : null}
      {execution ? (
        <div className="reality-check-copy">
          <p>{realityCheckReason(execution)}</p>
          <p>{realityCheckRecommendation(execution, orderType)}</p>
        </div>
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

function formatRiskUsage(used?: number | null, limit?: number | null): string {
  if (used == null || limit == null) return "-";
  return `${formatCompactPercent(used)} / ${limit <= 0 ? "Off" : formatCompactPercent(limit)}`;
}

function executionQualityText(status: ExecutionGateStatus, impactRisk: ImpactRisk): string {
  if (status === "blocked") return "Poor";
  if (status === "warning" || impactRisk !== "low") return "Risky";
  return "Good";
}

function realityCheckReason(execution: VirtualExecutionReport): string {
  const depthOne = execution.liquidity.orderbook_depth_1_percent_usd;
  const depthRatio = depthOne > 0 ? execution.requested_size_usd / depthOne * 100 : null;
  const slippagePercent = execution.entry_slippage_bps / 100;
  const exitSlippagePercent = execution.exit_slippage_bps / 100;

  if (execution.quality_gate.status === "blocked") {
    const depthText = depthRatio == null ? "current depth" : `${formatCompactPercent(depthRatio)} of liquidity inside 1%`;
    return `Your size would consume ${depthText}. Real entry could be worse by about ${formatCompactPercent(slippagePercent)}, and stop execution could add about ${formatCompactPercent(exitSlippagePercent)} friction.`;
  }
  if (execution.quality_gate.status === "warning" || execution.liquidity.impact_risk !== "low") {
    return `The setup is tradable, but execution is sensitive: expected entry slippage is ${formatCompactPercent(slippagePercent)} and impact risk is ${impactRiskLabel(execution.liquidity.impact_risk)}.`;
  }
  return `The requested size fits current liquidity with expected entry slippage around ${formatCompactPercent(slippagePercent)}.`;
}

function realityCheckRecommendation(execution: VirtualExecutionReport, orderType: string): string {
  const suggestedMax = execution.quality_gate.suggested_max_size_usd;
  if (execution.quality_gate.status === "blocked") {
    return suggestedMax == null
      ? `Recommendation: skip this trade or use a much smaller ${orderType.toLowerCase()} setup.`
      : `Recommendation: reduce position size to about $${suggestedMax.toFixed(0)}, use a limit order, or skip the trade.`;
  }
  if (execution.quality_gate.status === "warning" || execution.liquidity.impact_risk !== "low") {
    return `Recommendation: prefer ${orderType.toLowerCase()}, reduce size if the book thins out, and avoid chasing a market order.`;
  }
  return "Recommendation: execution looks realistic for this virtual size.";
}

function formatCompactPercent(value: number): string {
  if (!Number.isFinite(value)) return "0%";
  if (value > 0 && value < 0.01) return "<0.01%";
  if (value < 10) return `${value.toFixed(2)}%`;
  return `${value.toFixed(1)}%`;
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
