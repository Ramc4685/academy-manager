import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Issue #865, the People remainder left after #871 landed tappable contacts.
 *
 * Four separate gaps, each one a place where an admin knew a fact the
 * interface would not act on:
 *   1. every Families row carried an outstanding balance and the list would
 *      neither filter to the families who owe nor sort by what they owe;
 *   2. the Students list opened on five stacked KPI cards and ten wrapped
 *      filter chips, so the first student sat below a 400x860 fold;
 *   3. the student Sessions tab was the last admin list still rendering a
 *      bare `<table>` at every width (#847/#857 converted the rest);
 *   4. the shell had no people search at all — three list pages each had
 *      their own box and finding a name meant guessing which one.
 *
 * These pages render behind auth with a live query client, so — matching
 * `admin-lists-are-phone-ready.test.ts` and `people-are-linked.test.ts` —
 * this guards the source text rather than mounting them. Behaviour at a real
 * 400px viewport is covered by the mobile Playwright projects.
 */

const APP = path.resolve(__dirname);
const FRONTEND = path.resolve(__dirname, "..");

const appSource = (rel: string) => readFileSync(path.join(APP, rel), "utf8");
const source = (rel: string) => readFileSync(path.join(FRONTEND, rel), "utf8");

describe("Families can be filtered and sorted by what is owed (#865)", () => {
  const page = () => appSource("(admin)/admin/families/page.tsx");

  it("derives the visible rows through the shared, tested helper", () => {
    expect(page()).toContain("visibleFamilyRows");
  });

  it("offers an Owes money toggle with a stable testid", () => {
    expect(page()).toContain("admin-families-owes-filter");
    expect(page()).toContain("Owes money");
  });

  it("offers a sort control for the outstanding column", () => {
    expect(page()).toContain("admin-families-sort");
    expect(page()).toContain("outstanding_desc");
  });

  it("keeps the client-side narrowing out of the query key, so no new request is made", () => {
    // `status`/`q` go to the backend; owes/sort run over rows already loaded.
    expect(page()).not.toContain("owes_only");
  });
});

describe("the Students header fits a phone (#865)", () => {
  const page = () => appSource("(admin)/admin/students/page.tsx");

  it("scrolls the KPI cards sideways instead of stacking five of them", () => {
    const src = page();
    expect(src).not.toContain('<div className="grid gap-4 md:grid-cols-5">');
    expect(src).toContain("admin-students-kpis");
    expect(src).toMatch(/flex .*overflow-x-auto[^"]*md:grid/);
  });

  it("scrolls the lifecycle chips in one row rather than wrapping ten of them", () => {
    // #897: the row is the shared `FilterBar` now — the page names it, the
    // design system lays it out.
    expect(page()).toContain('testId="admin-students-tabs"');
    const toolbar = source("components/ds/list-toolbar.tsx");
    expect(toolbar).toMatch(/overflow-x-auto[\s\S]{0,80}md:overflow-visible/);
    // The chips must not shrink to fit, or a scrolling row is just a
    // narrower wrap.
    expect(toolbar).toContain("shrink-0");
    expect(toolbar).toContain("whitespace-nowrap");
  });

  it("keeps the 44px chip target #847 gave these filters", () => {
    expect(page()).toContain("<FilterChip");
    expect(source("components/ds/list-toolbar.tsx")).toContain("min-h-touch");
  });
});

describe("the student Sessions tab gets phone rows (#865)", () => {
  const panel = () => appSource("(admin)/admin/students/[studentId]/SessionsPanel.tsx");

  it("swaps the table for PhoneListRow below md", () => {
    const src = panel();
    expect(src).toContain("useIsPhone");
    expect(src).toContain("PhoneListRow");
    // One layout at a time — see `lib/use-is-phone.ts`.
    expect(src).not.toContain("md:hidden");
  });

  it("builds both layouts' actions from the one tested helper", () => {
    // A second derivation is how the phone and the desktop end up disagreeing
    // about what can be done to an enrollment.
    expect(panel()).toContain("enrolledSessionActions");
  });

  it("keeps the enrolled-sessions hook so existing specs still resolve it", () => {
    expect(panel().match(/data-testid="admin-student-enrolled-sessions"/g)?.length).toBe(2);
  });
});

describe("one people search in the admin shell (#865)", () => {
  const shell = () => appSource("(admin)/layout.tsx");
  const widget = () => source("components/admin/PeopleSearch.tsx");

  it("is mounted in the shell", () => {
    expect(shell()).toContain("<PeopleSearch");
    expect(existsSync(path.join(FRONTEND, "components/admin/PeopleSearch.tsx"))).toBe(true);
  });

  it("is a dialog, not a new route — the route manifest is untouched", () => {
    // The shared `Modal` brings the focus trap, the Escape handler and the
    // scroll lock with it; a hand-rolled popover here would be a fourth
    // dialog implementation in the admin shell.
    expect(widget()).toContain("<Modal");
    expect(source("components/ds/modal.tsx")).toContain('role="dialog"');
    expect(existsSync(path.join(APP, "(admin)/admin/search"))).toBe(false);
  });

  it("reads the three existing list endpoints and nothing new", () => {
    const src = widget();
    expect(src).toContain("listAdminStudents");
    expect(src).toContain("fetchBillingSetup");
    expect(src).toContain("listAdminUsers");
    expect(src).toContain("peopleSearchGroups");
  });

  it("debounces and stays closed-quiet, so the shell adds no polling", () => {
    const src = widget();
    expect(src).toContain("300");
    // Nothing is fetched until the box is open AND the query is long enough.
    expect(src).toMatch(/enabled:\s*open && /);
    expect(src).toContain("PEOPLE_SEARCH_MIN_CHARS");
  });

  it("gives the trigger a 44px target and a name", () => {
    const src = widget();
    expect(src).toContain("min-h-touch min-w-touch");
    expect(src).toContain("admin-people-search-open");
  });
});
