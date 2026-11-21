/**
 * Filters for the admin "All classes" list (L2 A0-6). The server returns every
 * class with its phase; narrowing happens here because one academy's catalog
 * is small.
 */

export type SessionPhaseFilter = "any" | "active" | "upcoming" | "ended";

type FilterableSession = {
  title: string;
  location: string;
  coach_name: string | null;
  days_of_week: string[];
  phase?: "active" | "upcoming" | "ended" | null;
};

export function filterSessions<T extends FilterableSession>(
  sessions: T[],
  { phase, text }: { phase: SessionPhaseFilter; text: string },
): T[] {
  const needle = text.trim().toLowerCase();
  return sessions.filter((s) => {
    if (phase !== "any" && s.phase !== phase) return false;
    if (!needle) return true;
    return [s.title, s.location, s.coach_name ?? "", ...s.days_of_week]
      .join(" ")
      .toLowerCase()
      .includes(needle);
  });
}
