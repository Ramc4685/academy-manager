/**
 * Base API client.
 *
 * Per-persona typed clients (lib/api/admin.ts, coach.ts, parent.ts) are thin
 * wrappers over this. Wave 1A wires those up against generated types from
 * lib/api/generated/v2.d.ts.
 */

import { getIdToken } from "@/lib/auth/firebase";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "/api/v2";

const inflight = new Map<string, Promise<Response>>();

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
  }
  return err;
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit & { dedup?: boolean } = {}
): Promise<T> {
  const url = path.startsWith("http") ? path : `${API_BASE}${path}`;
  const token = await getIdToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  headers.set("Accept", "application/json");
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  // Dedup identical in-flight GETs (or anything else if explicitly requested).
  const isReadable = init.method === "GET" || init.method === undefined;
  const shouldDedup = init.dedup ?? isReadable;
  const dedupKey = shouldDedup ? `${init.method ?? "GET"} ${url}` : null;
  if (dedupKey && inflight.has(dedupKey)) {
    const r = await inflight.get(dedupKey)!;
    return parseResponse<T>(r.clone());
  }

  const promise = fetch(url, { ...init, headers });
  if (dedupKey) inflight.set(dedupKey, promise);
  try {
    const res = await promise;
    return await parseResponse<T>(res);
  } finally {
    if (dedupKey) inflight.delete(dedupKey);
  }
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
