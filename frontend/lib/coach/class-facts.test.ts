import { describe, expect, it } from "vitest";

import {
  ageBandLabel,
  classFacts,
  coachPlanHref,
  headcountLabel,
  rosterRowMeta,
  venueLines,
} from "./class-facts";

describe("class facts", () => {
  it("labels a class age span", () => {
    expect(ageBandLabel({ min_age: 8, max_age: 12 })).toBe("Ages 8–12");
    expect(ageBandLabel({ min_age: 13, max_age: null })).toBe("Ages 13+");
    expect(ageBandLabel({ min_age: null, max_age: 9 })).toBe("Up to age 9");
    expect(ageBandLabel(null)).toBeNull();
  });

  it("puts age and level on a roster row only when known", () => {
    expect(rosterRowMeta({ age_years: 9, level_name: "Grip & Control" })).toBe("Age 9 · Grip & Control");
    expect(rosterRowMeta({ age_years: 9 })).toBe("Age 9");
    expect(rosterRowMeta({})).toBe("");
  });

  it("counts children and links the day's plan", () => {
    expect(headcountLabel(1)).toBe("1 child");
    expect(headcountLabel(0)).toBe("0 children");
    expect(coachPlanHref("2026-12-01")).toBe("/coach/today/plan?date=2026-12-01");
  });

  it("summarises a Sessions row with headcount and ages", () => {
    expect(classFacts({ enrolled_count: 8, age_band: { min_age: 8, max_age: 12 } })).toBe(
      "8 children · Ages 8–12",
    );
    expect(classFacts({ enrolled_count: null, age_band: null })).toBe("");
  });
});

describe("venue lines", () => {
  it("lists address, parking and arrival time the owner set", () => {
    expect(
      venueLines({
        venue_address: "12 Court Lane, Normal IL",
        parking_notes: "North lot",
        arrival_minutes_before: 10,
      }),
    ).toEqual(["12 Court Lane, Normal IL", "Parking: North lot", "Arrive 10 minutes before the start"]);
  });

  it("is empty when the class has no venue details", () => {
    expect(venueLines({ venue_address: null, parking_notes: " ", arrival_minutes_before: 0 })).toEqual([]);
  });
});
