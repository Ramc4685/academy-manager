/**
 * Unit tests for the edge routing decision logic.
 *
 * Pure functions only — `decide(url, env)` does not touch the network.
 * Run with `pnpm vitest` inside `edge/` once Wrangler's vitest pool is added.
 */

import { decide, type Env } from "./router";

const baseEnv: Env = {
  API_ORIGIN: "https://api.example",
  WEB_ORIGIN: "https://web.example",
};

const cases: Array<[string, string, Env, "proxy:api" | "proxy:web"]> = [
  ["GET", "/api", baseEnv, "proxy:api"],
  ["GET", "/api/users/me", baseEnv, "proxy:api"],
  ["GET", "/api/v2/coach/today", baseEnv, "proxy:api"],
  ["GET", "/coach/today", baseEnv, "proxy:web"],
  ["GET", "/coach/sessions/abc", baseEnv, "proxy:web"],
  ["GET", "/parent/onboarding", baseEnv, "proxy:web"],
  ["GET", "/admin/sessions", baseEnv, "proxy:web"],
  ["GET", "/login", baseEnv, "proxy:web"],
  ["GET", "/register", baseEnv, "proxy:web"],
  ["GET", "/_next/static/app.js", baseEnv, "proxy:web"],
  ["GET", "/sw.js", baseEnv, "proxy:web"],
  ["GET", "/manifest.webmanifest", baseEnv, "proxy:web"],
  ["GET", "/", baseEnv, "proxy:web"],
];

function tag(d: ReturnType<typeof decide>, env: Env): string {
  if (d.origin === env.API_ORIGIN) return "proxy:api";
  if (d.origin === env.WEB_ORIGIN) return "proxy:web";
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
