"use client";

import type { Route } from "next";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { Card, Overline } from "@/components/ds";
import {
  deletionForFamily,
  deletionSummary,
  fetchAccountDeletions,
} from "@/lib/api/admin-account-deletions";

const KEY = ["admin", "account-deletions"] as const;

function useAccountDeletions() {
  return useQuery({ queryKey: KEY, queryFn: fetchAccountDeletions, staleTime: 60_000 });
}

/** Family page banner: this parent deleted their own account (mobile M5, D4). */
export function AccountDeletionBanner({ familyIds }: { familyIds: (string | null | undefined)[] }) {
  const row = deletionForFamily(useAccountDeletions().data?.deletions, familyIds);
  if (!row) return null;
  return (
    <p
      role="status"
      data-testid="family-account-deleted"
      className="rounded-lg border border-rally-line bg-rally-paper px-3 py-2 text-sm text-rally-ink"
    >
      {deletionSummary(row)} Any balance owed stays on the family and can be collected offline.
    </p>
  );
}

/** Families list: every account deleted in this academy, newest first. */
export function AccountDeletionsCard() {
  const rows = useAccountDeletions().data?.deletions ?? [];
  if (rows.length === 0) return null;
  return (
    <Card p={20} data-testid="admin-account-deletions">
      <Overline>Deleted accounts</Overline>
      <ul className="mt-2 space-y-2 text-sm">
        {rows.map((row) => (
          <li key={row.request_id}>
            <Link
              href={`/admin/families/${encodeURIComponent(row.user_id)}` as Route}
              className="font-semibold text-rally-ink underline-offset-2 hover:underline"
            >
              {row.display_name}
            </Link>
            <span className="text-rally-muted"> · {deletionSummary(row)}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
