export type Locale = "ru" | "en" | "zh";

export const DEFAULT_LOCALE: Locale = "ru";
export const LOCALE_STORAGE_KEY = "crypto-radar:locale";

export const LOCALE_OPTIONS: Array<{
  code: Locale;
  label: string;
  nativeName: string;
}> = [
  { code: "ru", label: "RU", nativeName: "Русский" },
  { code: "en", label: "EN", nativeName: "English" },
  { code: "zh", label: "中文", nativeName: "中文" }
];

export function normalizeLocale(value: string | null | undefined): Locale | null {
  if (!value) return null;
  const normalized = value.trim().toLowerCase();
  if (!normalized) return null;
  if (normalized === "zh" || normalized.startsWith("zh-") || normalized.startsWith("zh_")) return "zh";
  if (normalized === "ru" || normalized.startsWith("ru-") || normalized.startsWith("ru_")) return "ru";
  if (normalized === "en" || normalized.startsWith("en-") || normalized.startsWith("en_")) return "en";
  return null;
}

export function detectLocale(languages: readonly string[] | undefined | null): Locale {
  for (const language of languages ?? []) {
    const locale = normalizeLocale(language);
    if (locale) return locale;
  }
  return DEFAULT_LOCALE;
}
