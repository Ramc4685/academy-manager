"use client";

/**
 * Admin payout review page (Wave 5).
 *
 * MOCKED occurrence breakdown. Wave 5 Agent A still owns the
 * occurrence-based payout backend. This page renders the review UX
 * today against a deterministic synthetic breakdown so the design,
 * copy, and interaction surfaces can be exercised. Real data flips on
 * when `getAdminPayoutReview` switches to a real fetch (see TODO
 * inside `lib/api/v2/payouts.ts`).
 *
 * The page uses semantic labels for occurrences (`Session #N`,
 * `Coaching block 03`) instead of raw occurrence ids per the Wave 5
 * design rules.
 */

import { useMemo } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft } from "lucide-react";

import {
  listAdminSessions,
  listAdminUsers,
} from "@/lib/api/admin";
import {
  getAdminPayoutReview,
  listAdminPayouts,
  type AdminPayoutReview,
  type PayoutOccurrenceLine,
} from "@/lib/api/v2/payouts";
import { Avatar } from "@/components/ds/avatar";
import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";
import { Overline } from "@/components/ds/typography";

function money(cents: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
}

export default function AdminPayoutReviewPage() {
  const params = useParams<{ payoutId: string }>();
  const payoutId = params?.payoutId ?? "";

  // Look up the summary from the list (avoids a dedicated endpoint
  // until Agent A's detail route ships).
  const listQuery = useQuery({
    queryKey: ["admin", "finance", "payouts"],
    queryFn: listAdminPayouts,
  });
  const coachesQuery = useQuery({
    queryKey: ["admin", "users", "coach"],
    queryFn: () => listAdminUsers("coach"),
  });
  const sessionsQuery = useQuery({
    queryKey: ["admin", "sessions", "payout-review-display"],
    queryFn: () => listAdminSessions(),
  });

  const summary = useMemo(
    () => listQuery.data?.payouts.find((p) => p.payout_id === payoutId) ?? null,
    [listQuery.data, payoutId],
  );

  const reviewQuery = useQuery({
    queryKey: ["admin", "finance", "payouts", payoutId, "review"],
    queryFn: () => getAdminPayoutReview(payoutId, summary!),
    enabled: Boolean(summary),
  });
  const coach = useMemo(
    () => coachesQuery.data?.users.find((user) => user.user_id === summary?.coach_id) ?? null,
    [coachesQuery.data, summary?.coach_id],
  );
  const assignedSessions = useMemo(
    () => sessionsQuery.data?.sessions.filter((session) => session.coach_id === summary?.coach_id).length ?? 0,
    [sessionsQuery.data, summary?.coach_id],
  );
  const coachName = coach?.display_name || coach?.email || "Coach";

  if (!payoutId) {
    return (
      <section className="space-y-4">
        <BackLink />
        <Card p={20}>
          <p className="text-sm text-rally-muted">Missing payout.</p>
        </Card>
      </section>
    );
  }

  if (listQuery.isPending) {
    return (
      <section className="space-y-4">
        <BackLink />
        <Skeleton />
      </section>
    );
  }

  if (listQuery.isError || !summary) {
    return (
      <section className="space-y-4">
        <BackLink />
        <Card p={20}>
          <p role="alert" className="text-sm text-red-700">
            Payout not found.
          </p>
        </Card>
      </section>
    );
  }

  return (
    <section
      className="space-y-6"
      data-testid="admin-payout-review"
      data-payout-id={payoutId}
    >
      <BackLink />
      <MockBanner />
      <Header
        coachName={coachName}
        coachEmail={coach?.email ?? null}
        assignedSessions={assignedSessions}
        amountCents={summary.amount_cents}
        periodStart={summary.period_start}
        periodEnd={summary.period_end}
        paidAt={summary.paid_at}
      />
      {reviewQuery.isPending ? (
        <Skeleton />
      ) : reviewQuery.isError || !reviewQuery.data ? (
        <Card p={20}>
          <p role="alert" className="text-sm text-red-700">
            Could not build payout breakdown.
          </p>
        </Card>
      ) : (
        <Breakdown review={reviewQuery.data} />
      )}
    </section>
  );
}

function MockBanner() {
  return (
    <div
      role="status"
      data-testid="admin-payout-mock-banner"
      className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900"
    >
      <AlertTriangle className="size-4 mt-0.5 shrink-0" aria-hidden="true" />
      <div>
        <strong className="font-semibold">Breakdown is provisional.</strong>{" "}
        Session-level payout details are not available yet. Amounts below are estimated
        from the rolled-up payout total until the detailed payout view is added.
      </div>
    </div>
  );
}

