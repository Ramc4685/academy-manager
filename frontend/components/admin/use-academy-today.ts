"use client";

import { useQuery } from "@tanstack/react-query";

import { getAdminAcademy } from "@/lib/api/admin";
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
