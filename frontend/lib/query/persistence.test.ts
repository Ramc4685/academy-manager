import { describe, expect, it } from "vitest";

import { shouldPersistQuery } from "./persistence";

/**
 * The persister writes plaintext to localStorage with a 24h maxAge, so what
 * it accepts is a privacy boundary — not just a cache-tuning knob (UIM13).
 */
describe("shouldPersistQuery", () => {
  it("persists successful coach reads", () => {
    expect(shouldPersistQuery(["coach", "today"], "success")).toBe(true);
    expect(shouldPersistQuery(["coach", "roster", "s-1"], "success")).toBe(true);
  });

  it("never persists coach message bodies", () => {
    expect(shouldPersistQuery(["coach", "messages"], "success")).toBe(false);
  });

  it("never persists student pricing", () => {
    expect(shouldPersistQuery(["coach", "billing-enrollments", "st-1"], "success")).toBe(false);
  });

  it("never persists coach notes about children", () => {
    // Progress and skill notes are private by default (slice 3) and read
    // online-only, so nothing offline needs a localStorage copy of them.
    expect(shouldPersistQuery(["coach", "progress-notes", "s-1"], "success")).toBe(false);
    expect(shouldPersistQuery(["coach", "skill-notes", "st-1", "sk-1"], "success")).toBe(false);
  });

  it("does not persist other personas", () => {
    expect(shouldPersistQuery(["parent", "messages"], "success")).toBe(false);
    expect(shouldPersistQuery(["parent", "children"], "success")).toBe(false);
    expect(shouldPersistQuery(["admin", "messages"], "success")).toBe(false);
  });

  it("only persists settled successful reads", () => {
    expect(shouldPersistQuery(["coach", "today"], "error")).toBe(false);
    expect(shouldPersistQuery(["coach", "today"], "pending")).toBe(false);
  });

  it("ignores non-array query keys", () => {
    expect(shouldPersistQuery("coach", "success")).toBe(false);
    expect(shouldPersistQuery(undefined, "success")).toBe(false);
  });
});
