import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Issue #897: the People pages' last consistency gaps.
 *
 * Four separate defects, all presentational, none of them reachable without
 * auth and a live query client — so, like `contacts-are-tappable` and
 * `admin-lists-are-phone-ready`, this guards the source text. The two
 * acceptance criteria that are really geometry (a 44px tap target at phone
 * width, the student tabs inside the first screen) are asserted for real in
 * `e2e/specs/admin-students.spec.ts`, which runs on both the mobile and the
 * desktop project.
 */

const APP = path.resolve(__dirname);
const FRONTEND = path.resolve(__dirname, "..");

function appSource(rel: string): string {
  return readFileSync(path.join(APP, rel), "utf8");
}

function source(rel: string): string {
  return readFileSync(path.join(FRONTEND, rel), "utf8");
}

const STUDENTS = "(admin)/admin/students/page.tsx";
const FAMILIES = "(admin)/admin/families/page.tsx";
const USERS = "components/admin/AdminUsersDirectory.tsx";
const STUDENT_DETAIL = "(admin)/admin/students/[studentId]/page.tsx";

/** The hand-rolled "mono Th" className each of the three tables carried a copy of. */
const MONO_TH = /<th className="[^"]*font-mono[^"]*"/;

describe("contact links look tappable at phone width (#897)", () => {
  const src = () => source("components/ds/contact-links.tsx");

  it("gives every link a 44px hit area on a phone and collapses it on desktop", () => {
    expect(src()).toMatch(/min-h-touch/);
    expect(src()).toMatch(/md:min-h-0/);
  });

  it("underlines unconditionally, not only on hover — a phone has no hover", () => {
    expect(src()).toMatch(/\bunderline\b/);
    expect(src()).not.toMatch(/hover:underline/);
  });

  it("names its own colour instead of inheriting the caller's muted text", () => {
    expect(src()).toMatch(/text-rally-cobalt-700/);
  });
});

describe("the three People lists share one toolbar (#897)", () => {
  it("the toolbar parts are design-system exports, not per-page markup", () => {
    expect(source("components/ds/index.ts")).toContain(
      'export { ListToolbar, FilterBar, FilterChip, ToolbarSearch } from "./list-toolbar"',
    );
  });

  it.each([
    ["students", () => appSource(STUDENTS)],
    ["families", () => appSource(FAMILIES)],
    ["users", () => source(USERS)],
  ])("%s uses the shared filter chips and search", (_name, read) => {
    const src = read();
    expect(src).toContain("FilterChip");
    expect(src).toContain("ToolbarSearch");
    expect(src).toContain("list-toolbar");
  });

  it.each([
    ["students", () => appSource(STUDENTS)],
    ["families", () => appSource(FAMILIES)],
    ["users", () => source(USERS)],
  ])("%s renders its table head through the shared Th", (_name, read) => {
    const src = read();
    expect(src).toContain("<Th");
    expect(src).not.toMatch(MONO_TH);
  });
});

describe("every People chip reads in one case (#897)", () => {
  it("students dues chips come from the shared people vocabulary", () => {
    expect(source("lib/people-status.ts")).toContain("DUES_LABELS");
    const src = appSource(STUDENTS);
    expect(src).toContain("duesChip");
    expect(src).not.toContain('label="CURRENT"');
    expect(src).not.toContain('label="OVERDUE"');
  });

  it("users role and status chips stop shouting", () => {
    const src = source(USERS);
    expect(src).not.toContain("toUpperCase()");
    expect(src).toContain("userLoginChip");
  });
});

describe("families can invite everyone who was never invited (#897)", () => {
  const src = () => appSource(FAMILIES);

  it("offers the bulk action from the list toolbar", () => {
    expect(src()).toContain('data-testid="admin-families-bulk-invite"');
  });

  it("sends through the existing per-family invite call, not a new endpoint", () => {
    expect(src()).toContain("inviteBillingSetupParent");
  });

  it("asks first, with the recipient count in the dialog", () => {
    expect(src()).toContain("ConfirmActionDialog");
    expect(src()).toContain("notInvited");
  });
});

describe("the student detail fits a phone's first screen (#897)", () => {
  const src = () => appSource(STUDENT_DETAIL);

  it("lays the stat strip out two-up below sm, not four stacked cards", () => {
    expect(src()).toMatch(/grid grid-cols-2 gap-3/);
  });

  it("moves Stop all classes into an actions menu, away from the contact links", () => {
    const text = src();
    expect(text).toContain("OverflowMenu");
    expect(text).toContain('key: "stop-all-classes"');
    // The dialog itself is untouched — only the trigger moved.
    expect(text).toContain("StopAllClassesDialog");
  });

  it("names the tab strip so a spec can measure where it lands", () => {
    expect(src()).toContain('data-testid="admin-student-tabs"');
  });
});
