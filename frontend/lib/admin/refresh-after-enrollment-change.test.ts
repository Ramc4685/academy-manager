import { readFileSync } from "node:fs";
import path from "node:path";
import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { familyReadsAreFresh, markFamilyWrite } from "@/lib/api/admin-families";

import { refreshAfterEnrollmentChange } from "./refresh-after-enrollment-change";

describe("families fresh-read window (S26)", () => {
  afterEach(() => vi.useRealTimers());

  it("is fresh for 60 seconds after a write, then cached again", () => {
    markFamilyWrite(1_000);
    expect(familyReadsAreFresh(1_000)).toBe(true);
    expect(familyReadsAreFresh(60_999)).toBe(true);
    expect(familyReadsAreFresh(61_000)).toBe(false);
  });
});

describe("refreshAfterEnrollmentChange (S26)", () => {
  it("marks the write and invalidates student, discount, rosters, classes and families", () => {
    vi.useFakeTimers();
    vi.setSystemTime(500_000);
    const client = new QueryClient();
    const spy = vi.spyOn(client, "invalidateQueries");
    refreshAfterEnrollmentChange(client, { studentId: "stu-1", parentId: "par-1" });
    expect(familyReadsAreFresh(500_000)).toBe(true);
    expect(spy.mock.calls.map(([filters]) => filters?.queryKey)).toEqual([
      ["admin", "student", "stu-1"],
      ["admin", "families", "par-1", "billing", "sibling-discount"],
      ["admin", "enrollments"],
      ["admin", "session"],
      ["admin", "sessions"],
      ["admin", "families"],
    ]);
    vi.useRealTimers();
  });

  it("is used by every enrollment write path", () => {
    const root = path.join(__dirname, "../../app/(admin)/admin");
    for (const file of [
      "families/QuickAddFamily.tsx",
      "students/[studentId]/SessionsPanel.tsx",
      "sessions/[id]/page.tsx",
    ]) {
      expect(readFileSync(path.join(root, file), "utf8")).toContain("refreshAfterEnrollmentChange(queryClient");
    }
  });

  it("opens the fresh window after a Families-page import, quick add or bulk invite", () => {
    const src = readFileSync(path.join(__dirname, "../../app/(admin)/admin/families/page.tsx"), "utf8");
    expect(src).toMatch(/const refreshAll = \(\) => \{\s+markFamilyWrite\(\);/);
  });

  it("sends fresh=true only inside the window", () => {
    const src = readFileSync(path.join(__dirname, "../api/admin-families.ts"), "utf8");
    expect(src).toContain('withFresh("/admin/families", familyIndexQueryString(params))');
    expect(src).toContain('withFresh("/admin/families/summary", "")');
  });
});
