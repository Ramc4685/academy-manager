import type { ChildPractice, RecapRosterEntry, ReportOutcome } from "@/lib/api/class-recap";

/** Only children marked present or late can be credited with practice. */
export function practiceEligible(roster: RecapRosterEntry[]): RecapRosterEntry[] {
  return roster.filter((r) => r.attendance === "present" || r.attendance === "late");
}

/** Flip one child's practice of one skill; a child with no skills left is dropped. */
export function togglePractice(
  practice: ChildPractice[],
  studentId: string,
  skillId: string,
): ChildPractice[] {
  const current = practice.find((p) => p.student_id === studentId)?.skill_ids ?? [];
  const next = current.includes(skillId)
    ? current.filter((id) => id !== skillId)
    : [...current, skillId];
  const others = practice.filter((p) => p.student_id !== studentId);
  return next.length ? [...others, { student_id: studentId, skill_ids: next }] : others;
}

/**
 * Credit skills to every eligible (present/late) child. Only adds, so a second
 * tap changes nothing and per-child exceptions made after stay editable.
 */
export function creditEveryone(
  practice: ChildPractice[],
  roster: RecapRosterEntry[],
  skillIds: string[],
): ChildPractice[] {
  const eligible = new Set(practiceEligible(roster).map((r) => r.student_id));
  const credited = practice.map((p) =>
    eligible.has(p.student_id)
      ? { ...p, skill_ids: [...new Set([...p.skill_ids, ...skillIds])] }
      : p,
  );
  const missing = [...eligible]
    .filter((id) => !practice.some((p) => p.student_id === id))
    .map((student_id) => ({ student_id, skill_ids: [...skillIds] }));
  return skillIds.length ? [...credited, ...missing] : practice;
}

/** Removing a taught skill also removes it from every child's practice. */
export function withoutSkill(practice: ChildPractice[], skillId: string): ChildPractice[] {
  return practice
    .map((p) => ({ ...p, skill_ids: p.skill_ids.filter((id) => id !== skillId) }))
    .filter((p) => p.skill_ids.length > 0);
}

export function reportOutcomeLabel(outcome: ReportOutcome): string {
  switch (outcome) {
    case "applied":
      return "Added to the recap";
    case "needs_clarification":
      return "Needs a clearer report";
    case "sent_to_owner":
      return "Sent to the owner";
  }
}
