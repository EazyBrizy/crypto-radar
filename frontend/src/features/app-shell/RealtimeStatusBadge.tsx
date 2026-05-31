"use client";

import { Wifi, WifiOff } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { RealtimeConnectionStatus } from "@/realtime/event-types";
import { formatRealtimeAge, getLastRealtimeUpdateAt, isTradingActionDisabled } from "@/stores/ui-selectors";
import { useUiStore } from "@/stores/ui-store";

export function RealtimeStatusBadge() {
  const status = useUiStore((state) => state.connectionStatus);
  const lastEventAt = useUiStore((state) => state.lastEventAt);
  const lastHeartbeatAt = useUiStore((state) => state.lastHeartbeatAt);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, []);

  const lastUpdateAt = getLastRealtimeUpdateAt(lastEventAt, lastHeartbeatAt);
  const view = useMemo(() => getRealtimeStatusView(status), [status]);
  const ageLabel = formatRealtimeAge(lastUpdateAt, now);
  const Icon = view.icon;

  return (
    <span className={`realtime-status ${view.className}`} title={view.title}>
      <Icon size={13} />
      <strong>{view.primary}</strong>
      <small>{view.secondary ?? `Last update: ${ageLabel}`}</small>
    </span>
  );
}

function getRealtimeStatusView(status: RealtimeConnectionStatus): {
  className: string;
  icon: typeof Wifi;
  primary: string;
  secondary?: string;
  title: string;
} {
  if (isTradingActionDisabled(status)) {
    if (status === "offline" || status === "closed") {
      return {
        className: "offline-dot",
        icon: WifiOff,
        primary: "Offline",
        secondary: "Trading actions disabled",
        title: "Realtime connection is offline. Trading actions are disabled."
      };
    }

    if (status === "delayed" || status === "fallback") {
      return {
        className: "syncing-dot",
        icon: Wifi,
        primary: "Live data delayed",
        secondary: "Data may be delayed",
        title: "Realtime data is delayed. Review data freshness before acting."
      };
    }

    return {
      className: "offline-dot",
      icon: WifiOff,
      primary: "Connection issue",
      secondary: "Trading actions disabled",
      title: "Realtime connection has an auth or transport issue."
    };
  }

  if (status === "open") {
    return {
      className: "live-dot",
      icon: Wifi,
      primary: "Online · Connected",
      title: "Realtime stream is connected."
    };
  }

  if (status === "authenticating" || status === "connecting" || status === "reconnecting") {
    return {
      className: "syncing-dot",
      icon: Wifi,
      primary: "Reconnecting...",
      secondary: "Data may be delayed",
      title: "Realtime stream is reconnecting."
    };
  }

  return {
    className: "syncing-dot",
    icon: Wifi,
    primary: "Preparing",
    secondary: "Waiting for stream",
    title: "Realtime stream is preparing."
  };
}
