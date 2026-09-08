import { describe, expect, it } from "vitest";

import { isTopLevel, parentRoute } from "./parent-route";

const COACH_KNOWN = [
  "/coach/dashboard",
  "/coach/today",
  "/coach/sessions",
  "/coach/profile",
  "/coach/calendar",
  "/coach/messages",
  "/coach/needs-review",
] as const;

const ADMIN_KNOWN = ["/admin", "/admin/sessions", "/admin/reports", "/admin/dashboard"] as const;

describe("parentRoute", () => {
  it("falls back to home when no ancestor is known", () => {
    expect(parentRoute("/coach/students/abc/passport", COACH_KNOWN, "/coach/dashboard")).toBe(
      "/coach/dashboard",
    );
  });

  it("returns the nearest known ancestor, skipping unknown middle segments", () => {
    expect(parentRoute("/coach/sessions/abc/skills", COACH_KNOWN, "/coach/dashboard")).toBe(
      "/coach/sessions",
    );
  });

  it("returns the immediate known parent", () => {
    expect(parentRoute("/admin/reports/dues", ADMIN_KNOWN, "/admin")).toBe("/admin/reports");
  });

  it("walks past a dynamic id to the known list route", () => {
    expect(parentRoute("/admin/sessions/abc/skill-board", ADMIN_KNOWN, "/admin")).toBe(
      "/admin/sessions",
    );
  });

  it("ignores a trailing slash", () => {
    expect(parentRoute("/coach/sessions/abc/", COACH_KNOWN, "/coach/dashboard")).toBe(
      "/coach/sessions",
    );
  });

  it("returns home for a top-level or root path with no known ancestor", () => {
    expect(parentRoute("/coach/today", COACH_KNOWN, "/coach/dashboard")).toBe("/coach/dashboard");
    expect(parentRoute("/", COACH_KNOWN, "/coach/dashboard")).toBe("/coach/dashboard");
    expect(parentRoute("/coach", COACH_KNOWN, "/coach/dashboard")).toBe("/coach/dashboard");
  });
});

describe("isTopLevel", () => {
  it("matches a known route exactly", () => {
    expect(isTopLevel("/coach/sessions", COACH_KNOWN)).toBe(true);
    expect(isTopLevel("/admin", ADMIN_KNOWN)).toBe(true);
  });

  it("does not treat a child of a known route as top-level", () => {
    expect(isTopLevel("/coach/sessions/abc", COACH_KNOWN)).toBe(false);
    expect(isTopLevel("/admin/sessions/abc", ADMIN_KNOWN)).toBe(false);
  });

  it("tolerates a trailing slash", () => {
    expect(isTopLevel("/coach/sessions/", COACH_KNOWN)).toBe(true);
  });

  it("rejects unknown routes", () => {
    expect(isTopLevel("/coach/students", COACH_KNOWN)).toBe(false);
  });
});
