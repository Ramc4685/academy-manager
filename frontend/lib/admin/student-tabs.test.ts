import { describe, expect, it } from "vitest";

import {
  STUDENT_TABS,
  resolveStudentTab,
  studentDocumentTitle,
} from "./student-tabs";

describe("resolveStudentTab (#839)", () => {
  it("resolves every tab id from the query string", () => {
    for (const tab of STUDENT_TABS) {
      expect(resolveStudentTab(tab.id)).toBe(tab.id);
    }
  });

  it("opens Billing when the URL asks for it, instead of always Overview", () => {
    // The bug: the active tab lived in local state, so a shared
    // /admin/students/{id}?tab=billing link landed on Overview.
    expect(resolveStudentTab("billing")).toBe("billing");
  });

  it("falls back to Overview for a missing or unknown tab", () => {
    expect(resolveStudentTab(null)).toBe("overview");
    expect(resolveStudentTab(undefined)).toBe("overview");
    expect(resolveStudentTab("")).toBe("overview");
    expect(resolveStudentTab("money")).toBe("overview");
  });
});

describe("studentDocumentTitle (#839)", () => {
  it("titles the page with the student, not the directory", () => {
    expect(studentDocumentTitle("Priya Raman")).toBe("Priya Raman · Students");
  });

  it("falls back to the directory title when the name is not loaded", () => {
    expect(studentDocumentTitle(null)).toBe("Students");
    expect(studentDocumentTitle("   ")).toBe("Students");
  });
});
