# UI Kit Policy

Crypto Radar UI should feel fast, quiet, clear, and precise.

Approved UI stack:

- Tailwind CSS for controlled styling and design tokens.
- shadcn/ui for copied, local components rather than a heavy runtime UI library.
- Radix UI primitives for accessible behavior.
- Lucide Icons for lightweight iconography.
- Framer Motion only when a specific micro-interaction needs it.

Current status:

- Tailwind v4 is wired through `src/app/globals.css` and `@tailwindcss/postcss`.
- shadcn/ui config lives in `components.json`.
- Local shadcn-style primitives exist in `src/components/ui`.
- Radix is used for `Slot` and form labels.
- Lucide is used for app navigation, buttons, states, and panels.
- Framer Motion is intentionally not installed yet.

Rules:

- Prefer CSS transitions for hover, focus, selected, loading, and connection-state changes.
- Do not add page-level entrance animations, parallax, decorative motion, or animation libraries for static UI.
- If Framer Motion is added later, keep it isolated to tiny Client Components such as a toast, row highlight, or connection pulse.
- Do not animate high-frequency realtime data directly through React. Batch price updates with `requestAnimationFrame`.
- Keep controls familiar: icon buttons for tools, segmented controls for modes, toggles for binary settings, and compact tables/lists for dense data.
- Avoid decorative cards, oversized hero treatment, and marketing-style layouts inside the SaaS app shell.
