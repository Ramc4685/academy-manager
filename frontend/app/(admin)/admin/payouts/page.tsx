"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import {
  listAdminSessions,
  listAdminUsers,
  listPayouts,
  type AdminPayoutView,
  type AdminSessionView,
  type AdminUserView,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { Avatar } from "@/components/ds/avatar";
import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";

function money(cents: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
}

function dateLabel(value: string): string {
  return new Intl.DateTimeFormat("en-US", { timeZone: "UTC" }).format(new Date(value));
}

export default function AdminPayoutsPage() {
  const query = useQuery({ queryKey: queryKeys.admin.payouts(), queryFn: listPayouts });
  const coachesQuery = useQuery({
    queryKey: ["admin", "users", "coach"],
    queryFn: () => listAdminUsers("coach"),
  });
  const sessionsQuery = useQuery({
    queryKey: ["admin", "sessions", "payout-display"],
    queryFn: () => listAdminSessions(),
  });
  const payouts = query.data?.payouts ?? [];
  const coaches = coachesQuery.data?.users ?? [];
  const sessions = sessionsQuery.data?.sessions ?? [];

  return (
    <section data-testid="admin-payouts" className="space-y-5">
      {query.isError ? (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load payouts.
        </p>
      ) : query.isLoading ? (
        <Skeleton />
      ) : payouts.length === 0 ? (
        <p data-testid="admin-payouts-empty" className="text-sm text-rally-subtle">
          No payouts yet.
        </p>
      ) : (
        <Card p={20}>
          <PayoutsTable payouts={payouts} coaches={coaches} sessions={sessions} />
        </Card>
      )}
    </section>
  );
}

function PayoutsTable({
  payouts,
  coaches,
  sessions,
}: {
  payouts: AdminPayoutView[];
  coaches: AdminUserView[];
  sessions: AdminSessionView[];
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-sm">
        <thead>
          <tr className="border-b border-rally-line text-left">
            <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
              Coach
            </th>
            <th className="px-2 pb-3 text-right font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
              Amount
            </th>
            <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
              Period
            </th>
            <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
              Status
            </th>
          </tr>
        </thead>
        <tbody>
          {payouts.map((payout) => {
            const coach = coaches.find((user) => user.user_id === payout.coach_id) ?? null;
            const assignedSessions = sessions.filter((session) => session.coach_id === payout.coach_id).length;
            const coachName = coach?.display_name || coach?.email || "Coach";
            return (
              <tr
                key={payout.payout_id}
                data-testid={`admin-payouts-row-${payout.payout_id}`}
                className="border-b border-rally-line last:border-0"
              >
                <td className="px-2 py-3">
                  <Link
                    href={`/admin/payouts/${payout.payout_id}`}
                    className="flex items-center gap-3 group focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600 rounded"
                    data-testid={`admin-payouts-link-${payout.payout_id}`}
                  >
                    <Avatar name={coachName} size={32} />
                    <div>
                      <div className="font-medium text-rally-ink group-hover:underline">{coachName}</div>
                      <div className="text-xs text-rally-muted">
                        {coach?.email ? `${coach.email} · ` : ""}
                        {payout.sessions_count ?? assignedSessions} session
                        {(payout.sessions_count ?? assignedSessions) === 1 ? "" : "s"} ·{" "}
                        {payout.students_count ?? 0} student
                        {(payout.students_count ?? 0) === 1 ? "" : "s"}
                      </div>
                    </div>
                  </Link>
                </td>
                <td className="px-2 py-3 text-right font-mono font-medium tabular-nums">
                  <div>{money(payout.amount_cents)}</div>
                  {payout.expected_revenue_cents != null ? (
                    <div className="text-xs font-normal text-rally-muted">
                      {money(payout.expected_revenue_cents)} expected
                    </div>
                  ) : null}
                </td>
                <td className="px-2 py-3 font-mono text-xs text-rally-muted">
                  {dateLabel(payout.period_start)} - {dateLabel(payout.period_end)}
                  {payout.rule_label ? <div>{payout.rule_label}</div> : null}
                </td>
                <td className="px-2 py-3">
                  <Chip
                    variant={payout.paid_at ? "paid" : "pending"}
                    label={payout.paid_at ? "PAID" : "PENDING"}
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Skeleton() {
  return (
    <div className="space-y-2">
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-14 animate-pulse rounded-lg bg-rally-paper" />
      ))}
    </div>
  );
}
