import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ParentScheduleEntry } from "@/lib/api/parent";
import { calendarSubscribeLinks } from "./AddToCalendar";
import { ScheduleList } from "./ScheduleList";

const NOW = new Date("2026-11-17T12:00:00Z");

function entry(over: Partial<ParentScheduleEntry>): ParentScheduleEntry {
  return {
    occurrence_id: "o1",
    session_id: "s1",
    session_title: "Junior A",
    location: null,
    start_at: "2026-11-20T00:00:00Z",
    end_at: "2026-11-20T01:00:00Z",
    status: "scheduled",
    coach_name: null,
    ...over,
  };
}

function html(rows: ParentScheduleEntry[], publishedThrough: string | null) {
  return renderToStaticMarkup(
    <ScheduleList
      rows={rows.map((e) => ({ entry: e, childName: "Ava" }))}
      timeZone="America/Chicago"
      publishedThrough={publishedThrough}
      now={NOW}
    />,
  );
}

describe("ScheduleList", () => {
  it("marks no-class dates with the academy's reason and hides past dates", () => {
    const out = html(
      [
        entry({ occurrence_id: "past", start_at: "2026-11-01T00:00:00Z", end_at: "2026-11-01T01:00:00Z", session_title: "Old class" }),
        entry({ occurrence_id: "a" }),
        entry({ occurrence_id: "b", start_at: "2026-11-27T00:00:00Z", end_at: "2026-11-27T01:00:00Z", status: "cancelled", cancellation_reason: "Gym not available" }),
      ],
      "2026-11",
    );
    expect(out).not.toContain("Old class");
    expect(out).toContain("Gym not available");
    expect(out).toContain("No class");
    expect(out).toContain("Confirmed");
    expect(out).not.toContain("schedule-month-unconfirmed");
  });

  it("flags months the academy has not published yet", () => {
    const out = html([entry({ start_at: "2026-12-04T00:00:00Z", end_at: "2026-12-04T01:00:00Z" })], "2026-11");
    expect(out).toContain("schedule-month-unconfirmed");
  });
});

describe("ScheduleList ?occurrence= deep link", () => {
  const rows = [
    entry({ occurrence_id: "a" }),
    entry({ occurrence_id: "b", start_at: "2026-11-27T00:00:00Z", end_at: "2026-11-27T01:00:00Z", status: "cancelled" }),
  ];
  const render = (highlight: string | null) =>
    renderToStaticMarkup(
      <ScheduleList
        rows={rows.map((e) => ({ entry: e, childName: "Ava" }))}
        timeZone="America/Chicago"
        publishedThrough="2026-11"
        now={NOW}
        highlightOccurrenceId={highlight}
      />,
    );

  it("outlines exactly the linked date", () => {
    const out = render("b");
    expect(out.match(/data-highlighted="true"/g)).toHaveLength(1);
    expect(out).not.toContain("schedule-occurrence-missing");
  });

  it("says so when the linked date is not this family's upcoming schedule", () => {
    const out = render("someone-elses-occurrence");
    expect(out).toContain("schedule-occurrence-missing");
    expect(out).not.toContain("data-highlighted");
    expect(out).toContain("schedule-row");
  });

  it("is unchanged without a link", () => {
    const out = render(null);
    expect(out).not.toContain("schedule-occurrence-missing");
    expect(out).not.toContain("data-highlighted");
  });
});

describe("calendarSubscribeLinks", () => {
  it("builds webcal, Google and Outlook subscribe links from the https feed", () => {
    const links = calendarSubscribeLinks("https://blno.example.com/api/v2/calendar-feed/p1.sig.ics", "BLNO classes");
    expect(links.apple).toBe("webcal://blno.example.com/api/v2/calendar-feed/p1.sig.ics");
    expect(links.google).toContain(encodeURIComponent("webcal://blno.example.com/api/v2/calendar-feed/p1.sig.ics"));
    expect(links.outlook).toContain("name=BLNO%20classes");
  });
});
