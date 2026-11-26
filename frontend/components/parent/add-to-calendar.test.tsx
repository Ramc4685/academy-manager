import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/parent", () => ({
  getCalendarFeedLink: vi.fn(),
  resetCalendarFeedLink: vi.fn(),
}));

import { queryKeys } from "@/lib/query/keys";
import { AddToCalendar } from "./AddToCalendar";

function html(feed: { url: string } | null): string {
  const client = new QueryClient();
  client.setQueryData([...queryKeys.parent.calendar(), "feed-link"], feed);
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <AddToCalendar academyName="Demo Academy" />
    </QueryClientProvider>,
  );
}

describe("AddToCalendar (S19)", () => {
  it("offers Add to my calendar when the academy has a feed", () => {
    const out = html({ url: "https://demo.example.com/api/v2/calendar-feed/p1.sig.ics" });
    expect(out).toContain('data-testid="add-to-calendar"');
    expect(out).not.toContain("add-to-calendar-unavailable");
  });

  it("says plainly when the calendar feed is not available instead of hiding", () => {
    const out = html(null);
    expect(out).toContain('data-testid="add-to-calendar-unavailable"');
    expect(out).toContain("not available yet");
  });
});
