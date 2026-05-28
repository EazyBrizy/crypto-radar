import { create } from "zustand";

import type { RadarSignal, SignalStatus } from "@/types";

export type SignalPatch = Partial<RadarSignal>;

interface SignalState {
  signalIds: string[];
  signalsById: Record<string, RadarSignal>;
  addSignal: (signal: RadarSignal) => void;
  clearSignals: () => void;
  markInvalid: (signalId: string) => void;
  removeSignal: (signalId: string) => void;
  replaceSignals: (signals: RadarSignal[]) => void;
  updateSignal: (signalId: string, patch: SignalPatch) => void;
  updateSignalStatus: (signalId: string, status: SignalStatus) => void;
  upsertSignal: (signal: RadarSignal) => void;
  upsertSignals: (signals: RadarSignal[]) => void;
}

export const useSignalStore = create<SignalState>((set) => ({
  signalIds: [],
  signalsById: {},
  addSignal: (signal) =>
    set((state) => ({
      signalIds: [signal.id, ...state.signalIds.filter((id) => id !== signal.id)],
      signalsById: {
        ...state.signalsById,
        [signal.id]: signal
      }
    })),
  clearSignals: () => set({ signalIds: [], signalsById: {} }),
  markInvalid: (signalId) =>
    set((state) => {
      const signal = state.signalsById[signalId];
      if (!signal) return state;
      return {
        signalsById: {
          ...state.signalsById,
          [signalId]: { ...signal, status: "invalidated", updated_at: new Date().toISOString() }
        }
      };
    }),
  removeSignal: (signalId) =>
    set((state) => {
      if (!state.signalsById[signalId]) return state;
      const signalsById = { ...state.signalsById };
      delete signalsById[signalId];
      return {
        signalIds: state.signalIds.filter((id) => id !== signalId),
        signalsById
      };
    }),
  replaceSignals: (signals) => set(normalizeSignals(signals)),
  updateSignal: (signalId, patch) =>
    set((state) => {
      const signal = state.signalsById[signalId];
      if (!signal) return state;
      return {
        signalsById: {
          ...state.signalsById,
          [signalId]: { ...signal, ...patch, id: signal.id }
        }
      };
    }),
  updateSignalStatus: (signalId, status) =>
    set((state) => {
      const signal = state.signalsById[signalId];
      if (!signal) return state;
      return {
        signalsById: {
          ...state.signalsById,
          [signalId]: { ...signal, status, updated_at: new Date().toISOString() }
        }
      };
    }),
  upsertSignal: (signal) =>
    set((state) => {
      const exists = Boolean(state.signalsById[signal.id]);
      return {
        signalIds: exists ? state.signalIds : [signal.id, ...state.signalIds],
        signalsById: {
          ...state.signalsById,
          [signal.id]: signal
        }
      };
    }),
  upsertSignals: (signals) =>
    set((state) => {
      let signalIds = state.signalIds;
      const signalsById = { ...state.signalsById };

      for (const signal of signals) {
        if (!signalsById[signal.id]) signalIds = [signal.id, ...signalIds];
        signalsById[signal.id] = signal;
      }

      return { signalIds, signalsById };
    })
}));

export const getSignalById = (signalId: string | null) =>
  signalId ? useSignalStore.getState().signalsById[signalId] ?? null : null;

export function normalizeSignals(signals: RadarSignal[]) {
  return {
    signalIds: signals.map((signal) => signal.id),
    signalsById: signals.reduce<Record<string, RadarSignal>>((acc, signal) => {
      acc[signal.id] = signal;
      return acc;
    }, {})
  };
}
