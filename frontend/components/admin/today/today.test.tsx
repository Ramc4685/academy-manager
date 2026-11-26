import { readFileSync } from "node:fs";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { AdminRosterHealth, AdminToday, AdminTodayClass } from "@/lib/api/admin";

import { countLine, normalizeToday, phaseChip } from "./format";
import { PRINT_FOOTER, RosterPrintTable, RosterSheetContent, type RosterHealthState } from "./roster-sheet";
import { HealthCountLine, TodayClassesView, tomorrowLine } from "./today-classes";

const TZ = "America/Chicago";
const NOTE = "Peanut allergy, carries EpiPen";

function klass(overrides: Partial<AdminTodayClass> = {}): AdminTodayClass {
  return {
    occurrence_id: "occ-now",
    session_id: "sess-1",
    title: "Junior Beginners",
    location: "Court 1",
    start_at: "2026-11-26T22:30:00Z",
    end_at: "2026-11-26T23:30:00Z",
    status: "scheduled",
    cancellation_reason: null,
    phase: "now",
    starts_in_minutes: null,
    coach_id: "coach-1",
    coach_name: "Demo Coach",
    cover_coach_name: null,
    cover_requested: false,
    staff_ids: ["coach-1"],
    enrolled_count: 3,
    here_count: 1,
    absent_count: 1,
    marked_count: 2,
    roster: [
      {
        student_id: "alex",
        full_name: "Alex Demo",
        kind: "enrolled",
        attendance: "present",
        expected_absent: false,
        parent_id: "p1",
        parent_name: "Demo Parent",
        parent_phone: "(309) 555-0120",
      },
      {
        student_id: "sam",
        full_name: "Sam Demo",
        kind: "enrolled",
        attendance: "absent",
        expected_absent: false,
        parent_id: "p1",
        parent_name: "Demo Parent",
        parent_phone: "(309) 555-0120",
      },
      {
        student_id: "mia",
        full_name: "Mia Kitwell",
        kind: "trial",
        attendance: null,
        expected_absent: false,
        parent_id: "p2",
        parent_name: "Kit Parent",
        parent_phone: null,
      },
    ],
    ...overrides,
  };
}

function today(classes: AdminTodayClass[]): AdminToday {
  return {
    date: "2026-11-26",
    timezone: TZ,
    classes,
    tomorrow: { class_count: 2, first_start_at: "2026-11-27T15:00:00Z" },
    messages_waiting: 0,
    health_enabled: true,
  };
}

const HEALTH: AdminRosterHealth = {
  occurrence_id: "occ-now",
  declared_count: 1,
  children: [
    {
      student_id: "sam",
      status: "declared",
      note: NOTE,
      emergency_contact_name: "Rosa Demo",
      emergency_contact_phone: "(309) 555-0177",
    },
    { student_id: "alex", status: "none_declared" },
    { student_id: "mia", status: "not_answered" },
  ],
};
const READY: RosterHealthState = { kind: "ready", data: HEALTH };

describe("Today class cards (S64)", () => {
  it("shows the server phase, the time, the coach and the count line", () => {
    const html = renderToStaticMarkup(
      <TodayClassesView
        data={today([
          klass(),
          klass({ occurrence_id: "occ-next", phase: "next", starts_in_minutes: 25, marked_count: 0 }),
          klass({ occurrence_id: "occ-x", phase: "cancelled", cancellation_reason: "Gym flooded" }),
        ])}
        isLoading={false}
        isError={false}
        onOpen={() => {}}
        renderHealth={() => <HealthCountLine count={1} />}
      />,
    );
    expect(html).toContain("Classes today");
    expect(html).toContain("NOW");
    expect(html).toContain("NEXT · in 25 min");
    expect(html).toContain("CANCELLED");
    expect(html).toContain("4:30 PM – 5:30 PM");
    expect(html).toContain("Coach Demo Coach · Court 1");
    expect(html).toContain("3 enrolled · 1 here · 1 absent");
    expect(html).toContain("3 enrolled · not marked yet");
    expect(html).toContain("Gym flooded");
    expect(html).toContain("line-through");
    expect(html).toContain("Tomorrow: 2 classes, first at 9:00 AM.");
    // Health counts on the two live classes only, never on the cancelled one.
    expect(html.match(/1 health note</g)).toHaveLength(2);
    expect(html).toContain('aria-label="Junior Beginners, now, 4:30 PM – 5:30 PM, 3 enrolled, 1 here. Open roster."');
  });

  it("draws no health line when the academy has health off", () => {
    const html = renderToStaticMarkup(
      <TodayClassesView
        data={today([klass()])}
        isLoading={false}
        isError={false}
        healthEnabled={false}
        onOpen={() => {}}
        renderHealth={() => <HealthCountLine count={1} />}
      />,
    );
    expect(html).not.toContain("health note");
  });

  it("empty and error states", () => {
    const empty = renderToStaticMarkup(
      <TodayClassesView data={today([])} isLoading={false} isError={false} onOpen={() => {}} />,
    );
    expect(empty).toContain("No classes today");
    expect(empty).toContain("Tomorrow: 2 classes, first at 9:00 AM.");
    const failed = renderToStaticMarkup(
      <TodayClassesView data={undefined} isLoading={false} isError onOpen={() => {}} />,
    );
    expect(failed).toContain("We could not load today&#x27;s classes.");
  });

  it("phase chips, count line and tomorrow copy", () => {
    expect(phaseChip({ phase: "next", starts_in_minutes: null }).label).toBe("NEXT");
    expect(phaseChip({ phase: "later", starts_in_minutes: null }).label).toBe("LATER");
    expect(phaseChip({ phase: "finished", starts_in_minutes: null }).label).toBe("FINISHED");
    expect(countLine({ enrolled_count: 4, here_count: 0, absent_count: 0, marked_count: 0 })).toBe(
      "4 enrolled · not marked yet",
    );
    expect(tomorrowLine({ class_count: 0, first_start_at: null }, TZ)).toBe("Nothing scheduled tomorrow.");
  });

  it("an e2e catch-all `{}` renders as no classes, not a crash", () => {
    const data = normalizeToday({} as AdminToday, "2026-11-26");
    expect(data?.classes).toEqual([]);
    expect(data?.health_enabled).toBe(false);
  });
});

