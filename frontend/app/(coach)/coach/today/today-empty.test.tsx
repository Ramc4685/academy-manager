import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { todayISO } from "@/lib/coach/marking";
import { queryKeys } from "@/lib/query/keys";

vi.mock("@/lib/offline/use-needs-review-count", () => ({ useQueuedMarkCount: () => 0 }));
vi.mock("@/lib/pwa/vitals", () => ({ reportVitals: () => {} }));

import CoachTodayPage from "./page";

const ACADEMY = {
  name: "Riverside",
  logo_url: null,
  brand_color: null,
  contact_phone: "555-0100",
  contact_email: null,
  timezone: "America/Chicago",
};

function entry(daysAhead: number, extra: Record<string, unknown> = {}) {
  const start = new Date(Date.now() + daysAhead * 86_400_000);
  return {
    session_id: `s${daysAhead}`,
    occurrence_id: `s${daysAhead}:occ`,
    title: "Junior Starters",
    location: "Court 1",
    timezone: "America/Chicago",
    coach_id: "coach-1",
    start_at: start.toISOString(),
    end_at: new Date(start.getTime() + 3_600_000).toISOString(),
    ...extra,
  };
}

function render(schedule: unknown[], today: unknown[] = []) {
  const client = new QueryClient();
  client.setQueryData(queryKeys.coach.today(todayISO()), { date: todayISO(), sessions: today });
  client.setQueryData(queryKeys.coach.schedule(), { sessions: schedule });
  client.setQueryData(queryKeys.coach.academy(), ACADEMY);
  client.setQueryData(queryKeys.coach.profile(), {
    user_id: "coach-1",
    display_name: "Casey",
    email: "casey@example.com",
    phone: null,
  });
  client.setQueryData(queryKeys.coach.pathway(), {
    programs: [
      {
        program_id: "p1",
        name: "Badminton Skill Pathway",
        levels: [1, 2, 3].map((n) => ({
          level_id: `l${n}`,
          sequence: n,
          name: `Level name ${n}`,
          description: "",
          skills: [],
          lessons: [],
        })),
      },
    ],
  });
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <CoachTodayPage />
    </QueryClientProvider>,
  );
}

describe("coach Today with no class today: My week", () => {
  it("on a first day with nothing assigned, says what happens next and who to call", () => {
    const html = render([]);
    expect(html).toContain("No class today.");
    expect(html).toContain("You have no classes yet.");
    expect(html).toContain("Riverside adds you to classes.");
    expect(html).toContain('href="tel:');
    expect(html).toContain("Running late or unwell? Call first.");
    expect(html).toContain("Level 1 · Level name 1");
    expect(html).toContain("See all 3 levels and lessons");
    expect(html).toContain('href="/coach/pathway"');
    expect(html.replace(/<[^>]+>/g, " ")).not.toMatch(/session/i);
  });

  it("lists this week's classes with the plan and the class one tap away", () => {
    const html = render([entry(5), entry(2, { coach_id: "lead-coach", title: "Junior Beginners" })]);
    expect(html).toContain('data-testid="next-class"');
    expect(html.indexOf("Junior Beginners")).toBeLessThan(html.indexOf("Junior Starters"));
    expect(html).toContain("Junior Beginners (assisting)");
    expect(html).toMatch(/IN 2 DAYS/);
    expect(html).toContain("Read the plan");
    expect(html).toContain("/coach/today/plan?date=");
    expect(html).toContain("All upcoming classes");
    expect(html).not.toContain("You have no classes yet.");
  });

  it("with nothing this week, shows the single next class", () => {
    const html = render([entry(12)]);
    expect(html).toContain("Your next class");
    expect(html).toContain('data-testid="next-class"');
  });

  it("a day with classes keeps its list and adds Later this week", () => {
    const html = render([entry(3, { title: "Thursday Squad" })], [
      {
        session_id: "t1",
        occurrence_id: "t1:occ",
        title: "Today Class",
        location: "Court 2",
        start_at: new Date(Date.now() + 3_600_000).toISOString(),
        end_at: new Date(Date.now() + 7_200_000).toISOString(),
        roster: [],
      },
    ]);
    expect(html).toContain("Today Class");
    expect(html).toContain('data-testid="later-this-week"');
    expect(html.indexOf("Today Class")).toBeLessThan(html.indexOf("Thursday Squad"));
    expect(html).not.toContain('data-testid="my-week"');
  });
});
