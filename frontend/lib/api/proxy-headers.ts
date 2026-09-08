const BFF_IDENTITY_HEADER = "x-courtmastr-identity";
const BACKEND_AUTH_HEADER = "x-courtmastr-auth";
const BFF_IDENTITY_COOKIE = "__cm_identity";
const PROXY_AUTH_HEADER = "x-cm-proxy-auth";
export const REQUEST_ID_HEADER = "x-request-id";

// Mirrors the backend's request-id validator (shared/observability/
// request_context.py): anything else is replaced so forged junk never reaches
// the logs or Sentry tags.
const REQUEST_ID_PATTERN = /^[A-Za-z0-9._-]{1,128}$/;

const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

export function buildProxyHeaders(requestHeaders: Headers, protocol: string): Headers {
  const headers = new Headers(requestHeaders);
  const host = requestHeaders.get("host");

  if (host) {
    headers.set("x-forwarded-host", host);
  }
  // Always overwrite proto from server context — never trust inbound value.
  headers.set("x-forwarded-proto", protocol.replace(":", ""));

  const bridgedAuth =
    headers.get(BFF_IDENTITY_HEADER) ??
    headers.get(BACKEND_AUTH_HEADER) ??
    readCookie(headers.get("cookie"), BFF_IDENTITY_COOKIE);
  if (bridgedAuth) {
    const bearer = normalizeBearer(bridgedAuth);
    if (!headers.has("authorization")) {
      headers.set("authorization", bearer);
    }
    headers.set(BACKEND_AUTH_HEADER, bearer);
  }

  headers.delete(BFF_IDENTITY_HEADER);
  stripCookie(headers, BFF_IDENTITY_COOKIE);
  headers.delete("host");

  // One request id for browser -> worker -> backend. Keep a valid inbound id
  // (a retry or an upstream proxy may already have stamped one); mint one
  // otherwise so the backend echo and the error toast share a reference.
  ensureRequestId(headers);

  // Never forward a client-supplied proxy-auth header; only the server-held
  // secret may vouch for CF-Connecting-IP to the backend rate limiter.
  headers.delete(PROXY_AUTH_HEADER);
  const proxySecret = process.env.BFF_PROXY_SHARED_SECRET;
  if (proxySecret) {
    headers.set(PROXY_AUTH_HEADER, proxySecret);
  }
  return headers;
}

export function buildProxyResponseHeaders(
  upstreamHeaders: Headers,
  requestId?: string | null
): Headers {
  const headers = new Headers(upstreamHeaders);
  for (const header of HOP_BY_HOP_HEADERS) {
    headers.delete(header);
  }
  // The backend echoes X-Request-ID; if it did not (e.g. an edge 502 before
  // the app saw the request) fall back to the id we sent so the browser
  // always gets one to show as a reference.
  if (!isValidRequestId(headers.get(REQUEST_ID_HEADER)) && isValidRequestId(requestId)) {
    headers.set(REQUEST_ID_HEADER, requestId as string);
  }
  return headers;
}

export function isValidRequestId(value: string | null | undefined): value is string {
  return typeof value === "string" && REQUEST_ID_PATTERN.test(value);
}

function ensureRequestId(headers: Headers): string {
  const inbound = headers.get(REQUEST_ID_HEADER);
  if (isValidRequestId(inbound)) return inbound;
  const minted = crypto.randomUUID();
  headers.set(REQUEST_ID_HEADER, minted);
  return minted;
}

function normalizeBearer(value: string): string {
  const trimmed = value.trim();
  return trimmed.toLowerCase().startsWith("bearer ") ? trimmed : `Bearer ${trimmed}`;
}

function readCookie(cookieHeader: string | null, name: string): string | null {
  if (!cookieHeader) return null;
  for (const part of cookieHeader.split(";")) {
    const [rawName, ...rawValue] = part.trim().split("=");
    if (rawName === name) {
      try {
        return decodeURIComponent(rawValue.join("="));
      } catch {
        return null;
      }
    }
  }
  return null;
}

function stripCookie(headers: Headers, name: string): void {
  const cookieHeader = headers.get("cookie");
  if (!cookieHeader) return;
  const remaining = cookieHeader
    .split(";")
    .map((part) => part.trim())
    .filter((part) => part && part.split("=", 1)[0] !== name);
  if (remaining.length === 0) {
    headers.delete("cookie");
    return;
  }
  headers.set("cookie", remaining.join("; "));
}
