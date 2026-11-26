import { beforeAll, describe, expect, it, vi } from "vitest";

/**
 * The coach today/sessions reads must be network-first: stale-while-revalidate
 * painted the cached roster first, so a transferred child stayed on screen.
 * sw.ts runs as a worker entry, so serwist is replaced by recording stubs.
 */
type Route = { matcher: (ctx: { request: Request; url: URL }) => boolean; handler: unknown };
type Handler = { constructor: { name: string }; options: { cacheName?: string } };
const captured: { routes: Route[] } = { routes: [] };

vi.mock("@serwist/next/worker", () => ({ defaultCache: [] }));
vi.mock("serwist", () => {
  class Strategy {
    constructor(public options: unknown = {}) {}
  }
  return {
    Serwist: class {
      constructor(opts: { runtimeCaching: Route[] }) {
        captured.routes = opts.runtimeCaching;
      }
      addEventListeners() {}
    },
    NetworkFirst: class NetworkFirst extends Strategy {},
    StaleWhileRevalidate: class StaleWhileRevalidate extends Strategy {},
    NetworkOnly: class NetworkOnly extends Strategy {},
    CacheFirst: class CacheFirst extends Strategy {},
    ExpirationPlugin: class ExpirationPlugin extends Strategy {},
  };
});

function handlerFor(method: string, path: string): Handler {
  const url = new URL(path, "https://academy.example.com");
  const request = new Request(url, { method });
  return captured.routes.find((r) => r.matcher({ request, url }))?.handler as Handler;
}

beforeAll(async () => {
  vi.stubGlobal("self", { __SW_MANIFEST: [], addEventListener: () => {}, skipWaiting: () => {} });
  await import("./sw");
});

describe("service worker coach reads", () => {
  it.each(["/api/v2/coach/today?date=2026-11-26", "/api/v2/coach/sessions/occ-1"])(
    "%s is network-first with the 24h cache as fallback",
    (path) => {
      const handler = handlerFor("GET", path);
      expect(handler.constructor.name).toBe("NetworkFirst");
      expect(handler.options.cacheName).toBe("coach-api-v1");
    },
  );

  it("never caches child progress notes", () => {
    expect(handlerFor("GET", "/api/v2/coach/sessions/occ-1/progress-notes").constructor.name).toBe("NetworkOnly");
  });

  it("sends coach attendance writes to the network", () => {
    expect(handlerFor("POST", "/api/v2/coach/attendance").constructor.name).toBe("NetworkOnly");
  });
});
