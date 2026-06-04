import type { AuthProviderKind } from "./types";

export const authConfig = {
  provider: "custom-fastapi-jwt" satisfies AuthProviderKind,
  mvpBypassAuth: process.env.NEXT_PUBLIC_AUTH_MVP_BYPASS !== "false",
  endpoints: {
    currentSession: "/api/auth/session",
    login: "/api/auth/login",
    logout: "/api/auth/logout",
    refresh: "/api/auth/refresh",
    webSocketToken: "/api/auth/ws-token",
    verifyTwoFactor: "/api/auth/2fa/verify",
    deviceSessions: "/api/auth/sessions",
    revokeDeviceSession: (deviceId: string) => `/api/auth/sessions/${deviceId}`,
    exchangeKeySecurity: "/api/auth/exchange-key-security"
  }
} as const;

export const demoAuthSession = {
  accessTokenExpiresAt: "2026-05-26T23:59:59.000Z",
  authLevel: "mfa",
  mfaRequired: false,
  refreshCookieMode: "http-only",
  user: {
    email: "demo@crypto-radar.local",
    id: "demo_user",
    name: "Demo Trader",
    roles: ["owner"]
  }
} as const;
