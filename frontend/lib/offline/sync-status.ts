/**
 * One word for a class screen's attendance state on this phone: are the
 * coach's marks on the server, still on the phone, or stuck?
 *
 * Attention wins over waiting (a stuck mark never sends itself), waiting wins
 * over saved, and a class with nothing marked yet shows nothing.
 */
export type ClassSyncStatus = "saved" | "waiting" | "attention";

export const CLASS_SYNC_LABELS: Record<ClassSyncStatus, string> = {
  saved: "Saved",
  waiting: "Waiting to sync",
  attention: "Needs attention",
};

export function classSyncStatus(state: {
  /** Marks the sync parked in the tray, or a save the server refused. */
  needsAttention: boolean;
  /** Marks queued on the phone, in flight, or held in an undo window. */
  waiting: boolean;
  /** At least one mark the server has confirmed. */
  saved: boolean;
}): ClassSyncStatus | null {
  if (state.needsAttention) return "attention";
  if (state.waiting) return "waiting";
  if (state.saved) return "saved";
  return null;
}
