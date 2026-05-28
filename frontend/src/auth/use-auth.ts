"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { authApi } from "@/api/auth.api";
import { serverStateKeys } from "@/features/server-state/query-keys";
import { serverStatePolicy } from "@/features/server-state/query-policy";
import { useAuthUiStore } from "./auth-ui-store";
import type { LoginCredentials, TwoFactorChallenge } from "./types";

export function useAuthSessionQuery() {
  return useQuery({
    queryKey: serverStateKeys.auth.session(),
    queryFn: authApi.currentSession,
    staleTime: serverStatePolicy.defaultStaleTimeMs
  });
}

export function useLoginMutation() {
  const queryClient = useQueryClient();
  const setLastAttemptEmail = useAuthUiStore((state) => state.setLastAttemptEmail);
  const setMfaChallenge = useAuthUiStore((state) => state.setMfaChallenge);
  const setView = useAuthUiStore((state) => state.setView);

  return useMutation({
    mutationFn: (credentials: LoginCredentials) => authApi.login(credentials),
    onSuccess: async (result, variables) => {
      setLastAttemptEmail(variables.email);

      if (result.status === "authenticated") {
        queryClient.setQueryData(serverStateKeys.auth.session(), result.session);
        setMfaChallenge(null);
        setView("sign-in");
        return;
      }

      setMfaChallenge(result.challengeId, result.methods);
      setView("two-factor");
    }
  });
}

export function useLogoutMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: authApi.logout,
    onSuccess: async () => {
      queryClient.setQueryData(serverStateKeys.auth.session(), null);
      await queryClient.invalidateQueries({ queryKey: serverStateKeys.auth.all() });
    }
  });
}

export function useTwoFactorMutation() {
  const queryClient = useQueryClient();
  const setMfaChallenge = useAuthUiStore((state) => state.setMfaChallenge);
  const setView = useAuthUiStore((state) => state.setView);

  return useMutation({
    mutationFn: (challenge: TwoFactorChallenge) => authApi.verifyTwoFactor(challenge),
    onSuccess: (session) => {
      queryClient.setQueryData(serverStateKeys.auth.session(), session);
      setMfaChallenge(null);
      setView("sign-in");
    }
  });
}

export function useDeviceSessionsQuery(options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: serverStateKeys.auth.devices(),
    queryFn: authApi.listDeviceSessions,
    enabled: options.enabled ?? false,
    staleTime: serverStatePolicy.defaultStaleTimeMs
  });
}

export function useExchangeApiKeySecurityQuery(options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: serverStateKeys.auth.exchangeKeySecurity(),
    queryFn: authApi.exchangeApiKeySecurity,
    enabled: options.enabled ?? false,
    staleTime: serverStatePolicy.defaultStaleTimeMs
  });
}

export async function getWebSocketAuthToken(): Promise<string | null> {
  const token = await authApi.issueWebSocketToken();
  return token?.token ?? null;
}
