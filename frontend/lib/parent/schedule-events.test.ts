import { describe, expect, it } from "vitest";

import type { ParentScheduleEntry } from "@/lib/api/parent";
import {
  CANCELLED_EVENT_COLOR,
  isMonthPublished,
  noClassReason,
  scheduleEntryToEvent,
  scheduleSourceLabel,
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

    expect(event.title).toBe("No class (Class cancelled) — Ana — Thursday 6:00 PM Beginner");
    expect(event.color).toBe(CANCELLED_EVENT_COLOR);
  });

  it("shows the academy's reason for a no-class day", () => {
    const event = scheduleEntryToEvent(
      entry({ status: "cancelled", cancellation_reason: "Gym not available" }),
      { childName: "Ana", color: "#2563eb" },
    );
    expect(event.title).toBe("No class (Gym not available) — Ana — Thursday 6:00 PM Beginner");
  });
});

describe("noClassReason / isMonthPublished", () => {
  it("turns the whole-session code into words", () => {
    expect(noClassReason({ cancellation_reason: "session_cancelled" })).toBe("Class cancelled");
    expect(noClassReason({ cancellation_reason: null })).toBe("Class cancelled");
    expect(noClassReason({ cancellation_reason: " Holiday " })).toBe("Holiday");
  });

  it("treats every month as final when the academy never publishes", () => {
    expect(isMonthPublished("2027-01", null)).toBe(true);
    expect(isMonthPublished("2026-12", "2026-12")).toBe(true);
    expect(isMonthPublished("2027-01", "2026-12")).toBe(false);
  });
});

describe("one-time classes (#1038)", () => {
  it("labels an approved make-up on the calendar", () => {
    const event = scheduleEntryToEvent(entry({ source: "makeup" }), {
      childName: "Ana",
      color: "#2563eb",
    });

    expect(event.title).toBe("Make-up — Ana — Thursday 6:00 PM Beginner");
    expect(event.color).toBe("#2563eb");
  });

  it("labels an approved trial on the calendar", () => {
    const event = scheduleEntryToEvent(entry({ source: "trial" }), {
      childName: "Ana",
      color: "#2563eb",
    });

    expect(event.title).toBe("Trial — Ana — Thursday 6:00 PM Beginner");
  });

  it("keeps a regular class unlabelled", () => {
    expect(scheduleSourceLabel("regular")).toBeNull();
    expect(scheduleSourceLabel(undefined)).toBeNull();
    expect(scheduleSourceLabel("makeup")).toBe("Make-up");
    expect(scheduleSourceLabel("trial")).toBe("Trial");
  });
});

describe("scheduleEntryToEvent reported absence (S17)", () => {
  it("leads the month-grid title with Absent (reported)", () => {
    const event = scheduleEntryToEvent(entry({ absence_reported: true }), {
      childName: "Alex",
      color: "#2563eb",
    });
    expect(event.title.startsWith("Absent (reported) — Alex")).toBe(true);
  });
});
