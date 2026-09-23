import { describe, expect, it } from "vitest";

import type { FamilyIndexRow, FamilyStudent } from "@/lib/api/admin-families";

import {
  FAMILY_TABS,
  SECOND_PARENT_SWITCHES,
  adjacentFamilyTab,
  attendanceStatusLabel,
  correctionConfirmCopy,
  correctionTargets,
  correctTriggerId,
  drawerAttendanceRows,
  familyTabQuery,
  overviewChildren,
  primaryContactRows,
  resolveFamilyTab,
} from "./family-record";

const ROW: FamilyIndexRow = {
  family_id: "parent-1",
  parent_name: "Testparent One",
  email: "one@example.test",
  phone: null,
  has_account: true,
  stage: "active",
  children: [
    {
      student_id: "stu-a",
      name: "Kid Alpha",
      lifecycle: "active",
      lifecycle_as_of: null,
      classes: [{ session_id: "sess-sat", title: "Sat Beginners" }],
      matched: false,
    },
  ],
  card_on_file: true,
  registration: "registered",
  money: null,
  matched_parent: false,
};

const STUDENT_B: FamilyStudent = {
  student_id: "stu-b",
  name: "Kid Bravo",
  status: "active",
  enrollments: [
    {
      enrollment_id: "enr-b",
      session_id: "sess-wed",
      session_title: "Wed Intermediate",
      schedule: null,
      status: "paused",
      monthly_price_cents: null,
      override_price_cents: null,
      autopay_status: null,
      recurring_discount: null,
      resume_on: null,
      actions: [],
    },
  ],
};

describe("family tabs", () => {
  it("lists Overview, Details, Billing, Timeline in order", () => {
    expect(FAMILY_TABS.map((t) => t.id)).toEqual(["overview", "details", "billing", "timeline"]);
  });

  it("resolves ?tab= and falls back to Overview", () => {
    expect(resolveFamilyTab("billing")).toBe("billing");
    expect(resolveFamilyTab("timeline")).toBe("timeline");
    expect(resolveFamilyTab(null)).toBe("overview");
    expect(resolveFamilyTab("payments")).toBe("overview");
  });

  it("writes the tab into the query and keeps other params", () => {
    expect(familyTabQuery("", "billing")).toBe("?tab=billing");
    expect(familyTabQuery("tab=billing&from=list", "overview")).toBe("?from=list");
    expect(familyTabQuery("tab=billing", "overview")).toBe("?");
    expect(familyTabQuery("from=list", "details")).toBe("?from=list&tab=details");
  });

  it("moves with arrow keys, wrapping at the ends", () => {
    expect(adjacentFamilyTab("overview", "ArrowRight")).toBe("details");
    expect(adjacentFamilyTab("overview", "ArrowLeft")).toBe("timeline");
    expect(adjacentFamilyTab("timeline", "ArrowRight")).toBe("overview");
    expect(adjacentFamilyTab("billing", "Home")).toBe("overview");
    expect(adjacentFamilyTab("billing", "End")).toBe("timeline");
    expect(adjacentFamilyTab("billing", "Enter")).toBeNull();
  });
});

describe("details", () => {
  it("prefers the index row and fills gaps from the billing parent", () => {
    const rows = primaryContactRows(ROW, {
      parent_id: "parent-1",
      name: "Other Name",
      email: null,
      phone: "555-0100",
    });
    expect(rows.map((r) => r.value)).toEqual(["Testparent One", "one@example.test", "555-0100"]);
  });

  it("says Not on file rather than leaving a blank", () => {
    expect(primaryContactRows(null, null).map((r) => r.value)).toEqual([
      "Not on file",
      "Not on file",
      "Not on file",
    ]);
  });

  it("second-parent switches are off and disabled", () => {
    expect(SECOND_PARENT_SWITCHES.map((s) => s.label)).toEqual([
      "Gets notices",
      "Gets invoices (opted in)",
    ]);
    expect(SECOND_PARENT_SWITCHES.every((s) => s.disabled && !s.checked)).toBe(true);
  });
});

describe("overviewChildren", () => {
  it("uses the index children and adds billing-only children", () => {
    const kids = overviewChildren(ROW, [STUDENT_B]);
    expect(kids.map((k) => k.studentId)).toEqual(["stu-a", "stu-b"]);
    expect(kids[0]).toMatchObject({ lifecycle: "active", classes: ["Sat Beginners"] });
    expect(kids[1]).toMatchObject({ lifecycle: null, classes: ["Wed Intermediate"] });
  });

  it("does not list a child twice", () => {
    const kids = overviewChildren(ROW, [{ ...STUDENT_B, student_id: "stu-a" }]);
    expect(kids).toHaveLength(1);
  });
});

describe("drawer attendance", () => {
  const rows = drawerAttendanceRows([
    {
      session_id: "sess-sat",
      date: "2026-09-12",
      status: "absent",
      marked_at: "2026-09-12T15:00:00Z",
      occurrence_id: "occ-2",
      previous_status: "present",
      corrected_at: "2026-09-13T10:00:00Z",
    },
    {
      session_id: "sess-sat",
      date: "",
      status: "present",
      marked_at: "2026-09-05T15:00:00Z",
      occurrence_id: "occ-1",
    },
    { session_id: "sess-old", date: "2026-08-01", status: "present", marked_at: null },
  ]);

  it("labels dates, statuses and corrections", () => {
    expect(rows[0]).toMatchObject({
      key: "occ-2",
      dateLabel: "Sep 12",
      statusLabel: "Absent",
      correctedNote: "Was Present",
      correctable: true,
    });
    expect(rows[1].dateLabel).toBe("Sep 5");
    expect(rows[1].correctedNote).toBeNull();
  });

  it("a mark without an occurrence cannot be corrected", () => {
    expect(rows[2].correctable).toBe(false);
  });

  it("offers every other real status as a target", () => {
    expect(correctionTargets("present")).toEqual(["late", "absent"]);
    expect(correctionTargets("absent")).toEqual(["present", "late"]);
  });

  it("confirm copy names the child, the date and both statuses", () => {
    expect(
      correctionConfirmCopy({ childName: "Kid Alpha", dateLabel: "Sep 12", from: "absent", to: "present" }),
    ).toBe(
      "Change Kid Alpha's Sep 12 mark from Absent to Present? The old mark, your name and the reason are kept in the attendance history.",
    );
  });

  it("status labels and focus ids", () => {
    expect(attendanceStatusLabel("late")).toBe("Late");
    expect(attendanceStatusLabel("excused")).toBe("Excused");
    expect(attendanceStatusLabel(null)).toBe("Unknown");
    expect(correctTriggerId("occ-1")).toBe("drawer-correct-occ-1");
  });
});
