import { create } from "zustand";

interface PricePoint {
  price: number;
  updatedAt: number;
}

interface PriceState {
  pricesBySymbol: Record<string, PricePoint>;
  queuePrice: (symbol: string, price: number) => void;
}

const pendingPrices = new Map<string, PricePoint>();
let frameId: number | null = null;

export const usePriceStore = create<PriceState>((set) => ({
  pricesBySymbol: {},
  queuePrice: (symbol, price) => {
    pendingPrices.set(symbol, { price, updatedAt: Date.now() });

    if (frameId !== null) return;
    if (typeof window === "undefined") {
      const batch = Object.fromEntries(pendingPrices);
      pendingPrices.clear();
      set((state) => ({
        pricesBySymbol: {
          ...state.pricesBySymbol,
          ...batch
        }
      }));
      return;
    }

    frameId = window.requestAnimationFrame(() => {
      const batch = Object.fromEntries(pendingPrices);
      pendingPrices.clear();
      frameId = null;

      set((state) => ({
        pricesBySymbol: {
          ...state.pricesBySymbol,
          ...batch
        }
      }));
    });
  }
}));

export const useSignalPrice = (symbol: string) =>
  usePriceStore((state) => state.pricesBySymbol[symbol] ?? null);
