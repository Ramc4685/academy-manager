"use client";

import Link from "next/link";

export type SessionDetailTab = "attendance" | "skills" | "progress";

const TAB_BUTTON_BASE =
  "whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600";
const TAB_BUTTON_SELECTED = "border-rally-blue text-rally-ink";
const TAB_BUTTON_UNSELECTED = "border-transparent text-rally-muted hover:text-rally-ink";

/**
 * Shared tab strip for coach session detail and its skills/progress
 * subroutes. The skills backend route accepts either an occurrence_id or a
 * session_id (see backend/v2/interfaces/coach/skill_routes.py), so either id
 * is safe to link with here. See docs/audit/plans/UIC5-progress-tabs.md.
 */
export function SessionDetailTabs({
  sessionOrOccurrenceId,
  date,
  active,
}: {
  sessionOrOccurrenceId: string;
  date: string;
  active: SessionDetailTab;
}) {
  const encodedId = encodeURIComponent(sessionOrOccurrenceId);
  const encodedDate = encodeURIComponent(date);
  const tabs: Array<{ id: SessionDetailTab; label: string; href: string }> = [
    {
      id: "attendance",
      label: "Attendance",
      href: `/coach/sessions/${encodedId}?date=${encodedDate}`,
    },
    {
      id: "skills",
      label: "Skills",
      href: `/coach/sessions/${encodedId}/skills?date=${encodedDate}`,
    },
    {
      id: "progress",
      label: "Progress",
      href: `/coach/sessions/${encodedId}/progress?date=${encodedDate}`,
    },
  ];

  return (
    <div
      role="tablist"
      aria-label="Session detail sections"
      className="mb-4 flex gap-1 overflow-x-auto border-b border-neutral-200"
    >
      {tabs.map((tab) => {
        const selected = active === tab.id;
        return (
          <Link
            key={tab.id}
            href={tab.href as Parameters<typeof Link>[0]["href"]}
            role="tab"
            aria-selected={selected}
            id={`session-tab-${tab.id}`}
            className={`${TAB_BUTTON_BASE} ${selected ? TAB_BUTTON_SELECTED : TAB_BUTTON_UNSELECTED}`}
          >
            {tab.label}
          </Link>
        );
      })}
    </div>
  );
}