describe("Roster sheet (S64, D-14)", () => {
  it("lists every child with attendance, tags and a call link", () => {
    const html = renderToStaticMarkup(
      <RosterSheetContent cls={klass()} date="2026-11-26" timezone={TZ} health={READY} />,
    );
    expect(html).toContain("Thu, Nov 26 · 4:30 PM – 5:30 PM · Court 1");
    expect(html).toContain("Print roster");
    expect(html).toContain('href="/admin/sessions/sess-1"');
    expect(html).toContain("PRESENT");
    expect(html).toContain("ABSENT");
    expect(html).toContain("NOT MARKED");
    expect(html).toContain("TRIAL");
    expect(html).toContain('aria-label="Call Demo Parent"');
    expect(html).toContain('href="tel:(309) 555-0120"');
    expect(html).toContain("no phone on file");
    expect(html).toContain("1 health note in this class");
    expect(html).toContain("Health: none declared");
    expect(html).toContain("Health: not answered");
  });

  it("shows the note only after the flag is tapped", () => {
    const closed = renderToStaticMarkup(
      <RosterSheetContent cls={klass()} date="2026-11-26" timezone={TZ} health={READY} />,
    );
    expect(closed).toContain('aria-label="Health note for Sam Demo"');
    expect(closed).toContain('aria-expanded="false"');
    expect(closed).not.toContain(NOTE);

    const open = renderToStaticMarkup(
      <RosterSheetContent cls={klass()} date="2026-11-26" timezone={TZ} health={READY} initialExpanded={["sam"]} />,
    );
    expect(open).toContain('aria-expanded="true"');
    expect(open).toContain(NOTE);
    expect(open).toContain("Emergency contact");
    expect(open).toContain("Rosa Demo");
    expect(open).toContain('href="tel:(309) 555-0177"');
  });

  it("a failed health read shows no flag and asks for a connection", () => {
    const html = renderToStaticMarkup(
      <RosterSheetContent
        cls={klass()}
        date="2026-11-26"
        timezone={TZ}
        health={{ kind: "error", onRetry: () => {}, retrying: false }}
      />,
    );
    expect(html).toContain("Health notes need a connection.");
    expect(html).not.toContain("Health note for");
    expect(html).not.toContain("Health: none declared");
  });

  it("prints the flag and the footer but never the note or the emergency contact", () => {
    const html = renderToStaticMarkup(
      <RosterSheetContent cls={klass()} date="2026-11-26" timezone={TZ} health={READY} initialExpanded={["sam"]} />,
    );
    const start = html.indexOf('data-testid="admin-today-print-table"');
    expect(start).toBeGreaterThan(-1);
    const printed = html.slice(start);
    expect(printed).toContain("Sam Demo ⚑");
    expect(printed).toContain("Alex Demo<");
    expect(printed).toContain(PRINT_FOOTER);
    expect(printed).not.toContain(NOTE);
    expect(printed).not.toContain("Rosa Demo");
    expect(printed).not.toContain("555-0177");
    expect(printed).toContain('scope="col"');
    expect(printed).toContain("<caption");
  });

  it("the print table alone never sees note text", () => {
    const html = renderToStaticMarkup(
      <RosterPrintTable cls={klass()} date="2026-11-26" timezone={TZ} health={READY} declared={(id) => id === "sam"} />,
    );
    expect(html).not.toContain(NOTE);
  });
});

describe("dashboard order (S64, D-20)", () => {
  const src = readFileSync(path.resolve(__dirname, "../../../app/(admin)/admin/page.tsx"), "utf8");

  it("renders Today before Needs your attention and the money tiles", () => {
    const todayAt = src.indexOf("<TodayBlock");
    expect(todayAt).toBeGreaterThan(-1);
    expect(todayAt).toBeLessThan(src.indexOf("Needs your attention"));
    expect(todayAt).toBeLessThan(src.indexOf("dashboard-tile-owed"));
    expect(src.indexOf("<MyFollowUpsCard")).toBeLessThan(src.indexOf("<SetupChecklistCard"));
  });

  it("drops the Sessions today tile and its query", () => {
    expect(src).not.toContain("dashboard-tile-sessions");
    expect(src).not.toContain(`label="Sessions today"`);
    expect(src).not.toContain("listAdminSessions");
  });
});
