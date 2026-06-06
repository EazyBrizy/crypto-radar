"use client";

import { useEffect, useRef } from "react";

import { notificationDisplayCopy, useNotificationStore } from "@/stores/notification-store";

export const TOAST_AUTO_DISMISS_MS = 6_000;

export function NotificationRuntime() {
  const notifications = useNotificationStore((state) => state.notifications);
  const dismiss = useNotificationStore((state) => state.dismiss);
  const markRead = useNotificationStore((state) => state.markRead);
  const soundEnabled = useNotificationStore((state) => state.soundEnabled);
  const browserPermission = useNotificationStore((state) => state.browserPermission);
  const browserNotificationsEnabled = useNotificationStore((state) => state.browserNotificationsEnabled);
  const setBrowserPermission = useNotificationStore((state) => state.setBrowserPermission);
  const seenIds = useRef(new Set<string>());
  const toastTimers = useRef(new Map<string, number>());
  const initialized = useRef(false);

  useEffect(() => {
    if (!("Notification" in window)) {
      setBrowserPermission("unsupported");
      return;
    }
    setBrowserPermission(Notification.permission);
  }, [setBrowserPermission]);

  useEffect(() => {
    if (!initialized.current) {
      notifications.forEach((notification) => seenIds.current.add(notification.id));
      initialized.current = true;
      return;
    }

    const latest = notifications.find((notification) => !seenIds.current.has(notification.id));
    if (!latest) return;

    seenIds.current.add(latest.id);
    const display = notificationDisplayCopy(latest);
    if (soundEnabled) playNotificationSound();
    if (browserNotificationsEnabled && browserPermission === "granted") {
      const browserNotification = new Notification(display.title, {
        body: display.message,
        tag: latest.id
      });
      browserNotification.onclick = () => markRead(latest.id);
    }
  }, [browserNotificationsEnabled, browserPermission, markRead, notifications, soundEnabled]);

  const toasts = notifications.filter((notification) => !notification.read).slice(0, 3);

  useEffect(() => {
    const visibleToastIds = new Set(toasts.map((notification) => notification.id));

    for (const notification of toasts) {
      if (toastTimers.current.has(notification.id)) continue;
      const timer = window.setTimeout(() => {
        markRead(notification.id);
        toastTimers.current.delete(notification.id);
      }, TOAST_AUTO_DISMISS_MS);
      toastTimers.current.set(notification.id, timer);
    }

    for (const [notificationId, timer] of toastTimers.current) {
      if (visibleToastIds.has(notificationId)) continue;
      window.clearTimeout(timer);
      toastTimers.current.delete(notificationId);
    }
  }, [markRead, toasts]);

  useEffect(() => {
    const timers = toastTimers.current;
    return () => {
      for (const timer of timers.values()) {
        window.clearTimeout(timer);
      }
      timers.clear();
    };
  }, []);

  return (
    <div className="notification-toast-viewport" aria-live="polite">
      {toasts.map((notification) => (
        <article className={`notification-toast ${notification.kind}`} key={notification.id}>
          <div>
            <strong>{notificationDisplayCopy(notification).title}</strong>
            <p>{notificationDisplayCopy(notification).message}</p>
          </div>
          <button className="icon-button" onClick={() => dismiss(notification.id)} type="button" title="Dismiss">
            ×
          </button>
        </article>
      ))}
    </div>
  );
}

function playNotificationSound() {
  const AudioContextConstructor = window.AudioContext;
  if (!AudioContextConstructor) return;

  const context = new AudioContextConstructor();
  const oscillator = context.createOscillator();
  const gain = context.createGain();
  oscillator.type = "sine";
  oscillator.frequency.value = 880;
  gain.gain.value = 0.04;
  oscillator.connect(gain);
  gain.connect(context.destination);
  oscillator.start();
  oscillator.stop(context.currentTime + 0.12);
}
