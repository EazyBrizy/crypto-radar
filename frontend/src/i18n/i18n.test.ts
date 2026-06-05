import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

import { detectLocale, normalizeLocale, normalizeReasonCode, REASON_CODE_KEYS, translateReasonCode, translateText } from "@/i18n";

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

  it("normalizes Radar details labels in Russian", () => {
    expect(translateText("Waiting Entry", "ru")).toBe("Ждём вход");
    expect(translateText("Cancel waiting", "ru")).toBe("Отменить ожидание");
    expect(translateText("Paper Trade", "ru")).toBe("Виртуальная сделка");
    expect(translateText("Open exchange", "ru")).toBe("Открыть биржу");
    expect(translateText("Risk blockers / warnings", "ru")).toBe("Блокеры и предупреждения");
    expect(translateText("Decision Snapshot", "ru")).toBe("Диагностика решения");
    expect(translateText("Edge Snapshot", "ru")).toBe("Статистика преимущества");
    expect(translateText("Trade Plan", "ru")).toBe("План сделки");
    expect(translateText("Risk / Reward Guard", "ru")).toBe("Проверка RR");
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

  it("has RU and EN translations for every typed reason code", () => {
    for (const code of REASON_CODE_KEYS) {
      expect(normalizeReasonCode(code), code).toBe(code);
      for (const locale of ["ru", "en"] as const) {
        const translated = translateReasonCode(code, locale);
        expect(translated.trim(), `${locale}:${code}`).not.toBe("");
        expect(translated, `${locale}:${code}`).not.toBe(code);
      }
    }
  });

  it("covers backend known reason codes in the frontend dictionary", () => {
    const repoRoot = path.resolve(process.cwd(), "..");
    const source = fs.readFileSync(path.join(repoRoot, "backend/app/services/reason_codes.py"), "utf8");
    const backendCodes = Array.from(source.matchAll(/"([a-z][a-z0-9_]+)"/g), (match) => match[1])
      .filter((code) => code.includes("_") || REASON_CODE_KEYS.includes(code as (typeof REASON_CODE_KEYS)[number]));
    for (const code of new Set(backendCodes)) {
      expect(normalizeReasonCode(code), code).toBe(code);
    }
  });

  it("rejects raw JSX text on localized app surfaces", () => {
    const files = [
      "src/components/SignalDetails.tsx",
      "src/components/SignalFeed.tsx",
      "src/components/TradeRow.tsx",
      "src/components/data-table/TradeJournalTable.tsx",
      "src/features/app-shell/ActiveTradeChart.tsx",
      "src/features/app-shell/RadarPage.tsx",
      "src/features/app-shell/SettingsPage.tsx",
      "src/features/app-shell/TradesPage.tsx",
      "src/features/app-shell/WatchlistPage.tsx"
    ];
    const violations = files.flatMap((file) => rawJsxTextViolations(path.join(process.cwd(), file), file));
    expect(violations).toEqual([]);
  });
});

function rawJsxTextViolations(filePath: string, label: string): string[] {
  const source = fs.readFileSync(filePath, "utf8");
  const ast = ts.createSourceFile(filePath, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const violations: string[] = [];

  function visit(node: ts.Node): void {
    if (ts.isJsxText(node)) {
      const text = normalizeJsxText(node.getText());
      if (text && !rawJsxWhitelist(text)) {
        const pos = ast.getLineAndCharacterOfPosition(node.getStart(ast));
        violations.push(`${label}:${pos.line + 1} "${text}"`);
      }
    }
    if (ts.isJsxExpression(node) && node.expression && ts.isStringLiteralLike(node.expression)) {
      const text = normalizeJsxText(node.expression.text);
      if (text && !rawJsxWhitelist(text)) {
        const pos = ast.getLineAndCharacterOfPosition(node.expression.getStart(ast));
        violations.push(`${label}:${pos.line + 1} "${text}"`);
      }
    }
    ts.forEachChild(node, visit);
  }

  visit(ast);
  return violations;
}

function normalizeJsxText(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function rawJsxWhitelist(value: string): boolean {
  return (
    value === "|" ||
    value === "/" ||
    value === "-" ||
    value === "PnL" ||
    value === "run" ||
    value === "/ U" ||
    value === "x" ||
    /^[A-Z0-9.$:%/+_-]+$/u.test(value) ||
    /^\$[0-9.,]+$/u.test(value)
  );
}
