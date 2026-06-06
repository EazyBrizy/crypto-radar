import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useNotificationStore } from "@/stores/notification-store";
import { NotificationRuntime, TOAST_AUTO_DISMISS_MS } from "./NotificationRuntime";

describe("NotificationRuntime", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    useNotificationStore.getState().clear();
  });

  afterEach(() => {
    useNotificationStore.getState().clear();
    vi.useRealTimers();
  });

  it("auto-hides unread toasts after the dismiss timeout", () => {
    useNotificationStore.getState().push({
      kind: "signal",
      message: "ETHUSDT LONG score 84",
      title: "New signal"
    });

    render(<NotificationRuntime />);

    expect(screen.getByText("New signal")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(TOAST_AUTO_DISMISS_MS);
    });

    expect(screen.queryByText("New signal")).not.toBeInTheDocument();
    expect(useNotificationStore.getState().notifications[0]?.read).toBe(true);
  });

  it("labels legacy signal.created notifications as ideas", () => {
    useNotificationStore.getState().push({
      kind: "signal",
      message: "BTCUSDT LONG score 62",
      title: "New signal",
      type: "signal.created"
    });

    render(<NotificationRuntime />);

    expect(screen.getByText("New idea")).toBeInTheDocument();
    expect(screen.queryByText("New signal")).not.toBeInTheDocument();
  });

  it("labels signal.execution_ready notifications as execution-ready", () => {
    useNotificationStore.getState().push({
      kind: "signal",
      message: "ETHUSDT LONG score 84",
      title: "New signal",
      type: "signal.execution_ready"
    });

    render(<NotificationRuntime />);

    expect(screen.getByText("Execution signal ready")).toBeInTheDocument();
    expect(screen.queryByText("New signal")).not.toBeInTheDocument();
  });
});
