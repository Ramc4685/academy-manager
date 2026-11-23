import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import type { AdminAttendanceReview } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";

import { AttendanceTab } from "./AttendanceTab";

function render(review: AdminAttendanceReview): string {
  const client = new QueryClient();
  client.setQueryData(queryKeys.admin.inboxAttendance(), review);
  return renderToStaticMarkup(
    createElement(QueryClientProvider, { client }, createElement(AttendanceTab)),
  );
}

const REVIEW: AdminAttendanceReview = {
  missing: [
    {
      occurrence_id: "occ-1",
      session_id: "sess-1",
      session_name: "Juniors Tuesday",
      start_at: "2026-11-18T22:00:00Z",
      enrolled_count: 6,
      href: "/admin/sessions/sess-1?tab=dates&occurrence=occ-1",
    },
  ],
  corrections: [
    {
      attendance_id: "att-1",
      occurrence_id: "occ-2",
      session_id: "sess-1",
      session_name: "Juniors Tuesday",
      start_at: "2026-11-11T22:00:00Z",
      student_name: "Ava Pine",
      status: "voided",
      previous_status: "present",
      corrected_at: "2026-11-20T15:00:00Z",
      corrected_by_name: "Coach Lee",
      reason: "Marked the wrong class",
      href: "/admin/sessions/sess-1?tab=dates&occurrence=occ-2",
    },
  ],
};

describe("AttendanceTab", () => {
  it("links each missing date straight to that class date's attendance", () => {
    const html = render(REVIEW);
    expect(html).toContain('href="/admin/sessions/sess-1?tab=dates&amp;occurrence=occ-1"');
    expect(html).toContain("Juniors Tuesday");
    expect(html).toContain("6 students on the roster, no marks");
    expect(html).toContain("NOT MARKED");
  });

  it("shows who changed a mark, from what, and why", () => {
    const html = render(REVIEW);
    expect(html).toContain('href="/admin/sessions/sess-1?tab=dates&amp;occurrence=occ-2"');
    expect(html).toContain("Ava Pine");
    expect(html).toContain("VOIDED");
    expect(html).toContain("Was Present.");
    expect(html).toContain("by Coach Lee");
    expect(html).toContain("Reason: Marked the wrong class");
  });

  it("says so when there is nothing to review", () => {
    const html = render({ missing: [], corrections: [] });
    expect(html).toContain("Every recent class date has attendance.");
    expect(html).toContain("No attendance corrections.");
  });
});
