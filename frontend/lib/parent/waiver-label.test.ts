import { describe, expect, it } from "vitest";

import type { ParentWaiverStudentView } from "@/lib/api/parent";

import { waiverAcceptLabel } from "./waiver-label";

const kid = (
  student_name: string,
  status: ParentWaiverStudentView["status"],
): ParentWaiverStudentView => ({
  student_id: `stu-${student_name}`,
  student_name,
  status,
  signed_at: null,
  waiver_version: null,
});

describe("waiverAcceptLabel", () => {
  it("names the one child who still needs a signature", () => {
    expect(waiverAcceptLabel([kid("Test Kid A", "pending"), kid("Test Kid B", "signed")])).toBe(
      "Accept waiver for Test Kid A",
    );
  });

  it("joins several names with a final 'and', counting outdated signatures", () => {
    expect(
      waiverAcceptLabel([
        kid("Kid One", "pending"),
        kid("Kid Two", "outdated"),
        kid("Kid Three", "pending"),
        kid("Kid Four", "not_required"),
      ]),
    ).toBe("Accept waiver for Kid One, Kid Two and Kid Three");
  });

  it("falls back to the plain verb when no child is named", () => {
    expect(waiverAcceptLabel([kid("Kid Five", "not_required")])).toBe("Accept waiver");
    expect(waiverAcceptLabel([kid("  ", "pending")])).toBe("Accept waiver");
  });
});
