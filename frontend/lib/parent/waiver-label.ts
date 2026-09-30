import type { ParentWaiverStudentView } from "@/lib/api/parent";

/**
 * UI-7 (critique run 4, leftover 16): the waiver button said only "Accept
 * waiver", so a parent with two children could not tell whom they were
 * signing for. Name the children whose signature is missing or out of date.
 */
export function waiverAcceptLabel(
  students: ReadonlyArray<ParentWaiverStudentView>,
  waiverCount = 1,
): string {
  // Several waivers on the page (Settings Phase 6): one button signs them all.
  const noun = waiverCount > 1 ? "waivers" : "waiver";
  const names = Array.from(
    new Set(
      students
        .filter((s) => s.status === "pending" || s.status === "outdated")
        .map((s) => s.student_name.trim())
        .filter(Boolean),
    ),
  );
  if (names.length === 0) return `Accept ${noun}`;
  if (names.length === 1) return `Accept ${noun} for ${names[0]}`;
  return `Accept ${noun} for ${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}
