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
const STATIC = /\.(?:js|css|woff2?|svg|png|jpg|jpeg|webp|avif|ico)$/;
const MANIFEST = /manifest\.webmanifest$/;

const serwist = new Serwist({
  precacheEntries: self.__SW_MANIFEST,
  skipWaiting: false, // explicit user action — see lib/pwa/update-flow.ts
  clientsClaim: true,
  navigationPreload: true,
  runtimeCaching: [
    {
      // Firebase auth helper (proxied via next.config.ts rewrites). A
      // cached/stale response here breaks the OAuth redirect round-trip,
      // and the STATIC rule below would otherwise cache-first its JS.
      matcher: ({ url }) => url.pathname.startsWith("/__/auth"),
      handler: new NetworkOnly(),
    },
    {
      matcher: ({ request, url }) => request.method === "GET" && COACH_API.test(url.pathname),
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
      // Wave 1A: writes go through, no queue. The UI disables the toggle
      // while offline (lib/pwa/online.ts), so we don't try to be clever
      // here. Wave 1B replaces this with a BackgroundSync queue.
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
