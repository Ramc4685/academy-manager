import type { ParentSkillNoteView } from "@/lib/api/parent";
import { formatInAcademyZone } from "@/lib/format/academy-time";

/** The parent's card for coach skill notes (D-15). The coach's "See what the
 * parent sees" preview renders this same component from coach data. */
export function CoachSkillNotesList({
  notes,
  firstName,
}: {
  notes: ParentSkillNoteView[];
  firstName: string;
}) {
  return (
    <section
      data-testid="parent-skill-notes"
      className="rounded-2xl border border-rally-line bg-white p-4"
    >
      <h3 className="font-display text-base font-bold text-rally-ink">
        Skill notes about {firstName}
      </h3>
      {notes.length === 0 ? (
        <p className="mt-2 text-sm text-rally-muted">
          When a coach shares a note about a skill, it shows up here.
        </p>
      ) : (
        <ul className="mt-2 divide-y divide-rally-line">
          {notes.map((n) => (
            <li key={n.note_id} className="py-2" data-testid={`parent-skill-note-${n.note_id}`}>
              <p className="text-xs font-semibold text-rally-muted">
                {n.skill_name} ·{" "}
                {formatInAcademyZone(n.shared_at, undefined, { month: "short", day: "numeric" })}
              </p>
              <p className="mt-1 whitespace-pre-wrap text-sm text-rally-ink">{n.body}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
