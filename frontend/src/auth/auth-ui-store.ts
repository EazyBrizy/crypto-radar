"use client";

import { create } from "zustand";

import type { MfaMethod } from "./types";

type AuthView = "sign-in" | "register" | "two-factor" | "password-reset";

interface AuthUiState {
  lastAttemptEmail: string | null;
  mfaChallengeId: string | null;
  mfaMethods: MfaMethod[];
  view: AuthView;
  setLastAttemptEmail: (email: string | null) => void;
  setMfaChallenge: (challengeId: string | null, methods?: MfaMethod[]) => void;
  setView: (view: AuthView) => void;
}

export const useAuthUiStore = create<AuthUiState>((set) => ({
  lastAttemptEmail: null,
  mfaChallengeId: null,
  mfaMethods: [],
  view: "sign-in",
  setLastAttemptEmail: (email) => set({ lastAttemptEmail: email }),
  setMfaChallenge: (challengeId, methods = []) => set({ mfaChallengeId: challengeId, mfaMethods: methods }),
  setView: (view) => set({ view })
}));
