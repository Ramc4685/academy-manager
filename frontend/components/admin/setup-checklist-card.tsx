"use client";

/**
 * "Set up your academy" on the admin dashboard (roadmap L7). Reads
 * `GET /admin/setup-checklist`, whose steps are derived from settings the
 * academy already keeps (nothing to tick by hand). The card disappears once
 * every step is done. Owner-only steps (billing rules, Stripe) show their
 * status to every admin but link only for owners.
 *
 * S09: it sits below "Needs your attention", collapsed to one line, and
 * lists only the steps still open, so it never pushes today's work off a
 * phone screen.
 */

import Link from "next/link";
import type { Route } from "next";
import { useQuery } from "@tanstack/react-query";

import { Card } from "@/components/ds/card";
import { Chip, type ChipVariant } from "@/components/ds/chip";
import { ErrorNotice } from "@/components/ds/error-notice";
import { LaneHeader } from "@/components/ds/lane";
import { useIsOwner } from "@/components/admin/owner-context";
import { getAdminSetupChecklist, type SetupChecklistStatus } from "@/lib/api/admin";
import {
  setupChecklistProgress,
  setupChecklistRows,
  shouldShowSetupChecklist,
} from "@/lib/admin/setup-checklist-view";
import { queryKeys } from "@/lib/query/keys";

const STATUS_CHIP: Record<SetupChecklistStatus, ChipVariant> = {
  done: "approved",
  todo: "pending",
  unknown: "expired",
};

export function SetupChecklistCard() {
  const isOwner = useIsOwner();
  const query = useQuery({
    queryKey: queryKeys.admin.setupChecklist(),
    queryFn: () => getAdminSetupChecklist(),
  });

  if (query.isLoading) return null;
  if (query.isError) {
    return (
      <Card p={20} data-testid="dashboard-setup-checklist">
        <LaneHeader title="Set up your academy" />
        <ErrorNotice
          testId="dashboard-setup-checklist-error"
          message="The setup checklist is unavailable right now."
          onRetry={() => void query.refetch()}
          retrying={query.isFetching}
        />
      </Card>
    );
  }
  const data = query.data;
  if (!data || !shouldShowSetupChecklist(data)) return null;

  const rows = setupChecklistRows(data, isOwner);
  return (
    <Card p={16} data-testid="dashboard-setup-checklist">
      <details data-testid="dashboard-setup-checklist-details">
        <summary className="flex min-h-touch cursor-pointer list-none flex-wrap items-center justify-between gap-2 rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-rally-cobalt-600">
          <span className="font-display text-[15px] font-semibold text-rally-ink">
            Set up your academy
          </span>
          <span className="text-sm text-rally-muted" data-testid="dashboard-setup-checklist-progress">
            {setupChecklistProgress(data)}
          </span>
        </summary>
        <ul className="mt-2 divide-y divide-rally-line" data-testid="dashboard-setup-checklist-list">
          {rows.map((row) => {
            const body = (
              <>
                <span className="min-w-0">
                  <span className="block text-sm font-medium text-rally-ink">{row.label}</span>
                  <span className="block text-xs text-rally-muted">
                    {row.link === null ? `${row.detail} The owner finishes this step.` : row.detail}
                  </span>
                </span>
                <Chip variant={STATUS_CHIP[row.status] ?? "expired"} label={row.statusLabel.toUpperCase()} />
              </>
            );
            return (
              <li key={row.key} className="py-2" data-testid={`setup-step-${row.key}`} data-status={row.status}>
                {row.link === null ? (
                  <div className="flex flex-wrap items-center justify-between gap-2">{body}</div>
                ) : (
                  <Link
                    href={row.link as Route}
                    className="flex flex-wrap items-center justify-between gap-2 rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-rally-cobalt-600"
                  >
                    {body}
                  </Link>
                )}
              </li>
            );
          })}
        </ul>
      </details>
    </Card>
  );
}
