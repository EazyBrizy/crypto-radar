import createClient from "openapi-fetch";

import type { paths } from "./generated/openapi-types";

export const API_BASE = process.env.NEXT_PUBLIC_FASTAPI_HTTP_URL ?? "http://127.0.0.1:8000";
export const API_ORIGIN_LABEL = API_BASE;
export const API_TIMEOUT_MS = Number(process.env.NEXT_PUBLIC_FASTAPI_TIMEOUT_MS ?? 8_000);
const DEV_SLOW_REQUEST_MS = 1_500;

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

export async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  try {
    const headers = new Headers(init.headers);
    if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    const response = await apiFetch(`${API_BASE}${path}`, {
      ...init,
      headers
    });
    if (!response.ok) {
      throw new Error(await responseErrorDetail(response));
    }
    return await response.json() as T;
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

async function responseErrorDetail(response: Response): Promise<string> {
  try {
    const payload = await response.json();
    const detail = getErrorDetail(payload);
    return detail ?? `API error ${response.status}`;
  } catch {
    return `API error ${response.status}`;
  }
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

export type ApiRequestDescriptor = {
  apiBase: string;
  method: string;
  path: string;
};

export function describeApiRequest(input: RequestInfo | URL, init: RequestInit = {}): ApiRequestDescriptor {
  const request = isRequest(input) ? input : null;
  const method = String(init.method ?? request?.method ?? "GET").toUpperCase();
  const rawUrl = request?.url ?? String(input);
  const apiBase = normalizedApiBase();

  try {
    const url = new URL(rawUrl, apiBase);
    const query = sanitizeSearchParams(url.searchParams);
    return {
      apiBase,
      method,
      path: `${url.pathname}${query ? `?${query}` : ""}`
    };
  } catch {
    return {
      apiBase,
      method,
      path: rawUrl
    };
  }
}

export function formatApiTimeoutMessage(request: ApiRequestDescriptor): string {
  return `FastAPI request timed out after ${API_TIMEOUT_MS}ms: ${request.method} ${request.path} at ${request.apiBase}.`;
}

export function formatApiNetworkErrorMessage(request: ApiRequestDescriptor): string {
  return `FastAPI network error: ${request.method} ${request.path} at ${request.apiBase}. Check that the backend is running.`;
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

export async function apiFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const request = describeApiRequest(input, init);
  const requestInput = isRequest(input) ? input : null;
  const startedAt = nowMs();
  const controller = new AbortController();
  const timeout = globalThis.setTimeout(() => controller.abort(), API_TIMEOUT_MS);
  const upstreamSignal = init.signal ?? requestInput?.signal;
  const abortFromUpstream = () => controller.abort();

  if (upstreamSignal) {
    if (upstreamSignal.aborted) controller.abort();
    upstreamSignal.addEventListener("abort", abortFromUpstream, { once: true });
  }

  let response: Response | null = null;
  try {
    response = await fetch(input, {
      ...init,
      credentials: init.credentials ?? "include",
      signal: controller.signal
    });
    return response;
  } catch (exc) {
    if (isAbortError(exc)) {
      throw new Error(formatApiTimeoutMessage(request));
    }
    if (isNetworkError(exc)) {
      throw new Error(formatApiNetworkErrorMessage(request));
    }
    throw exc;
  } finally {
    globalThis.clearTimeout(timeout);
    upstreamSignal?.removeEventListener("abort", abortFromUpstream);
    warnIfSlowRequest(request, nowMs() - startedAt, response?.status);
  }
}

function isAbortError(exc: unknown): boolean {
  return (typeof DOMException !== "undefined" && exc instanceof DOMException && exc.name === "AbortError")
    || (exc instanceof Error && exc.name === "AbortError");
}

function isRequest(input: RequestInfo | URL): input is Request {
  return typeof Request !== "undefined" && input instanceof Request;
}

function normalizedApiBase(): string {
  return API_BASE.replace(/\/+$/, "") || API_BASE;
}

function sanitizeSearchParams(params: URLSearchParams): string {
  const sanitized = new URLSearchParams();
  params.forEach((value, key) => {
    sanitized.append(key, isSensitiveSearchParam(key) ? "redacted" : value);
  });
  return sanitized.toString();
}

function isSensitiveSearchParam(key: string): boolean {
  const normalized = key.trim().toLowerCase().replace(/[\s.-]+/g, "_");
  return normalized === "api_key"
    || normalized === "apikey"
    || normalized === "key"
    || normalized === "token"
    || normalized === "auth"
    || normalized === "authorization"
    || normalized === "cookie"
    || normalized === "session"
    || normalized === "sig"
    || normalized.includes("token")
    || normalized.includes("secret")
    || normalized.includes("password")
    || normalized.includes("passwd")
    || normalized.includes("credential")
    || normalized.includes("signature")
    || normalized.includes("private_key");
}

function warnIfSlowRequest(request: ApiRequestDescriptor, durationMs: number, status?: number): void {
  if (typeof process === "undefined" || process.env.NODE_ENV !== "development" || durationMs <= DEV_SLOW_REQUEST_MS) return;
  console.warn("Slow FastAPI request", {
    apiBase: request.apiBase,
    durationMs: Math.round(durationMs),
    method: request.method,
    path: request.path,
    status: status ?? "error"
  });
}

function nowMs(): number {
  return globalThis.performance?.now() ?? Date.now();
}
