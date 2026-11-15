"use client";

import { useQuery } from "@tanstack/react-query";

import { getAdminAcademy } from "@/lib/api/admin";
import { academyDateISO } from "@/lib/format/academy-time";
import { queryKeys } from "@/lib/query/keys";

/**
 * The academy's IANA zone, from the same cached `/admin/academy` read the
 * admin shell already makes (no extra request). Null until it loads.
 */
export function useAcademyTimezone(): string | null {
  const { data } = useQuery({
    queryKey: queryKeys.admin.academy(),
    queryFn: getAdminAcademy,
    staleTime: 5 * 60_000,
  });
  return data?.timezone ?? null;
}

/** Today ("YYYY-MM-DD") on the academy's clock: the default for admin date fields. */
export function useAcademyToday(): string {
  return academyDateISO(useAcademyTimezone());
}
