/**
 * Base API client.
 *
 * Per-persona typed clients (lib/api/admin.ts, coach.ts, parent.ts) are thin
 * wrappers over this. Wave 1A wires those up against generated types from
 * lib/api/generated/v2.d.ts.
 */

import { getIdToken } from "@/lib/auth/firebase";
import { setBffIdentityCookie } from "@/lib/api/auth-bridge-cookie";
import { resolveApiAuthToken } from "@/lib/api/auth-token";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "/api/v2";
const BFF_IDENTITY_HEADER = "X-CourtMastr-Identity";

const inflight = new Map<string, Promise<Response>>();

/**
 * Browser-side active-academy cache.
 *
 * In production the tenant is resolved on the backend from
 * subdomain/custom-domain (ADR-0007). For local development, admin
 * impersonation, and the academy switcher we attach the user's
 * selected academy id as `X-Academy-Id`. The header is accepted only
 * when the request originates from an approved internal source — the
 * resolver still falls back to subdomain otherwise.
 */
const ACTIVE_ACADEMY_KEY = "am.activeAcademy";

export function setActiveAcademyId(academyId: string | null): void {
  if (typeof window === "undefined") return;
  if (academyId) {
    window.localStorage.setItem(ACTIVE_ACADEMY_KEY, academyId);
  } else {
    window.localStorage.removeItem(ACTIVE_ACADEMY_KEY);
  }
}

export function getActiveAcademyId(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(ACTIVE_ACADEMY_KEY);
}

export interface ApiError extends Error {
  status: number;
  code?: string;
  details?: Record<string, unknown>;
}

function makeError(status: number, body: unknown): ApiError {
  const err = new Error(typeof body === "string" ? body : "Request failed") as ApiError;
  err.status = status;
  if (typeof body === "object" && body !== null && "error" in body) {
    const e = (body as { error: { code?: string; message?: string; details?: Record<string, unknown> } })
      .error;
    err.code = e.code;
    err.message = e.message ?? err.message;
    err.details = e.details;
  } else if (typeof body === "object" && body !== null && "detail" in body) {
    // FastAPI raises HTTPException with a `detail` payload. Surface it so the
    // real reason (e.g. "no saved card") reaches the UI instead of the generic
    // "Request failed" fallback.
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail) err.message = detail;
  }
  return err;
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit & { dedup?: boolean; authToken?: string | null } = {}
): Promise<T> {
  const usesSameOriginBff = !path.startsWith("http");
  const url = path.startsWith("http") ? path : `${API_BASE}${path}`;
  const { authToken, dedup, ...requestInit } = init;
  const token = await resolveApiAuthToken(authToken, getIdToken);
  const headers = new Headers(init.headers);
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
    if (usesSameOriginBff) {
      headers.set(BFF_IDENTITY_HEADER, token);
      setBffIdentityCookie(token);
    }
  }
  headers.set("Accept", "application/json");
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (!headers.has("X-Academy-Id")) {
    const activeAcademy = getActiveAcademyId();
    if (activeAcademy) headers.set("X-Academy-Id", activeAcademy);
  }

  // Dedup identical in-flight GETs (or anything else if explicitly requested).
  const isReadable = requestInit.method === "GET" || requestInit.method === undefined;
  const shouldDedup = dedup ?? isReadable;
  const dedupKey = shouldDedup ? `${requestInit.method ?? "GET"} ${url}` : null;
  if (dedupKey && inflight.has(dedupKey)) {
    const r = await inflight.get(dedupKey)!;
    return parseResponse<T>(r.clone());
  }

  // Abort hung requests after 20 s so loading states surface as errors
  // instead of spinning forever when the backend is slow to respond.
  const controller = new AbortController();
  const abortTimer = setTimeout(() => controller.abort(), 20_000);
  const promise = fetch(url, { ...requestInit, headers, signal: controller.signal });
  if (dedupKey) inflight.set(dedupKey, promise);
  try {
    const res = await promise;
    return await parseResponse<T>(res);
  } finally {
    clearTimeout(abortTimer);
    if (dedupKey) inflight.delete(dedupKey);
  }
}

/**
 * Authenticated fetch for binary downloads (xlsx, pdf).
 *
 * Same auth/tenant headers as `apiFetch`, but returns the raw Blob
 * instead of parsing JSON — `parseResponse` would corrupt binary
 * bodies by reading them as text.
 */
export async function apiFetchBlob(
  path: string,
  init: RequestInit & { authToken?: string | null } = {}
): Promise<Blob> {
  const usesSameOriginBff = !path.startsWith("http");
  const url = path.startsWith("http") ? path : `${API_BASE}${path}`;
  const { authToken, ...requestInit } = init;
  const token = await resolveApiAuthToken(authToken, getIdToken);
  const headers = new Headers(init.headers);
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
    if (usesSameOriginBff) {
      headers.set(BFF_IDENTITY_HEADER, token);
      setBffIdentityCookie(token);
    }
  }
  if (!headers.has("X-Academy-Id")) {
    const activeAcademy = getActiveAcademyId();
    if (activeAcademy) headers.set("X-Academy-Id", activeAcademy);
  }
  const res = await fetch(url, { ...requestInit, headers });
  if (!res.ok) {
    const contentType = res.headers.get("content-type") ?? "";
    const body = contentType.includes("application/json") ? await res.json() : await res.text();
    throw makeError(res.status, body);
  }
  return res.blob();
}

async function parseResponse<T>(res: Response): Promise<T> {
  const contentType = res.headers.get("content-type") ?? "";
  // 204 No Content (and any empty-body response) must not be passed to
  // res.json() — that throws SyntaxError on an empty string. Treat
  // empty bodies as null, which is what callers expect for mutations
  // that don't return a payload (pause/resume/cancel/refund, etc.).
  const isEmpty = res.status === 204 || res.headers.get("content-length") === "0";
  let body: unknown = null;
  if (!isEmpty) {
    body = contentType.includes("application/json") ? await res.json() : await res.text();
  }
  if (!res.ok) throw makeError(res.status, body);
  return body as T;
}
