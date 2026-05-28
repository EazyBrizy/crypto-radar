# Auth architecture

Frontend auth is prepared for the long-term Crypto Radar target: FastAPI custom auth with JWT access tokens and an HttpOnly refresh cookie.

## Current MVP mode

- `NEXT_PUBLIC_AUTH_MVP_BYPASS` defaults to enabled unless set to `false`.
- In bypass mode the frontend returns a local demo session so dashboard routes stay usable while backend auth endpoints are not ready.
- No secrets, refresh tokens, exchange API keys, or 2FA data are stored in the browser.

## Planned FastAPI endpoints

- `GET /api/auth/session`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `POST /api/auth/refresh`
- `POST /api/auth/ws-token`
- `POST /api/auth/2fa/verify`
- `GET /api/auth/sessions`
- `DELETE /api/auth/sessions/{deviceId}`
- `GET /api/auth/exchange-key-security`

## State split

- TanStack Query owns server auth state: current session, device sessions, exchange key security status.
- Zustand owns local auth UI state: active auth view, pending 2FA challenge, last attempted email.

## WebSocket auth

- Browser WebSocket connects with a short-lived token in the handshake URL: `/ws?token=...`.
- The frontend obtains that token from `POST /api/auth/ws-token` with `credentials: include`.
- The token is requested again for every reconnect, so the realtime client never reuses a stale token.
- Backend must validate the token before accepting private subscriptions and must only subscribe the socket to user-owned data.
- SSE stays read-only fallback and must not expose private account, order, or exchange-position streams without its own auth gate.

## Future integrations

Auth.js and Clerk remain viable MVP alternatives, but the frontend contracts here intentionally match the custom FastAPI JWT path needed for 2FA, session/device management, and encrypted exchange API key workflows.
