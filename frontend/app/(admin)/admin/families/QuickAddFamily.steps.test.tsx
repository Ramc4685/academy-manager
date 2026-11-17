import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as adminApi from "@/lib/api/admin";
import * as importApi from "@/lib/api/admin-family-import";
import type { ImportRow } from "@/lib/api/admin-family-import";

import { QuickAddResult, runQuickAdd } from "./QuickAddFamily";

function row(overrides: Partial<ImportRow> = {}): ImportRow {
  return {
    status: "create",
    family_id: "par-okafor",
    family_link: "/admin/families/par-okafor",
    student_id: "stu-9",
    student_name: "Simone Okafor",
    parent_name: "Maya Okafor",
    errors: [],
    warnings: [],
    ...overrides,
  } as ImportRow;
}

function commitReturns(r: ImportRow | null) {
  vi.spyOn(importApi, "commitFamilyImport").mockResolvedValue({
    rows: r ? [r] : [],
  } as never);
}

describe("quick add steps after the commit (L12)", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("keeps the family when the enrollment fails, says so, and sends no invite", async () => {
    commitReturns(row());
    vi.spyOn(adminApi, "createEnrollment").mockRejectedValue(new Error("Class is full."));
    const invite = vi.spyOn(adminApi, "inviteBillingSetupParent");

    const result = await runQuickAdd({ batchId: "b1", sessionId: "sess-1", invite: true });

    expect(result).toMatchObject({ enrolled: false, invited: null, failure: "Class is full." });
    expect(invite).not.toHaveBeenCalled();
    const out = renderToStaticMarkup(<QuickAddResult result={result} />);
    expect(out).toContain("Added Simone Okafor");
    expect(out).toContain("Saved the family, but: Class is full.");
    expect(out).not.toContain("enrolled them");
  });

  it("reports an invite that throws after a good enrollment", async () => {
    commitReturns(row());
    vi.spyOn(adminApi, "createEnrollment").mockResolvedValue({} as never);
    vi.spyOn(adminApi, "inviteBillingSetupParent").mockRejectedValue(new Error("Mail is down."));

    const result = await runQuickAdd({ batchId: "b1", sessionId: "sess-1", invite: true });

    expect(result).toMatchObject({ enrolled: true, invited: false, failure: "Mail is down." });
    const out = renderToStaticMarkup(<QuickAddResult result={result} />);
    expect(out).toContain("enrolled them");
    expect(out).not.toContain("login invite sent");
    expect(out).toContain("Saved the family, but: Mail is down.");
  });

  it("stops when the child already existed: no enroll, no invite, no 'Added'", async () => {
    commitReturns(row({ status: "skip", student_id: null }));
    const enroll = vi.spyOn(adminApi, "createEnrollment");
    const invite = vi.spyOn(adminApi, "inviteBillingSetupParent");

    const result = await runQuickAdd({ batchId: "b1", sessionId: "sess-1", invite: true });

    expect(result.existed).toBe(true);
    expect(enroll).not.toHaveBeenCalled();
    expect(invite).not.toHaveBeenCalled();
    const out = renderToStaticMarkup(<QuickAddResult result={result} />);
    expect(out).toContain("already existed");
    expect(out).toContain("Open the family to enroll");
    expect(out).not.toContain("Added");
  });

  it("fails loudly when the commit returns no row", async () => {
    commitReturns(null);
    await expect(runQuickAdd({ batchId: "b1", sessionId: "", invite: false })).rejects.toThrow(
      /no row/,
    );
  });
});
