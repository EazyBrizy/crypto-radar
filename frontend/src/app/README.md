# App Router

Next.js App Router owns product navigation.

Structure:

- `/` redirects to `/dashboard/radar`
- `/dashboard` redirects to `/dashboard/radar`
- `/dashboard/radar`
- `/dashboard/watchlist`
- `/dashboard/trades/active`
- `/dashboard/trades/journal`
- `/dashboard/trades/analytics`
- `/dashboard/settings`
- `/auth`
- `/billing`

`dashboard/layout.tsx` mounts the shared SaaS shell, realtime gateway, sidebar,
topbar, scanner controls, and connection status.

Routes render focused Client Components for realtime views. URL routing should
be preferred over storing active pages in Zustand.
