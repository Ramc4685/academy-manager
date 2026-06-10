"use client";

/**
 * Admin payout review page.
 *
 * Renders the persisted payout period behind a payouts-list row.
 * Opening the page materialises the draft period for the coach+window
 * if it does not exist yet (`generatePayoutPeriod` is idempotent), so
 * the breakdown is always the real line-level record — not a derived
 * estimate.
 *
 * Admin corrections live here too: recompute (draft), reopen with a
 * required reason (approved/paid), per-line amount override with a
 * required reason (draft), and the audit trail those actions write.
 */

import { useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, History, Pencil, RefreshCw, RotateCcw, Undo2 } from "lucide-react";

import { listAdminUsers } from "@/lib/api/admin";
import {
  generatePayoutPeriod,
  approvePayoutPeriod,
  getPayoutAuditTrail,
  listAdminPayouts,
  overridePayoutLine,
  recomputePayoutPeriod,
  reopenPayoutPeriod,
  type AdminPayoutPeriodLineView,
  type AdminPayoutPeriodView,
  type PayoutAuditEntryView,
} from "@/lib/api/v2/payouts";
import { Avatar } from "@/components/ds/avatar";
import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";
import { Overline } from "@/components/ds/typography";

function money(cents: number, currency = "USD"): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(cents / 100);
}

const STATUS_CHIP: Record<AdminPayoutPeriodView["status"], { variant: "paid" | "pending"; label: string }> = {
  draft: { variant: "pending", label: "DRAFT" },
  approved: { variant: "pending", label: "APPROVED" },
  paid: { variant: "paid", label: "PAID" },
};

export default function AdminPayoutReviewPage() {
  const params = useParams<{ payoutId: string }>();
  const payoutId = params?.payoutId ?? "";
  const queryClient = useQueryClient();

  // The payouts list row carries the coach + window for this payout.
  const listQuery = useQuery({
    queryKey: ["admin", "finance", "payouts"],
    queryFn: listAdminPayouts,
  });
  const coachesQuery = useQuery({
    queryKey: ["admin", "users", "coach"],
    queryFn: () => listAdminUsers("coach"),
  });

  const summary = useMemo(
    () => listQuery.data?.payouts.find((p) => p.payout_id === payoutId) ?? null,
    [listQuery.data, payoutId],
  );

  const periodQuery = useQuery({
    queryKey: ["admin", "payout-periods", summary?.coach_id, summary?.period_start, summary?.period_end],
    queryFn: () =>
      generatePayoutPeriod({
        coach_id: summary!.coach_id,
        period_start: summary!.period_start,
        period_end: summary!.period_end,
      }),
    enabled: Boolean(summary),
  });
  const period = periodQuery.data ?? null;

  const auditQuery = useQuery({
    queryKey: ["admin", "payout-periods", period?.period_id, "audit"],
    queryFn: () => getPayoutAuditTrail(period!.period_id),
    enabled: Boolean(period),
  });

  const refresh = (updated: AdminPayoutPeriodView) => {
    queryClient.setQueryData(
      ["admin", "payout-periods", summary?.coach_id, summary?.period_start, summary?.period_end],
      updated,
    );
    void queryClient.invalidateQueries({
      queryKey: ["admin", "payout-periods", updated.period_id, "audit"],
    });
    void queryClient.invalidateQueries({ queryKey: ["admin", "finance", "payouts"] });
  };

  const coach = useMemo(
    () => coachesQuery.data?.users.find((user) => user.user_id === summary?.coach_id) ?? null,
    [coachesQuery.data, summary?.coach_id],
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
      <Header
        coachName={coachName}
        coachEmail={coach?.email ?? null}
        period={period}
        fallbackAmountCents={summary.amount_cents}
        periodStart={summary.period_start}
        periodEnd={summary.period_end}
      />
      {periodQuery.isPending ? (
        <Skeleton />
      ) : periodQuery.isError || !period ? (
        <Card p={20}>
          <p role="alert" className="text-sm text-red-700">
            Could not load the payout period.
          </p>
        </Card>
      ) : (
        <>
          <Actions period={period} onChanged={refresh} />
          <Breakdown period={period} onChanged={refresh} />
          <AuditTrail entries={auditQuery.data?.entries ?? []} loading={auditQuery.isPending} />
        </>
      )}
    </section>
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
  period,
  fallbackAmountCents,
  periodStart,
  periodEnd,
}: {
  coachName: string;
  coachEmail: string | null;
  period: AdminPayoutPeriodView | null;
  fallbackAmountCents: number;
  periodStart: string;
  periodEnd: string;
}) {
  const status = period ? STATUS_CHIP[period.status] : null;
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
              {new Date(periodStart).toLocaleDateString()} - {new Date(periodEnd).toLocaleDateString()}
            </p>
            <div className="mt-1 flex items-center gap-2">
              {status && <Chip variant={status.variant} label={status.label} />}
              {period?.paid_at && (
                <span className="font-mono text-[11px] text-rally-muted">
                  Paid {new Date(period.paid_at).toLocaleDateString()}
                  {period.paid_method ? ` · ${period.paid_method}` : ""}
                </span>
              )}
            </div>
          </div>
        </div>
        <div className="text-right">
          <Overline>Total</Overline>
          <div className="font-mono text-2xl font-semibold tabular-nums text-rally-ink mt-1">
            {money(period?.total_amount_cents ?? fallbackAmountCents, period?.currency)}
          </div>
        </div>
      </div>
    </Card>
  );
}

