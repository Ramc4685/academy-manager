import { describe, expect, it } from "vitest";

import { checkImportHeader, parseCsv } from "@/lib/admin/import-column-mapping";

import { quickAddCsv } from "./QuickAddFamily";

describe("quickAddCsv (L12 quick add)", () => {
  const form = {
    parent_name: "Maya Okafor, Jr.",
    parent_email: " maya@example.com ",
    parent_phone: "555-010-1001",
    student_name: 'Simone "Sim" Okafor',
    student_date_of_birth: "",
  };

  it("is a one-row import file with the import's exact header", () => {
    const csv = quickAddCsv(form);
    expect(checkImportHeader(csv).ok).toBe(true);
    const rows = parseCsv(csv);
    expect(rows[0]).toEqual([
      "parent_name",
      "parent_email",
      "parent_phone",
      "student_name",
      "student_date_of_birth",
    ]);
    // Commas and quotes survive the round trip; values are trimmed.
    expect(rows[1]).toEqual([
      "Maya Okafor, Jr.",
      "maya@example.com",
      "555-010-1001",
      'Simone "Sim" Okafor',
      "",
    ]);
  });
});
