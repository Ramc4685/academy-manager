import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { CoverOptions, CreditMissedClassResponse } from "@/lib/api/admin";

import { DateBlock } from "./cover-flow";
import {
  cancelResultLine,
  coverResultLine,
  coverReviewLines,
  creditRows,
  creditTotal,
  readyToConfirm,
} from "./cover-flow.logic";

const OPT: CoverOptions = {
  occurrence_id: "occ_1",
  session_id: "ses_1",
  title: "Beginner Tue",
  start_at: "2026-12-08T23:30:00Z",
  end_at: "2026-12-09T00:30:00Z",
  status: "scheduled",
  enrolled_count: 3,
  scheduled_coach: { coach_id: "c_sick", name: "Pat Example" },
  free: [{ coach_id: "c_free", name: "Riley Example" }],
  busy: [{ coach_id: "c_busy", name: "Sam Example", class_title: "Advanced Tue" }],
  families: [
    { parent_id: "p1", family_name: "Demo family", has_email: true },
    { parent_id: "p2", family_name: "Test family", has_email: false },
  ],
} as CoverOptions;

const PREVIEW = {
  occurrence_id: "occ_1",
  start_at: OPT.start_at,
  dry_run: true,
  schedule_changed: false,
  credits_issued: 0,
  credit_total_cents: 3000,
  makeups_reopened: 0,
  trials_reopened: 0,
  roster_entries_removed: 0,
  families: [
    { enrollment_id: "e1", student_name: "Ada Demo", amount_cents: 3000, outcome: "credited" },
    { enrollment_id: "e2", student_name: "Bo Demo", amount_cents: 0, outcome: "already_credited" },
  ],
} as CreditMissedClassResponse;

describe("Coach is sick review (S66)", () => {
  it("names the cover, and only families with an email are emailed", () => {
    expect(coverReviewLines(OPT, "c_free", true)).toEqual([
      "Riley Example covers for Pat Example.",
      "Riley Example is told in the app.",
      "1 family is emailed: Demo family",
    ]);
    expect(coverReviewLines(OPT, "c_free", false)).toContain("Families are not told.");
  });

  it("lists each family's credit from the server preview", () => {
    expect(creditRows(PREVIEW)).toEqual([
      { who: "Ada Demo", credit: "$30.00" },
      { who: "Bo Demo", credit: "already credited" },
    ]);
    expect(creditTotal(PREVIEW)).toBe("$30.00");
  });

  it("holds Confirm until every date has what it needs", () => {
    expect(readyToConfirm({ occ_1: { kind: "leave" } }, {}, {})).toBe(false);
    expect(readyToConfirm({ occ_1: { kind: "cover", coachId: null } }, {}, {})).toBe(false);
    expect(readyToConfirm({ occ_1: { kind: "cover", coachId: "c_free" } }, {}, {})).toBe(true);
    expect(readyToConfirm({ occ_1: { kind: "cancel" } }, {}, { occ_1: "Coach unwell" })).toBe(false);
    expect(readyToConfirm({ occ_1: { kind: "cancel" } }, { occ_1: PREVIEW }, { occ_1: "  " })).toBe(false);
    expect(readyToConfirm({ occ_1: { kind: "cancel" } }, { occ_1: PREVIEW }, { occ_1: "Coach unwell" })).toBe(true);
    expect(
      readyToConfirm({ occ_1: { kind: "cancel" } }, { occ_1: { ...PREVIEW, schedule_changed: true } }, { occ_1: "x" }),
    ).toBe(false);
  });

  it("says what happened per date", () => {
    expect(coverResultLine("Tue, Dec 8", "Riley Example", 2, true)).toBe(
      "Tue, Dec 8: Riley Example is covering. 2 families emailed.",
    );
    expect(cancelResultLine("Tue, Dec 8", 1, 3000, true)).toBe(
      "Tue, Dec 8: cancelled. 1 family credited $30.00. Families and the coach were emailed.",
    );
  });
});

describe("a class date's choices (S66)", () => {
  it("splits free coaches from those teaching then", () => {
    const html = renderToStaticMarkup(
      <DateBlock opt={OPT} timezone="America/Chicago" choice={{ kind: "cover", coachId: null }} onChoice={() => {}} />,
    );
    expect(html).toContain("Free at this time");
    expect(html).toContain("Riley Example");
    expect(html).toContain("Teaching then");
    expect(html).toContain("Sam Example · Advanced Tue");
    expect(html).toContain("Cancel this class date");
    expect(html).toContain("Leave as it is");
  });

  it("explains when nobody is free and disables Assign cover", () => {
    const html = renderToStaticMarkup(
      <DateBlock opt={{ ...OPT, free: [] }} timezone="America/Chicago" choice={{ kind: "leave" }} onChoice={() => {}} />,
    );
    expect(html).toContain("No other coach is free at this time.");
    expect(html).toMatch(/<input type="radio"[^>]*disabled=""/);
  });
});
