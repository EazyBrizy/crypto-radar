import { create } from "zustand";

import type { RadarSignal, SignalStatus } from "@/types";
import { isOpenFeedSignal } from "@/utils";

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
    set((state) => {
      if (!isOpenFeedSignal(signal)) return removeSignalFromState(state, signal.id);
      return {
        signalIds: [signal.id, ...state.signalIds.filter((id) => id !== signal.id)],
        signalsById: {
          ...state.signalsById,
          [signal.id]: signal
        }
      };
    }),
  clearSignals: () => set({ signalIds: [], signalsById: {} }),
  markInvalid: (signalId) =>
    set((state) => {
      if (!state.signalsById[signalId]) return state;
      return removeSignalFromState(state, signalId);
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
      const updated = { ...signal, ...patch, id: signal.id };
      if (!isOpenFeedSignal(updated)) return removeSignalFromState(state, signalId);
      return {
        signalsById: {
          ...state.signalsById,
          [signalId]: updated
        }
      };
    }),
  updateSignalStatus: (signalId, status) =>
    set((state) => {
      const signal = state.signalsById[signalId];
      if (!signal) return state;
      const updated = { ...signal, status, updated_at: new Date().toISOString() };
      if (!isOpenFeedSignal(updated)) return removeSignalFromState(state, signalId);
      return {
        signalsById: {
          ...state.signalsById,
          [signalId]: updated
        }
      };
    }),
  upsertSignal: (signal) =>
    set((state) => {
      if (!isOpenFeedSignal(signal)) return removeSignalFromState(state, signal.id);
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
        if (!isOpenFeedSignal(signal)) {
          delete signalsById[signal.id];
          signalIds = signalIds.filter((id) => id !== signal.id);
          continue;
        }
        if (!signalsById[signal.id]) signalIds = [signal.id, ...signalIds];
        signalsById[signal.id] = signal;
      }

      return { signalIds, signalsById };
    })
}));

export const getSignalById = (signalId: string | null) =>
  signalId ? useSignalStore.getState().signalsById[signalId] ?? null : null;

export function normalizeSignals(signals: RadarSignal[]) {
  const openSignals = signals.filter((signal) => isOpenFeedSignal(signal));
  return {
    signalIds: openSignals.map((signal) => signal.id),
    signalsById: openSignals.reduce<Record<string, RadarSignal>>((acc, signal) => {
      acc[signal.id] = signal;
      return acc;
    }, {})
  };
}

function removeSignalFromState(
  state: Pick<SignalState, "signalIds" | "signalsById">,
  signalId: string,
): Pick<SignalState, "signalIds" | "signalsById"> {
  if (!state.signalsById[signalId]) return state;
  const signalsById = { ...state.signalsById };
  delete signalsById[signalId];
  return {
    signalIds: state.signalIds.filter((id) => id !== signalId),
    signalsById
  };
}
