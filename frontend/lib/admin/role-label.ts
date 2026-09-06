/**
 * Human labels for academy roles. Role literals are snake_case on the wire
 * (`assistant_coach`), so a CSS `capitalize` renders "Assistant_coach"; every
 * admin surface that prints a role should go through here instead.
 */
const ROLE_LABELS: Record<string, string> = {
  admin: "Admin",
  owner: "Owner",
  coach: "Coach",
  assistant_coach: "Assistant coach",
  parent: "Parent",
  student: "Student",
};

export function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role.replace(/_/g, " ");
}
