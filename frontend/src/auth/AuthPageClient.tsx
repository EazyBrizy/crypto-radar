"use client";

import { KeyRound, ShieldCheck } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import type { z } from "zod";

import { Button } from "@/components/ui/button";
import { FormTextField, useZodForm, ValidatedForm } from "@/components/forms/form-pattern";
import { authConfig } from "./auth-config";
import { LoginFormSchema } from "./auth-schemas";
import { useAuthUiStore } from "./auth-ui-store";
import { useLoginMutation } from "./use-auth";

type LoginFormValues = z.infer<typeof LoginFormSchema>;

export function AuthPageClient() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const view = useAuthUiStore((state) => state.view);
  const mfaMethods = useAuthUiStore((state) => state.mfaMethods);
  const loginMutation = useLoginMutation();
  const form = useZodForm<LoginFormValues>(LoginFormSchema, {
    defaultValues: {
      email: "demo@crypto-radar.local",
      password: "demo-password"
    }
  });

  const redirectPath = getSafeRedirect(searchParams?.get("redirect") ?? null);

  async function handleLogin(values: LoginFormValues) {
    const result = await loginMutation.mutateAsync(values);
    if (result.status === "authenticated") {
      router.replace(redirectPath);
    }
  }

  return (
    <main className="auth-shell auth-centered">
      <section className="auth-grid">
        <div className="wide-panel auth-copy">
          <span className="muted">Crypto Radar Auth</span>
          <h1>Sign in</h1>
          <p>
            The frontend is prepared for FastAPI JWT access tokens, HttpOnly refresh cookies,
            2FA, device sessions, and encrypted exchange key status.
          </p>
          <div className="chip-cloud">
            <span className="badge badge-blue">{authConfig.provider}</span>
            {authConfig.mvpBypassAuth ? <span className="badge badge-yellow">MVP demo session</span> : null}
          </div>
        </div>

        <div className="wide-panel auth-card">
          <div className="section-title">
            <KeyRound size={18} />
            <h2>{view === "two-factor" ? "Two-factor check" : "Account access"}</h2>
          </div>

          {view === "two-factor" ? (
            <div className="auth-placeholder">
              <ShieldCheck size={22} />
              <h3>2FA challenge prepared</h3>
              <p>Backend challenge methods: {mfaMethods.join(", ") || "pending"}</p>
            </div>
          ) : (
            <ValidatedForm form={form} onSubmit={handleLogin}>
              <FormTextField<LoginFormValues> autoComplete="email" label="Email" name="email" type="email" />
              <FormTextField<LoginFormValues> autoComplete="current-password" label="Password" name="password" type="password" />
              {loginMutation.error ? <p className="form-error">{loginMutation.error.message}</p> : null}
              <Button disabled={loginMutation.isPending} type="submit">
                {loginMutation.isPending ? "Signing in" : "Sign in"}
              </Button>
            </ValidatedForm>
          )}
        </div>
      </section>
    </main>
  );
}

function getSafeRedirect(value: string | null): string {
  if (!value || !value.startsWith("/") || value.startsWith("//")) return "/dashboard/radar";
  return value;
}
