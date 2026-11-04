import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { AssignedClassView } from "@/lib/api/parent";

import { AssignedClassDetails, OneTimeClassChip } from "./one-time-class";

// Fictional fixture: no real academy, venue or family.
const assigned: AssignedClassView = {
  occurrence_id: "occ-1",
  session_id: "sess-1",
  session_title: "Sample Squad B",
  location: "Court 7",
  start_at: "2026-10-03T22:00:00Z",
  end_at: "2026-10-03T23:00:00Z",
  timezone: "America/Chicago",
  status: "scheduled",
};

function chip(source: string | null | undefined): string {
  return renderToStaticMarkup(createElement(OneTimeClassChip, { source }));
}

function details(props: Parameters<typeof AssignedClassDetails>[0]): string {
  return renderToStaticMarkup(createElement(AssignedClassDetails, props));
}

describe("OneTimeClassChip (#1038)", () => {
  it("renders a blue MAKE-UP chip for a make-up", () => {
    const html = chip("makeup");
    expect(html).toContain("MAKE-UP");
    expect(html).toContain("bg-rally-cobalt-50");
  });

  it("renders a TRIAL chip in a different colour from a make-up", () => {
    const html = chip("trial");
    expect(html).toContain("TRIAL");
    expect(html).toContain("bg-status-yellow-50");
    expect(html).not.toContain("bg-rally-cobalt-50");
  });

  it("renders nothing for a regular class or a payload without source", () => {
    expect(chip("regular")).toBe("");
    expect(chip(undefined)).toBe("");
  });
});

describe("AssignedClassDetails (#1038)", () => {
  it("shows the class, academy-local time and venue for an approved trial", () => {
    const html = details({ kind: "trial", assigned, academyTimezone: null });
    expect(html).toContain('data-testid="assigned-class"');
    expect(html).toContain("TRIAL");
    expect(html).toContain("Sample Squad B");
    expect(html).toContain("Court 7");
    // 22:00Z is 5:00 PM in America/Chicago (CDT) — academy time, not UTC.
    expect(html).toContain("5:00 PM – 6:00 PM CDT");
    expect(html).not.toContain("will not run");
  });

  it("marks a called-off make-up class as cancelled", () => {
    const html = details({
      kind: "makeup",
      assigned: { ...assigned, status: "cancelled" },
      academyTimezone: "America/Chicago",
    });
    expect(html).toContain("MAKE-UP");
    expect(html).toContain("line-through");
    expect(html).toContain("Cancelled — this class will not run");
  });

  it("renders nothing when no class is assigned", () => {
    expect(details({ kind: "makeup", assigned: null, academyTimezone: "America/Chicago" })).toBe("");
  });
});
