import { type ReactNode, useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";

import { SignalCardById } from "@/components/SignalCard";
import type { RadarSignal } from "@/types";

interface SignalFeedProps {
  emptyState: ReactNode;
  loading: boolean;
  onSelectSignal: (signal: RadarSignal) => void;
  selectedSignalId: string | null;
  signalIds: string[];
}

export function SignalFeed({ emptyState, loading, onSelectSignal, selectedSignalId, signalIds }: SignalFeedProps) {
  const parentRef = useRef<HTMLDivElement | null>(null);
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: signalIds.length,
    estimateSize: () => 186,
    getScrollElement: () => parentRef.current,
    overscan: 8
  });
  const virtualItems = virtualizer.getVirtualItems();

  if (loading) return <div className="empty-state">Р—Р°РіСЂСѓР¶Р°РµРј СЃРёРіРЅР°Р»С‹...</div>;
  if (!signalIds.length) return <>{emptyState}</>;

  return (
    <div className="signal-feed virtual-signal-feed" ref={parentRef}>
      <div
        className="virtual-signal-feed-inner"
        style={{
          height: `${virtualizer.getTotalSize()}px`
        }}
      >
        {virtualItems.map((virtualItem) => {
          const signalId = signalIds[virtualItem.index];
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
              <SignalCardById
                signalId={signalId}
                selected={selectedSignalId === signalId}
                onSelect={onSelectSignal}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}
