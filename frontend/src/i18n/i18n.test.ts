import { describe, expect, it } from "vitest";

import { detectLocale, normalizeLocale, translateText } from "@/i18n";

describe("i18n locale helpers", () => {
  it("normalizes supported browser locales", () => {
    expect(normalizeLocale("ru-RU")).toBe("ru");
    expect(normalizeLocale("en-US")).toBe("en");
    expect(normalizeLocale("zh-CN")).toBe("zh");
    expect(normalizeLocale("de-DE")).toBeNull();
  });

  it("uses browser language priority with Russian fallback", () => {
    expect(detectLocale(["de-DE", "zh-CN", "en-US"])).toBe("zh");
    expect(detectLocale(["de-DE"])).toBe("ru");
  });

  it("translates exact and dynamic UI phrases", () => {
    expect(translateText("Market opportunities", "ru")).toBe("Рыночные возможности");
    expect(translateText("Risk: Balanced", "ru")).toBe("Риск: Сбалансированный");
    expect(translateText("Signals found: 12", "zh")).toBe("发现信号: 12");
  });

  it("keeps common tech status terms in Russian UI", () => {
    expect(translateText("Online", "ru")).toBe("Online");
    expect(translateText("Offline", "ru")).toBe("Offline");
    expect(translateText("On", "ru")).toBe("On");
    expect(translateText("Off", "ru")).toBe("Off");
    expect(translateText("Online · Connected", "ru")).toBe("Online · Connected");
    expect(translateText("Scanner offline", "ru")).toBe("Сканер Offline");
  });

  it("translates backend strategy and risk explanations", () => {
    expect(translateText("Recommended action", "ru")).toBe("Рекомендованное действие");
    expect(translateText("Status: Strategy setup exists, but confirmation is incomplete", "ru")).toBe(
      "Статус: Setup стратегии есть, но подтверждение неполное"
    );
    expect(translateText("Risk/reward passed: nearest target is 6.51R, minimum 1.50R", "ru")).toBe(
      "Риск/прибыль пройдены: ближайшая цель 6.51R, минимум 1.50R"
    );
    expect(translateText("regime alignment: long vs bearish context (strong)", "ru")).toBe(
      "Режим: LONG против контекста: медвежий (сильный)"
    );
    expect(translateText("Wick ratio 0% is below the sweep threshold", "ru")).toBe(
      "Доля фитиля 0% ниже порога sweep"
    );
    expect(translateText("Price is testing previous swing low; waiting for liquidity sweep and reclaim", "ru")).toBe(
      "Цена тестирует предыдущий swing low; ждём liquidity sweep и reclaim"
    );
  });
});
