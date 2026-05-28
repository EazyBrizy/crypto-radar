# Validation

Use Zod at application boundaries:

- forms
- filters
- query params
- runtime realtime events

Realtime validation is mandatory because WebSocket payloads are outside
TypeScript's runtime guarantees. Invalid events must be dropped before they can
touch Zustand, TanStack Query, or React rendering.

Rules:

- Use `safeParse` for WebSocket/SSE payloads.
- Prefer `z.discriminatedUnion("type", ...)` for realtime events.
- Keep OpenAPI-generated DTO types as the REST source of truth.
- Use Zod for user input and realtime runtime validation, not as a replacement
  for OpenAPI-generated REST types.
