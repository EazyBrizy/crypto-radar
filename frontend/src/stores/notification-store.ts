import { create } from "zustand";

export type NotificationKind = "signal" | "trade" | "order" | "connection" | "alert" | "system";
export type BrowserNotificationPermission = "default" | "denied" | "granted" | "unsupported";

export interface RadarNotification {
  createdAt: number;
  id: string;
  kind: NotificationKind;
  message: string;
  read: boolean;
  signalId?: string;
  title: string;
  type?: string;
}

interface NotificationState {
  browserNotificationsEnabled: boolean;
  browserPermission: BrowserNotificationPermission;
  notifications: RadarNotification[];
  soundEnabled: boolean;
  clear: () => void;
  dismiss: (notificationId: string) => void;
  markAllRead: () => void;
  markRead: (notificationId: string) => void;
  push: (notification: Omit<RadarNotification, "createdAt" | "id" | "read"> & { id?: string }) => void;
  upsertMany: (notifications: RadarNotification[]) => void;
  setBrowserNotificationsEnabled: (enabled: boolean) => void;
  setBrowserPermission: (permission: BrowserNotificationPermission) => void;
  toggleSound: () => void;
}

export const useNotificationStore = create<NotificationState>((set) => ({
  browserNotificationsEnabled: false,
  browserPermission: "default",
  notifications: [],
  soundEnabled: false,
  clear: () => set({ notifications: [] }),
  dismiss: (notificationId) =>
    set((state) => ({
      notifications: state.notifications.filter((notification) => notification.id !== notificationId)
    })),
  markAllRead: () =>
    set((state) => ({
      notifications: state.notifications.map((notification) => ({ ...notification, read: true }))
    })),
  markRead: (notificationId) =>
    set((state) => ({
      notifications: state.notifications.map((notification) =>
        notification.id === notificationId ? { ...notification, read: true } : notification
      )
    })),
  push: (notification) =>
    set((state) => ({
      notifications: [
        {
          ...notification,
          createdAt: Date.now(),
          id: notification.id ?? `ntf_${Date.now()}_${Math.random().toString(16).slice(2)}`,
          read: false
        },
        ...state.notifications
      ].slice(0, 100)
    })),
  upsertMany: (notifications) =>
    set((state) => {
      const byId = new Map<string, RadarNotification>();
      for (const notification of [...notifications, ...state.notifications]) {
        byId.set(notification.id, notification);
      }
      return {
        notifications: [...byId.values()]
          .sort((left, right) => right.createdAt - left.createdAt)
          .slice(0, 100)
      };
    }),
  setBrowserNotificationsEnabled: (browserNotificationsEnabled) => set({ browserNotificationsEnabled }),
  setBrowserPermission: (browserPermission) => set({ browserPermission }),
  toggleSound: () => set((state) => ({ soundEnabled: !state.soundEnabled }))
}));
