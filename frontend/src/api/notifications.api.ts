import type { NotificationDraft, PersistedNotification } from "@/features/server-state/types";
import { openApiClient, request } from "./client";
import { normalizeNotification } from "./mappers";
import { currentUserId, currentUserQuery } from "./user-identity";

export const notificationsApi = {
  async list(): Promise<PersistedNotification[]> {
    const query = {
      ...(await currentUserQuery()),
      limit: 50
    };
    const response = await request(() =>
      openApiClient.GET("/api/v1/notifications", {
        params: { query }
      })
    );
    return response.map(normalizeNotification);
  },

  async create(draft: NotificationDraft): Promise<PersistedNotification> {
    const userId = await currentUserId();
    return normalizeNotification(
      await request(() =>
        openApiClient.POST("/api/v1/notifications", {
          body: {
            user_id: userId,
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
    const userId = await currentUserId();
    return normalizeNotification(
      await request(() =>
        openApiClient.POST("/api/v1/notifications/test", {
          body: {
            user_id: userId,
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
    const query = await currentUserQuery();
    const response = await request(() =>
      openApiClient.POST("/api/v1/notifications/read-all", {
        params: { query }
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
