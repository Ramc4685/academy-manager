/**
 * Issue #839: the student detail tabs.
 *
 * The active tab used to be local component state, so `?tab=billing` was not a
 * thing you could send anyone and a reload always dropped back to Overview.
 * The tab now lives in the URL; this module holds the pure parts so they can
 * be tested without rendering the page.
 */

export type StudentTab = "overview" | "training" | "sessions" | "billing" | "family";

export const STUDENT_TABS: ReadonlyArray<{ id: StudentTab; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "training", label: "Training" },
  { id: "sessions", label: "Sessions" },
  { id: "billing", label: "Billing" },
  { id: "family", label: "Family & Compliance" },
];

/** The tab a `?tab=` value asks for; Overview for anything unrecognised. */
export function resolveStudentTab(value: string | null | undefined): StudentTab {
  return STUDENT_TABS.some((tab) => tab.id === value) ? (value as StudentTab) : "overview";
}

/**
 * The browser-tab title for a student page. The shell titles every student
 * page "Students", so a handful of open tabs were indistinguishable.
 */
export function studentDocumentTitle(fullName: string | null | undefined): string {
  const name = fullName?.trim();
  return name ? `${name} · Students` : "Students";
}
