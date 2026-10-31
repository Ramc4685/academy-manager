"use client";

/**
 * "My follow-ups" on the admin dashboard (People CRM Phase 4a): the signed-in
 * staff member's open follow-ups that are overdue or due today, soonest
 * first, each linking to its family's Notes & follow-ups tab. Reads
 * `GET /admin/follow-ups?assignee=me` (open only) and keeps the overdue and
 * today rows; upcoming ones stay on the family record.
 */

import Link from "next/link";
import type { Route } from "next";
import { useQuery } from "@tanstack/react-query";

import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";
import { ErrorNotice } from "@/components/ds/error-notice";
import { LaneHeader } from "@/components/ds/lane";
import { fetchFollowUpQueue } from "@/lib/api/admin-family-crm";
import { queryKeys } from "@/lib/query/keys";
import {
  bucketLabel,
  bucketVariant,
  dueLabel,
  queueCounts,
} from "@/app/(admin)/admin/families/[parentId]/family-notes";

const SHOWN = 8;

export function MyFollowUpsCard() {
  const queue = useQuery({
    queryKey: queryKeys.admin.followUpQueue("me", null),
    queryFn: () => fetchFollowUpQueue("me"),
  });
  const due = (queue.data?.follow_ups ?? []).filter(
    (row) => row.bucket === "overdue" || row.bucket === "today",
  );
  const counts = queueCounts(due);

  return (
    <Card p={20} data-testid="dashboard-my-follow-ups">
      <LaneHeader title="My follow-ups" />
      {queue.isLoading ? (
        <p className="text-sm text-rally-muted">Loading…</p>
      ) : queue.isError ? (
        <ErrorNotice
          testId="dashboard-my-follow-ups-error"
          message="Your follow-ups are unavailable right now. This is not an empty list."
          onRetry={() => void queue.refetch()}
          retrying={queue.isFetching}
        />
      ) : due.length === 0 ? (
        <p className="text-sm text-rally-muted" data-testid="dashboard-my-follow-ups-empty">
          Nothing overdue or due today.
        </p>
      ) : (
        <>
          <p className="mb-2 text-sm text-rally-muted" data-testid="dashboard-my-follow-ups-counts">
            {counts.overdue} overdue, {counts.today} due today
          </p>
          <ul className="divide-y divide-rally-line" data-testid="dashboard-my-follow-ups-list">
            {due.slice(0, SHOWN).map((row) => (
              <li key={row.follow_up_id} className="py-2">
                <Link
                  href={
                    `/admin/families/${encodeURIComponent(row.parent_id)}?tab=notes` as Route
                  }
                  className="flex flex-wrap items-center justify-between gap-2 rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-rally-cobalt-600"
                  data-testid={`dashboard-follow-up-${row.follow_up_id}`}
                >
                  <span className="min-w-0">
                    <span className="block text-sm font-medium text-rally-ink">{row.title}</span>
                    <span className="block text-xs text-rally-muted">
                      {row.family_name ?? "Family"} · due {dueLabel(row.due_on)}
                    </span>
                  </span>
                  <Chip variant={bucketVariant(row.bucket)} label={bucketLabel(row.bucket)} />
                </Link>
              </li>
            ))}
          </ul>
          {due.length > SHOWN && (
            <p className="mt-2 text-xs text-rally-muted">
              And {due.length - SHOWN} more on their family records.
            </p>
          )}
        </>
      )}
    </Card>
  );
}
