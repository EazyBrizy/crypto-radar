"use client";

import { Languages } from "lucide-react";

import { LOCALE_OPTIONS, type Locale } from "./locale";
import { useI18n } from "./I18nProvider";

export function LocaleSwitcher() {
  const { locale, setLocale } = useI18n();

  return (
    <label className="locale-switcher" title="Language">
      <Languages size={15} />
      <select
        aria-label="Language"
        onChange={(event) => setLocale(event.target.value as Locale)}
        value={locale}
      >
        {LOCALE_OPTIONS.map((option) => (
          <option key={option.code} value={option.code}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}
