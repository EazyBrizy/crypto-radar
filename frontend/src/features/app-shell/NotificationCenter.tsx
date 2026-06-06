"use client";

import { Bell, CheckCheck, Send, Volume2, VolumeX, X } from "lucide-react";
import { useEffect } from "react";

import {
  useCreateTestNotificationMutation,
  useDeleteNotificationMutation,
  useMarkAllNotificationsReadMutation,
  useNotificationsQuery
} from "@/features/server-state/use-server-state";
import {
  notificationDisplayCopy,
  useNotificationStore,
  type BrowserNotificationPermission,
  type NotificationKind
} from "@/stores/notification-store";
import { useUiStore } from "@/stores/ui-store";

export function NotificationCenter() {
  const activeModal = useUiStore((state) => state.activeModal);
  const closeModal = useUiStore((state) => state.closeModal);
  const openModal = useUiStore((state) => state.openModal);
  const notifications = useNotificationStore((state) => state.notifications);
  const soundEnabled = useNotificationStore((state) => state.soundEnabled);
  const browserPermission = useNotificationStore((state) => state.browserPermission);
  const browserNotificationsEnabled = useNotificationStore((state) => state.browserNotificationsEnabled);
  const dismiss = useNotificationStore((state) => state.dismiss);
  const markAllRead = useNotificationStore((state) => state.markAllRead);
  const upsertMany = useNotificationStore((state) => state.upsertMany);
  const setBrowserNotificationsEnabled = useNotificationStore((state) => state.setBrowserNotificationsEnabled);
  const setBrowserPermission = useNotificationStore((state) => state.setBrowserPermission);
  const toggleSound = useNotificationStore((state) => state.toggleSound);
  const notificationsQuery = useNotificationsQuery();
  const createTestNotification = useCreateTestNotificationMutation();
  const markAllNotificationsRead = useMarkAllNotificationsReadMutation();
  const deleteNotification = useDeleteNotificationMutation();
  const unreadCount = notifications.filter((notification) => !notification.read).length;
  const panelOpen = activeModal === "notifications";

  useEffect(() => {
    if (!notificationsQuery.data) return;
    upsertMany(notificationsQuery.data.map((notification) => ({
      createdAt: Date.parse(notification.created_at) || Date.now(),
      id: notification.id,
      kind: notificationKind(notification.type),
      message: notification.body ?? "",
      read: notification.is_read,
      signalId: typeof notification.payload.signal_id === "string" ? notification.payload.signal_id : undefined,
      title: notification.title,
      type: notification.type
    })));
  }, [notificationsQuery.data, upsertMany]);

  async function requestBrowserPermission() {
    if (!("Notification" in window)) {
      setBrowserPermission("unsupported");
      return;
    }

    const permission = await Notification.requestPermission();
    setBrowserPermission(permission as BrowserNotificationPermission);
    setBrowserNotificationsEnabled(permission === "granted");
  }

  return (
    <div className="notification-center">
      <button
        className="icon-button notification-button"
        onClick={() => (panelOpen ? closeModal() : openModal("notifications"))}
        type="button"
        title="Notifications"
      >
        <Bell size={18} />
        {unreadCount ? <span className="notification-count">{unreadCount > 9 ? "9+" : unreadCount}</span> : null}
      </button>

      {panelOpen ? (
        <section className="notification-panel">
          <div className="notification-panel-head">
            <div>
              <span className="muted">Notifications</span>
              <h3>Realtime events</h3>
            </div>
            <button className="icon-button" onClick={closeModal} type="button" title="Close">
              <X size={16} />
            </button>
          </div>

          <div className="notification-controls">
            <button className={soundEnabled ? "filter-chip active" : "filter-chip"} onClick={toggleSound} type="button">
              {soundEnabled ? <Volume2 size={15} /> : <VolumeX size={15} />}
              Sound
            </button>
            <button
              className={browserNotificationsEnabled ? "filter-chip active" : "filter-chip"}
              onClick={() => void requestBrowserPermission()}
              type="button"
            >
              <Bell size={15} />
              Browser: {browserPermission}
            </button>
            <button
              className="filter-chip"
              disabled={markAllNotificationsRead.isPending}
              onClick={() => handleMarkAllRead(markAllRead, markAllNotificationsRead)}
              type="button"
            >
              <CheckCheck size={15} />
              Read all
            </button>
            <button
              className="filter-chip"
              disabled={createTestNotification.isPending}
              onClick={() => void createTestNotification.mutateAsync()}
              type="button"
            >
              <Send size={15} />
              Test
            </button>
          </div>

          <div className="notification-list">
            {notifications.length ? notifications.slice(0, 12).map((notification) => (
              <article className={notification.read ? "notification-item read" : "notification-item"} key={notification.id}>
                <div>
                  <strong>{notificationDisplayCopy(notification).title}</strong>
                  <p>{notificationDisplayCopy(notification).message}</p>
                  <span>{formatNotificationTime(notification.createdAt)}</span>
                </div>
                <button
                  className="icon-button"
                  onClick={() => {
                    void deleteNotification
                      .mutateAsync(notification.id)
                      .finally(() => dismiss(notification.id));
                  }}
                  type="button"
                  title="Dismiss"
                >
                  <X size={14} />
                </button>
              </article>
            )) : (
              <div className="empty-state">
                <Bell size={24} />
                <strong>No notifications yet</strong>
                <span>New signals, trade lifecycle events, and exchange issues will appear here.</span>
              </div>
            )}
          </div>
        </section>
      ) : null}
    </div>
  );
}

function handleMarkAllRead(
  markAllRead: () => void,
  markAllNotificationsRead: ReturnType<typeof useMarkAllNotificationsReadMutation>,
) {
  markAllRead();
  void markAllNotificationsRead.mutateAsync();
}

function notificationKind(type: string): NotificationKind {
  if (type.startsWith("signal")) return "signal";
  if (type.startsWith("trade") || type.startsWith("virtual_trade")) return "trade";
  if (type.startsWith("order")) return "order";
  if (type.startsWith("alert")) return "alert";
  if (type.startsWith("connection")) return "connection";
  return "system";
}

function formatNotificationTime(createdAt: number): string {
  const ageMs = Math.max(0, Date.now() - createdAt);
  if (ageMs < 60_000) return "just now";
  if (ageMs < 3_600_000) return `${Math.round(ageMs / 60_000)}m ago`;
  return `${Math.round(ageMs / 3_600_000)}h ago`;
}
