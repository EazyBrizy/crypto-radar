import createClient from "openapi-fetch";

import type { paths } from "./generated/openapi-types";

export const API_BASE = process.env.NEXT_PUBLIC_FASTAPI_HTTP_URL ?? "http://127.0.0.1:8000";
export const API_ORIGIN_LABEL = API_BASE;
export const API_TIMEOUT_MS = Number(process.env.NEXT_PUBLIC_FASTAPI_TIMEOUT_MS ?? 8_000);

export const openApiClient = createClient<paths>({
  baseUrl: API_BASE,
  fetch: apiFetch
});

type ApiResult<T> = {
  data?: T;
  error?: unknown;
  response: Response;
};

export async function request<T>(operation: () => Promise<ApiResult<T>>): Promise<T> {
  try {
    return unwrap(await operation());
  } catch (exc) {
    throw normalizeApiError(exc);
  }
}

async function unwrap<T>(result: ApiResult<T>): Promise<T> {
  if (result.error || !result.response.ok) {
    const detail = getErrorDetail(result.error);
    throw new Error(detail ?? `API error ${result.response.status}`);
  }

  if (result.data === undefined) {
    throw new Error("API returned an empty response");
  }

  return result.data;
}

function getErrorDetail(error: unknown): string | null {
  if (!error || typeof error !== "object") return null;
  if ("message" in error && typeof error.message === "string") return error.message;
  if (!("detail" in error)) return null;
  if (typeof error.detail === "string") return error.detail;
  if (error.detail && typeof error.detail === "object" && "message" in error.detail) {
    return typeof error.detail.message === "string" ? error.detail.message : null;
  }
  return null;
}

function normalizeApiError(exc: unknown): Error {
  if (isAbortError(exc)) {
    return new Error(`FastAPI request timed out after ${API_TIMEOUT_MS}ms at ${API_BASE}.`);
  }

  if (isNetworkError(exc)) {
    return new Error(`FastAPI недоступен по адресу ${API_BASE}. Запустите backend и повторите действие.`);
  }

  return exc instanceof Error ? exc : new Error("Не удалось выполнить запрос к API");
}

function isNetworkError(exc: unknown): boolean {
  return exc instanceof TypeError && /fetch|network|load failed/i.test(exc.message);
}

async function apiFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const controller = new AbortController();
  const timeout = globalThis.setTimeout(() => controller.abort(), API_TIMEOUT_MS);
  const upstreamSignal = init.signal;

  if (upstreamSignal) {
    if (upstreamSignal.aborted) controller.abort();
    upstreamSignal.addEventListener("abort", () => controller.abort(), { once: true });
  }

  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } finally {
    globalThis.clearTimeout(timeout);
  }
}

function isAbortError(exc: unknown): boolean {
  return exc instanceof DOMException && exc.name === "AbortError";
}
