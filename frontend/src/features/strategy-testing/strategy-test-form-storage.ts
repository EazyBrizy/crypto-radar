import type {
  StrategyTestMode,
  StrategyTestSameCandlePolicy,
  StrategyTestType
} from "./types";

export const STRATEGY_TEST_FORM_STORAGE_KEY = "crypto-radar:strategy-testing-panel:v1";

export interface StoredStrategyTestForm {
  selectedStrategyCodes?: string[];
  selectedPairIds?: string[];
  selectedTimeframes?: string[];
  mode?: StrategyTestMode;
  testType?: StrategyTestType;
  startAt?: string;
  endAt?: string;
  initialCapital?: string;
  feeRate?: string;
  slippageBps?: string;
  sameCandlePolicy?: StrategyTestSameCandlePolicy;
  historicalPendingEntriesEnabled?: boolean;
  pendingEntryMaxWaitBars?: string;
}

const MODES = new Set<StrategyTestMode>(["discovery", "research_virtual", "production_like"]);
const TEST_TYPES = new Set<StrategyTestType>(["historical_backtest", "forward_virtual"]);
const SAME_CANDLE_POLICIES = new Set<StrategyTestSameCandlePolicy>([
  "conservative_stop_first",
  "ignore_ambiguous",
  "intrabar_unknown",
  "stop_first",
  "target_first"
]);

export function strategyTestFormStorageKey(userId: string | null | undefined): string {
  const normalizedUserId = typeof userId === "string" ? userId.trim() : "";
  return normalizedUserId ? `${STRATEGY_TEST_FORM_STORAGE_KEY}:${normalizedUserId}` : STRATEGY_TEST_FORM_STORAGE_KEY;
}

export function readStrategyTestForm(key: string): StoredStrategyTestForm | null {
  const storage = browserLocalStorage();
  if (!storage) return null;
  const raw = storage.getItem(key);
  if (!raw) return null;

  try {
    const parsed = JSON.parse(raw) as unknown;
    return coerceStoredStrategyTestForm(parsed);
  } catch {
    return null;
  }
}

export function saveStrategyTestForm(key: string, form: Required<StoredStrategyTestForm>): void {
  const storage = browserLocalStorage();
  if (!storage) return;

  try {
    storage.setItem(key, JSON.stringify(form));
  } catch {
    return;
  }
}

export function clearStrategyTestForm(key: string): void {
  const storage = browserLocalStorage();
  if (!storage) return;

  try {
    storage.removeItem(key);
  } catch {
    return;
  }
}

function coerceStoredStrategyTestForm(value: unknown): StoredStrategyTestForm | null {
  if (!isRecord(value)) return null;

  const form: StoredStrategyTestForm = {};
  const selectedStrategyCodes = readStringArray(value.selectedStrategyCodes);
  if (selectedStrategyCodes) form.selectedStrategyCodes = selectedStrategyCodes;
  const selectedPairIds = readStringArray(value.selectedPairIds);
  if (selectedPairIds) form.selectedPairIds = selectedPairIds;
  const selectedTimeframes = readStringArray(value.selectedTimeframes);
  if (selectedTimeframes) form.selectedTimeframes = selectedTimeframes;
  if (isMode(value.mode)) form.mode = value.mode;
  if (isTestType(value.testType)) form.testType = value.testType;
  if (typeof value.startAt === "string") form.startAt = value.startAt;
  if (typeof value.endAt === "string") form.endAt = value.endAt;
  if (typeof value.initialCapital === "string") form.initialCapital = value.initialCapital;
  if (typeof value.feeRate === "string") form.feeRate = value.feeRate;
  if (typeof value.slippageBps === "string") form.slippageBps = value.slippageBps;
  if (isSameCandlePolicy(value.sameCandlePolicy)) form.sameCandlePolicy = value.sameCandlePolicy;
  if (typeof value.historicalPendingEntriesEnabled === "boolean") {
    form.historicalPendingEntriesEnabled = value.historicalPendingEntriesEnabled;
  }
  if (typeof value.pendingEntryMaxWaitBars === "string") {
    form.pendingEntryMaxWaitBars = value.pendingEntryMaxWaitBars;
  }

  return form;
}

function readStringArray(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null;
  return value.filter((item): item is string => typeof item === "string" && item.trim().length > 0);
}

function isMode(value: unknown): value is StrategyTestMode {
  return typeof value === "string" && MODES.has(value as StrategyTestMode);
}

function isTestType(value: unknown): value is StrategyTestType {
  return typeof value === "string" && TEST_TYPES.has(value as StrategyTestType);
}

function isSameCandlePolicy(value: unknown): value is StrategyTestSameCandlePolicy {
  return typeof value === "string" && SAME_CANDLE_POLICIES.has(value as StrategyTestSameCandlePolicy);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function browserLocalStorage(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}
