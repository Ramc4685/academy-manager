/**
 * Coach "By skill" bulk-update selection (#1042).
 *
 * `null` means the coach has not touched the checkboxes yet, so every student
 * in the group is selected. An empty array means the coach unchecked them all
 * and stays empty; it must never fall back to the whole group.
 */
export type SkillGroupSelection = string[] | null;

/** Selected ids, limited to the students currently in the group. */
export function selectedStudentIds(
  selection: SkillGroupSelection,
  groupStudentIds: readonly string[],
): string[] {
  if (selection === null) return [...groupStudentIds];
  const chosen = new Set(selection);
  return groupStudentIds.filter((id) => chosen.has(id));
}

export function toggleStudent(
  selection: SkillGroupSelection,
  groupStudentIds: readonly string[],
  studentId: string,
  checked: boolean,
): string[] {
  const current = selectedStudentIds(selection, groupStudentIds);
  if (checked)
    return current.includes(studentId) ? current : [...current, studentId];
  return current.filter((id) => id !== studentId);
}
