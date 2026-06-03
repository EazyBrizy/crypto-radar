import { Plus, Save, SlidersHorizontal, Star, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/Badge";
import { canShowEnterButton } from "@/domain/signal-status";
import type { MarketPairOption, StrategyConfig, StrategyConfigPatch, StrategyPairScope } from "@/features/server-state/types";
import type { RadarSignal } from "@/types";

interface WatchlistPageProps {
  signals: RadarSignal[];
  strategyConfigs: StrategyConfig[];
  availablePairs: MarketPairOption[];
  loading: boolean;
  busy: boolean;
  onUpdateStrategyConfig: (configId: string, patch: StrategyConfigPatch) => Promise<unknown>;
}

export function WatchlistPage({
  signals,
  strategyConfigs,
  availablePairs,
  loading,
  busy,
  onUpdateStrategyConfig
}: WatchlistPageProps) {
  const enabledStrategies = useMemo(
    () => strategyConfigs.filter((strategyConfig) => strategyConfig.is_enabled),
    [strategyConfigs]
  );
  const [selectedStrategyId, setSelectedStrategyId] = useState("");
  const [selectedPairId, setSelectedPairId] = useState("");
  const selectedStrategy = useMemo(
    () =>
      enabledStrategies.find((strategyConfig) => strategyConfig.id === selectedStrategyId) ??
      enabledStrategies[0] ??
      null,
    [enabledStrategies, selectedStrategyId]
  );
  const selectedPairs = useMemo(() => selectedStrategy?.pairs ?? [], [selectedStrategy]);
  const selectedPairKeys = useMemo(
    () => new Set(selectedPairs.map(pairKey)),
    [selectedPairs]
  );
  const addablePairs = useMemo(
    () => availablePairs.filter((pair) => pair.status === "active" && !selectedPairKeys.has(pairKey(pair))),
    [availablePairs, selectedPairKeys]
  );
  const selectedSignals = useMemo(
    () => signals.filter((signal) => signal.strategy === selectedStrategy?.strategy_code),
    [selectedStrategy?.strategy_code, signals]
  );
  const configuredPairOptions = useMemo(
    () =>
      selectedPairs.map((pair) => ({
        scope: pair,
        option: availablePairs.find((candidate) => pairKey(candidate) === pairKey(pair))
      })),
    [availablePairs, selectedPairs]
  );

  async function handleAddPair() {
    if (!selectedStrategy) return;
    const pairId = selectedPairId || addablePairs[0]?.id;
    if (!pairId) return;
    const pair = availablePairs.find((candidate) => candidate.id === pairId);
    if (!pair) return;
    const nextPairs = dedupeStrategyPairs([
      ...selectedStrategy.pairs,
      { exchange: pair.exchange, symbol: pair.symbol }
    ]);
    await onUpdateStrategyConfig(selectedStrategy.id, { pairs: nextPairs });
    setSelectedPairId("");
  }

  async function handleRemovePair(pair: StrategyPairScope) {
    if (!selectedStrategy) return;
    await onUpdateStrategyConfig(selectedStrategy.id, {
      pairs: selectedStrategy.pairs.filter((item) => pairKey(item) !== pairKey(pair))
    });
  }

  async function handleUseAllPairs() {
    if (!selectedStrategy) return;
    await onUpdateStrategyConfig(selectedStrategy.id, { pairs: [] });
  }

  return (
    <section className="wide-panel">
      <div className="page-head">
        <div>
          <span className="muted">Watchlist</span>
          <h1>Strategy watchlist</h1>
        </div>
        {selectedStrategy ? (
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
          <button className="secondary-action" disabled={busy || loading || selectedPairs.length === 0} onClick={handleUseAllPairs} type="button">
            <Save size={16} />
            All pairs
          </button>
        </div>
        ) : null}
      </div>

      <div className="watchlist-strategy-grid">
        {loading ? <div className="empty-state compact-empty">Loading watchlist</div> : null}
        {!loading && enabledStrategies.length === 0 ? <div className="empty-state compact-empty">No enabled strategies</div> : null}
        {enabledStrategies.map((strategyConfig) => {
          const strategySignals = signals.filter((signal) => signal.strategy === strategyConfig.strategy_code);
          const actionableSignals = strategySignals.filter(canShowEnterButton);
          return (
            <button
              className={`watch-strategy-card ${selectedStrategy?.id === strategyConfig.id ? "selected" : ""}`}
              key={strategyConfig.id}
              onClick={() => setSelectedStrategyId(strategyConfig.id)}
              type="button"
            >
              <div className="pair-row">
                <SlidersHorizontal size={17} />
                <strong>{strategyConfig.strategy_name}</strong>
              </div>
              <div className="watch-meta">
                <span>Pairs</span>
                <Badge tone="blue">{strategyConfig.pairs.length ? strategyConfig.pairs.length : "all"}</Badge>
              </div>
              <div className="watch-meta">
                <span>Signals</span>
                <Badge tone={actionableSignals.length ? "green" : "yellow"}>{actionableSignals.length}/{strategySignals.length}</Badge>
              </div>
              <div className="watch-meta">
                <span>TF</span>
                <strong>{strategyConfig.timeframes.join(", ")}</strong>
              </div>
            </button>
          );
        })}
      </div>

      {selectedStrategy ? (
        <div className="watch-strategy-panel">
          <div className="watch-strategy-panel-head">
            <div>
              <span className="muted">Pairs</span>
              <h2>{selectedStrategy.strategy_name}</h2>
            </div>
            <div className="status-strip">
              <Badge tone="purple">{selectedStrategy.timeframes.join(", ")}</Badge>
              <Badge tone={selectedStrategy.risk_settings.show_only_active_setups ? "green" : "blue"}>
                {selectedStrategy.risk_settings.show_only_active_setups ? "Active only" : "All setups"}
              </Badge>
            </div>
          </div>

          <div className="watch-pair-grid">
            {selectedPairs.length === 0 ? (
              <div className="watch-pair-card all-pairs">
                <Star size={17} />
                <strong>All pairs</strong>
                <span>Quality filter on</span>
              </div>
            ) : null}
            {configuredPairOptions.map(({ option, scope }) => {
              const currentSignal = selectedSignals.find((signal) => signal.symbol === scope.symbol && signal.exchange === scope.exchange);
              return (
                <div className="watch-pair-card" key={pairKey(scope)}>
                  <div className="pair-row">
                    <Star size={17} />
                    <strong>{scope.symbol}</strong>
                    <button
                      className="icon-button compact"
                      disabled={busy}
                      onClick={() => handleRemovePair(scope)}
                      title="Remove"
                      type="button"
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                  <div className="watch-meta">
                    <span>{scope.exchange}</span>
                    {option ? <Badge tone="blue">{option.base_asset}/{option.quote_asset}</Badge> : <Badge>custom</Badge>}
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
                    <span>Status</span>
                    <strong>{currentSignal?.status?.replaceAll("_", " ") ?? "Waiting"}</strong>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function pairKey(pair: Pick<StrategyPairScope, "exchange" | "symbol">): string {
  return `${pair.exchange.toLowerCase()}:${pair.symbol.toUpperCase()}`;
}

function dedupeStrategyPairs(pairs: StrategyPairScope[]): StrategyPairScope[] {
  const seen = new Set<string>();
  return pairs.filter((pair) => {
    const key = pairKey(pair);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
