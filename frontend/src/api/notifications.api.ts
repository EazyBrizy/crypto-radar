import type { NotificationDraft, PersistedNotification } from "@/features/server-state/types";
import { openApiClient, request } from "./client";
import { normalizeNotification } from "./mappers";

export const notificationsApi = {
  async list(): Promise<PersistedNotification[]> {
    const response = await request(() =>
      openApiClient.GET("/api/v1/notifications", {
        params: {
          query: {
            user_id: "demo_user",
            limit: 50
          }
        }
      })
    );
    return response.map(normalizeNotification);
  },

  async create(draft: NotificationDraft): Promise<PersistedNotification> {
    return normalizeNotification(
      await request(() =>
        openApiClient.POST("/api/v1/notifications", {
          body: {
            user_id: "demo_user",
            type: draft.type,
            title: draft.title,
            body: draft.body ?? null,
            payload: draft.payload ?? {},
            channels: draft.channels ?? ["websocket"]
          }
        })
      )
    );
  },

  async createTest(): Promise<PersistedNotification> {
    return normalizeNotification(
      await request(() =>
        openApiClient.POST("/api/v1/notifications/test", {
          body: {
            user_id: "demo_user",
            channels: ["websocket", "email", "telegram"]
          }
        })
      )
    );
  },

  async markRead(notificationId: string, isRead = true): Promise<PersistedNotification> {
    return normalizeNotification(
      await request(() =>
        openApiClient.PATCH("/api/v1/notifications/{notification_id}", {
          params: {
            path: { notification_id: notificationId }
          },
          body: { is_read: isRead }
        })
      )
    );
  },

  async markAllRead(): Promise<{ updated: number }> {
    const response = await request(() =>
      openApiClient.POST("/api/v1/notifications/read-all", {
        params: {
          query: { user_id: "demo_user" }
        }
      })
    );
    return { updated: Number(response.updated ?? 0) };
  },

  async delete(notificationId: string): Promise<void> {
    const result = await openApiClient.DELETE("/api/v1/notifications/{notification_id}", {
      params: {
        path: { notification_id: notificationId }
      }
    });
    if (result.error || !result.response.ok) {
      throw new Error(`Notification delete failed: ${result.response.status}`);
    }
  }
};
