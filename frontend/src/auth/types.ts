export type AuthProviderKind = "custom-fastapi-jwt" | "auth-js" | "clerk" | "keycloak";

export type AuthRole = "owner" | "admin" | "trader" | "viewer";

export type AuthLevel = "anonymous" | "password" | "mfa";

export type MfaMethod = "totp" | "webauthn" | "recovery-code";

export type DeviceTrustState = "current" | "trusted" | "untrusted" | "revoked";

export type ExchangeKeySecurityState = "not-configured" | "pending-backend" | "encrypted";

export interface AuthUser {
  email: string;
  id: string;
  name: string;
  roles: AuthRole[];
}

export interface AuthSession {
  accessTokenExpiresAt: string;
  authLevel: AuthLevel;
  mfaRequired: boolean;
  refreshCookieMode: "http-only";
  user: AuthUser;
}

export interface LoginCredentials {
  email: string;
  password: string;
}

export interface LoginSuccess {
  session: AuthSession;
  status: "authenticated";
}

export interface LoginMfaRequired {
  challengeId: string;
  methods: MfaMethod[];
  status: "mfa-required";
}

export type LoginResult = LoginSuccess | LoginMfaRequired;

export interface TwoFactorChallenge {
  challengeId: string;
  code: string;
  method: MfaMethod;
}

export interface DeviceSession {
  browser: string;
  createdAt: string;
  deviceId: string;
  ipAddress: string;
  lastSeenAt: string;
  locationLabel: string;
  state: DeviceTrustState;
}

export interface ExchangeApiKeySecurityStatus {
  encryptedAt: string | null;
  state: ExchangeKeySecurityState;
}

export interface WebSocketAuthToken {
  expiresAt: string;
  token: string;
}
