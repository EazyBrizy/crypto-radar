import { API_BASE, API_TIMEOUT_MS } from "./client";
import {
  AuthSessionSchema,
  DeviceSessionSchema,
  LoginFormSchema,
  LoginResultSchema,
  TwoFactorFormSchema,
  WebSocketAuthTokenSchema
} from "@/auth/auth-schemas";
import { authConfig, demoAuthSession } from "@/auth/auth-config";
import type {
  AuthSession,
  DeviceSession,
  ExchangeApiKeySecurityStatus,
  LoginCredentials,
  LoginResult,
  TwoFactorChallenge,
  WebSocketAuthToken
} from "@/auth/types";

const jsonHeaders = {
  "Content-Type": "application/json"
};

export const authApi = {
  currentSession,
  login,
  logout,
  refreshSession,
  issueWebSocketToken,
  verifyTwoFactor,
  listDeviceSessions,
  revokeDeviceSession,
  exchangeApiKeySecurity
};

async function currentSession(): Promise<AuthSession | null> {
  if (authConfig.mvpBypassAuth) return AuthSessionSchema.parse(demoAuthSession);

  const response = await authFetch(authConfig.endpoints.currentSession);
  if (response.status === 401) return null;
  return AuthSessionSchema.parse(await readJson(response));
}

async function login(credentials: LoginCredentials): Promise<LoginResult> {
  const payload = LoginFormSchema.parse(credentials);
  if (authConfig.mvpBypassAuth) {
    return { session: AuthSessionSchema.parse(demoAuthSession), status: "authenticated" };
  }

  const response = await authFetch(authConfig.endpoints.login, {
    body: JSON.stringify(payload),
    method: "POST"
  });
  return LoginResultSchema.parse(await readJson(response));
}

async function logout(): Promise<void> {
  if (authConfig.mvpBypassAuth) return;

  await authFetch(authConfig.endpoints.logout, { method: "POST" });
}

async function refreshSession(): Promise<AuthSession | null> {
  if (authConfig.mvpBypassAuth) return AuthSessionSchema.parse(demoAuthSession);

  const response = await authFetch(authConfig.endpoints.refresh, { method: "POST" });
  if (response.status === 401) return null;
  return AuthSessionSchema.parse(await readJson(response));
}

async function issueWebSocketToken(): Promise<WebSocketAuthToken | null> {
  if (authConfig.mvpBypassAuth) {
    return WebSocketAuthTokenSchema.parse({
      expiresAt: "2026-05-26T23:59:59.000Z",
      token: "dev_short_lived_ws_token"
    });
  }

  const response = await authFetch(authConfig.endpoints.webSocketToken, { method: "POST" });
  if (response.status === 401) return null;
  return WebSocketAuthTokenSchema.parse(await readJson(response));
}

async function verifyTwoFactor(challenge: TwoFactorChallenge): Promise<AuthSession> {
  const payload = TwoFactorFormSchema.parse(challenge);
  const response = await authFetch(authConfig.endpoints.verifyTwoFactor, {
    body: JSON.stringify(payload),
    method: "POST"
  });
  return AuthSessionSchema.parse(await readJson(response));
}

async function listDeviceSessions(): Promise<DeviceSession[]> {
  if (authConfig.mvpBypassAuth) {
    return [
      DeviceSessionSchema.parse({
        browser: "Local development",
        createdAt: "2026-05-26T00:00:00.000Z",
        deviceId: "dev_current",
        ipAddress: "127.0.0.1",
        lastSeenAt: "2026-05-26T00:00:00.000Z",
        locationLabel: "Developer workstation",
        state: "current"
      })
    ];
  }

  const response = await authFetch(authConfig.endpoints.deviceSessions);
  return DeviceSessionSchema.array().parse(await readJson(response));
}

async function revokeDeviceSession(deviceId: string): Promise<void> {
  if (authConfig.mvpBypassAuth) return;

  await authFetch(authConfig.endpoints.revokeDeviceSession(deviceId), { method: "DELETE" });
}

async function exchangeApiKeySecurity(): Promise<ExchangeApiKeySecurityStatus> {
  if (authConfig.mvpBypassAuth) {
    return { encryptedAt: null, state: "pending-backend" };
  }

  const response = await authFetch(authConfig.endpoints.exchangeKeySecurity);
  return await readJson(response) as ExchangeApiKeySecurityStatus;
}

async function authFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const controller = new AbortController();
  const timeout = globalThis.setTimeout(() => controller.abort(), API_TIMEOUT_MS);
  const upstreamSignal = init.signal;

  if (upstreamSignal) {
    if (upstreamSignal.aborted) controller.abort();
    upstreamSignal.addEventListener("abort", () => controller.abort(), { once: true });
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      credentials: "include",
      headers: {
        ...jsonHeaders,
        ...init.headers
      },
      signal: controller.signal
    });
  } catch (exc) {
    if (exc instanceof DOMException && exc.name === "AbortError") {
      throw new Error(`Auth API request timed out after ${API_TIMEOUT_MS}ms at ${API_BASE}.`);
    }
    throw exc;
  } finally {
    globalThis.clearTimeout(timeout);
  }

  if (!response.ok && response.status !== 401) {
    throw new Error(await getApiErrorMessage(response));
  }

  return response;
}

async function readJson(response: Response): Promise<unknown> {
  if (response.status === 204) return null;
  return await response.json();
}

async function getApiErrorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json() as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : `Auth API error ${response.status}`;
  } catch {
    return `Auth API error ${response.status}`;
  }
}
