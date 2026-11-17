/**
 * #1029: a session's enrolled count is students, not families. Siblings share
 * a parent email and the send deduplicates by address, so the label names
 * students and says siblings get one copy instead of promising N families.
 */
export function sessionAudienceLabel(enrolledCount: number, sessionTitle: string): string {
  const students = enrolledCount === 1 ? "1 student" : `${enrolledCount} students`;
  return `the families of ${students} on ${sessionTitle} (one email per family)`;
}
