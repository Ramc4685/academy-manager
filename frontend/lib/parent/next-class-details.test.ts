import { describe, expect, it } from "vitest";

import type { ParentHomeNextSession } from "@/lib/api/parent-home";
import { directionsHref, nextClassDetails } from "./next-class-details";

const next: ParentHomeNextSession = {
  occurrence_id: "occ-1",
  session_id: "s-1",
  session_title: "Junior Beginners",
  location: "Court 2",
  start_at: "2026-11-28T16:00:00Z",
  end_at: "2026-11-28T17:00:00Z",
  coach_name: "Pat Coach",
  venue_address: "100 Example Gym Rd, Normal IL",
  parking_notes: "North lot",
  what_to_bring: "Water bottle, sneakers",
  arrival_minutes_before: 15,
};

describe("nextClassDetails (S45)", () => {
  it("shows the first-class card until the first attended class, then only the disclosure", () => {
    const before = nextClassDetails(next, true)!;
    expect(before.firstClass).toBe(true);
    expect(before.rows.map((r) => r.label)).toEqual([
      "Where",
      "Parking",
      "What to bring and wear",
      "Arrive",
      "Coach",
    ]);
    expect(nextClassDetails(next, false)!.firstClass).toBe(false);
  });

  it("builds a directions link from the address and hides an empty block", () => {
    expect(directionsHref("100 Example Gym Rd, Normal IL")).toBe(
      "https://www.google.com/maps/search/?api=1&query=100%20Example%20Gym%20Rd%2C%20Normal%20IL",
    );
    expect(directionsHref("  ")).toBeNull();
    const bare = { ...next, coach_name: null, venue_address: null, parking_notes: null, what_to_bring: null, arrival_minutes_before: null };
    expect(nextClassDetails(bare, true)).toBeNull();
    expect(nextClassDetails(null, true)).toBeNull();
  });
});
