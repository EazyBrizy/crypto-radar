import type { BillingPlan, SubscriptionStatus } from "@/features/server-state/types";
import { openApiClient, request } from "./client";
import { normalizeBillingPlan, normalizeSubscriptionStatus } from "./mappers";

export const billingApi = {
  async plans(): Promise<BillingPlan[]> {
    const response = await request(() => openApiClient.GET("/api/v1/billing/plans"));
    return response.map(normalizeBillingPlan);
  },
  async subscription(): Promise<SubscriptionStatus> {
    return normalizeSubscriptionStatus(
      await request(() =>
        openApiClient.GET("/api/v1/billing/subscription", {
          params: { query: { user_id: "demo_user" } }
        })
      )
    );
  },
  async checkout(planCode: string): Promise<unknown> {
    return request(() =>
      openApiClient.POST("/api/v1/billing/checkout", {
        body: {
          user_id: "demo_user",
          plan_code: planCode,
          success_url: null,
          cancel_url: null
        }
      })
    );
  },
  async customerPortal(): Promise<unknown> {
    return request(() =>
      openApiClient.POST("/api/v1/billing/customer-portal", {
        body: {
          user_id: "demo_user",
          return_url: null
        }
      })
    );
  }
};
