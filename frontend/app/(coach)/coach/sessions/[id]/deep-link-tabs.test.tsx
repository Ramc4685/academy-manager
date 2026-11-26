import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { queryKeys } from "@/lib/query/keys";

// A class on another day, opened from a link that carries no ?date=.
const OCC = "s1:2026-12-01:16:00";
const params = { id: encodeURIComponent(OCC) };

vi.mock("next/navigation", () => ({
  useParams: () => params,
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => `/coach/sessions/${params.id}`,
}));

import ClassPage from "./page";
import ProgressPage from "./progress/page";
import SkillsPage from "./skills/page";

/** A promise React's `use` reads synchronously during a static render. */
function settled<T>(value: T): Promise<T> {
  return Object.assign(Promise.resolve(value), { status: "fulfilled", value });
}

function tabHrefs(ui: ReactElement): string[] {
  const client = new QueryClient();
  // Cached only under the class's own date: the class page finds it only if it asks for that date.
  client.setQueryData(queryKeys.coach.today("2026-12-01"), {
    date: "2026-12-01",
    sessions: [
      {
        session_id: "s1",
        occurrence_id: OCC,
        title: "Junior Starters",
        location: "Court 1",
        timezone: "America/Chicago",
        start_at: "2026-12-01T22:00:00Z",
        end_at: "2026-12-01T23:00:00Z",
        status: "scheduled",
        roster: [],
      },
    ],
  });
  const html = renderToStaticMarkup(
    <QueryClientProvider client={client}>{ui}</QueryClientProvider>,
  );
  return [...html.matchAll(/<a[^>]*id="session-tab-[^"]*"[^>]*>/g)].map(
    (m) => /href="([^"]*)"/.exec(m[0])?.[1] ?? "",
  );
}

describe("session tabs without ?date=", () => {
  const pages: Array<[string, ReactElement]> = [
    ["class", <ClassPage key="c" params={settled(params)} searchParams={settled({})} />],
    ["skills", <SkillsPage key="s" params={settled(params)} searchParams={settled({})} />],
    ["progress", <ProgressPage key="p" />],
  ];

  it.each(pages)("the %s page carries the class date on every tab", (_name, ui) => {
    const hrefs = tabHrefs(ui);
    expect(hrefs.length).toBeGreaterThan(0);
    for (const href of hrefs) expect(href).toContain("date=2026-12-01");
  });

  it("the progress tab names the class, not the occurrence", () => {
    const hrefs = tabHrefs(<ProgressPage />);
    expect(hrefs).toContain("/coach/sessions/s1/progress?date=2026-12-01");
  });
});
