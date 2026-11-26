import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { todayISO } from "@/lib/coach/marking";
import { queryKeys } from "@/lib/query/keys";

vi.mock("@/lib/offline/use-needs-review-count", () => ({ useQueuedMarkCount: () => 0 }));
vi.mock("@/lib/pwa/vitals", () => ({ reportVitals: () => {} }));

import CoachTodayPage from "./page";

function render(schedule: unknown[]) {
  const client = new QueryClient();
  client.setQueryData(queryKeys.coach.today(todayISO()), { date: todayISO(), sessions: [] });
  client.setQueryData(queryKeys.coach.schedule(), { sessions: schedule });
  client.setQueryData(queryKeys.coach.academy(), {
    name: "Riverside",
    logo_url: null,
    brand_color: null,
    contact_phone: "555-0100",
    contact_email: null,
  });
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <CoachTodayPage />
    </QueryClientProvider>,
  );
}

describe("coach Today with no class today", () => {
  it("on a first day with nothing assigned, says what happens next and who to call", () => {
    const html = render([]);
    expect(html).toContain("Classes appear here once the academy assigns them.");
    expect(html).toContain("Questions? Call 555-0100.");
  });

  it("with a class coming up, points at it instead of the first-day message", () => {
    const start = new Date(Date.now() + 3 * 86_400_000);
    const html = render([
      {
        session_id: "s1",
        occurrence_id: "s1:later",
        title: "Junior Starters",
        location: "Court 1",
        timezone: "America/Chicago",
        start_at: start.toISOString(),
        end_at: new Date(start.getTime() + 3_600_000).toISOString(),
      },
    ]);
    expect(html).toContain('data-testid="next-class"');
    expect(html).not.toContain("Classes appear here once the academy assigns them.");
  });
});
