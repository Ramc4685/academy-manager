/**
 * Unit tests for the edge routing decision logic.
 *
 * Pure functions only — `decide(url, env)` does not touch the network.
 * Run with `pnpm vitest` inside `edge/` once Wrangler's vitest pool is added.
 */

import { decide, type Env } from "./router";

const baseEnv: Env = {
  LEGACY_API_ORIGIN: "https://legacy-api.example",
  V2_API_ORIGIN: "https://v2-api.example",
  LEGACY_WEB_ORIGIN: "https://legacy-web.example",
  V2_WEB_ORIGIN: "https://v2-web.example",
};

function withFlags(flags: Record<string, string>): Env {
  return { ...baseEnv, ...flags } as Env;
}

const cases: Array<[string, string, Env, "proxy:legacy-api" | "proxy:v2-api" | "proxy:legacy-web" | "proxy:v2-web" | "gone"]> = [
  // Default Phase 0 state: legacy everywhere.
  ["GET", "/api/users/me", baseEnv, "proxy:legacy-api"],
  ["GET", "/api/v2/coach/today", baseEnv, "proxy:v2-api"],
  ["GET", "/coach/today", baseEnv, "proxy:legacy-web"],
  ["GET", "/parent/onboarding", baseEnv, "proxy:legacy-web"],
  ["GET", "/admin/sessions", baseEnv, "proxy:legacy-web"],
  ["GET", "/", baseEnv, "proxy:legacy-web"],

  // Wave 1A: FLAG_COACH_TODAY=v2 routes coach traffic to v2 web.
  ["GET", "/coach/today", withFlags({ FLAG_COACH_TODAY: "v2" }), "proxy:v2-web"],
  ["GET", "/coach/sessions/abc", withFlags({ FLAG_COACH_TODAY: "v2" }), "proxy:legacy-web"], // others still legacy
  ["GET", "/coach/sessions/abc", withFlags({ FLAG_COACH_ALL: "v2" }), "proxy:v2-web"],
  ["GET", "/_next/static/app.js", withFlags({ FLAG_COACH_ALL: "v2" }), "proxy:v2-web"],
  ["GET", "/sw.js", withFlags({ FLAG_PARENT_ALL: "v2" }), "proxy:v2-web"],
  ["GET", "/manifest.webmanifest", withFlags({ FLAG_ADMIN_ALL: "v2" }), "proxy:v2-web"],
  ["GET", "/manifest.webmanifest", baseEnv, "proxy:legacy-web"],

  // Wave 4A: FLAG_LEGACY_API_GONE=1 returns 410.
  ["GET", "/api/users/me", withFlags({ FLAG_LEGACY_API_GONE: "1" }), "gone"],
  ["GET", "/api/v2/coach/today", withFlags({ FLAG_LEGACY_API_GONE: "1" }), "proxy:v2-api"], // v2 unaffected
];

function tag(d: ReturnType<typeof decide>, env: Env): string {
  if (d.kind === "gone") return "gone";
  if (d.origin === env.LEGACY_API_ORIGIN) return "proxy:legacy-api";
  if (d.origin === env.V2_API_ORIGIN) return "proxy:v2-api";
  if (d.origin === env.LEGACY_WEB_ORIGIN) return "proxy:legacy-web";
  if (d.origin === env.V2_WEB_ORIGIN) return "proxy:v2-web";
  return `unknown:${d.origin}`;
}

let failures = 0;
for (const [_method, path, env, expected] of cases) {
  const url = new URL(`https://academy.example${path}`);
  const actual = tag(decide(url, env), env);
  if (actual !== expected) {
    failures += 1;
    console.error(`FAIL ${path} → ${actual} (expected ${expected})`);
  }
}
if (failures > 0) {
  console.error(`${failures} failure(s)`);
  process.exit(1);
}
console.log(`OK — ${cases.length} cases`);
