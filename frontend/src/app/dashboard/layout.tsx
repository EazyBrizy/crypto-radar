import type { ReactNode } from "react";

import { RequireAuth } from "@/auth/RequireAuth";
import { DashboardShell } from "@/features/app-shell/DashboardShell";

export default function DashboardLayout({ children }: { children: ReactNode }) {
  return (
    <RequireAuth>
      <DashboardShell>{children}</DashboardShell>
    </RequireAuth>
  );
}
