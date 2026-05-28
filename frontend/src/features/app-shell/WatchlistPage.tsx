import { Plus, Star, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/Badge";
import type { MarketPairOption, Watchlist } from "@/features/server-state/types";
import type { RadarSignal } from "@/types";

interface WatchlistPageProps {
  signals: RadarSignal[];
  watchlist: Watchlist | null;
  availablePairs: MarketPairOption[];
  loading: boolean;
  busy: boolean;
  onAddPair: (pairId: string) => Promise<unknown>;
  onRemovePair: (pairId: string) => Promise<unknown>;
}

export function WatchlistPage({
  signals,
  watchlist,
  availablePairs,
  loading,
  busy,
  onAddPair,
  onRemovePair
}: WatchlistPageProps) {
  const [selectedPairId, setSelectedPairId] = useState("");
  const selectedPairIds = useMemo(() => new Set(watchlist?.pairs.map((pair) => pair.id) ?? []), [watchlist?.pairs]);
  const addablePairs = useMemo(
    () => availablePairs.filter((pair) => !selectedPairIds.has(pair.id)),
    [availablePairs, selectedPairIds]
  );
  const pairs = watchlist?.pairs ?? [];

  async function handleAddPair() {
    const pairId = selectedPairId || addablePairs[0]?.id;
    if (!pairId) return;
    await onAddPair(pairId);
    setSelectedPairId("");
  }

  return (
    <section className="wide-panel">
      <div className="page-head">
        <div>
          <span className="muted">Watchlist</span>
          <h1>{watchlist?.name ?? "Default"} pairs</h1>
        </div>
        <div className="inline-form">
          <select
            aria-label="Pair"
            disabled={busy || loading || addablePairs.length === 0}
            onChange={(event) => setSelectedPairId(event.target.value)}
            value={selectedPairId}
          >
            <option value="">{addablePairs.length ? "Select pair" : "All seeded pairs added"}</option>
            {addablePairs.map((pair) => (
              <option key={pair.id} value={pair.id}>
                {pair.exchange}:{pair.symbol}
              </option>
            ))}
          </select>
          <button className="primary-action" disabled={busy || loading || addablePairs.length === 0} onClick={handleAddPair} type="button">
            <Plus size={16} />
            Add
          </button>
        </div>
      </div>

      <div className="watchlist-grid">
        {loading ? <div className="empty-state">Loading watchlist</div> : null}
        {!loading && pairs.length === 0 ? <div className="empty-state">No pairs in watchlist</div> : null}
        {pairs.map((pair) => {
          const currentSignal = signals.find((signal) => signal.symbol === pair.symbol);
          return (
            <div className="watch-card" key={pair.id}>
              <div className="pair-row">
                <Star size={17} />
                <strong>{pair.symbol}</strong>
                <button
                  className="icon-button compact"
                  disabled={busy}
                  onClick={() => onRemovePair(pair.id)}
                  title="Remove"
                  type="button"
                >
                  <Trash2 size={15} />
                </button>
              </div>
              <div className="watch-meta">
                <span>{pair.exchange}</span>
                <Badge tone="blue">{pair.base_asset}/{pair.quote_asset}</Badge>
              </div>
              <div className="watch-meta">
                <span>Signal</span>
                {currentSignal ? (
                  <Badge tone={currentSignal.direction === "long" ? "green" : "red"}>
                    {currentSignal.direction} - {currentSignal.score}
                  </Badge>
                ) : (
                  <Badge>none</Badge>
                )}
              </div>
              <div className="watch-meta">
                <span>Trend</span>
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
