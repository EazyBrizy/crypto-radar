"use client";

import { type ReactNode, useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";

import { SignalCard, SignalCardById } from "@/components/SignalCard";
import { useI18n } from "@/i18n";
import type { RadarSignal } from "@/types";

interface SignalFeedProps {
  emptyState: ReactNode;
  loading: boolean;
  onSelectSignal: (signal: RadarSignal) => void;
  selectedSignalId: string | null;
  signalIds: string[];
  signals?: RadarSignal[];
}

export function SignalFeed({ emptyState, loading, onSelectSignal, selectedSignalId, signalIds, signals }: SignalFeedProps) {
  const { t } = useI18n();
  const parentRef = useRef<HTMLDivElement | null>(null);
  const renderedSignalIds = signals ? signals.map((signal) => signal.id) : signalIds;
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: renderedSignalIds.length,
    estimateSize: () => 186,
    getScrollElement: () => parentRef.current,
    overscan: 8
  });
  const virtualItems = virtualizer.getVirtualItems();

  if (loading) return <div className="empty-state">{t("Loading signals...")}</div>;
  if (!renderedSignalIds.length) return <>{emptyState}</>;

  return (
    <div className="signal-feed virtual-signal-feed" ref={parentRef}>
      <div
        className="virtual-signal-feed-inner"
        style={{
          height: `${virtualizer.getTotalSize()}px`
        }}
      >
        {virtualItems.map((virtualItem) => {
          const signal = signals?.[virtualItem.index] ?? null;
          const signalId = signal?.id ?? signalIds[virtualItem.index];
          return (
            <div
              className="virtual-signal-row"
              data-index={virtualItem.index}
              key={signalId}
              ref={virtualizer.measureElement}
              style={{
                transform: `translateY(${virtualItem.start}px)`
              }}
            >
              {signal ? (
                <SignalCard signal={signal} selected={selectedSignalId === signalId} onSelect={onSelectSignal} />
              ) : (
                <SignalCardById
                  signalId={signalId}
                  selected={selectedSignalId === signalId}
                  onSelect={onSelectSignal}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
