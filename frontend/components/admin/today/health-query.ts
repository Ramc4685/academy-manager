import { getAdminTodayRosterHealth } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";

/**
 * D-14: a class date's health notes are read fresh every time and dropped as
 * soon as nothing on screen uses them. No stale copy can stand in for a
 * failed read, so a missing flag never means "no notes".
 */
export function rosterHealthQuery(occurrenceId: string) {
  return {
    queryKey: queryKeys.admin.todayRosterHealth(occurrenceId),
    queryFn: () => getAdminTodayRosterHealth(occurrenceId),
    gcTime: 0,
    staleTime: 0,
    refetchOnWindowFocus: false,
    retry: false,
  } as const;
}
