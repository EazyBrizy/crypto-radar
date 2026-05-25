import { CheckCircle2, Circle, ExternalLink, FileCheck2, ShieldAlert, XCircle } from "lucide-react";

import { Badge } from "./Badge";
import type { RadarSignal } from "../types";
import { entryZone, formatPrice, riskLabel } from "../utils";

interface SignalDetailsProps {
  signal: RadarSignal | null;
  onPaperTrade: (signal: RadarSignal) => void;
  onReject: (signal: RadarSignal) => void;
  busy: boolean;
}

export function SignalDetails({ signal, onPaperTrade, onReject, busy }: SignalDetailsProps) {
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

      <div className="confidence-breakdown">
        <div className="section-title">
          <ShieldAlert size={18} />
          <h3>Confidence Score</h3>
        </div>
        <ScoreLine label="Trend" value={Math.min(signal.score, 25)} max={25} />
        <ScoreLine label="Volume" value={Math.min(Math.max(signal.score - 25, 12), 20)} max={20} />
        <ScoreLine label="Risk/Reward" value={signal.risk_reward ? Math.min(signal.risk_reward * 7, 20) : 8} max={20} />
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
        <button className="primary-action" onClick={() => onPaperTrade(signal)} disabled={busy} type="button">
          <FileCheck2 size={17} /> Paper Trade
        </button>
        <button className="secondary-action" type="button" disabled>
          <ExternalLink size={17} /> Open Exchange
        </button>
        <button className="danger-action" onClick={() => onReject(signal)} disabled={busy} type="button">
          <XCircle size={17} /> Ignore Signal
        </button>
      </div>
    </section>
  );
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

function CheckRow({ done = false, text }: { done?: boolean; text: string }) {
  return (
    <div className="check-row">
      {done ? <CheckCircle2 size={16} /> : <Circle size={16} />}
      <span>{text}</span>
    </div>
  );
}
