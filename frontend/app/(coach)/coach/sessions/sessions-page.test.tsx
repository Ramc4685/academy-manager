import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { CoachScheduleResponse } from "@/lib/api/coach";
import { queryKeys } from "@/lib/query/keys";

import CoachSessionsPage from "./page";

describe("coach Sessions list", () => {
  it("shows each class's headcount and ages and links its teaching plan", () => {
    const client = new QueryClient();
    const data: CoachScheduleResponse = {
      sessions: [
        {
          session_id: "s1",
          occurrence_id: "s1:2026-12-01:16:00",
          title: "Junior Starters",
          location: "Court 1",
          timezone: "America/Chicago",
          start_at: "2026-12-01T22:00:00Z",
          end_at: "2026-12-01T23:00:00Z",
          enrolled_count: 3,
          age_band: { min_age: 8, max_age: 12 },
        },
      ],
    };
    client.setQueryData(queryKeys.coach.schedule(), data);
    const html = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <CoachSessionsPage />
      </QueryClientProvider>,
    );
    expect(html).toContain("3 children · Ages 8–12");
    const plan = /<a[^>]*data-testid="session-plan-[^"]*"[^>]*>/.exec(html)?.[0] ?? "";
    expect(plan).toContain('href="/coach/today/plan?date=2026-12-01"');
  });
});
