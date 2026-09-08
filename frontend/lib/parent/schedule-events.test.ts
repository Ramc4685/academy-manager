import { describe, expect, it } from "vitest";

import type { ParentScheduleEntry } from "@/lib/api/parent";
import {
  CANCELLED_EVENT_COLOR,
  scheduleEntryToEvent,
} from "./schedule-events";

function entry(overrides: Partial<ParentScheduleEntry> = {}): ParentScheduleEntry {
  return {
    occurrence_id: "occ-1",
    session_id: "sess-1",
    session_title: "Thursday 6:00 PM Beginner",
    location: "Court 1",
    start_at: "2026-09-10T23:00:00Z",
    end_at: "2026-09-11T00:00:00Z",
    status: "scheduled",
    coach_name: null,
    ...overrides,
  };
}

describe("scheduleEntryToEvent (#671)", () => {
  it("renders a live class in the child's own colour", () => {
    const event = scheduleEntryToEvent(entry(), {
      childName: "Ana",
      color: "#2563eb",
    });

    expect(event.title).toBe("Ana — Thursday 6:00 PM Beginner");
    expect(event.color).toBe("#2563eb");
  });

  it("marks a cancelled class so the calendar cannot contradict the email", () => {
    const event = scheduleEntryToEvent(entry({ status: "cancelled" }), {
      childName: "Ana",
      color: "#2563eb",
    });

    expect(event.title).toBe("Cancelled — Ana — Thursday 6:00 PM Beginner");
    expect(event.color).toBe(CANCELLED_EVENT_COLOR);
  });
});
