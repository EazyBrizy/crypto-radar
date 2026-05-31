"use client";

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { DomLocalizer } from "./DomLocalizer";
import { translateText } from "./dictionary";
import { DEFAULT_LOCALE, detectLocale, LOCALE_STORAGE_KEY, normalizeLocale, type Locale } from "./locale";

interface I18nContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (value: string) => string;
}

const I18nContext = createContext<I18nContextValue | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(() => readInitialLocale());

  useEffect(() => {
    document.documentElement.lang = locale;
    document.documentElement.dir = "ltr";
  }, [locale]);

  const value = useMemo<I18nContextValue>(() => ({
    locale,
    setLocale: (nextLocale) => {
      try {
        window.localStorage.setItem(LOCALE_STORAGE_KEY, nextLocale);
      } catch {
        // Locale switching should still work if storage is unavailable.
      }
      setLocaleState(nextLocale);
    },
    t: (text) => translateText(text, locale)
  }), [locale]);

  return (
    <I18nContext.Provider value={value}>
      <DomLocalizer locale={locale} />
      {children}
    </I18nContext.Provider>
  );
}

export function useI18n(): I18nContextValue {
  const value = useContext(I18nContext);
  if (!value) throw new Error("useI18n must be used within I18nProvider");
  return value;
}

function readInitialLocale(): Locale {
  if (typeof window === "undefined") return DEFAULT_LOCALE;

  try {
    const storedLocale = normalizeLocale(window.localStorage.getItem(LOCALE_STORAGE_KEY));
    return storedLocale ?? detectLocale(window.navigator.languages);
  } catch {
    return detectLocale(window.navigator.languages);
  }
}
