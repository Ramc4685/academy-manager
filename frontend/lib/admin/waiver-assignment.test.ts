import { describe, expect, it } from "vitest";

import type { AdminStudentWaiverRow } from "@/lib/api/admin";

import { requiredForLabel, studentWaiverSummary, unsignedStudentWaivers } from "./waiver-assignment";

const programs = [
  { program_id: "prog-juniors", name: "Juniors" },
  { program_id: "prog-adults", name: "Adults" },
];

describe("requiredForLabel", () => {
  it("reads a row with only the old registration flag as all families", () => {
    expect(
      requiredForLabel({ assigned_to_registration: true } as never, programs),
    ).toBe("All families");
    expect(
      requiredForLabel({ assigned_to_registration: false } as never, programs),
    ).toBe("Not required");
  });

  it("names the programs a waiver is assigned to", () => {
    expect(
      requiredForLabel(
        {
          required: true,
          scope: "programs",
          program_ids: ["prog-juniors", "prog-adults"],
          assigned_to_registration: false,
        },
        programs,
      ),
    ).toBe("Juniors, Adults");
  });

  it("does not crash on a program that was removed", () => {
    expect(
      requiredForLabel(
        { required: true, scope: "programs", program_ids: ["gone"], assigned_to_registration: false },
        programs,
      ),
    ).toBe("Removed program");
  });

  it("says not required when the explicit flag is off, even with a stale registration flag", () => {
    expect(
      requiredForLabel(
        { required: false, scope: "all", program_ids: [], assigned_to_registration: true },
        programs,
      ),
    ).toBe("Not required");
  });
});

const row = (status: AdminStudentWaiverRow["status"], signed_version: string | null) =>
  ({
    waiver_template_id: "wt",
    lineage_key: "wl",
    title: "Liability",
    version: "2",
    status,
    signed_version,
    signed_at: null,
    signature_id: null,
  }) satisfies AdminStudentWaiverRow;

describe("student waiver rows", () => {
  it("summarises signed, older version and unsigned", () => {
    expect(studentWaiverSummary(row("signed", "2"))).toBe("Signed v2");
    expect(studentWaiverSummary(row("older_version", "1"))).toBe("Signed an older version (v1)");
    expect(studentWaiverSummary(row("unsigned", null))).toBe("Not signed");
  });

  it("warns about everything that is not signed at the live version", () => {
    const rows = [row("signed", "2"), row("older_version", "1"), row("unsigned", null)];
    expect(unsignedStudentWaivers(rows).map((r) => r.status)).toEqual(["older_version", "unsigned"]);
  });
});
