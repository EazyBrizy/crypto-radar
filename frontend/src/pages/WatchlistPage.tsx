import { Star } from "lucide-react";

import { Badge } from "../components/Badge";
import type { RadarSignal } from "../types";

interface WatchlistPageProps {
  signals: RadarSignal[];
}

const defaultPairs = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "1000PEPEUSDT"];

export function WatchlistPage({ signals }: WatchlistPageProps) {
  return (
    <section className="wide-panel">
      <div className="page-head">
        <div>
          <span className="muted">Watchlist</span>
          <h1>Избранные пары</h1>
        </div>
      </div>

      <div className="watchlist-grid">
        {defaultPairs.map((pair) => {
          const currentSignal = signals.find((signal) => signal.symbol === pair);
          return (
            <div className="watch-card" key={pair}>
              <div className="pair-row">
                <Star size={17} />
                <strong>{pair}</strong>
              </div>
              <div className="watch-meta">
                <span>Current Signal</span>
                {currentSignal ? (
                  <Badge tone={currentSignal.direction === "long" ? "green" : "red"}>
                    {currentSignal.direction} · {currentSignal.score}
                  </Badge>
                ) : (
                  <Badge>none</Badge>
                )}
              </div>
              <div className="watch-meta">
                <span>Trend Status</span>
                <strong>{currentSignal?.score && currentSignal.score > 70 ? "Opportunity" : "Waiting"}</strong>
              </div>
              <div className="mini-chart" />
            </div>
          );
        })}
      </div>
    </section>
  );
}
