import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Source-level guards for issue #896 (run 3 of the 2026-09-21 design
 * critique). Same style as `batch-10c-quick-wins.test.ts`: each assertion
 * pins wiring a rendered test would otherwise need a whole page stub for,
 * and each one fails against the pre-fix source.
 *
 * The colour maths behind the two badge fixes lives in
 * `lib/design/contrast.node-test.mjs`, next to the WCAG helper.
 */
const root = join(__dirname, "..");
const read = (rel: string) => readFileSync(join(root, rel), "utf8");

const STUDENT_DETAIL = "app/(admin)/admin/students/[studentId]/page.tsx";
const PROGRESS = "app/(admin)/admin/students/[studentId]/progress/page.tsx";
const SESSION_DETAIL = "app/(admin)/admin/sessions/[id]/page.tsx";
const ADMIN_LAYOUT = "app/(admin)/layout.tsx";
const SKILL_BOARD = "components/pathway/skill-board.tsx";
const CALENDAR = "components/calendar/PersonaCalendarView.tsx";
const CALENDAR_CSS = "components/calendar/persona-calendar-view.module.css";
const IDENTITY_HEADER = "components/admin/student-identity-header.tsx";

describe("#896 — student stat figures are Outfit, not mono", () => {
  it("SummaryMetric sets its value in the display face", () => {
    const page = read(STUDENT_DETAIL);
    expect(page).not.toMatch(/font-mono text-2xl font-semibold tabular-nums/);
    expect(page).toMatch(/font-display text-2xl font-semibold tabular-nums/);
  });

  it("…and keeps the label as a mono overline", () => {
    expect(read(STUDENT_DETAIL)).toMatch(
      /font-mono text-\[10px\] font-bold uppercase tracking-overline/,
    );
  });
});

describe("#896 — the student Progress page is on the design system", () => {
  it("shares one student identity header with the detail page", () => {
    const header = read(IDENTITY_HEADER);
    expect(header).toContain("Avatar");
    expect(header).toContain("lifecycleLabel");
    expect(header).toContain("lifecycleVariant");
    expect(header).toContain("<Chip");
    expect(read(PROGRESS)).toContain("StudentIdentityHeader");
  });

  it("drops the hand-rolled level-up pill for a Chip", () => {
    const page = read(PROGRESS);
    expect(page).not.toContain("bg-yellow-100");
    expect(page).not.toContain("text-yellow-800");
    expect(page).toMatch(/<Chip\b/);
  });

  it("fills the progress bar with the Rally status green", () => {
    const page = read(PROGRESS);
    expect(page).not.toMatch(/\bbg-green-500\b/);
    expect(page).toContain("bg-status-green-500");
  });

  it("builds the skill-count tiles from tokens and BigNum, not raw hexes", () => {
    const page = read(PROGRESS);
    for (const hex of ["#059669", "#d97706", "#9ca3af"]) {
      expect(page).not.toContain(hex);
    }
    expect(page).toContain("BigNum");
    expect(page).toContain("status-green");
    expect(page).toContain("status-amber");
    expect(page).toContain("status-slate");
  });

  it("uses the AA red for the Required flag (red-600 on red-50 is 4.41:1)", () => {
    const page = read(PROGRESS);
    expect(page).not.toContain("text-red-600");
    expect(page).not.toContain("bg-red-50");
    expect(page).toContain("status-red-800");
  });
});

describe("#896 — the skill board uses shared DS pills", () => {
  it("renders the level-up Ready flag as a Chip", () => {
    const board = read(SKILL_BOARD);
    expect(board).not.toContain("bg-green-100");
    expect(board).not.toContain("text-green-700");
    expect(board).toMatch(/<Chip\b/);
  });

  it("leaves the status swatch tokens alone (owned by #895)", () => {
    const board = read(SKILL_BOARD);
    expect(board).toContain("STATUS_GLYPH");
    expect(board).toContain("border-2 border-status-green-800");
  });
});

describe("#896 — the phone calendar is not stock FullCalendar", () => {
  it("defaults to a single-day view on a phone", () => {
    const view = read(CALENDAR);
    expect(view).toContain("useIsPhone");
    expect(view).toContain("dayGridDay");
    // initialView only applies at mount, so the breakpoint has to remount.
    expect(view).toMatch(/key=\{/);
    expect(view).not.toMatch(/initialView="dayGridMonth"/);
  });

  it("gives the toolbar 44px touch targets", () => {
    const css = read(CALENDAR_CSS);
    expect(css).toMatch(/\.fc-button[^}]*\{[^}]*min-height:\s*44px/s);
  });

  it("keeps every rule scoped to this component, so AdminCalendarView is untouched", () => {
    const css = read(CALENDAR_CSS).replace(/\/\*[\s\S]*?\*\//g, "");
    // Every rule head in the module — media queries excluded, their inner
    // rules are matched on their own lines.
    const selectors = (css.match(/[^{}@]+\{/g) ?? []).filter(
      (head) => head.includes(":global(") || head.includes(".fc"),
    );
    expect(selectors.length).toBeGreaterThan(0);
    for (const selector of selectors) {
      expect(selector.trim().startsWith(".wrap")).toBe(true);
    }
    expect(read("components/admin/AdminCalendarView.tsx")).not.toContain(
      "persona-calendar-view.module.css",
    );
  });
});

describe("#896 — nav and roster badges clear AA", () => {
  it("the sidebar count badge sits on an opaque token", () => {
    const layout = read(ADMIN_LAYOUT);
    expect(layout).not.toContain("rgba(255,255,255,0.08)");
    const badge = layout.slice(
      layout.indexOf("{item.count != null"),
      layout.indexOf("function renderNavIcon"),
    );
    // Every fill the badge can take is an opaque token, never an overlay.
    const fills = badge.match(/var\(--rally-[a-z-]+\)/g) ?? [];
    expect(fills).toContain("var(--rally-night-line)");
    expect(fills).toContain("var(--rally-night)");
    expect(badge).not.toMatch(/rgba\(/);
  });

  it("the roster tab count is ink on the line fill, not muted", () => {
    const page = read(SESSION_DETAIL);
    expect(page).not.toMatch(/bg-rally-line[^"]*text-rally-muted/);
    expect(page).toMatch(/bg-rally-line[^"]*text-rally-ink/);
  });
});

describe("#896 — the phone drawer has 44px rows", () => {
  it("NavRow is touch-sized below lg and keeps desktop density above it", () => {
    const layout = read(ADMIN_LAYOUT);
    const navRow = layout.slice(layout.indexOf("function NavRow"));
    const className = navRow.match(/className="([^"]*)"/)?.[1] ?? "";
    expect(className).toContain("min-h-touch");
    expect(className).toContain("lg:min-h-0");
    // The desktop sidebar's own 32px row (issue #842) must survive.
    expect(navRow).toMatch(/py-1\.5/);
  });
});
