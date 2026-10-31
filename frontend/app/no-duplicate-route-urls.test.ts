import { readdirSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Settings overhaul Phase 2 PR 8 (Lane E) — the frontend twin of
 * `backend/v2/tests/structural/test_no_duplicate_routes.py`, written after
 * the #967 Pathway route-collision class of bug: two FastAPI routers (or
 * here, two `app/` route groups) silently registering the same effective
 * path, with one shadowing the other.
 *
 * Next's App Router segments a route by its file path, but a "route group"
 * folder — `(admin)`, `(owner)`, etc. — is stripped from the URL. Two
 * `page.tsx`/`route.ts` files under *different* route groups can therefore
 * resolve to the exact same URL, and only one of them is ever reachable
 * (Next fails the dev/build server for a true static collision, but a
 * dynamic-vs-static or param-name mismatch can slip through). This walks the
 * whole `app/` tree, strips route groups the way Next does, and asserts every
 * resolved URL is backed by exactly one route file.
 */

const APP_DIR = path.resolve(__dirname);

const ROUTE_FILES = new Set(["page.tsx", "page.ts", "route.ts", "route.tsx"]);
const SKIP_DIRS = new Set(["node_modules", ".next"]);

function isRouteGroup(segment: string): boolean {
  return segment.startsWith("(") && segment.endsWith(")");
}

// Parallel route slots (`@modal`) render alongside their parent and are not
// part of the URL; intercepting-route markers (`(.)`, `(..)`, `(...)`)
// resolve to another real segment at match time. Both are excluded from the
// plain "does this URL collide" walk — this check is for the ordinary case.
function isParallelSlot(segment: string): boolean {
  return segment.startsWith("@");
}

function isInterceptingMarker(segment: string): boolean {
  return /^\(\.{1,3}\)$/.test(segment) || segment.startsWith("(..)(");
}

function isCatchAll(segment: string): boolean {
  return /^\[\.\.\..+\]$/.test(segment);
}

function isOptionalCatchAll(segment: string): boolean {
  return /^\[\[\.\.\..+\]\]$/.test(segment);
}

function isDynamic(segment: string): boolean {
  return segment.startsWith("[") && segment.endsWith("]");
}

// Normalize dynamic segments to a fixed placeholder, ignoring the param
// name, so two differently-named dynamic segments at the same position
// (e.g. `[id]` vs `[coachId]`) are treated as the collision they are at
// request time, matching what Next's own router does.
function urlSegment(segment: string): string | null {
  if (isRouteGroup(segment) || isInterceptingMarker(segment)) return null;
  if (isParallelSlot(segment)) return null;
  if (isOptionalCatchAll(segment)) return "[[...catchAll]]";
  if (isCatchAll(segment)) return "[...catchAll]";
  if (isDynamic(segment)) return "[param]";
  return segment;
}

function walk(dir: string, segments: string[], out: Map<string, string[]>): void {
  for (const entry of readdirSync(dir)) {
    const full = path.join(dir, entry);
    const stat = statSync(full);
    if (stat.isDirectory()) {
      if (SKIP_DIRS.has(entry)) continue;
      const seg = urlSegment(entry);
      walk(full, seg === null ? segments : [...segments, seg], out);
      continue;
    }
    if (ROUTE_FILES.has(entry)) {
      const url = "/" + segments.join("/");
      const rel = path.relative(APP_DIR, full);
      const existing = out.get(url) ?? [];
      existing.push(rel);
      out.set(url, existing);
    }
  }
}

describe("app/ route URLs", () => {
  it("resolves every page.tsx/route.ts to a distinct URL", () => {
    const byUrl = new Map<string, string[]>();
    walk(APP_DIR, [], byUrl);

    expect(byUrl.size, "route walk found no routes; the helper is broken").toBeGreaterThan(0);

    const collisions = [...byUrl.entries()].filter(([, files]) => files.length > 1);
    expect(
      collisions,
      collisions
        .map(([url, files]) => `${url}: ${files.join(" vs ")}`)
        .join("\n"),
    ).toEqual([]);
  });
});
