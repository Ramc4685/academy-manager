/// <reference lib="webworker" />
/**
 * Service worker entry, compiled by @serwist/next.
 *
 * Wave 1A cache strategies:
 * - `GET /api/v2/coach/today*` → stale-while-revalidate (24h)
 * - `POST /api/v2/coach/attendance` → network-only (Wave 1A: no queueing)
 * - other `/api/*` calls → network-only; auth-scoped responses must not be cached
 * - static / icons / manifest → cache-first
 * - everything else → defaults from @serwist/next
 *
 * The mutation queue and background-sync replay are Wave 1B; do not add
 * them here until 1A holds 1 week in production.
 */

import { defaultCache } from "@serwist/next/worker";
import {
  Serwist,
  StaleWhileRevalidate,
  NetworkOnly,
  CacheFirst,
  ExpirationPlugin,
  type PrecacheEntry,
} from "serwist";

declare global {
  interface WorkerGlobalScope {
    __SW_MANIFEST: (PrecacheEntry | string)[] | undefined;
  }
}

declare const self: ServiceWorkerGlobalScope & typeof globalThis;

const COACH_API = /\/api\/v2\/coach\/(today|sessions)/;
const COACH_WRITE = /\/api\/v2\/coach\/attendance/;
// Child progress notes are never cached on the device (they are kept out of
// localStorage for the same reason); they fall through to NetworkOnly.
const COACH_PRIVATE = /\/progress-notes/;
const STATIC = /\.(?:js|css|woff2?|svg|png|jpg|jpeg|webp|avif|ico)$/;
const MANIFEST = /manifest\.webmanifest$/;
const CLOUDFLARE_INSIGHTS_HOST = "static.cloudflareinsights.com";

const networkOnlyQuiet = {
  async handle({ request }: { request: Request }): Promise<Response> {
    try {
      return await fetch(request);
    } catch {
      return Response.error();
    }
  },
};

const optionalScriptQuiet = {
  async handle({ request }: { request: Request }): Promise<Response> {
    try {
      return await fetch(request);
    } catch {
      return new Response("", {
        status: 204,
        headers: { "Content-Type": "application/javascript; charset=utf-8" },
      });
    }
  },
};

const serwist = new Serwist({
  precacheEntries: self.__SW_MANIFEST,
  skipWaiting: false, // explicit user action — see lib/pwa/update-flow.ts
  clientsClaim: true,
  navigationPreload: true,
  runtimeCaching: [
    {
      matcher: ({ request, url }) =>
        request.method === "GET" &&
        url.hostname === CLOUDFLARE_INSIGHTS_HOST &&
        url.pathname.startsWith("/beacon.min.js"),
      handler: optionalScriptQuiet,
    },
    {
      // Firebase auth helper (proxied via next.config.ts rewrites). A
      // cached/stale response here breaks the OAuth redirect round-trip,
      // and the STATIC rule below would otherwise cache-first its JS.
      matcher: ({ url }) => url.pathname.startsWith("/__/auth"),
      handler: networkOnlyQuiet,
    },
    {
      matcher: ({ request, url }) =>
        request.method === "GET" &&
        COACH_API.test(url.pathname) &&
        !COACH_PRIVATE.test(url.pathname),
      handler: new StaleWhileRevalidate({
        cacheName: "coach-api-v1",
        plugins: [
          new ExpirationPlugin({
            maxEntries: 50,
            maxAgeSeconds: 24 * 60 * 60,
            purgeOnQuotaError: true,
          }),
        ],
      }),
    },
    {
      // Writes go straight to the network. Offline and failed marks are
      // queued by the page itself (lib/offline/queue.ts) and replayed by
      // lib/offline/sync.ts, which knows who queued them.
      matcher: ({ request, url }) =>
        request.method === "POST" && COACH_WRITE.test(url.pathname),
      handler: new NetworkOnly(),
    },
    {
      matcher: ({ url }) => url.pathname.startsWith("/api/"),
      handler: new NetworkOnly(),
    },
    {
      matcher: ({ request, url }) =>
        request.method === "GET" && (STATIC.test(url.pathname) || MANIFEST.test(url.pathname)),
      handler: new CacheFirst({
        cacheName: "static-v1",
        plugins: [
          new ExpirationPlugin({ maxEntries: 200, maxAgeSeconds: 30 * 24 * 60 * 60 }),
        ],
      }),
    },
    ...defaultCache,
  ],
});

self.addEventListener("message", (event) => {
  if (event.data?.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});

serwist.addEventListeners();
