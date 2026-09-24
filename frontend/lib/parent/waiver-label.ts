import type { ParentWaiverStudentView } from "@/lib/api/parent";

/**
 * UI-7 (critique run 4, leftover 16): the waiver button said only "Accept
 * waiver", so a parent with two children could not tell whom they were
 * signing for. Name the children whose signature is missing or out of date.
 */
export function waiverAcceptLabel(students: ReadonlyArray<ParentWaiverStudentView>): string {
  const names = students
    .filter((s) => s.status === "pending" || s.status === "outdated")
    .map((s) => s.student_name.trim())
    .filter(Boolean);
  if (names.length === 0) return "Accept waiver";
  if (names.length === 1) return `Accept waiver for ${names[0]}`;
  return `Accept waiver for ${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}
