/**
 * Tab identity for the admin Inbox (issue #776).
 *
 * Pure, and deliberately outside the page component so the "which tab opens
 * first" rule — the one piece of behaviour an admin notices every morning —
 * can be tested without rendering eight queues.
 */

export type InboxTab =
  | "registrations"
  | "waitlist"
  | "level-ups"
  | "makeups"
  | "trials"
  | "absences"
  | "cancellations"
  | "pauses";

/** Ids match the backend's `INBOX_QUEUE_IDS`; `?tab=` values key off them. */
export const INBOX_TABS: { id: InboxTab; label: string }[] = [
  { id: "registrations", label: "Registrations" },
  { id: "waitlist", label: "Waitlist" },
  { id: "level-ups", label: "Level-ups" },
  { id: "makeups", label: "Makeups" },
  { id: "trials", label: "Trials" },
  { id: "absences", label: "Absences" },
  { id: "cancellations", label: "Cancellations" },
  { id: "pauses", label: "Pauses" },
];

export function isInboxTab(value: string | null): value is InboxTab {
  return Boolean(value) && INBOX_TABS.some((t) => t.id === value);
}

/**
 * The first queue with work, or the first queue when everything is clear.
 *
 * An explicit `?tab=` always wins: a link from the dashboard or a bookmark
 * must land where it says it will, even when that queue happens to be empty.
 */
export function defaultInboxTab(
  requested: string | null,
  counts: Record<string, number> | undefined,
): InboxTab {
  if (isInboxTab(requested)) return requested;
  if (!counts) return INBOX_TABS[0].id;
  return INBOX_TABS.find((t) => (counts[t.id] ?? 0) > 0)?.id ?? INBOX_TABS[0].id;
}
