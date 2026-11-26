import type { ParentSelfProfile } from "@/lib/api/parent";

/** S23: name what a profile is missing instead of "1 missing". */

const PARENT_GAP_LABELS: Record<string, string> = {
  display_name: "your name",
  phone: "your phone number",
  email_confirmed: "a confirmed email",
};

const CHILD_GAP_LABELS: Record<string, string> = {
  full_name: "name",
  date_of_birth: "date of birth",
  emergency_contact_name: "emergency contact name",
  emergency_contact_phone: "emergency contact phone",
  medical_notes: "medical notes (or \"none\")",
};

/** "a", "a and b", "a, b and c" */
export function listPhrase(items: readonly string[]): string {
  if (items.length <= 1) return items[0] ?? "";
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

export function parentGapLabels(keys: readonly string[]): string[] {
  return keys.map((key) => PARENT_GAP_LABELS[key] ?? key.replace(/_/g, " "));
}

export function childGapLabels(keys: readonly string[]): string[] {
  return keys.map((key) => CHILD_GAP_LABELS[key] ?? key.replace(/_/g, " "));
}

/** Badge text on a profile card: "Missing: your phone number", or null when complete. */
export function gapBadgeText(labels: readonly string[]): string | null {
  return labels.length ? `Missing: ${listPhrase(labels)}` : null;
}

/** The layout banner sentence: "Still needed: your phone number and Lucia's date of birth." */
export function profileGapSummary(profile: Pick<ParentSelfProfile, "gaps" | "children">): string | null {
  const parts = parentGapLabels(profile.gaps.parent);
  for (const [studentId, keys] of Object.entries(profile.gaps.children)) {
    if (!keys.length) continue;
    const name = profile.children.find((c) => c.student_id === studentId)?.full_name?.split(" ")[0];
    const owner = name ? `${name}'s` : "a child's";
    parts.push(`${owner} ${listPhrase(childGapLabels(keys))}`);
  }
  return parts.length ? `Still needed: ${listPhrase(parts)}.` : null;
}
