import { Suspense } from "react";

import { AuthPageClient } from "@/auth/AuthPageClient";

export default function AuthPage() {
  return (
    <Suspense fallback={<AuthFallback />}>
      <AuthPageClient />
    </Suspense>
  );
}

function AuthFallback() {
  return (
    <main className="auth-shell auth-centered">
      <section className="wide-panel auth-status-panel">
        <h1>Loading sign in</h1>
      </section>
    </main>
  );
}
