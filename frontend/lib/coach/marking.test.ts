import { describe, expect, it } from "vitest";

import {
  coachSessionHref,
  correctionWindowClosed,
  isCancelled,
  markingNotOpenYet,
  markProgress,
  recentUnmarkedSessions,
  withoutUnconfirmedMark,
} from "./marking";

type Row = { student_id: string; attendance_status?: string | null };

function session(
  occurrence_id: string,
  start_at: string,
  roster: Row[],
  extra: Record<string, unknown> = {},
) {
  return {
    session_id: `s-${occurrence_id}`,
    occurrence_id,
    title: "Junior A",
    location: "Court 1",
    start_at,
    end_at: start_at,
    roster,
    ...extra,
  } as never;
}

describe("markProgress", () => {
  it("counts students whose attendance is already recorded", () => {
    const progress = markProgress([
      { student_id: "a", attendance_status: "present" },
      { student_id: "b", attendance_status: "late" },
      { student_id: "c", attendance_status: null },
      { student_id: "d" },
    ]);
    expect(progress).toEqual({ marked: 2, total: 4, complete: false, label: "2/4 marked" });
  });

  it("is complete when every student is marked", () => {
    const progress = markProgress([
      { student_id: "a", attendance_status: "absent" },
      { student_id: "b", attendance_status: "present" },
    ]);
    expect(progress.complete).toBe(true);
    expect(progress.label).toBe("2/2 marked");
  });

  it("treats an empty roster as nothing to mark, not as needing marks", () => {
    const progress = markProgress([]);
    expect(progress).toEqual({ marked: 0, total: 0, complete: true, label: "0/0 marked" });
  });

  it("counts an extra locally-marked student id", () => {
    const progress = markProgress(
      [{ student_id: "a" }, { student_id: "b" }],
      new Set(["a"]),
    );
    expect(progress.label).toBe("1/2 marked");
  });
});

describe("isCancelled", () => {
  it("is true only for the cancelled status", () => {
    expect(isCancelled({ status: "cancelled" })).toBe(true);
    expect(isCancelled({ status: "scheduled" })).toBe(false);
    expect(isCancelled({})).toBe(false);
  });
});

describe("coachSessionHref", () => {
  it("carries the occurrence id and the class's local date", () => {
    expect(coachSessionHref("occ 1", "2026-09-13")).toBe(
      "/coach/sessions/occ%201?date=2026-09-13",
    );
  });

  it("omits the query when no date can be resolved", () => {
    expect(coachSessionHref("occ-1")).toBe("/coach/sessions/occ-1");
  });
});

describe("recentUnmarkedSessions", () => {
  const now = new Date("2026-09-13T12:00:00Z");

  it("keeps classes that started in the last 48h and are not fully marked", () => {
    const rows = recentUnmarkedSessions(
      [
        session("occ-partial", "2026-09-12T18:00:00Z", [
          { student_id: "a", attendance_status: "present" },
          { student_id: "b" },
        ]),
        session("occ-done", "2026-09-12T19:00:00Z", [
          { student_id: "a", attendance_status: "present" },
        ]),
        session("occ-old", "2026-09-10T18:00:00Z", [{ student_id: "a" }]),
        session("occ-future", "2026-09-13T18:00:00Z", [{ student_id: "a" }]),
        session("occ-cancelled", "2026-09-12T20:00:00Z", [{ student_id: "a" }], {
          status: "cancelled",
        }),
        session("occ-empty", "2026-09-12T21:00:00Z", []),
      ],
      now,
    );
    expect(rows.map((s) => s.occurrence_id)).toEqual(["occ-partial"]);
  });

  it("de-duplicates an occurrence returned by two overlapping day queries", () => {
    const rows = recentUnmarkedSessions(
      [
        session("occ-dup", "2026-09-12T20:00:00Z", [{ student_id: "a" }]),
        session("occ-dup", "2026-09-12T20:00:00Z", [{ student_id: "a" }]),
      ],
      now,
    );
    expect(rows).toHaveLength(1);
  });

  it("sorts the most recent class first", () => {
    const rows = recentUnmarkedSessions(
      [
        session("occ-early", "2026-09-12T08:00:00Z", [{ student_id: "a" }]),
        session("occ-late", "2026-09-12T20:00:00Z", [{ student_id: "a" }]),
      ],
      now,
    );
    expect(rows.map((s) => s.occurrence_id)).toEqual(["occ-late", "occ-early"]);
  });
});

describe("voided and held rows", () => {
  it("counts a voided mark as unmarked", () => {
    const progress = markProgress([
      { student_id: "a", attendance_status: "present" },
      { student_id: "b", attendance_status: "voided" },
    ]);
    expect(progress).toEqual({ marked: 1, total: 2, complete: false, label: "1/2 marked" });
  });

  it("does not owe a mark for an unmarked held seat (#1040)", () => {
    const progress = markProgress([
      { student_id: "a", attendance_status: "present" },
      { student_id: "b", attendance_status: null, enrollment_status: "held" },
    ] as never);
    expect(progress).toEqual({ marked: 1, total: 1, complete: true, label: "1/1 marked" });
  });

  it("still counts a held seat that was marked", () => {
    const progress = markProgress([
      { student_id: "b", attendance_status: "absent", enrollment_status: "held" },
    ] as never);
    expect(progress.total).toBe(1);
    expect(progress.complete).toBe(true);
  });
});

describe("marking windows", () => {
  const now = new Date("2026-11-15T12:00:00Z");

  it("closes the coach correction window after 48 hours", () => {
    expect(correctionWindowClosed("2026-11-13T11:59:00Z", now)).toBe(true);
    expect(correctionWindowClosed("2026-11-13T12:01:00Z", now)).toBe(false);
    expect(correctionWindowClosed(null, now)).toBe(false);
  });

  it("opens marking an hour before the class starts", () => {
    expect(markingNotOpenYet("2026-11-16T12:00:00Z", now)).toBe(true);
    expect(markingNotOpenYet("2026-11-15T12:45:00Z", now)).toBe(false);
    expect(markingNotOpenYet("2026-11-15T09:00:00Z", now)).toBe(false);
  });
});

describe("withoutUnconfirmedMark", () => {
  const entry = (pending: boolean, error?: string) => ({
    student_id: "st1",
    status: "present" as const,
    pending,
    error,
  });

  it("drops an optimistic tap whose request died, so the queued state shows", () => {
    expect(withoutUnconfirmedMark({ st1: entry(true) }, "st1")).toEqual({});
  });

  it("drops an errored entry", () => {
    expect(withoutUnconfirmedMark({ st1: entry(false, "boom") }, "st1")).toEqual({});
  });

  it("keeps a confirmed save and other rows", () => {
    const marks = { st1: entry(false), st2: entry(true) };
    expect(withoutUnconfirmedMark(marks, "st1")).toBe(marks);
  });
});
