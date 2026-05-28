# REST API Layer

FastAPI owns the schema. Frontend types must come from OpenAPI generation.

Pipeline:

1. FastAPI `/openapi.json`
2. `openapi-typescript`
3. generated TypeScript schema
4. typed `openapi-fetch` client
5. domain API modules
6. TanStack Query hooks

Structure:

- `generated/` stores the exported OpenAPI schema and schema re-exports.
- `client.ts` owns the configured `openapi-fetch` client and error handling.
- `signals.api.ts` owns signal and radar signal actions.
- `trades.api.ts` owns trade endpoints.
- `journal.api.ts` owns journal history reads.
- `settings.api.ts` owns radar config, scanner status, profile, and subscription contracts.
- `exchanges.api.ts` owns exchange catalog/connection reads.
- `candles.api.ts` owns candle series reads for charts.

Do not hand-write backend DTOs in frontend. If FastAPI changes a response shape,
regenerate the OpenAPI types and update the domain mapper if needed.
