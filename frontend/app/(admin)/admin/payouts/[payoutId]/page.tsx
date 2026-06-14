"use client";

/**
 * Admin payout review page (per the approved coach-payroll mockup).
 *
 * Renders the persisted payout period behind a payouts-list row.
 * Opening the page materialises the draft period for the coach+window
 * if it does not exist yet (`generatePayoutPeriod` is idempotent), so
 * the breakdown is always the real line-level record.
 *
 * Layout: header (coach, pay rule, status, actions incl. Excel export),
 * summary metric cards, a session-by-session pay log (paid lines plus
 * not-paid occurrences), and the audit trail.
 */

import { useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  CheckCircle2,
  Download,
  Pencil,
  RefreshCw,
  RotateCcw,
  Undo2,
} from "lucide-react";

import { listAdminUsers, listCoachPayRates, type AdminCoachPayRateView } from "@/lib/api/admin";
import {
  generatePayoutPeriod,
  approvePayoutPeriod,
  exportPayoutPeriodXlsx,
  getPayoutAuditTrail,
  listAdminPayouts,
  markPayoutPeriodPaid,
  overridePayoutLine,
  recomputePayoutPeriod,
  reopenPayoutPeriod,
  type AdminPayoutPeriodLineView,
  type AdminPayoutPeriodView,
  type MarkPayoutPaidInput,
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

function payRuleLabel(rate: AdminCoachPayRateView | null): string | null {
  if (!rate) return null;
  const since = new Date(rate.effective_from).toLocaleDateString(undefined, {
    month: "short",
    year: "numeric",
  });
  if (rate.billing_unit === "percent_of_revenue") {
    return `Pay rule: ${rate.percent ?? 0}% of session fee · effective since ${since}`;
  }
  const unit = rate.billing_unit === "per_hour" ? "per hour" : "per session";
  return `Pay rule: ${money(rate.amount_cents, rate.currency)} ${unit} · effective since ${since}`;
}

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

  const ratesQuery = useQuery({
    queryKey: ["admin", "coach-pay-rates", summary?.coach_id],
    queryFn: () => listCoachPayRates(summary!.coach_id),
    enabled: Boolean(summary),
  });
  const activeRate = useMemo(
    () => ratesQuery.data?.rates.find((rate) => rate.status === "active") ?? null,
    [ratesQuery.data],
  );

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
        payRule={payRuleLabel(activeRate)}
        period={period}
        fallbackAmountCents={summary.amount_cents}
        periodStart={summary.period_start}
        periodEnd={summary.period_end}
        onChanged={refresh}
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
          <SummaryCards period={period} />
          <PayLog period={period} onChanged={refresh} />
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
  payRule,
  period,
  fallbackAmountCents,
  periodStart,
  periodEnd,
  onChanged,
}: {
  coachName: string;
  coachEmail: string | null;
  payRule: string | null;
  period: AdminPayoutPeriodView | null;
  fallbackAmountCents: number;
  periodStart: string;
  periodEnd: string;
  onChanged: (updated: AdminPayoutPeriodView) => void;
}) {
  const status = period ? STATUS_CHIP[period.status] : null;
  const monthLabel = new Date(periodStart).toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
  });
  return (
    <Card p={20}>
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div className="flex items-center gap-4 min-w-0">
          <Avatar name={coachName} size={48} />
          <div className="min-w-0">
            <h2 className="font-display text-xl font-semibold tracking-[-0.01em] text-rally-ink">
              {coachName} — {monthLabel}
            </h2>
            <p className="mt-0.5 text-sm text-rally-muted">
              {payRule ??
                `${coachEmail ? `${coachEmail} · ` : ""}${new Date(periodStart).toLocaleDateString()} - ${new Date(periodEnd).toLocaleDateString()}`}
            </p>
            <div className="mt-1.5 flex items-center gap-2">
              {status && <Chip variant={status.variant} label={status.label} />}
              {period?.paid_at && (
                <span className="font-mono text-[11px] text-rally-muted">
                  Paid {new Date(period.paid_at).toLocaleDateString()}
                  {period.paid_method ? ` · ${period.paid_method}` : ""}
                </span>
              )}
              <span className="font-mono text-sm font-semibold tabular-nums text-rally-ink">
                {money(period?.total_amount_cents ?? fallbackAmountCents, period?.currency)}
              </span>
            </div>
          </div>
        </div>
        {period && <Actions period={period} onChanged={onChanged} />}
      </div>
    </Card>
  );
}