function Actions({
  period,
  onChanged,
}: {
  period: AdminPayoutPeriodView;
  onChanged: (updated: AdminPayoutPeriodView) => void;
}) {
  const [error, setError] = useState<string | null>(null);

  const recompute = useMutation({
    mutationFn: () => recomputePayoutPeriod(period.period_id),
    onSuccess: (updated) => {
      setError(null);
      onChanged(updated);
    },
    onError: (err: Error) => setError(err.message),
  });
  const approve = useMutation({
    mutationFn: () => approvePayoutPeriod(period.period_id),
    onSuccess: (updated) => {
      setError(null);
      onChanged(updated);
    },
    onError: (err: Error) => setError(err.message),
  });
  const reopen = useMutation({
    mutationFn: (reason: string) => reopenPayoutPeriod(period.period_id, reason),
    onSuccess: (updated) => {
      setError(null);
      onChanged(updated);
    },
    onError: (err: Error) => setError(err.message),
  });

  const onReopen = () => {
    const reason = window.prompt(
      "Reopening returns this payout to draft so it can be corrected. Why is it being reopened?",
    );
    if (reason && reason.trim()) reopen.mutate(reason.trim());
  };

  const busy = recompute.isPending || approve.isPending || reopen.isPending;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2" data-testid="payout-period-actions">
        {period.status === "draft" && (
          <>
            <ActionButton
              icon={<RefreshCw className="size-4" aria-hidden="true" />}
              label="Recompute"
              title="Re-run the calculation against current attendance and rates. Manual line edits are kept."
              disabled={busy}
              onClick={() => recompute.mutate()}
            />
            <ActionButton
              icon={<History className="size-4" aria-hidden="true" />}
              label="Approve"
              title="Lock the lines and move this payout to approved."
              disabled={busy}
              onClick={() => approve.mutate()}
            />
          </>
        )}
        {period.status !== "draft" && (
          <ActionButton
            icon={<RotateCcw className="size-4" aria-hidden="true" />}
            label="Reopen"
            title="Return this payout to draft for corrections. A reason is required and recorded."
            disabled={busy}
            onClick={onReopen}
          />
        )}
      </div>
      {error && (
        <p role="alert" className="text-sm text-red-700">
          {error}
        </p>
      )}
    </div>
  );
}

