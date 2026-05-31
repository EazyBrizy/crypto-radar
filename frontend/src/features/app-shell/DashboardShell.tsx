"use client";

import type { ReactNode } from "react";
import type { ElementType } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, LayoutDashboard, PanelLeft, Play, RefreshCw, Settings, Square, Star, WalletCards } from "lucide-react";

import { API_ORIGIN_LABEL } from "@/api";
import { FastApiRealtimeGateway } from "@/features/realtime/FastApiRealtimeGateway";
import { NotificationCenter } from "./NotificationCenter";
import { NotificationRuntime } from "./NotificationRuntime";
import { RealtimeStatusBadge } from "./RealtimeStatusBadge";
import { LocaleSwitcher } from "@/i18n";
import {
  useHealthQuery,
  useRadarConfigQuery,
  useRadarStatusQuery,
  useStartScannerMutation,
  useStopScannerMutation
} from "@/hooks/use-radar-queries";
import { useUiStore } from "@/stores/ui-store";

const navItems: Array<{ href: string; label: string; icon: ElementType }> = [
  { href: "/dashboard/radar", label: "Radar", icon: LayoutDashboard },
  { href: "/dashboard/watchlist", label: "Watchlist", icon: Star },
  { href: "/dashboard/trades/active", label: "Trades", icon: WalletCards },
  { href: "/dashboard/settings", label: "Settings", icon: Settings }
];

export function DashboardShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "";
  const sidebarOpen = useUiStore((state) => state.sidebarOpen);
  const toggleSidebar = useUiStore((state) => state.toggleSidebar);

  const healthQuery = useHealthQuery();
  const radarStatusQuery = useRadarStatusQuery();
  const configQuery = useRadarConfigQuery();
  const startScannerMutation = useStartScannerMutation();
  const stopScannerMutation = useStopScannerMutation();

  const health = healthQuery.data ?? null;
  const radarStatus = radarStatusQuery.data ?? null;
  const config = configQuery.data ?? null;
  const scannerBusy = startScannerMutation.isPending || stopScannerMutation.isPending;
  const scannerStatusKnown = Boolean(health || radarStatus);
  const scannerRunning = health?.scanner_running ?? radarStatus?.scanner_running ?? false;
  const scannerStopping = health?.scanner_stopping ?? radarStatus?.scanner_stopping ?? false;
  const scannerStatusClass = scannerStatusKnown ? (scannerRunning ? "live-dot" : "offline-dot") : "syncing-dot";
  const scannerStatusText = scannerStatusKnown ? (scannerStopping ? "Scanner stopping" : scannerRunning ? "Scanner live" : "Scanner offline") : "Scanner status unknown";
  const scannerButtonMode = scannerStatusKnown ? (scannerRunning ? "stop" : "start") : "syncing";
  const ScannerButtonIcon = scannerStatusKnown ? (scannerRunning ? Square : Play) : RefreshCw;
  const scannerButtonText = scannerStatusKnown ? (scannerRunning ? "Stop scanner" : "Start scanner") : "Retry scanner status";
  const scannerActionDisabled = scannerBusy;
  const statusError = scannerStatusKnown ? null : healthQuery.error ?? radarStatusQuery.error;
  const blockingError = [configQuery, startScannerMutation, stopScannerMutation]
    .find((result) => result.error)?.error;
  const error = errorMessage(blockingError ?? statusError);

  async function refreshData() {
    await Promise.all([
      healthQuery.refetch(),
      radarStatusQuery.refetch(),
      configQuery.refetch()
    ]);
  }

  async function handleScannerToggle() {
    try {
      if (!scannerStatusKnown) {
        await refreshData();
        return;
      }
      const mutation = scannerRunning ? stopScannerMutation : startScannerMutation;
      await mutation.mutateAsync();
      await refreshData();
    } catch {
      // Mutation state renders the error banner.
    }
  }

  return (
    <div className={sidebarOpen ? "app-shell" : "app-shell sidebar-collapsed"}>
      <FastApiRealtimeGateway />
      <NotificationRuntime />
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><Activity size={22} /></div>
          <div><strong>Crypto Radar</strong><span>Signal Feed</span></div>
        </div>
        <nav className="nav-list">
          {navItems.map((item) => {
            const Icon = item.icon;
            const active = pathname === item.href || (item.href.includes("/trades/") && pathname.startsWith("/dashboard/trades"));
            return (
              <Link className={active ? "nav-item active" : "nav-item"} href={item.href} key={item.href}>
                <Icon size={18} /> {item.label}
              </Link>
            );
          })}
        </nav>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <button className="icon-button" onClick={toggleSidebar} type="button" title="Sidebar">
            <PanelLeft size={18} />
          </button>
          <div className="status-strip">
            <span>{config?.exchanges.join(", ") ?? "bybit"}</span>
            <span>{config?.symbols.slice(0, 3).join(", ") || "Top MVP pairs"}</span>
            <span>Risk: Balanced</span>
            <span className={scannerStatusClass}>{scannerStatusText}</span>
            <RealtimeStatusBadge />
            <span>{API_ORIGIN_LABEL}</span>
          </div>
          <div className="topbar-actions">
            <button
              className={`scanner-button ${scannerButtonMode}`}
              disabled={scannerActionDisabled}
              onClick={handleScannerToggle}
              type="button"
            >
              <ScannerButtonIcon size={15} />
              {scannerButtonText}
            </button>
            <LocaleSwitcher />
            <NotificationCenter />
            <button className="icon-button" onClick={() => void refreshData()} type="button" title="Refresh"><RefreshCw size={18} /></button>
          </div>
        </header>

        {error ? <div className="error-banner">{error}</div> : null}
        {children}
      </main>
    </div>
  );
}

function errorMessage(exc: unknown): string | null {
  if (!exc) return null;
  return exc instanceof Error ? exc.message : "Не удалось загрузить данные API";
}
