"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { CreditCard, ExternalLink } from "lucide-react";
import { useState } from "react";

import { api } from "@/api";
import { Badge } from "@/components/Badge";
import { serverStateKeys } from "@/features/server-state/query-keys";
import type { BillingPlan } from "@/features/server-state/types";

export function BillingRoute() {
  const [providerError, setProviderError] = useState<string | null>(null);
  const plansQuery = useQuery({
    queryKey: serverStateKeys.billing.plans(),
    queryFn: api.billingPlans
  });
  const subscriptionQuery = useQuery({
    queryKey: serverStateKeys.billing.subscription(),
    queryFn: api.billingSubscription
  });
  const checkoutMutation = useMutation({
    mutationFn: api.createBillingCheckout,
    onError: (error) => setProviderError(error instanceof Error ? error.message : "Checkout is unavailable")
  });
  const portalMutation = useMutation({
    mutationFn: api.createBillingCustomerPortal,
    onError: (error) => setProviderError(error instanceof Error ? error.message : "Portal is unavailable")
  });

  const subscription = subscriptionQuery.data;
  const busy = checkoutMutation.isPending || portalMutation.isPending;

  return (
    <main className="auth-shell">
      <section className="wide-panel">
        <div className="page-head">
          <div>
            <span className="muted">Billing</span>
            <h1>Subscription</h1>
          </div>
          <button
            className="primary-action"
            disabled={busy}
            onClick={() => {
              setProviderError(null);
              portalMutation.mutate();
            }}
            type="button"
          >
            <ExternalLink size={16} />
            Portal
          </button>
        </div>

        {providerError ? <div className="error-banner">{providerError}</div> : null}

        <div className="settings-grid">
          <div className="settings-section">
            <div className="section-title"><CreditCard size={18} /><h3>Current</h3></div>
            <div className="billing-current">
              <strong>{subscription?.plan_name ?? "Free"}</strong>
              <Badge tone={subscription?.state === "active" ? "green" : "purple"}>{subscription?.state ?? "none"}</Badge>
              <span>{subscription?.current_period_end ? formatDate(subscription.current_period_end) : "No renewal date"}</span>
              <code>{subscription?.external_provider ?? "provider:stub"}</code>
            </div>
          </div>

          <div className="settings-section">
            <div className="section-title"><CreditCard size={18} /><h3>Plans</h3></div>
            <div className="billing-plan-list">
              {plansQuery.data?.map((plan) => (
                <PlanRow
                  busy={busy}
                  currentCode={subscription?.plan_code ?? null}
                  key={plan.id}
                  onCheckout={() => {
                    setProviderError(null);
                    checkoutMutation.mutate(plan.code);
                  }}
                  plan={plan}
                />
              ))}
              {!plansQuery.data?.length ? <div className="empty-state compact-empty">No plans</div> : null}
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}

function PlanRow({
  busy,
  currentCode,
  onCheckout,
  plan
}: {
  busy: boolean;
  currentCode: string | null;
  onCheckout: () => void;
  plan: BillingPlan;
}) {
  const isCurrent = currentCode === plan.code;
  return (
    <div className="billing-plan-row">
      <div>
        <strong>{plan.name}</strong>
        <span>{formatMoney(plan.price_monthly, plan.currency)} / mo</span>
      </div>
      <Badge tone={isCurrent ? "green" : "purple"}>{plan.code}</Badge>
      <button className="icon-button compact" disabled={busy || isCurrent} onClick={onCheckout} title="Checkout" type="button">
        <CreditCard size={15} />
      </button>
    </div>
  );
}

function formatMoney(value: number, currency: string): string {
  return new Intl.NumberFormat("en-US", {
    currency,
    maximumFractionDigits: 2,
    style: "currency"
  }).format(value);
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("en-US", {
    day: "2-digit",
    month: "short",
    year: "numeric"
  }).format(new Date(value));
}
