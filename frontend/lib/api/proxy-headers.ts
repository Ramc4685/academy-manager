const BFF_IDENTITY_HEADER = "x-courtmastr-identity";
const BACKEND_AUTH_HEADER = "x-courtmastr-auth";
const BFF_IDENTITY_COOKIE = "__cm_identity";

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

  if (host && !headers.has("x-forwarded-host")) {
    headers.set("x-forwarded-host", host);
  }
  if (!headers.has("x-forwarded-proto")) {
    headers.set("x-forwarded-proto", protocol.replace(":", ""));
  }

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
  return headers;
}

export function buildProxyResponseHeaders(upstreamHeaders: Headers): Headers {
  const headers = new Headers(upstreamHeaders);
  for (const header of HOP_BY_HOP_HEADERS) {
    headers.delete(header);
  }
  return headers;
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
      return decodeURIComponent(rawValue.join("="));
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
