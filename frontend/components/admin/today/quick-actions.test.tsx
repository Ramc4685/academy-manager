import { readFileSync } from "node:fs";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { AdminToday, AdminTodayClass } from "@/lib/api/admin";

import { liveClass, runningLateMessage } from "./format";
import { QuickActionButtons } from "./quick-actions";
import { runningLateChoices } from "./running-late-dialog";

const TZ = "America/Chicago";

function klass(id: string, phase: AdminTodayClass["phase"], names: string[]): AdminTodayClass {
  return {
    occurrence_id: id,
    session_id: `sess-${id}`,
    title: `Class ${id}`,
    location: "Court 1",
    start_at: "2026-11-26T22:30:00Z",
    end_at: "2026-11-26T23:30:00Z",
    status: phase === "cancelled" ? "cancelled" : "scheduled",
    phase,
    cover_requested: false,
    staff_ids: ["coach-1"],
    enrolled_count: names.length,
    here_count: 0,
    absent_count: 0,
    marked_count: 0,
    roster: names.map((full_name) => ({
      student_id: full_name.toLowerCase().replace(/\s/g, "-"),
      full_name,
      kind: "enrolled" as const,
      expected_absent: false,
    })),
  };
}

const TODAY: AdminToday = {
  date: "2026-11-26",
  timezone: TZ,
  classes: [
    klass("done", "finished", ["Early Bird"]),
    klass("now", "now", ["Sam Demo", "Alex Demo"]),
    klass("next", "next", ["Sam Lee"]),
    klass("off", "cancelled", ["Sam Gone"]),
  ],
  tomorrow: { class_count: 0, first_start_at: null },
  messages_waiting: 0,
  health_enabled: true,
};

describe("Today quick actions (S65)", () => {
  const noop = () => {};

  it("shows the four buttons, 64px tall on a phone", () => {
    const html = renderToStaticMarkup(
      <QuickActionButtons isPhone onAbsent={noop} onLate={noop} onSick={noop} onWalkIn={noop} />,
    );
    for (const label of ["Absent", "Running late", "Coach is sick", "New walk-in"]) {
      expect(html).toContain(`>${label}<`);
    }
    expect(html).toContain("grid-cols-2");
    expect(html.match(/min-height:64px/g)).toHaveLength(4);
  });

  it("uses the 38px md buttons on desktop", () => {
    const html = renderToStaticMarkup(
      <QuickActionButtons isPhone={false} onAbsent={noop} onLate={noop} onSick={noop} onWalkIn={noop} />,
    );
    expect(html).not.toContain("height:64px");
    expect(html).toContain("height:38px");
  });

  it("defaults to the class on now, else the next one", () => {
    expect(liveClass(TODAY.classes)?.occurrence_id).toBe("now");
    expect(liveClass(TODAY.classes.filter((c) => c.phase !== "now"))?.occurrence_id).toBe("next");
    expect(liveClass([])).toBeUndefined();
  });

  it("the running-late message says only the child, the class and the time", () => {
    const cls = TODAY.classes[1];
    expect(runningLateMessage("Sam Demo", cls, TZ, "")).toBe("Sam Demo is running late for Class now (4:30 PM).");
    expect(runningLateMessage("Sam Demo", cls, TZ, " about 10 minutes ")).toBe(
      "Sam Demo is running late for Class now (4:30 PM). about 10 minutes",
    );
    expect(runningLateMessage("Sam Demo", cls, TZ, "x".repeat(60)).endsWith(" " + "x".repeat(40))).toBe(true);
  });

  it("offers only children in classes still to happen, filtered by name", () => {
    expect(runningLateChoices(TODAY, "sam").map((c) => c.row.full_name)).toEqual(["Sam Demo", "Sam Lee"]);
    expect(runningLateChoices(TODAY, "").map((c) => c.cls.occurrence_id)).toEqual(["now", "now", "next"]);
    expect(runningLateChoices(undefined, "")).toEqual([]);
  });

  it("Absent reuses the inbox's RecordAbsenceDialog; walk-in reuses QuickAddFamily", () => {
    const src = readFileSync(path.join(__dirname, "quick-actions.tsx"), "utf8");
    expect(src).toContain("<RecordAbsenceDialog");
    expect(src).toContain("<QuickAddFamily");
    // Running late never writes an attendance mark.
    const late = readFileSync(path.join(__dirname, "running-late-dialog.tsx"), "utf8");
    expect(late).not.toMatch(/attendance\(|markAttendance|recordAttendance/i);
  });
});