function BackLink() {
  return (
    <Link
      href="/admin/payouts"
      className="inline-flex items-center gap-1.5 text-sm text-rally-muted hover:text-rally-ink focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600 rounded"
    >
      <ArrowLeft className="size-4" aria-hidden="true" />
      <span>All payouts</span>
    </Link>
  );
}

function Header({
  coachName,
  coachEmail,
  assignedSessions,
  amountCents,
  periodStart,
  periodEnd,
  paidAt,
}: {
  coachName: string;
  coachEmail: string | null;
  assignedSessions: number;
  amountCents: number;
  periodStart: string;
  periodEnd: string;
  paidAt: string | null;
}) {
  return (
    <Card p={20}>
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-4 min-w-0">
          <Avatar name={coachName} size={48} />
          <div className="min-w-0">
            <Overline>Coach payout</Overline>
            <h2 className="font-display text-xl font-semibold tracking-[-0.01em] text-rally-ink mt-1">
              {coachName}
            </h2>
            <p className="mt-0.5 text-sm text-rally-muted">
              {coachEmail ? `${coachEmail} · ` : ""}
              {assignedSessions} assigned session{assignedSessions === 1 ? "" : "s"} ·{" "}
              {new Date(periodStart).toLocaleDateString()} - {new Date(periodEnd).toLocaleDateString()}
            </p>
            <div className="mt-1 flex items-center gap-2">
              <Chip
                variant={paidAt ? "paid" : "pending"}
                label={paidAt ? "PAID" : "PENDING"}
              />
              {paidAt && (
                <span className="font-mono text-[11px] text-rally-muted">
                  Paid {new Date(paidAt).toLocaleDateString()}
                </span>
              )}
            </div>
          </div>
        </div>
        <div className="text-right">
          <Overline>Total</Overline>
          <div className="font-mono text-2xl font-semibold tabular-nums text-rally-ink mt-1">
            {money(amountCents)}
          </div>
        </div>
      </div>
    </Card>
  );
}

function Breakdown({ review }: { review: AdminPayoutReview }) {
  return (
    <Card p={0}>
      <div className="flex items-center justify-between border-b border-rally-line px-5 py-4">
        <Overline>Occurrence breakdown ({review.total_occurrences})</Overline>
        <span className="font-mono text-[11px] text-rally-muted">
          {review.total_students_attended} student-attendances
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-sm">
          <thead>
            <tr className="border-b border-rally-line text-left">
              <th className="px-5 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                Occurrence
              </th>
              <th className="px-3 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                Date
              </th>
              <th className="px-3 py-3 text-right font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                Students
              </th>
              <th className="px-3 py-3 text-right font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                Rate
              </th>
              <th className="px-5 py-3 text-right font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                Amount
              </th>
            </tr>
          </thead>
          <tbody>
            {review.lines.map((line) => (
              <PayoutRow key={`${line.occurrence_label}-${line.occurred_at}`} line={line} />
            ))}
          </tbody>
          <tfoot>
            <tr className="bg-neutral-50">
              <td className="px-5 py-3 font-mono text-[11px] font-bold uppercase tracking-overline text-rally-muted" colSpan={4}>
                Total
              </td>
              <td className="px-5 py-3 text-right font-mono font-semibold tabular-nums">
                {money(review.amount_cents)}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
    </Card>
  );
}

function PayoutRow({ line }: { line: PayoutOccurrenceLine }) {
  return (
    <tr className="border-b border-rally-line last:border-0">
      <td className="px-5 py-3">
        <div className="font-medium text-rally-ink">{line.occurrence_label}</div>
        <div className="font-mono text-[10px] text-rally-muted">{line.session_title}</div>
      </td>
      <td className="px-3 py-3 font-mono text-xs text-rally-muted">
        {new Date(line.occurred_at).toLocaleDateString()}
      </td>
      <td className="px-3 py-3 text-right font-mono tabular-nums">{line.students_attended}</td>
      <td className="px-3 py-3 text-right font-mono tabular-nums text-rally-muted">
        {money(line.rate_cents)}
      </td>
      <td className="px-5 py-3 text-right font-mono tabular-nums font-medium">
        {money(line.amount_cents)}
      </td>
    </tr>
  );
}

function Skeleton() {
  return (
    <div className="space-y-2" aria-label="Loading payout">
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="h-14 animate-pulse rounded-lg bg-neutral-100" />
      ))}
    </div>
  );
}