function SummaryCards({ period }: { period: AdminPayoutPeriodView }) {
  const replacementCount = period.lines.filter((line) => line.basis === "substitute").length;
  const metrics: { label: string; value: string }[] = [
    { label: "Sessions coached", value: String(period.lines.length) },
    { label: "As replacement", value: String(replacementCount) },
    { label: "Not paid", value: String(period.unpaid_occurrence_ids.length) },
    { label: "Total pay", value: money(period.total_amount_cents, period.currency) },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-testid="payout-summary-cards">
      {metrics.map((metric) => (
        <Card key={metric.label} p={16}>
          <Overline>{metric.label}</Overline>
          <div className="mt-1 font-mono text-xl font-semibold tabular-nums text-rally-ink">
            {metric.value}
          </div>
        </Card>
      ))}
    </div>
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
  const [exporting, setExporting] = useState(false);
  const [showPaid, setShowPaid] = useState(false);

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
  const markPaid = useMutation({
    mutationFn: (input: MarkPayoutPaidInput) => markPayoutPeriodPaid(period.period_id, input),
    onSuccess: (updated) => {
      setError(null);
      setShowPaid(false);
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

  const onExport = async () => {
    setExporting(true);
    try {
      const blob = await exportPayoutPeriodXlsx(period.period_id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `payout-${period.coach_id}-${period.period_start.slice(0, 10)}.xlsx`;
      anchor.click();
      URL.revokeObjectURL(url);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Export failed.");
    } finally {
      setExporting(false);
    }
  };

  const busy = recompute.isPending || approve.isPending || reopen.isPending || markPaid.isPending;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2" data-testid="payout-period-actions">
        {period.status === "draft" && (
          <ActionButton
            icon={<RefreshCw className="size-4" aria-hidden="true" />}
            label="Recompute"
            title="Re-run the calculation against current attendance and rates. Manual line edits are kept."
            disabled={busy}
            onClick={() => recompute.mutate()}
          />
        )}
        <ActionButton
          icon={<Download className="size-4" aria-hidden="true" />}
          label={exporting ? "Exporting…" : "Export"}
          title="Download this payout period as an Excel workbook."
          disabled={exporting}
          onClick={() => void onExport()}
        />
        {period.status === "draft" && (
          <ActionButton
            icon={<CheckCircle2 className="size-4" aria-hidden="true" />}
            label="Approve"
            title="Lock the lines and move this payout to approved."
            disabled={busy}
            onClick={() => approve.mutate()}
            primary
          />
        )}
        {period.status === "approved" && (
          <ActionButton
            icon={<CheckCircle2 className="size-4" aria-hidden="true" />}
            label="Mark paid"
            title="Record that this approved payout has been paid out."
            disabled={markPaid.isPending}
            onClick={() => setShowPaid(true)}
            primary
          />
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
      {showPaid && (
        <MarkPaidDialog
          defaultAmountCents={period.total_amount_cents}
          pending={markPaid.isPending}
          onCancel={() => setShowPaid(false)}
          onSubmit={(input) => markPaid.mutate(input)}
        />
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
  primary = false,
}: {
  icon: React.ReactNode;
  label: string;
  title: string;
  disabled?: boolean;
  onClick: () => void;
  primary?: boolean;
}) {
  return (
    <button
      type="button"
      title={title}
      disabled={disabled}
      onClick={onClick}
      className={
        primary
          ? "inline-flex items-center gap-1.5 rounded-md bg-rally-ink px-3 py-1.5 text-sm font-medium text-white hover:bg-neutral-800 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600"
          : "inline-flex items-center gap-1.5 rounded-md border border-rally-line bg-white px-3 py-1.5 text-sm font-medium text-rally-ink hover:bg-neutral-50 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600"
      }
    >
      {icon}
      {label}
    </button>
  );
}

const TH = "px-3 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted";

function PayLog({
  period,
  onChanged,
}: {
  period: AdminPayoutPeriodView;
  onChanged: (updated: AdminPayoutPeriodView) => void;
}) {
  return (
    <Card p={0}>
      <div className="border-b border-rally-line px-5 py-4">
        <Overline>
          Session pay log ({period.lines.length + period.unpaid_occurrences.length})
        </Overline>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] text-sm">
          <thead>
            <tr className="border-b border-rally-line text-left">
              <th className={`${TH} pl-5`}>Date</th>
              <th className={TH}>Session</th>
              <th className={TH}>Role</th>
              <th className={TH}>Status</th>
              <th className={`${TH} text-right`}>%</th>
              <th className={`${TH} text-right`}>Pay</th>
              <th className="px-3 py-3" aria-label="Line actions" />
            </tr>
          </thead>
          <tbody>
            {period.lines.map((line) => (
              <PaidRow key={line.occurrence_id} period={period} line={line} onChanged={onChanged} />
            ))}
            {period.unpaid_occurrences.map((occ) => (
              <tr key={occ.occurrence_id} className="border-b border-rally-line last:border-0 bg-neutral-50/50">
                <td className="px-3 py-3 pl-5 font-mono text-xs text-rally-muted">
                  {occ.occurred_at ? new Date(occ.occurred_at).toLocaleDateString() : "—"}
                </td>
                <td className="px-3 py-3 text-rally-muted">
                  {occ.session_title || occ.occurrence_id}
                </td>
                <td className="px-3 py-3 text-xs text-rally-muted">—</td>
                <td className="px-3 py-3">
                  <span className="rounded bg-amber-100 px-1.5 py-0.5 font-mono text-[10px] font-bold uppercase text-amber-800">
                    Not paid
                  </span>
                </td>
                <td className="px-3 py-3 text-right font-mono text-rally-muted">—</td>
                <td className="px-3 py-3 text-right font-mono tabular-nums text-rally-muted line-through">
                  {money(0, period.currency)}
                </td>
                <td />
              </tr>
            ))}
            {period.lines.length === 0 && period.unpaid_occurrences.length === 0 && (
              <tr>
                <td colSpan={7} className="px-5 py-6 text-center text-sm text-rally-muted">
                  No sessions in this period.
                </td>
              </tr>
            )}
          </tbody>
          <tfoot>
            <tr className="bg-neutral-50">
              <td
                className="px-5 py-3 font-mono text-[11px] font-bold uppercase tracking-overline text-rally-muted"
                colSpan={5}
              >
                Total
              </td>
              <td className="px-3 py-3 text-right font-mono font-semibold tabular-nums">
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

function PaidRow({
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
    line.percent_bps !== null
      ? `${(line.percent_bps / 100).toFixed(line.percent_bps % 100 === 0 ? 0 : 1)}%`
      : "—";

  return (
    <tr className="border-b border-rally-line last:border-0">
      <td className="px-3 py-3 pl-5 font-mono text-xs text-rally-muted">
        {line.occurred_at ? new Date(line.occurred_at).toLocaleDateString() : "—"}
      </td>
      <td className="px-3 py-3">
        <div className="font-medium text-rally-ink">
          {line.session_title || line.occurrence_id}
        </div>
        {line.expected_revenue_cents !== null && (
          <div className="font-mono text-[10px] text-rally-muted">
            of {money(line.expected_revenue_cents, line.currency)} expected revenue
          </div>
        )}
      </td>
      <td className="px-3 py-3 text-xs text-rally-muted">
        {line.basis === "substitute" ? "Replacement" : "Scheduled"}
      </td>
      <td className="px-3 py-3">
        <span className="rounded bg-emerald-100 px-1.5 py-0.5 font-mono text-[10px] font-bold uppercase text-emerald-800">
          Paid
        </span>
      </td>
      <td className="px-3 py-3 text-right font-mono tabular-nums text-rally-muted">
        {percentLabel}
      </td>
      <td className="px-3 py-3 text-right">
        <span className="font-mono tabular-nums font-medium">
          {money(line.amount_cents, line.currency)}
        </span>
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

function MarkPaidDialog({
  defaultAmountCents,
  pending,
  onCancel,
  onSubmit,
}: {
  defaultAmountCents: number;
  pending: boolean;
  onCancel: () => void;
  onSubmit: (input: MarkPayoutPaidInput) => void;
}) {
  const today = new Date().toISOString().slice(0, 10);
  const [method, setMethod] = useState<MarkPayoutPaidInput["method"]>("bank_transfer");
  const [paidAt, setPaidAt] = useState(today);
  const [amount, setAmount] = useState((defaultAmountCents / 100).toFixed(2));
  const [reference, setReference] = useState("");

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    onSubmit({
      method,
      paid_at: new Date(paidAt).toISOString(),
      amount_cents: Math.round(parseFloat(amount) * 100),
      reference: reference || null,
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm rounded-lg bg-background p-6 shadow-lg space-y-4"
      >
        <h2 className="text-base font-semibold">Record payment</h2>
        <div className="space-y-3">
          <div>
            <label className="text-sm font-medium">Method</label>
            <select
              value={method}
              onChange={(e) => setMethod(e.target.value as MarkPayoutPaidInput["method"])}
              className="mt-1 w-full rounded border px-2 py-1.5 text-sm"
            >
              <option value="bank_transfer">Bank transfer</option>
              <option value="cash">Cash</option>
              <option value="check">Check</option>
              <option value="other">Other</option>
            </select>
          </div>
          <div>
            <label className="text-sm font-medium">Date paid</label>
            <input
              type="date"
              value={paidAt}
              onChange={(e) => setPaidAt(e.target.value)}
              required
              className="mt-1 w-full rounded border px-2 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="text-sm font-medium">Amount</label>
            <input
              type="number"
              step="0.01"
              min="0"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              required
              className="mt-1 w-full rounded border px-2 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="text-sm font-medium">Reference (optional)</label>
            <input
              type="text"
              value={reference}
              onChange={(e) => setReference(e.target.value)}
              placeholder="e.g. transaction ID"
              className="mt-1 w-full rounded border px-2 py-1.5 text-sm"
            />
          </div>
        </div>
        <div className="flex gap-2 justify-end">
          <button type="button" onClick={onCancel} className="rounded border px-3 py-1.5 text-sm">
            Cancel
          </button>
          <button
            type="submit"
            disabled={pending}
            className="rounded bg-primary px-3 py-1.5 text-sm text-primary-foreground disabled:opacity-50"
          >
            {pending ? "Saving…" : "Confirm payment"}
          </button>
        </div>
      </form>
    </div>
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
