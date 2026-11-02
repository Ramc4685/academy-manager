import { describe, expect, it } from "vitest";

import type { ParentWaiverStudentView } from "@/lib/api/parent";

import { waiverSignLabel } from "./waiver-label";

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

describe("waiverSignLabel", () => {
  it("names the one child who still needs a signature", () => {
    expect(waiverSignLabel([kid("Test Kid A", "pending"), kid("Test Kid B", "signed")])).toBe(
      "Sign waiver for Test Kid A",
    );
  });

  it("joins several names with a final 'and', counting outdated signatures", () => {
    expect(
      waiverSignLabel([
        kid("Kid One", "pending"),
        kid("Kid Two", "outdated"),
        kid("Kid Three", "pending"),
        kid("Kid Four", "not_required"),
      ]),
    ).toBe("Sign waiver for Kid One, Kid Two and Kid Three");
  });

  it("falls back to the plain verb when no child is named", () => {
    expect(waiverSignLabel([kid("Kid Five", "not_required")])).toBe("Sign waiver");
    expect(waiverSignLabel([kid("  ", "pending")])).toBe("Sign waiver");
  });

  it("says waivers, and names each child once, when several waivers are on the page", () => {
    expect(
      waiverSignLabel(
        [kid("Kid One", "pending"), kid("Kid One", "pending"), kid("Kid Two", "outdated")],
        2,
      ),
    ).toBe("Sign waivers for Kid One and Kid Two");
    expect(waiverSignLabel([kid("Kid Five", "signed")], 2)).toBe("Sign waivers");
  });
});
