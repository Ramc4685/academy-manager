/**
 * People CRM Phase 4a: the pure parts of the Notes & follow-ups tab and the
 * dashboard's "My follow-ups" card, kept here so they are tested without
 * rendering. Rules mirror backend/v2/contexts/crm/domain/family_notes.py.
 */
import type { FollowUp, FollowUpBucket } from "@/lib/api/admin-family-crm";
import type { AdminUserView } from "@/lib/api/admin";
import type { ChipVariant } from "@/components/ds";

export const MAX_NOTE_BODY_LEN = 4000;
export const MAX_FOLLOW_UP_TITLE_LEN = 200;

/** Staff who may be assigned a follow-up: active admins and owners. */
export interface StaffOption {
  userId: string;
  label: string;
}

export function staffOptions(users: readonly AdminUserView[]): StaffOption[] {
  return users
    .filter((u) => u.status !== "removed" && u.status !== "suspended")
    .filter((u) => (u.roles ?? [u.role]).some((r) => r === "admin" || r === "owner"))
    .map((u) => ({ userId: u.user_id, label: u.display_name || u.email }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

/** A user id as a name, for note authors and assignees. */
export function staffName(
  options: readonly StaffOption[],
  userId: string,
  meId: string | null | undefined,
): string {
  if (meId && userId === meId) return "You";
  return options.find((o) => o.userId === userId)?.label ?? "A staff member";
}

/** The error to show for a note draft, or null when it can be saved. */
export function noteDraftError(body: string): string | null {
  const text = body.trim();
  if (!text) return "Write something in the note.";
  if (text.length > MAX_NOTE_BODY_LEN) {
    return `A note can be at most ${MAX_NOTE_BODY_LEN} characters.`;
  }
  return null;
}

export interface FollowUpDraft {
  title: string;
  dueOn: string;
  assigneeUserId: string;
}

export function followUpDraftError(draft: FollowUpDraft): string | null {
  const title = draft.title.trim();
  if (!title) return "Say what needs doing.";
  if (title.length > MAX_FOLLOW_UP_TITLE_LEN) {
    return `A follow-up title can be at most ${MAX_FOLLOW_UP_TITLE_LEN} characters.`;
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(draft.dueOn)) return "Pick a due date.";
  if (!draft.assigneeUserId) return "Pick who it is for.";
  return null;
}

/** Open follow-ups first, soonest due first; done ones after, newest done first. */
export function sortFollowUps(rows: readonly FollowUp[]): FollowUp[] {
  return [...rows].sort((a, b) => {
    if (a.status !== b.status) return a.status === "open" ? -1 : 1;
    if (a.status === "open") {
      return a.due_on.localeCompare(b.due_on) || a.created_at.localeCompare(b.created_at);
    }
    return (b.done_at ?? "").localeCompare(a.done_at ?? "");
  });
}

const BUCKET_LABEL: Record<FollowUpBucket, string> = {
  overdue: "Overdue",
  today: "Due today",
  upcoming: "Upcoming",
  done: "Done",
};

export function bucketLabel(bucket: FollowUpBucket): string {
  return BUCKET_LABEL[bucket];
}

const BUCKET_CHIP: Record<FollowUpBucket, ChipVariant> = {
  overdue: "overdue",
  today: "pending",
  upcoming: "draft",
  done: "approved",
};

export function bucketVariant(bucket: FollowUpBucket): ChipVariant {
  return BUCKET_CHIP[bucket];
}

/** "Sep 23" style date for an ISO calendar date, with no timezone shift. */
export function dueLabel(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  if (!y || !m || !d) return isoDate;
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

/** Counts for the dashboard card: overdue and due today among open rows. */
export function queueCounts(rows: readonly FollowUp[]): { overdue: number; today: number } {
  let overdue = 0;
  let today = 0;
  for (const row of rows) {
    if (row.bucket === "overdue") overdue += 1;
    else if (row.bucket === "today") today += 1;
  }
  return { overdue, today };
}
