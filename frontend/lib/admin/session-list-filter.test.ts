import { describe, expect, it } from "vitest";

import { filterSessions } from "./session-list-filter";

const rows = [
  { title: "Beginners", location: "Court 1", coach_name: "Coach A", days_of_week: ["Mon"], phase: "active" as const },
  { title: "Juniors", location: "Court 2", coach_name: null, days_of_week: ["Sat"], phase: "upcoming" as const },
  { title: "Summer camp", location: "Court 1", coach_name: "Coach B", days_of_week: ["Tue"], phase: "ended" as const },
];

describe("filterSessions (L2 A0-6)", () => {
  it("keeps every phase by default, including ended classes", () => {
    expect(filterSessions(rows, { phase: "any", text: "" })).toHaveLength(3);
  });

  it("narrows by phase", () => {
    expect(filterSessions(rows, { phase: "ended", text: "" }).map((r) => r.title)).toEqual(["Summer camp"]);
  });

  it("matches title, location, coach and day text", () => {
    expect(filterSessions(rows, { phase: "any", text: "coach b" }).map((r) => r.title)).toEqual(["Summer camp"]);
    expect(filterSessions(rows, { phase: "any", text: "sat" }).map((r) => r.title)).toEqual(["Juniors"]);
    expect(filterSessions(rows, { phase: "any", text: "court 1" })).toHaveLength(2);
  });
});
