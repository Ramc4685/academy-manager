/**
 * Presentation rules for the dashboard setup checklist (roadmap L7).
 * Completion itself is decided by the BFF (`GET /admin/setup-checklist`);
 * this only decides what the card shows.
 */

import type { SetupChecklist, SetupChecklistItem } from "@/lib/api/admin";

export interface SetupChecklistRow extends SetupChecklistItem {
  /** Null when the viewer cannot open the step (owner-only, not owner). */
  link: string | null;
  statusLabel: string;
}

const STATUS_LABEL: Record<SetupChecklistItem["status"], string> = {
  done: "Done",
  todo: "To do",
  unknown: "Couldn't check",
};

/** Hide the card once every step is done, or when the payload is unusable. */
export function shouldShowSetupChecklist(data: SetupChecklist | undefined): boolean {
  if (!data || !Array.isArray(data.items) || data.items.length === 0) return false;
  return !data.complete;
}

/**
 * Open steps first (in the server's order), then done ones. An owner-only
 * step has no link for an admin without the owner scope: its panel would
 * only say "owner only".
 */
export function setupChecklistRows(
  data: SetupChecklist,
  isOwner: boolean,
): SetupChecklistRow[] {
  const rows = data.items.map((item) => ({
    ...item,
    link: item.owner_only && !isOwner ? null : item.href,
    statusLabel: STATUS_LABEL[item.status] ?? item.status,
  }));
  return [...rows.filter((row) => row.status !== "done"), ...rows.filter((row) => row.status === "done")];
}

export function setupChecklistProgress(data: SetupChecklist): string {
  return `${data.done_count} of ${data.total} steps done`;
}
