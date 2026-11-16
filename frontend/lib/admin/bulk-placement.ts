import type { BulkPlacementResult } from "@/lib/api/curriculum";

/** The most students one placement request takes (the backend caps it too). */
export const MAX_BULK_PLACEMENT = 50;

const REFUSAL_COPY: Record<string, string> = {
  "StudentProgress.LevelUpInProgress": "a level-up is being approved right now",
  "StudentProgress.SkillNotOnCurrentLevel": "a credited skill is not on that level",
  "StudentProgress.LevelNotConfigured": "that level is retired or not in this program",
};

/** The selected students still on screen; a filter change can hide some. */
export function visibleSelection(selected: string[], visibleIds: string[]): string[] {
  const visible = new Set(visibleIds);
  return selected.filter((id) => visible.has(id));
}

/** One line for the owner: how many moved, and why any did not. */
export function summarizePlacement(results: BulkPlacementResult[]): string {
  const placed = results.filter((r) => r.outcome === "placed").length;
  const refused = results.filter((r) => r.outcome === "refused");
  const head = `${placed} student${placed === 1 ? "" : "s"} placed.`;
  if (refused.length === 0) return head;
  const reasons = [
    ...new Set(refused.map((r) => REFUSAL_COPY[r.code ?? ""] ?? "it was refused")),
  ];
  return `${head} ${refused.length} not moved: ${reasons.join("; ")}.`;
}