function ActionButton({
  icon,
  label,
  title,
  disabled,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  title: string;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      title={title}
      disabled={disabled}
      onClick={onClick}
      className="inline-flex items-center gap-1.5 rounded-md border border-rally-line bg-white px-3 py-1.5 text-sm font-medium text-rally-ink hover:bg-neutral-50 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600"
    >
      {icon}
      {label}
    </button>
  );
}

function Breakdown({
  period,
  onChanged,
}: {
  period: AdminPayoutPeriodView;
  onChanged: (updated: AdminPayoutPeriodView) => void;
}) {
  return (
    <Card p={0}>
      <div className="flex items-center justify-between border-b border-rally-line px-5 py-4">
        <Overline>Occurrence breakdown ({period.lines.length})</Overline>
        {period.unpaid_occurrence_ids.length > 0 && (
          <span className="font-mono text-[11px] text-amber-700">
            {period.unpaid_occurrence_ids.length} occurrence
            {period.unpaid_occurrence_ids.length === 1 ? "" : "s"} not payable
          </span>
        )}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-sm">
          <thead>
            <tr className="border-b border-rally-line text-left">
              <th className="px-5 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                Occurrence
              </th>
              <th className="px-3 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                Basis
              </th>
              <th className="px-3 py-3 text-right font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                Minutes
              </th>
              <th className="px-3 py-3 text-right font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                Expected revenue
              </th>
              <th className="px-5 py-3 text-right font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                Amount
              </th>
              <th className="px-3 py-3" aria-label="Line actions" />
            </tr>
          </thead>
          <tbody>
            {period.lines.map((line) => (
              <PayoutRow key={line.occurrence_id} period={period} line={line} onChanged={onChanged} />
            ))}
            {period.lines.length === 0 && (
              <tr>
                <td colSpan={6} className="px-5 py-6 text-center text-sm text-rally-muted">
                  No payable occurrences in this period.
                </td>
              </tr>
            )}
          </tbody>
          <tfoot>
            <tr className="bg-neutral-50">
              <td
                className="px-5 py-3 font-mono text-[11px] font-bold uppercase tracking-overline text-rally-muted"
                colSpan={4}
              >
                Total
              </td>
              <td className="px-5 py-3 text-right font-mono font-semibold tabular-nums">
                {money(period.total_amount_cents, period.currency)}
              </td>
              <td />
            </tr>
          </tfoot>
        </table>
      </div>
    </Card>
  );
}

