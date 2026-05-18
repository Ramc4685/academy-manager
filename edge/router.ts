/**
 * Cloudflare Worker — academy-manager edge router.
 *
 * Routes traffic between legacy (CRA frontend, FastAPI /api/* routes) and v2
 * (Next.js frontend, FastAPI /api/v2/* routes) based on:
 *   1. Path prefix.
 *   2. Per-route env-var flags (FLAG_*).
 *   3. Per-route 410 Gone for decommissioned legacy paths (Wave 4A).
 *
 * Bind these env vars in `wrangler.toml`:
 *   LEGACY_API_ORIGIN          e.g. https://courtmastr-academy-api.fly.dev
 *   V2_API_ORIGIN              e.g. https://academy-v2-api.fly.dev (set when v2 backend deploys separately; defaults to LEGACY_API_ORIGIN if v2 is mounted in-process)
 *   LEGACY_WEB_ORIGIN          e.g. https://academy-legacy.pages.dev
 *   V2_WEB_ORIGIN              e.g. https://academy-next.pages.dev
 *
 *   FLAG_COACH_TODAY=v2|legacy
 *   FLAG_COACH_LEGACY_GONE=1|0
 *   ...
 *
 * See docs/edge-routing.md for the runbook.
 */

type Env = {
  LEGACY_API_ORIGIN: string;
  V2_API_ORIGIN: string;
  LEGACY_WEB_ORIGIN: string;
  V2_WEB_ORIGIN: string;
} & Record<`FLAG_${string}`, string | undefined>;

type Decision =
  | { kind: "proxy"; origin: string; rewritePath?: string }
  | { kind: "gone" };

function flag(env: Env, name: string): string | undefined {
  return env[`FLAG_${name}` as `FLAG_${string}`];
}

function isV2FrontendEnabled(env: Env): boolean {
  return (
    flag(env, "V2_MARKETING") === "v2" ||
    flag(env, "COACH_TODAY") === "v2" ||
    flag(env, "COACH_ALL") === "v2" ||
    flag(env, "PARENT_ALL") === "v2" ||
    flag(env, "ADMIN_ALL") === "v2"
  );
}

function isSharedV2AssetPath(path: string): boolean {
  return (
    path.startsWith("/_next/") ||
    path.startsWith("/icons/") ||
    path.startsWith("/workbox-") ||
    path.startsWith("/swe-worker-") ||
    path === "/favicon.ico" ||
    path === "/manifest.webmanifest" ||
    path === "/sw.js"
  );
}

function decide(url: URL, env: Env): Decision {
  const path = url.pathname;

  // --- Wave 4A: admin-only legacy escape hatch.
  // /legacy/* paths route to the legacy origin during the 30-day quiet
  // window after disablement. Auth is enforced at the origin (admin-only
  // session cookie); the worker is path-routing only.
  if (path.startsWith("/legacy/")) {
    if (flag(env, "LEGACY_HATCH_OPEN") === "1") {
      return {
        kind: "proxy",
        origin: env.LEGACY_WEB_ORIGIN,
        rewritePath: path.replace(/^\/legacy/, "") || "/",
      };
    }
    return { kind: "gone" };
  }

  // --- v2 API: always served by V2 origin. ---
  if (path.startsWith("/api/v2/")) {
    return { kind: "proxy", origin: env.V2_API_ORIGIN };
  }

  // --- Legacy API: 410 once Wave 4A disables it. ---
  if (path.startsWith("/api/")) {
    if (flag(env, "LEGACY_API_GONE") === "1") {
      return { kind: "gone" };
    }
    return { kind: "proxy", origin: env.LEGACY_API_ORIGIN };
  }

  // Next.js emits global asset URLs (/_next/*, /sw.js, icons, etc.). Once any
  // v2 frontend route is live, these must follow the v2 app or persona pages
  // render HTML from v2 with static assets from legacy.
  if (isSharedV2AssetPath(path) && isV2FrontendEnabled(env)) {
    return { kind: "proxy", origin: env.V2_WEB_ORIGIN };
  }

  // --- Persona-prefixed frontend paths: per-flag routing. ---
  // Each wave flips one FLAG_<persona>_<surface>=v2.
  // Wave 1A: FLAG_COACH_TODAY=v2 sends /coach/* to V2.

  if (path.startsWith("/coach/today") || path === "/coach") {
    return flag(env, "COACH_TODAY") === "v2"
      ? { kind: "proxy", origin: env.V2_WEB_ORIGIN }
      : { kind: "proxy", origin: env.LEGACY_WEB_ORIGIN };
  }

  if (path.startsWith("/coach/")) {
    // Other coach surfaces stay on legacy until they migrate per wave.
    return flag(env, "COACH_ALL") === "v2"
      ? { kind: "proxy", origin: env.V2_WEB_ORIGIN }
      : { kind: "proxy", origin: env.LEGACY_WEB_ORIGIN };
  }

  if (path.startsWith("/parent/")) {
    return flag(env, "PARENT_ALL") === "v2"
      ? { kind: "proxy", origin: env.V2_WEB_ORIGIN }
      : { kind: "proxy", origin: env.LEGACY_WEB_ORIGIN };
  }

  if (path.startsWith("/admin/")) {
    return flag(env, "ADMIN_ALL") === "v2"
      ? { kind: "proxy", origin: env.V2_WEB_ORIGIN }
      : { kind: "proxy", origin: env.LEGACY_WEB_ORIGIN };
  }

  // --- v2 marketing & shared paths during Phase 0 (login, post-login). ---
  if (path === "/login" || path === "/post-login") {
    return flag(env, "V2_MARKETING") === "v2"
      ? { kind: "proxy", origin: env.V2_WEB_ORIGIN }
      : { kind: "proxy", origin: env.LEGACY_WEB_ORIGIN };
  }

  // Default: legacy.
  return { kind: "proxy", origin: env.LEGACY_WEB_ORIGIN };
}

async function proxy(request: Request, origin: string, rewritePath?: string): Promise<Response> {
  const url = new URL(request.url);
  if (rewritePath) url.pathname = rewritePath;
  const target = new URL(url.pathname + url.search, origin);
  const init: RequestInit = {
    method: request.method,
    headers: request.headers,
    redirect: "manual",
  };
  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = await request.arrayBuffer();
  }
  // Forward trace headers for observability.
  return fetch(target.toString(), init);
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const decision = decide(url, env);
    switch (decision.kind) {
      case "gone":
        return new Response("Gone", { status: 410 });
      case "proxy":
        return proxy(request, decision.origin, decision.rewritePath);
    }
  },
};

// Exported for unit tests.
export { decide };
export type { Env, Decision };
