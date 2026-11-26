import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("date=2026-12-01"),
}));

import type { TeachingPlanResponse } from "@/lib/api/coach";
import { queryKeys } from "@/lib/query/keys";

import CoachTeachingPlanPage from "./page";

function render(plan: TeachingPlanResponse): string {
  const client = new QueryClient();
  client.setQueryData(queryKeys.coach.todayPlan("2026-12-01"), plan);
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <CoachTeachingPlanPage />
    </QueryClientProvider>,
  );
}

const SESSION = {
  session_id: "s1",
  occurrence_id: "s1:2026-12-01:17:30",
  title: "Tuesday Intermediate",
  location: "Court 2",
  start_at: null,
  end_at: null,
  groups: [],
  unplaced: [
    { student_id: "tej", student_name: "Tej Walkin" },
    { student_id: "lucia", student_name: "Lucia Alvarez" },
  ],
};

describe("coach teaching plan (S15 persona follow-up)", () => {
  it("says why the plan is empty when nobody in the class is placed", () => {
    const html = render({
      date: "2026-12-01",
      program_id: "p",
      program_name: "Badminton",
      pathway_configured: true,
      sessions: [SESSION] as TeachingPlanResponse["sessions"],
    });
    expect(html).toContain("Tej Walkin");
    expect(html).toContain('data-testid="plan-all-unplaced"');
    expect(html).toContain("the academy office places children");
  });
});