function PayoutRow({
  period,
  line,
  onChanged,
}: {
  period: AdminPayoutPeriodView;
  line: AdminPayoutPeriodLineView;
  onChanged: (updated: AdminPayoutPeriodView) => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const override = useMutation({
    mutationFn: (input: { amount_cents: number | null; reason: string }) =>
      overridePayoutLine(period.period_id, line.occurrence_id, input),
    onSuccess: (updated) => {
      setError(null);
      onChanged(updated);
    },
    onError: (err: Error) => setError(err.message),
  });

  const editable = period.status === "draft";
  const adjusted = line.original_amount_cents !== null;

  const onEdit = () => {
    const amountText = window.prompt(
      "New amount for this occurrence (e.g. 45.00):",
      (line.amount_cents / 100).toFixed(2),
    );
    if (amountText === null) return;
    const amount = Math.round(Number.parseFloat(amountText) * 100);
    if (!Number.isFinite(amount) || amount < 0) {
      setError("Enter a valid non-negative amount.");
      return;
    }
    const reason = window.prompt("Why is this amount being changed? (required)");
    if (!reason || !reason.trim()) return;
    override.mutate({ amount_cents: amount, reason: reason.trim() });
  };

  const onClear = () => {
    const reason = window.prompt("Why is the override being removed? (required)");
    if (!reason || !reason.trim()) return;
    override.mutate({ amount_cents: null, reason: reason.trim() });
  };

  const percentLabel =
    line.percent_bps !== null ? `${(line.percent_bps / 100).toFixed(line.percent_bps % 100 === 0 ? 0 : 1)}%` : null;

  return (
    <tr className="border-b border-rally-line last:border-0">
      <td className="px-5 py-3">
        <div className="font-mono text-xs text-rally-ink">{line.occurrence_id}</div>
        {percentLabel && (
          <div className="font-mono text-[10px] text-rally-muted">{percentLabel} of expected revenue</div>
        )}
      </td>
      <td className="px-3 py-3 text-xs text-rally-muted capitalize">{line.basis}</td>
      <td className="px-3 py-3 text-right font-mono tabular-nums">{line.minutes}</td>
      <td className="px-3 py-3 text-right font-mono tabular-nums text-rally-muted">
        {line.expected_revenue_cents !== null ? money(line.expected_revenue_cents, line.currency) : "—"}
      </td>
      <td className="px-5 py-3 text-right">
        <span className="font-mono tabular-nums font-medium">{money(line.amount_cents, line.currency)}</span>
        {adjusted && (
          <div
            className="font-mono text-[10px] text-amber-700"
            title={line.adjustment_reason ?? undefined}
          >
            edited · was {money(line.original_amount_cents!, line.currency)}
          </div>
        )}
        {error && (
          <div role="alert" className="text-[11px] text-red-700">
            {error}
          </div>
        )}
      </td>
      <td className="px-3 py-3 text-right whitespace-nowrap">
        {editable && (
          <span className="inline-flex items-center gap-1">
            <button
              type="button"
              title="Edit this line's amount (reason required)"
              disabled={override.isPending}
              onClick={onEdit}
              className="rounded p-1 text-rally-muted hover:text-rally-ink disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600"
            >
              <Pencil className="size-4" aria-hidden="true" />
              <span className="sr-only">Edit amount</span>
            </button>
            {adjusted && (
              <button
                type="button"
                title="Remove the override and restore the computed amount"
                disabled={override.isPending}
                onClick={onClear}
                className="rounded p-1 text-rally-muted hover:text-rally-ink disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600"
              >
                <Undo2 className="size-4" aria-hidden="true" />
                <span className="sr-only">Clear override</span>
              </button>
            )}
          </span>
        )}
      </td>
    </tr>
  );
}

const AUDIT_LABEL: Record<PayoutAuditEntryView["action"], string> = {
  generated: "Generated",
  recomputed: "Recomputed",
  reopened: "Reopened",
  approved: "Approved",
  marked_paid: "Marked paid",
  line_overridden: "Line amount edited",
  line_override_cleared: "Line edit removed",
};

function AuditTrail({
  entries,
  loading,
}: {
  entries: PayoutAuditEntryView[];
  loading: boolean;
}) {
  return (
    <Card p={0}>
      <div className="border-b border-rally-line px-5 py-4">
        <Overline>Audit trail</Overline>
      </div>
      {loading ? (
        <div className="px-5 py-4 text-sm text-rally-muted">Loading…</div>
      ) : entries.length === 0 ? (
        <div className="px-5 py-4 text-sm text-rally-muted">
          No changes recorded for this payout yet.
        </div>
      ) : (
        <ul className="divide-y divide-rally-line" data-testid="payout-audit-trail">
          {entries.map((entry) => (
            <li key={entry.audit_id} className="px-5 py-3 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span className="font-medium text-rally-ink">{AUDIT_LABEL[entry.action]}</span>
                <span className="font-mono text-[11px] text-rally-muted">
                  {new Date(entry.at).toLocaleString()}
                </span>
              </div>
              {entry.occurrence_id && (
                <div className="font-mono text-[11px] text-rally-muted">
                  Occurrence {entry.occurrence_id}
                </div>
              )}
              {entry.reason && <div className="mt-0.5 text-rally-muted">“{entry.reason}”</div>}
            </li>
          ))}
        </ul>
      )}
    </Card>
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
