# Components Agent Guide

Components should stay consistent with the product's quiet trading-dashboard UI.

## UI primitives

- Reusable base primitives belong in `src/components/ui`.
- Prefer shadcn/Radix patterns and Lucide icons.
- Do not create duplicate button/input/badge systems.

## Tables and lists

- Large lists must use virtualization.
- Tables should use `src/components/data-table/DataTable.tsx`.
- Signal feed should use `SignalFeed` and `SignalCardById`, not direct array rendering for large data.

## Charts

- Trading charts use TradingView Lightweight Charts wrappers.
- Position overlays belong in `src/components/charts`.
- Signal Details chart is lazy-loaded; do not import `lightweight-charts` into route shells, Settings, or generic dashboard components.

## Forms

- Forms should use React Hook Form + Zod via `src/components/forms/form-pattern.tsx`.
- Form schemas belong in validation/auth modules, not inline in JSX unless tiny and local.

## Realtime UI

- Components render state; they do not subscribe to sockets.
- Use selectors from stores when possible to avoid broad rerenders.
- Trading action buttons must honor realtime freshness/disabled selectors.
