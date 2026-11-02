import type { PathwayDashboard } from "@/lib/api/curriculum";

type AlmostThere = PathwayDashboard["almost_there"][number];
type Stuck = PathwayDashboard["stuck"][number];
type Level = PathwayDashboard["levels"][number];

const WEEK_MS = 7 * 24 * 60 * 60 * 1000;

export function weeksAgo(iso: string, now = Date.now()): string {
  const weeks = Math.floor((now - new Date(iso).getTime()) / WEEK_MS);
  return weeks <= 1 ? "a week ago" : `${weeks} weeks ago`;
}

function firstName(name: string): string {
  return name.trim().split(/\s+/)[0] || name;
}

/**
 * Editable starting text for the owner's "Message parent" action. One line:
 * the admin DM composer is a single-line input.
 */
export function almostThereDraft(row: AlmostThere, levels: Level[]): string {
  const kid = firstName(row.student_name);
  const next = levels.find((l) => l.sequence === row.level_sequence + 1);
  const after = next
    ? `Once that clicks, ${kid} moves up to Level ${next.sequence} (${next.name}).`
    : `Once that clicks, ${kid} has finished the whole pathway.`;
  return (
    `Hi! Quick update on ${kid}: just one skill left to finish Level ${row.level_sequence} ` +
    `(${row.level_name}), and it's ${row.missing_skill_name}. ${after} ` +
    `A little practice at home this week would help. Thanks!`
  );
}

/** Editable starting text for the owner's "Offer a 1-on-1" action. */
export function stuckDraft(row: Stuck, now = Date.now()): string {
  const kid = firstName(row.student_name);
  const progress = `${kid} has passed ${row.skills_passed} of ${row.skills_total} skills in Level ${row.level_sequence} (${row.level_name})`;
  const since = row.last_win_at
    ? `, and the last new skill was ${weeksAgo(row.last_win_at, now)}.`
    : `, starting this level ${weeksAgo(row.level_started_at, now)}.`;
  return (
    `Hi! ${progress}${since} Some kids move faster with a bit of one-on-one time, ` +
    `so we'd love to offer ${kid} a 1-on-1 session to get the next skill. ` +
    `Reply here if you're interested and we'll find a time.`
  );
}

/** Opens the admin DM composer for this family with the draft in the box. */
export function composeHref(parentId: string, draft: string): string {
  return `/admin/messages?${new URLSearchParams({ dm: parentId, draft })}#direct`;
}
