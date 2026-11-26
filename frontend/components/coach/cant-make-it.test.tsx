import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { queryKeys } from "@/lib/query/keys";

import { CantMakeIt, classDay, CoverRequestedBlock } from "./cant-make-it";

const TZ = "America/Chicago";
const NOW = new Date("2026-12-07T12:00:00Z");
const TUE = "2026-12-08T23:30:00Z";

function render(props: Partial<Parameters<typeof CantMakeIt>[0]>, requestedAt: string | null = null) {
  const client = new QueryClient();
  client.setQueryData(queryKeys.coach.academy(), { name: "Demo Academy", logo_url: null, brand_color: null });
  client.setQueryData(queryKeys.coach.coverRequest("occ-1"), { requested_at: requestedAt });
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <CantMakeIt occurrenceId="occ-1" title="Tuesday Intermediate" startAt={TUE} timezone={TZ} now={NOW} {...props} />
    </QueryClientProvider>,
  );
}

describe("I can't make it (S67)", () => {
  it("is offered on a future class date the coach has not asked about", () => {
    expect(render({})).toContain("I can&#x27;t make it");
    expect(classDay(TUE, TZ)).toBe("Tue, Dec 8");
  });

  it("is not offered once the date has started or is cancelled", () => {
    expect(render({ now: new Date("2026-12-09T00:00:00Z") })).toBe("");
    expect(render({ status: "cancelled" })).toBe("");
  });

  it("shows COVER REQUESTED instead of a second button", () => {
    const html = render({}, "2026-12-07T13:42:00Z");
    expect(html).toContain("Cover requested");
    expect(html).not.toContain("I can&#x27;t make it");
  });

  it("names when the academy was told and links its phone", () => {
    const html = renderToStaticMarkup(
      <CoverRequestedBlock requestedAt="2026-12-07T13:42:00Z" timezone={TZ} phone="(309) 555-0142" />,
    );
    expect(html).toContain("You told the academy at 7:42 AM");
    expect(html).toContain('href="tel:(309) 555-0142"');
  });
});
