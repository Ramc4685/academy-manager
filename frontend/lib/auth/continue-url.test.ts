import { describe, expect, it } from "vitest";

import { safeContinuePath } from "./continue-url";

const ORIGIN = "https://blno-academy.courtmastr.com";

describe("safeContinuePath", () => {
  it("keeps a same-origin continue URL as a relative path", () => {
    expect(safeContinuePath(`${ORIGIN}/login`, ORIGIN)).toBe("/login");
  });

  it("preserves query and hash on a same-origin target", () => {
    expect(safeContinuePath(`${ORIGIN}/parent/payments?invoice=1#due`, ORIGIN)).toBe(
      "/parent/payments?invoice=1#due"
    );
  });

  it("rejects another academy's host so a reset cannot cross tenants", () => {
    expect(safeContinuePath("https://other-academy.courtmastr.com/parent", ORIGIN)).toBe("/login");
  });

  it("rejects an unrelated origin (open-redirect guard)", () => {
    expect(safeContinuePath("https://evil.example/steal", ORIGIN)).toBe("/login");
  });

  it("rejects a protocol-relative URL", () => {
    expect(safeContinuePath("//evil.example/steal", ORIGIN)).toBe("/login");
  });

  it("rejects a javascript: URL", () => {
    expect(safeContinuePath("javascript:alert(1)", ORIGIN)).toBe("/login");
  });

  it("rejects a scheme change on the same host", () => {
    expect(safeContinuePath("http://blno-academy.courtmastr.com/login", ORIGIN)).toBe("/login");
  });

  it("falls back when the parameter is absent", () => {
    expect(safeContinuePath(null, ORIGIN)).toBe("/login");
    expect(safeContinuePath(undefined, ORIGIN)).toBe("/login");
    expect(safeContinuePath("", ORIGIN)).toBe("/login");
  });

  it("falls back on an unparseable value", () => {
    expect(safeContinuePath("http://[bad", ORIGIN)).toBe("/login");
  });

  it("resolves a bare relative path against the current origin", () => {
    expect(safeContinuePath("/parent/dashboard", ORIGIN)).toBe("/parent/dashboard");
  });

  it("works for a local staging origin with a port", () => {
    const local = "http://blno.localhost:3000";
    expect(safeContinuePath(`${local}/login`, local)).toBe("/login");
    expect(safeContinuePath("http://other.localhost:3000/login", local)).toBe("/login");
  });
});
