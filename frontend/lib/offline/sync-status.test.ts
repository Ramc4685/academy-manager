import { describe, expect, it } from "vitest";

import { classSyncStatus } from "./sync-status";

describe("classSyncStatus", () => {
  it("shows nothing before anything is marked", () => {
    expect(classSyncStatus({ needsAttention: false, waiting: false, saved: false })).toBeNull();
  });

  it("is saved once the server holds a mark and nothing is waiting", () => {
    expect(classSyncStatus({ needsAttention: false, waiting: false, saved: true })).toBe("saved");
  });

  it("is waiting while any mark is still on the phone", () => {
    expect(classSyncStatus({ needsAttention: false, waiting: true, saved: true })).toBe("waiting");
  });

  it("puts a stuck mark ahead of everything else", () => {
    expect(classSyncStatus({ needsAttention: true, waiting: true, saved: true })).toBe(
      "attention",
    );
  });
});
