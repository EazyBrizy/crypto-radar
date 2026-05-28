import { z } from "zod";

export const LoginFormSchema = z.object({
  email: z.string().trim().email("Enter a valid email"),
  password: z.string().min(8, "Password must be at least 8 characters")
});

export const RegisterFormSchema = LoginFormSchema.extend({
  name: z.string().trim().min(2, "Name must be at least 2 characters")
});

export const TwoFactorFormSchema = z.object({
  challengeId: z.string().min(1),
  code: z.string().trim().min(6, "Enter the 2FA code").max(12, "2FA code is too long"),
  method: z.enum(["totp", "webauthn", "recovery-code"])
});

export const PasswordResetRequestSchema = z.object({
  email: z.string().trim().email("Enter a valid email")
});

export const DeviceSessionSchema = z.object({
  browser: z.string(),
  createdAt: z.string().datetime(),
  deviceId: z.string(),
  ipAddress: z.string(),
  lastSeenAt: z.string().datetime(),
  locationLabel: z.string(),
  state: z.enum(["current", "trusted", "untrusted", "revoked"])
});

export const AuthSessionSchema = z.object({
  accessTokenExpiresAt: z.string().datetime(),
  authLevel: z.enum(["anonymous", "password", "mfa"]),
  mfaRequired: z.boolean(),
  refreshCookieMode: z.literal("http-only"),
  user: z.object({
    email: z.string().email(),
    id: z.string(),
    name: z.string(),
    roles: z.array(z.enum(["owner", "admin", "trader", "viewer"]))
  })
});

export const LoginResultSchema = z.discriminatedUnion("status", [
  z.object({
    session: AuthSessionSchema,
    status: z.literal("authenticated")
  }),
  z.object({
    challengeId: z.string(),
    methods: z.array(z.enum(["totp", "webauthn", "recovery-code"])),
    status: z.literal("mfa-required")
  })
]);

export const WebSocketAuthTokenSchema = z.object({
  expiresAt: z.string().datetime(),
  token: z.string().min(16)
});
