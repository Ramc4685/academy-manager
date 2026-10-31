/**
 * Server-side read of `GET /api/v2/public/academy` for the root route, its
 * metadata, the OG card, robots and sitemap.
 *
 * Headers: only the visitor facts the backend needs are forwarded (Host as
 * `x-forwarded-host` for tenant resolution, `CF-Connecting-IP` for the
 * per-visitor rate limit, user agent, language, request id). They go through
 * the same `buildProxyHeaders` the BFF proxy uses, which stamps the
 * `x-cm-proxy-auth` shared secret so the backend trusts CF-Connecting-IP.
 * Cookies and bearer tokens are deliberately NOT forwarded: this read is
 * anonymous even for a signed-in visitor.
 *
 * Caching: `cache: "no-store"`. The backend URL is the same for every host,
 * so Next's data cache (keyed by URL) would hand one academy's page to
 * another academy's visitors. The backend's own 60s `Vary: Host` cache is the
 * only cache.
 */

import { cache } from "react";
import { headers } from "next/headers";

import { buildProxyHeaders } from "@/lib/api/proxy-headers";
import { resolveBffApiOrigin } from "@/lib/api/proxy-origin";

import { isPlatformProductHost, siteOrigin } from "./host";
import { classifyPublicAcademyResponse } from "./page-model";
import type { PublicPageResult } from "./types";

export const PUBLIC_ACADEMY_PATH = "/api/v2/public/academy";
const FETCH_TIMEOUT_MS = 5_000;

/** Inbound headers the anonymous read may carry to the backend. */
export const PUBLIC_FORWARDED_HEADERS = [
  "host",
  "cf-connecting-ip",
  "user-agent",
  "accept-language",
  "x-request-id",
] as const;

export function buildPublicAcademyRequestHeaders(inbound: Headers, protocol: string): Headers {
  const minimal = new Headers();
  for (const name of PUBLIC_FORWARDED_HEADERS) {
    const value = inbound.get(name);
    if (value) minimal.set(name, value);
  }
  const outbound = buildProxyHeaders(minimal, protocol);
  outbound.set("accept", "application/json");
  return outbound;
}

export interface PublicRequestContext {
  host: string;
  origin: string;
  result: PublicPageResult;
}

async function load(): Promise<PublicRequestContext> {
  const inbound = await headers();
  const host = inbound.get("host") ?? "";
  const origin = siteOrigin(host, process.env.NODE_ENV);
  if (isPlatformProductHost(host, process.env)) {
    return { host, origin, result: { kind: "platform" } };
  }
  const protocol = process.env.NODE_ENV === "production" ? "https:" : "http:";
  const target = new URL(PUBLIC_ACADEMY_PATH, resolveBffApiOrigin(process.env));
  try {
    const response = await fetch(target, {
      method: "GET",
      headers: buildPublicAcademyRequestHeaders(new Headers(inbound), protocol),
      cache: "no-store",
      redirect: "manual",
      signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
    });
    let body: unknown = null;
    if (response.status === 200) {
      try {
        body = await response.json();
      } catch {
        body = null;
      }
    }
    return { host, origin, result: classifyPublicAcademyResponse(response.status, body) };
  } catch {
    return { host, origin, result: { kind: "unavailable" } };
  }
}

/** One backend read per request, shared by the page and `generateMetadata`. */
export const loadPublicAcademyPage = cache(load);
