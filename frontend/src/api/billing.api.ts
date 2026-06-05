import type { BillingPlan, SubscriptionStatus } from "@/features/server-state/types";
import { openApiClient, request } from "./client";
import { normalizeBillingPlan, normalizeSubscriptionStatus } from "./mappers";
import { currentUserId, currentUserQuery } from "./user-identity";

export const billingApi = {
  async plans(): Promise<BillingPlan[]> {
    const response = await request(() => openApiClient.GET("/api/v1/billing/plans"));
    return response.map(normalizeBillingPlan);
  },
  async subscription(): Promise<SubscriptionStatus> {
    const query = await currentUserQuery();
    return normalizeSubscriptionStatus(
      await request(() =>
        openApiClient.GET("/api/v1/billing/subscription", {
          params: { query }
        })
      )
    );
  },
  async checkout(planCode: string): Promise<unknown> {
    const userId = await currentUserId();
    return request(() =>
      openApiClient.POST("/api/v1/billing/checkout", {
        body: {
          user_id: userId,
          plan_code: planCode,
          success_url: null,
          cancel_url: null
        }
      })
    );
  },
  async customerPortal(): Promise<unknown> {
    const userId = await currentUserId();
    return request(() =>
      openApiClient.POST("/api/v1/billing/customer-portal", {
        body: {
          user_id: userId,
          return_url: null
        }
      })
    );
  }
};
