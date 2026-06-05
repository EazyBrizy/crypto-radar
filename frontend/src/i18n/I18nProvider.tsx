"use client";

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { DomLocalizer } from "./DomLocalizer";
import { translateKey, translateReasonCode, translateText, type I18nKey } from "./dictionary";
import { DEFAULT_LOCALE, detectLocale, LOCALE_STORAGE_KEY, normalizeLocale, type Locale } from "./locale";

interface I18nContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (value: string) => string;
  tKey: (key: I18nKey, params?: Record<string, string | number | boolean | null | undefined>) => string;
  tReason: (code: string | null | undefined, params?: Record<string, string | number | boolean | null | undefined>) => string;
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
    t: (text) => translateText(text, locale),
    tKey: (key, params) => translateKey(key, locale, params),
    tReason: (code, params) => translateReasonCode(code, locale, params)
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
  return value ?? fallbackContext();
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

function fallbackContext(): I18nContextValue {
  const locale = typeof window === "undefined" ? DEFAULT_LOCALE : detectLocale(window.navigator.languages);
  return {
    locale,
    setLocale: () => undefined,
    t: (text) => translateText(text, locale),
    tKey: (key, params) => translateKey(key, locale, params),
    tReason: (code, params) => translateReasonCode(code, locale, params)
  };
}
