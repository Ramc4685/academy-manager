import type { QueryClient } from "@tanstack/react-query";

import { markFamilyWrite } from "@/lib/api/admin-families";
import { queryKeys } from "@/lib/query/keys";

export interface EnrollmentChange {
  studentId?: string | null;
  parentId?: string | null;
}

/**
 * S26: one refresh for every enrollment write (add and enroll, hold, return,
 * move), so the student page, the sibling discount, both class rosters (old
 * and new), the classes list and the families list show it without a reload.
 * Rosters are refreshed by prefix: a move's target class is not always known.
 */
export function refreshAfterEnrollmentChange(
  queryClient: QueryClient,
  { studentId, parentId }: EnrollmentChange = {},
): void {
  markFamilyWrite();
  const keys: ReadonlyArray<readonly unknown[]> = [
    ...(studentId ? [queryKeys.admin.studentDetail(studentId)] : []),
    ...(parentId ? [queryKeys.admin.familySiblingDiscount(parentId)] : []),
    ["admin", "enrollments"],
    ["admin", "session"],
    ["admin", "sessions"],
    queryKeys.admin.families(),
  ];
  for (const queryKey of keys) void queryClient.invalidateQueries({ queryKey });
}
