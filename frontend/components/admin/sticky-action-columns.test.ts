import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Issue #747: the admin approval queues (Makeups, Trials, Pauses, Level-ups,
 * Registrations) kept their Approve/Deny/Review column as a plain trailing
 * `<td>`/`<th>` with no `position: sticky`. At 390px — well under each
 * table's `min-w-[...]` — the column scrolled off-screen and was reachable
 * only via horizontal scroll, and the Makeups/Trials/Pauses header was
 * `sr-only` (invisible) on top of that.
 *
 * These tables render behind auth, so — matching the existing pattern in
 * app/shell-safe-area.test.ts — this guards the source text for the sticky
 * class and a visible header label, rather than mounting the component.
 */

const COMPONENTS = path.resolve(__dirname);

function source(rel: string): string {
  return readFileSync(path.join(COMPONENTS, rel), "utf8");
}

describe("admin approval queues keep Approve/Deny sticky and labeled (#747)", () => {
  it("Makeups and Trials tabs (request-queues.tsx) use the sticky actions column", () => {
    const src = source("requests/request-queues.tsx");
    // Two tables (Makeups, Trials) each need a sticky, visibly-labeled header
    // and a sticky action cell — the old markup had `<Th className="sr-only">`.
    expect(src).not.toContain('<Th className="sr-only">Actions</Th>');
    expect(src.match(/<Th className=\{actionHeaderClass\}>Actions<\/Th>/g)?.length).toBe(2);
    expect(src.match(/className=\{`\$\{actionCellClass\} bg-white`\}/g)?.length).toBeGreaterThanOrEqual(2);
  });

  it("PausesTab uses the sticky actions column with a visible header", () => {
    const src = source("requests/PausesTab.tsx");
    expect(src).not.toMatch(/sr-only">Actions/);
    expect(src).toContain("actionHeaderClass");
    expect(src).toContain("actionCellClass");
  });

  it("LevelUpsTab gives the actions header real content and stickiness", () => {
    const src = source("admissions/LevelUpsTab.tsx");
    // The old header array ended with an empty-string column label — worse
    // than sr-only, since it had no accessible name at all.
    expect(src).not.toMatch(/"Status",\s*""\s*\]/);
    expect(src).toContain("actionHeaderClass");
    expect(src).toContain("actionCellClass");
  });

  it("RegistrationsTab's already-visible Review header becomes sticky", () => {
    const src = source("admissions/RegistrationsTab.tsx");
    expect(src).toContain("actionHeaderClass");
    expect(src).toContain("actionCellClass");
  });
});
