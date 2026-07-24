"use client";

import Link from "next/link";

import { buildStudentProgressHref } from "@/lib/navigation/admin-student-progress-return";

export type StudentDetailTabId =
  | "overview"
  | "training"
  | "sessions"
  | "billing"
  | "family";

export type StudentDetailTab = StudentDetailTabId | "progress";

const STATE_TABS: Array<{ id: StudentDetailTabId; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "training", label: "Training" },
  { id: "sessions", label: "Sessions" },
  { id: "billing", label: "Billing" },
  { id: "family", label: "Family & Compliance" },
];

const STATE_TAB_IDS: readonly StudentDetailTabId[] = STATE_TABS.map((tab) => tab.id);

export function parseStudentDetailTabId(value: string | null | undefined): StudentDetailTabId {
  return (STATE_TAB_IDS as readonly string[]).includes(value ?? "")
    ? (value as StudentDetailTabId)
    : "overview";
}

const TAB_BUTTON_BASE =
  "whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600";
const TAB_BUTTON_SELECTED = "border-rally-blue text-rally-ink";
const TAB_BUTTON_UNSELECTED = "border-transparent text-rally-muted hover:text-rally-ink";

/**
 * Shared tab strip for the student detail screen and its progress subroute.
 * State tabs (overview/training/sessions/billing/family) switch client-side
 * state when `onChangeTab` is provided; the Progress tab always links to the
 * standalone `/progress` route. See docs/audit/plans/UIC5-progress-tabs.md.
 */
export function StudentDetailTabs({
  studentId,
  active,
  onChangeTab,
}: {
  studentId: string;
  active: StudentDetailTab;
  onChangeTab?: (tab: StudentDetailTabId) => void;
}) {
  const detailHref = `/admin/students/${encodeURIComponent(studentId)}`;
  const progressHref = buildStudentProgressHref({
    studentId,
    returnTo: detailHref,
    returnLabel: "Back to student profile",
  });

  return (
    <div
      role="tablist"
      aria-label="Student record sections"
      className="flex gap-1 overflow-x-auto border-b border-neutral-200"
    >
      {STATE_TABS.map((tab) => {
        const selected = active === tab.id;
        const className = `${TAB_BUTTON_BASE} ${selected ? TAB_BUTTON_SELECTED : TAB_BUTTON_UNSELECTED}`;

        if (onChangeTab) {
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={selected}
              aria-controls={`student-tabpanel-${tab.id}`}
              id={`student-tab-${tab.id}`}
              className={className}
              onClick={() => onChangeTab(tab.id)}
            >
              {tab.label}
            </button>
          );
        }

        const linkHref = tab.id === "overview" ? detailHref : `${detailHref}?tab=${tab.id}`;

        return (
          <Link
            key={tab.id}
            href={linkHref as Parameters<typeof Link>[0]["href"]}
            role="tab"
            aria-selected={selected}
            id={`student-tab-${tab.id}`}
            className={className}
          >
            {tab.label}
          </Link>
        );
      })}
      <Link
        href={progressHref as Parameters<typeof Link>[0]["href"]}
        role="tab"
        aria-selected={active === "progress"}
        id="student-tab-progress"
        className={`${TAB_BUTTON_BASE} ${active === "progress" ? TAB_BUTTON_SELECTED : TAB_BUTTON_UNSELECTED}`}
      >
        Progress
      </Link>
    </div>
  );
}
