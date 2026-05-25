import type { ElementType } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, Bell, LayoutDashboard, RefreshCw, Settings, Star, WalletCards } from "lucide-react";

import { api } from "./api";
import { RadarPage } from "./pages/RadarPage";
import { SettingsPage } from "./pages/SettingsPage";
import { TradesPage } from "./pages/TradesPage";
import { WatchlistPage } from "./pages/WatchlistPage";
import type { HealthStatus, RadarConfig, RadarSignal, TradeJournalEntry } from "./types";

type Page = "radar" | "watchlist" | "trades" | "settings";

const navItems: Array<{ id: Page; label: string; icon: ElementType }> = [
  { id: "radar", label: "Radar", icon: LayoutDashboard },
  { id: "watchlist", label: "Watchlist", icon: Star },
  { id: "trades", label: "Trades", icon: WalletCards },
  { id: "settings", label: "Settings", icon: Settings }
];

export default function App() {
  const [page, setPage] = useState<Page>("radar");
  const [signals, setSignals] = useState<RadarSignal[]>([]);
  const [selectedSignalId, setSelectedSignalId] = useState<string | null>(null);
  const [trades, setTrades] = useState<TradeJournalEntry[]>([]);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [config, setConfig] = useState<RadarConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "long" | "short">("all");
  const [tradeTab, setTradeTab] = useState<"active" | "journal" | "analytics">("active");

  const loadData = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const [healthData, radarData, allSignals, tradeData, configData] = await Promise.all([
        api.health(),
        api.radar(),
        api.signals(),
        api.trades(),
        api.config()
      ]);
      const mergedSignals = radarData.signals.length ? radarData.signals : allSignals;
      setHealth(healthData);
      setSignals(mergedSignals);
      setTrades(tradeData.trades);
      setConfig(configData);
      setSelectedSignalId((current) => current ?? mergedSignals[0]?.id ?? null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Не удалось загрузить данные");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const visibleSignals = useMemo(() => {
    if (filter === "all") return signals;
    return signals.filter((signal) => signal.direction === filter);
  }, [filter, signals]);

  const selectedSignal = useMemo(
    () => signals.find((signal) => signal.id === selectedSignalId) ?? visibleSignals[0] ?? null,
    [selectedSignalId, signals, visibleSignals]
  );

  async function handlePaperTrade(signal: RadarSignal) {
    setBusy(true);
    setError(null);
    try {
      await api.confirmVirtual(signal.id);
      setPage("trades");
      setTradeTab("active");
      await loadData();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Не удалось открыть virtual trade");
    } finally {
      setBusy(false);
    }
  }

  async function handleReject(signal: RadarSignal) {
    setBusy(true);
    setError(null);
    try {
      await api.rejectSignal(signal.id);
      await loadData();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Не удалось отклонить сигнал");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><Activity size={22} /></div>
          <div><strong>Crypto Radar</strong><span>Signal Feed</span></div>
        </div>
        <nav className="nav-list">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button className={page === item.id ? "nav-item active" : "nav-item"} key={item.id} onClick={() => setPage(item.id)} type="button">
                <Icon size={18} /> {item.label}
              </button>
            );
          })}
        </nav>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div className="status-strip">
            <span>{config?.exchanges.join(", ") ?? "bybit"}</span>
            <span>{config?.symbols.slice(0, 3).join(", ") || "Top MVP pairs"}</span>
            <span>Risk: Balanced</span>
            <span className={health?.scanner_running ? "live-dot" : "offline-dot"}>{health?.scanner_running ? "WebSocket live" : "Scanner offline"}</span>
          </div>
          <div className="topbar-actions">
            <button className="icon-button" type="button" title="Уведомления"><Bell size={18} /></button>
            <button className="icon-button" onClick={loadData} type="button" title="Обновить"><RefreshCw size={18} /></button>
          </div>
        </header>

        {error ? <div className="error-banner">{error}</div> : null}

        {page === "radar" ? (
          <RadarPage
            signals={visibleSignals}
            selectedSignal={selectedSignal}
            health={health}
            loading={loading}
            busy={busy}
            filter={filter}
            onFilterChange={setFilter}
            onRefresh={loadData}
            onSelectSignal={(signal) => setSelectedSignalId(signal.id)}
            onPaperTrade={handlePaperTrade}
            onReject={handleReject}
          />
        ) : null}

        {page === "watchlist" ? <WatchlistPage signals={signals} /> : null}
        {page === "trades" ? <TradesPage trades={trades} activeTab={tradeTab} onTabChange={setTradeTab} /> : null}
        {page === "settings" ? <SettingsPage config={config} /> : null}
      </main>
    </div>
  );
}
