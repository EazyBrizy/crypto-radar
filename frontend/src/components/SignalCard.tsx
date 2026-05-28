import { memo, type CSSProperties } from "react";
import { Activity, ArrowDownRight, ArrowUpRight } from "lucide-react";

import { Badge } from "./Badge";
import { useSignalPrice } from "@/stores/price-store";
import { useSignalStore } from "@/stores/signal-store";
import type { RadarSignal } from "../types";
import { entryZone, formatPrice, riskLabel, signalAge } from "../utils";

interface SignalCardProps {
  signal: RadarSignal;
  selected: boolean;
  onSelect: (signal: RadarSignal) => void;
}

export const SignalCard = memo(function SignalCard({ signal, selected, onSelect }: SignalCardProps) {
  const isLong = signal.direction === "long";
  const price = useSignalPrice(signal.symbol);

  return (
    <button className={`signal-card ${selected ? "selected" : ""}`} onClick={() => onSelect(signal)} type="button">
      <div className="signal-card-head">
        <div>
          <div className="pair-row">
            <strong>{signal.symbol}</strong>
            <Badge>{signal.exchange}</Badge>
          </div>
          <span className="muted">{signal.strategy.replaceAll("_", " ")}</span>
        </div>
        <Badge tone={isLong ? "green" : "red"}>
          {isLong ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
          {signal.direction.toUpperCase()}
        </Badge>
      </div>

      <div className="signal-score-row">
        <div className="score-ring" style={{ "--score": `${signal.score}%` } as CSSProperties}>
          <span>{signal.score}</span>
        </div>
        <div>
          <strong>{Math.round(signal.confidence * 100)}% Confidence</strong>
          <span className="muted">Risk: {riskLabel(signal)} · {signalAge(signal)}</span>
        </div>
      </div>

      <div className="setup-grid">
        <span>Entry<strong>{entryZone(signal)}</strong></span>
        <span>TP<strong>{formatPrice(signal.take_profit_1)}</strong></span>
        <span>SL<strong>{formatPrice(signal.stop_loss)}</strong></span>
        <span>{price ? "Price" : "TF"}<strong>{price ? `${formatPrice(price.price)} · ${new Date(price.updatedAt).toLocaleTimeString()}` : signal.timeframe}</strong></span>
      </div>

      <div className="card-reason">
        <Activity size={15} />
        <span>{signal.explanation[0] ?? "Ожидается подтверждение контекста"}</span>
      </div>
    </button>
  );
});

SignalCard.displayName = "SignalCard";

export const SignalCardById = memo(function SignalCardById({
  signalId,
  selected,
  onSelect
}: {
  signalId: string;
  selected: boolean;
  onSelect: (signal: RadarSignal) => void;
}) {
  const signal = useSignalStore((state) => state.signalsById[signalId] ?? null);
  if (!signal) return null;
  return <SignalCard signal={signal} selected={selected} onSelect={onSelect} />;
});

SignalCardById.displayName = "SignalCardById";
