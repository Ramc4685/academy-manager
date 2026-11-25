import { formatAcademyDate } from "@/lib/format/academy-time";
import type { LevelTeachingGroup, TeachingAssignment } from "@/lib/api/coach";

/** Why this drill was picked for the group: who it is for, when the batch
 * last did it, and who needs something else. */
export function AssignmentSummary({
  group,
  timezone,
}: {
  group: LevelTeachingGroup;
  /** The session's zone: an evening class's date must not read as the next day. */
  timezone?: string | null;
}) {
  const assignment = group.assignment;
  if (!assignment) return null;
  const sequence = group.level_sequence;
  return (
    <div
      className="space-y-2 rounded-lg border border-rally-line p-3 text-sm"
      data-testid={`plan-assignment-${sequence}`}
    >
      {assignment.cue && (
        <p className="font-medium text-rally-ink" data-testid={`plan-cue-${sequence}`}>
          Cue: {assignment.cue}
        </p>
      )}
      <p className="text-rally-subtle" data-testid={`plan-why-${sequence}`}>
        {`For ${assignment.need_count} of ${group.students.length} ${
          group.students.length === 1 ? "child" : "children"
        }. `}
        {lastTaught(group, assignment, timezone)}
      </p>
      {assignment.is_repeat && (
        <p
          className="inline-flex rounded-full border border-rally-ink px-2 py-0.5 text-xs font-medium text-rally-ink"
          data-testid={`plan-repeat-${sequence}`}
        >
          Repeat: every drill for this group was just done
        </p>
      )}
      {assignment.variations.length > 0 && (
        <div data-testid={`plan-variations-${sequence}`}>
          <p className="text-xs font-medium text-rally-ink">Variation for</p>
          <ul className="mt-1 space-y-0.5 text-xs text-rally-subtle">
            {assignment.variations.map((v) => (
              <li key={v.student_id}>
                {v.student_name}: {v.skill_name}
              </li>
            ))}
          </ul>
        </div>
      )}
      {group.reinforcement && (
        <p className="text-xs text-rally-subtle" data-testid={`plan-reinforcement-${sequence}`}>
          Warm-up from the level below: {group.reinforcement.card.title}
          {group.reinforcement.cue ? ` (${group.reinforcement.cue})` : ""}
        </p>
      )}
    </div>
  );
}

function lastTaught(
  group: LevelTeachingGroup,
  assignment: TeachingAssignment,
  timezone: string | null | undefined,
): string {
  if (!group.history_known) return "No delivery history yet for this group.";
  if (assignment.last_taught_at) {
    return `Last worked on ${formatAcademyDate(assignment.last_taught_at, timezone)}.`;
  }
  return "Not done by this group yet.";
}
