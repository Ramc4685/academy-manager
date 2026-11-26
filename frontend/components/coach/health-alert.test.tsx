import { readFileSync } from "node:fs";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { CoachChildHealth, CoachRosterHealth } from "@/lib/api/coach";
import { shouldPersistQuery } from "@/lib/query/persistence";

import { coachRosterHealthQuery, HealthMarker, HealthStrip, type CoachHealthState } from "./health-alert";

const sam: CoachChildHealth = {
  student_id: "stu-sam",
  full_name: "Sam Demo",
  status: "declared",
  note: "Peanut allergy, carries EpiPen",
  emergency_contact_name: "Rosa Demo",
  emergency_contact_phone: "555-0177",
  parent_name: "Pat Demo",
  parent_phone: "555-0120",
};
const alex: CoachChildHealth = { student_id: "stu-alex", full_name: "Alex Demo", status: "none_declared" };

function ready(children: CoachChildHealth[]): CoachHealthState {
  const data: CoachRosterHealth = {
    occurrence_id: "occ-1",
    declared_count: children.filter((c) => c.status === "declared").length,
    children,
  };
  return { kind: "ready", data, byId: new Map(children.map((c) => [c.student_id, c])) };
}

describe("coach health alerts (S50)", () => {
  it("counts the declared notes in the class", () => {
    const html = renderToStaticMarkup(<HealthStrip state={ready([sam, alex])} />);
    expect(html).toContain('data-testid="health-strip"');
    expect(html).toContain("1 health note in this class");
  });

  it("shows no strip when nobody declared anything", () => {
    expect(renderToStaticMarkup(<HealthStrip state={ready([alex])} />)).toBe("");
  });

  it("says health notes need a connection offline", () => {
    const html = renderToStaticMarkup(<HealthStrip state={{ kind: "offline" }} />);
    expect(html).toContain("Health notes need a connection");
  });

  it("never offers a retry button inside a link", () => {
    const html = renderToStaticMarkup(<HealthStrip state={{ kind: "error", onRetry: () => {} }} retry={false} />);
    expect(html).toContain("Couldn&#x27;t load health notes.");
    expect(html).not.toContain("<button");
  });

  it("marks only a child with a declared note, and tapping reads the note and who to call", () => {
    expect(renderToStaticMarkup(<HealthMarker child={alex} />)).toBe("");
    const closed = renderToStaticMarkup(<HealthMarker child={sam} />);
    expect(closed).toContain('data-testid="health-marker-stu-sam"');
    expect(closed).not.toContain("Peanut");
    const open = renderToStaticMarkup(<HealthMarker child={sam} initialOpen />);
    expect(open).toContain("Peanut allergy, carries EpiPen");
    expect(open).toContain("Emergency contact: Rosa Demo");
    expect(open).toContain('href="tel:555-0177"');
  });

  it("uses a key the persister never stores and drops the data when unused", () => {
    const q = coachRosterHealthQuery("occ-1");
    expect(q.queryKey).toEqual(["coach", "roster-health", "occ-1"]);
    expect(q.gcTime).toBe(0);
    expect(shouldPersistQuery(q.queryKey, "success")).toBe(false);
  });

  it("is never read from a cached coach payload", () => {
    const src = readFileSync(path.join(__dirname, "../../lib/api/coach.ts"), "utf8");
    expect(src).toContain("/coach/roster-health?occurrence_id=");
    expect(src).toMatch(/roster-health[^\n]*\n\s*\{ method: "GET", cache: "no-store" \}/);
  });
});
