# Data Tables

Tables use TanStack Table plus TanStack Virtual.

Use this layer for:

- Trade Journal
- Scanner series
- Exchange orders
- Signal history
- Event timeline

Rules:

- Do not render large datasets with plain `.map`.
- Use `DataTable` for sorting, filtering, column logic, and virtualization.
- Keep domain tables as thin wrappers around `DataTable`.
- Prefer column definitions close to the domain table component.
- Use server state from TanStack Query, not Zustand, as the source for historical/table data.
