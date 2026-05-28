"use client";

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { getWebSocketAuthToken } from "@/auth/use-auth";
import { serverStateKeys } from "@/features/server-state/query-keys";
import { createRealtimeEventRouter } from "@/realtime/event-router";
import { RealtimeSocketClient } from "@/realtime/socket-client";
import { useUiStore } from "@/stores/ui-store";

const DEFAULT_WS_URL = "ws://127.0.0.1:8000/api/v1/realtime/ws";
const SSE_URL = process.env.NEXT_PUBLIC_FASTAPI_SSE_URL;
const WS_URL = process.env.NEXT_PUBLIC_FASTAPI_WS_URL ?? DEFAULT_WS_URL;

export function FastApiRealtimeGateway() {
  const queryClient = useQueryClient();
  const setConnectionStatus = useUiStore((state) => state.setConnectionStatus);
  const markRealtimeEvent = useUiStore((state) => state.markRealtimeEvent);
  const markRealtimeHeartbeat = useUiStore((state) => state.markRealtimeHeartbeat);

  useEffect(() => {
    const router = createRealtimeEventRouter({
      queryClient,
      onRealtimeEvent: markRealtimeEvent,
      onHeartbeat: markRealtimeHeartbeat
    });
    const client = new RealtimeSocketClient({
      webSocketUrl: WS_URL,
      readOnlyFallbackUrl: SSE_URL,
      authTokenProvider: getWebSocketAuthToken,
      getLastEventId: router.getLastEventId,
      onReconnect: async () => {
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: serverStateKeys.signals.active() }),
          queryClient.invalidateQueries({ queryKey: serverStateKeys.radar.status() }),
          queryClient.invalidateQueries({ queryKey: serverStateKeys.trades.all() }),
          queryClient.invalidateQueries({ queryKey: serverStateKeys.journal.all() })
        ]);
      },
      onStatusChange: setConnectionStatus,
      onMessage: router.route
    });

    client.connect();

    return () => client.close();
  }, [markRealtimeEvent, markRealtimeHeartbeat, queryClient, setConnectionStatus]);

  return null;
}
