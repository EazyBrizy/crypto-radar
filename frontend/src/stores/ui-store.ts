import { create } from "zustand";

import type { RealtimeConnectionStatus } from "@/realtime/event-types";

export type Page = "radar" | "watchlist" | "trades" | "settings";
export type SignalFilter = "all" | "long" | "short";
export type TradeTab = "active" | "journal" | "analytics";
export type AppLayout = "default" | "compact" | "focus";
export type AppModal = "notifications" | "signal-confirm" | "trade-close" | null;

interface UiState {
  activeModal: AppModal;
  connectionStatus: RealtimeConnectionStatus;
  layout: AppLayout;
  lastEventAt: number | null;
  lastHeartbeatAt: number | null;
  page: Page;
  selectedSignalId: string | null;
  selectedTradeId: string | null;
  sidebarOpen: boolean;
  signalFilter: SignalFilter;
  tradeTab: TradeTab;
  closeModal: () => void;
  markRealtimeEvent: () => void;
  markRealtimeHeartbeat: () => void;
  openModal: (modal: Exclude<AppModal, null>) => void;
  setConnectionStatus: (status: RealtimeConnectionStatus) => void;
  setLayout: (layout: AppLayout) => void;
  setPage: (page: Page) => void;
  setSelectedSignalId: (signalId: string | null) => void;
  setSelectedTradeId: (tradeId: string | null) => void;
  setSidebarOpen: (open: boolean) => void;
  setSignalFilter: (filter: SignalFilter) => void;
  setTradeTab: (tab: TradeTab) => void;
  toggleSidebar: () => void;
}

export const useUiStore = create<UiState>((set) => ({
  activeModal: null,
  connectionStatus: "idle",
  layout: "default",
  lastEventAt: null,
  lastHeartbeatAt: null,
  page: "radar",
  selectedSignalId: null,
  selectedTradeId: null,
  sidebarOpen: true,
  signalFilter: "all",
  tradeTab: "active",
  closeModal: () => set({ activeModal: null }),
  markRealtimeEvent: () => set({ lastEventAt: Date.now() }),
  markRealtimeHeartbeat: () => set({ lastHeartbeatAt: Date.now() }),
  openModal: (activeModal) => set({ activeModal }),
  setConnectionStatus: (connectionStatus) => set({ connectionStatus }),
  setLayout: (layout) => set({ layout }),
  setPage: (page) => set({ page }),
  setSelectedSignalId: (selectedSignalId) => set({ selectedSignalId }),
  setSelectedTradeId: (selectedTradeId) => set({ selectedTradeId }),
  setSidebarOpen: (sidebarOpen) => set({ sidebarOpen }),
  setSignalFilter: (signalFilter) => set({ signalFilter }),
  setTradeTab: (tradeTab) => set({ tradeTab }),
  toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen }))
}));
