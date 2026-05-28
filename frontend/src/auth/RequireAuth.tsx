"use client";

import { ShieldCheck } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { useEffect } from "react";

import { useAuthSessionQuery } from "./use-auth";

export function RequireAuth({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "/dashboard/radar";
  const router = useRouter();
  const sessionQuery = useAuthSessionQuery();
  const session = sessionQuery.data ?? null;

  useEffect(() => {
    if (!sessionQuery.isLoading && !session) {
      router.replace(`/auth?redirect=${encodeURIComponent(pathname)}`);
    }
  }, [pathname, router, session, sessionQuery.isLoading]);

  if (sessionQuery.isLoading) {
    return (
      <main className="auth-shell auth-centered">
        <section className="wide-panel auth-status-panel">
          <ShieldCheck size={22} />
          <h1>Checking session</h1>
        </section>
      </main>
    );
  }

  if (!session) {
    return (
      <main className="auth-shell auth-centered">
        <section className="wide-panel auth-status-panel">
          <ShieldCheck size={22} />
          <h1>Redirecting to sign in</h1>
        </section>
      </main>
    );
  }

  return children;
}
