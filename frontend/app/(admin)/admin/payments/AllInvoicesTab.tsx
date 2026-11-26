"use client";

/**
 * Admin payments — "All invoices" tab.
 *
 * The pre-buckets Payments page body, moved under a tab (payments buckets
 * spec §4). Preserves: sync-stripe, generate-monthly, apply-discount,
 * mark-paid, undo-paid, refund. Refund disabled when payment isn't eligible.
 * The KPI strip and the Month filter were dropped: the Collections tab's
 * buckets and period picker replace them.
 */

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  exportAdminReportCsv,
  listAdminSessions,
  listAdminPayments,
  undoPaymentPaid,
  type AdminPaymentListFilters,
  type AdminPaymentView,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { useIsOwner } from "@/components/admin/owner-context";
import { matchesInvoiceStatusFilter, type InvoiceStatusFilter } from "@/lib/billing-status";
import { actionCellClass, actionHeaderClass } from "@/lib/sticky-action-column";

import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";
import { Field, Th } from "@/components/ds/dialog-chrome";
import { PhoneList, PhoneListRow } from "@/components/ds/phone-row";
import { TableSkeleton } from "@/components/ds/skeleton";
import { useIsPhone } from "@/lib/use-is-phone";

import {
  disputeLabel,
  finalCents,
  formatCents,
  formatPeriodLabel,
  methodChip,
  paidCents,
  paymentDisplayLabel,
  paymentRowTitle,
  PAGE_SIZE,
  reconciliationLabel,
  sessionFilterKey,
  sessionFilterLabel,
  STATUS_FILTER_OPTIONS,
  statusChip,
  stripeIdSummary,
} from "./format";
import {
  DiscountDialog,
  GenerateDialog,
  InvoiceDialog,
  MarkPaidDialog,
  PaymentActions,
  paymentMenuItems,
  RefundDialog,
  SyncStripeDialog,
  VoidPaymentDialog,
} from "./dialogs";
import { useAcademyZone } from "@/lib/format/academy-zone";
import { formatInAcademyZone } from "@/lib/format/academy-time";

/** Server cap on one list request; used when the status filter runs client-side. */
const STATUS_FILTER_WINDOW = 200;

export function AllInvoicesTab() {
  const academyTimezone = useAcademyZone();
  const isOwner = useIsOwner();
  const isPhone = useIsPhone();
  const [refundTarget, setRefundTarget] = useState<AdminPaymentView | null>(null);
  const [paidTarget, setPaidTarget] = useState<AdminPaymentView | null>(null);
  const [discountTarget, setDiscountTarget] = useState<AdminPaymentView | null>(null);
  const [invoiceTarget, setInvoiceTarget] = useState<AdminPaymentView | null>(null);
  const [syncTarget, setSyncTarget] = useState<AdminPaymentView | null>(null);
  const [voidTarget, setVoidTarget] = useState<AdminPaymentView | null>(null);
  const [syncOpen, setSyncOpen] = useState(false);
  const [generateOpen, setGenerateOpen] = useState(false);
  const [sessionFilter, setSessionFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [methodFilter, setMethodFilter] = useState("all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [searchInput, setSearchInput] = useState("");
  // Voided payments (#619) are test/erroneous rows kept only for audit; off by
  // default so the list shows the money that is actually on the books.
  const [showVoided, setShowVoided] = useState(false);
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  // S41: owner-only CSV of one billing month, the same rows as Month close.
  const [exportPeriod, setExportPeriod] = useState(() => new Date().toISOString().slice(0, 7));
  const exportMutation = useMutation({
    mutationFn: () => exportAdminReportCsv("invoices", exportPeriod),
    onSuccess: (csv) => {
      const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `invoices-${exportPeriod}.csv`;
      anchor.click();
      URL.revokeObjectURL(url);
    },
  });
  const queryClient = useQueryClient();

  useEffect(() => {
    const handle = setTimeout(() => {
      setSearch(searchInput.trim());
      setOffset(0);
    }, 300);
    return () => clearTimeout(handle);
  }, [searchInput]);

  const serverFilters = useMemo<AdminPaymentListFilters>(
    () => ({
      date_from: dateFrom ? `${dateFrom}T00:00:00Z` : undefined,
      date_to: dateTo ? `${dateTo}T23:59:59Z` : undefined,
      // Status is filtered client-side in the chip vocabulary (see
      // matchesInvoiceStatusFilter): the server filter is an exact raw-status
      // match and could not reach every row that renders as PAID.
      method: methodFilter !== "all" ? methodFilter : undefined,
      q: search || undefined,
      // With a status filter the page is filtered client-side, so fetch the
      // server's maximum window instead of one page (pagination is hidden).
      limit: statusFilter !== "all" ? STATUS_FILTER_WINDOW : PAGE_SIZE,
      offset: statusFilter !== "all" ? 0 : offset,
      include_voided: showVoided || undefined,
    }),
    [dateFrom, dateTo, methodFilter, search, offset, statusFilter, showVoided],
  );

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: [...queryKeys.admin.payments(), serverFilters],
    queryFn: () => listAdminPayments(serverFilters),
  });
  const undoMutation = useMutation({
    mutationFn: (paymentId: string) => undoPaymentPaid(paymentId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.admin.payments() }),
  });

  const payments = useMemo(() => data?.payments ?? [], [data?.payments]);
  const totalCount = data?.total ?? null;
  const methodOptions = useMemo(
    () =>
      Array.from(
        new Set(
          payments
            .map((payment) => payment.payment_method)
            .filter((method): method is string => Boolean(method))
            .concat(methodFilter !== "all" ? [methodFilter] : []),
        ),
      ).sort(),
    [payments, methodFilter],
  );
  const sessionsQuery = useQuery({
    queryKey: queryKeys.admin.sessions("window-all"),
    queryFn: () => listAdminSessions(undefined, { window: "all" }),
  });
  const sessionTitles = useMemo(
    () => new Map((sessionsQuery.data?.sessions ?? []).map((s) => [s.session_id, s.title])),
    [sessionsQuery.data?.sessions],
  );
  const sessionOptions = useMemo(
    () =>
      Array.from(new Set(payments.map((payment) => sessionFilterKey(payment)))).sort((a, b) =>
        sessionFilterLabel(a, sessionTitles).localeCompare(sessionFilterLabel(b, sessionTitles)),
      ),
    [payments, sessionTitles],
  );
  const filteredPayments = useMemo(
    () =>
      payments.filter((payment) => {
        if (sessionFilter !== "all" && sessionFilterKey(payment) !== sessionFilter) return false;
        if (!matchesInvoiceStatusFilter(payment.status, statusFilter as InvoiceStatusFilter)) {
          return false;
        }
        return true;
      }),
    [payments, sessionFilter, statusFilter],
  );

  return (
    <div className="space-y-5" data-testid="payments-all-invoices">
      <div className="flex flex-wrap items-center justify-end gap-2">
        {isOwner && (
          <>
            <input
              type="month"
              aria-label="Month to export"
              value={exportPeriod}
              onChange={(event) => setExportPeriod(event.target.value || exportPeriod)}
              className="h-8 rounded-md border border-rally-line bg-white px-2 text-sm text-rally-ink dark:bg-neutral-950"
              data-testid="invoices-export-period"
            />
            <Button
              variant="secondary"
              size="sm"
              onClick={() => exportMutation.mutate()}
              disabled={exportMutation.isPending}
              data-testid="invoices-export"
            >
              {exportMutation.isPending ? "Exporting..." : "Export CSV"}
            </Button>
          </>
        )}
        <Button
          variant="secondary"
          size="sm"
          onClick={() => {
            setSyncTarget(null);
            setSyncOpen(true);
          }}
        >
          Sync Stripe
        </Button>
        <Button variant="primary" size="sm" onClick={() => setGenerateOpen(true)}>
          Generate monthly
        </Button>
      </div>

      {exportMutation.isError && (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not export that month.
        </p>
      )}

      {isOwner && (
        <p className="text-sm text-rally-subtle" data-testid="billing-health-pointer">
          Stripe not behaving: a payment that never reached an invoice, a stuck payment
          update, or parents who cannot pay?{" "}
          <Link href="/admin/billing-health" className="underline">
            Payment system status
          </Link>{" "}
          (Settings, Integrations) has the stuck-update queue, the lookup and the recovery
          actions.
        </p>
      )}


      <Card p={16}>
        <div className="grid gap-3 md:grid-cols-3 lg:grid-cols-4">
          <Field label="Search family or student">
            <input
              type="search"
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              placeholder="Name or invoice #"
              className={inputClass}
              data-testid="payments-search"
            />
          </Field>
          <Field label="Paid from">
            <input
              type="date"
              value={dateFrom}
              onChange={(event) => {
                setDateFrom(event.target.value);
                setOffset(0);
              }}
              className={inputClass}
            />
          </Field>
          <Field label="Paid to">
            <input
              type="date"
              value={dateTo}
              onChange={(event) => {
                setDateTo(event.target.value);
                setOffset(0);
              }}
              className={inputClass}
            />
          </Field>
          <Field label="Status">
            <select
              value={statusFilter}
              onChange={(event) => {
                setStatusFilter(event.target.value);
                setOffset(0);
              }}
              className={inputClass}
            >
              <option value="all">All statuses</option>
              {STATUS_FILTER_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Method">
            <select
              value={methodFilter}
              onChange={(event) => {
                setMethodFilter(event.target.value);
                setOffset(0);
              }}
              className={inputClass}
            >
              <option value="all">All methods</option>
              {methodOptions.map((method) => (
                <option key={method} value={method}>
                  {method}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Class">
            <select
              value={sessionFilter}
              onChange={(event) => setSessionFilter(event.target.value)}
              className={inputClass}
            >
              <option value="all">All classes</option>
              {sessionOptions.map((session) => (
                <option key={session} value={session}>
                  {sessionFilterLabel(session, sessionTitles)}
                </option>
              ))}
            </select>
          </Field>
          <label className="flex items-end gap-2 pb-2 text-sm text-rally-muted md:col-span-1">
            <input
              type="checkbox"
              checked={showVoided}
              onChange={(event) => {
                setShowVoided(event.target.checked);
                setOffset(0);
              }}
              className="h-4 w-4 rounded border-rally-line text-rally-cobalt-600"
              data-testid="payments-show-voided"
            />
            Show voided
          </label>
          <div className="flex items-end justify-between gap-2">
            <div className="text-sm text-rally-subtle md:pb-2" data-testid="payments-showing">
              {statusFilter !== "all"
                ? `Showing ${filteredPayments.length} matching in the latest ${payments.length} records${
                    totalCount !== null && totalCount > payments.length
                      ? ` (of ${totalCount}; narrow by date to see older ones)`
                      : ""
                  }`
                : totalCount === null
                  ? `Showing ${filteredPayments.length} of ${payments.length} records`
                  : `Showing ${totalCount === 0 ? 0 : offset + 1}–${offset + payments.length} of ${totalCount}`}
            </div>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                setSessionFilter("all");
                setStatusFilter("all");
                setMethodFilter("all");
                setDateFrom("");
                setDateTo("");
                setSearchInput("");
                setShowVoided(false);
                setOffset(0);
              }}
              disabled={
                sessionFilter === "all" &&
                statusFilter === "all" &&
                methodFilter === "all" &&
                !dateFrom &&
                !dateTo &&
                !searchInput &&
                !showVoided
              }
            >
              Reset
            </Button>
          </div>
        </div>
      </Card>

      {isError && (
        <Card p={16} style={{ borderColor: "#fecaca", background: "#fef2f2" }}>
          <div role="alert" className="flex items-center justify-between gap-3">
            <p className="text-sm text-red-800">Failed to load payments.</p>
            <Button variant="secondary" size="sm" onClick={() => void refetch()}>Retry</Button>
          </div>
        </Card>
      )}

      <Card p={0}>
        {isLoading ? (
          <div className="p-4">
            <TableSkeleton />
          </div>
        ) : payments.length === 0 ? (
          <p className="p-8 text-center text-sm text-rally-subtle" data-testid="payments-empty">
            No payments found.
          </p>
        ) : filteredPayments.length === 0 ? (
          <p className="p-8 text-center text-sm text-rally-subtle" data-testid="payments-filter-empty">
            No payments match these filters.
          </p>
        ) : isPhone ? (
          /* #857: ten columns over a 980px minimum. On a phone the amount, the
             status and the money actions were all past the right edge — the
             three things this list is read for. Same chips and the same
             `formatCents` the table uses; the menu items call the same
             handlers, so Void / Refund / Mark paid still open their #838
             confirm dialogs. */
          <PhoneList aria-label="Invoices" data-testid="admin-payments-phone-list">
            {filteredPayments.map((p) => {
              const chip = statusChip(p.status);
              const method = methodChip(p);
              const rowPaidCents = paidCents(p);
              const reconciliation = reconciliationLabel(p);
              const stripeSummary = stripeIdSummary(p);
              const label = paymentDisplayLabel(p);
              return (
                <PhoneListRow
                  key={p.payment_id}
                  data-testid={`payment-row-${p.payment_id}`}
                  title={p.student_name || "Unassigned"}
                  primary={
                    <span className="font-mono text-sm font-semibold tabular-nums text-rally-ink">
                      {formatCents(p.amount_cents)}
                    </span>
                  }
                  actionsLabel={`Actions for ${label}`}
                  actionsTestId={`payment-actions-${p.payment_id}`}
                  actions={paymentMenuItems({
                    payment: p,
                    canGovernMoney: isOwner,
                    onDiscount: () => setDiscountTarget(p),
                    onInvoice: () => setInvoiceTarget(p),
                    onPaid: () => setPaidTarget(p),
                    onRefund: () => setRefundTarget(p),
                    onSync: () => {
                      setSyncTarget(p);
                      setSyncOpen(true);
                    },
                    onUndo: () => undoMutation.mutate(p.payment_id),
                    onVoid: () => setVoidTarget(p),
                    undoPending: undoMutation.isPending,
                  })}
                  secondary={
                    <>
                      <div className="flex flex-wrap items-center gap-2">
                        <Chip variant={chip.variant} label={chip.label} />
                        {method && <Chip variant={method.variant} label={method.label} />}
                      </div>
                      <div className="break-words">
                        {paymentRowTitle(p)} · {p.parent_name || "Parent on file"}
                      </div>
                      <div>
                        {formatPeriodLabel(p.period) || "No period"} · paid{" "}
                        {rowPaidCents === null ? "—" : formatCents(rowPaidCents)}
                        {p.discount_cents ? ` · less ${formatCents(p.discount_cents)}` : ""}
                      </div>
                      {p.status === "voided" && (
                        <div data-testid={`payment-void-note-${p.payment_id}`}>
                          {p.void_reason || "Voided"}
                          {p.voided_at ? ` · ${formatInAcademyZone(p.voided_at, academyTimezone)}` : ""}
                        </div>
                      )}
                      <DisputeNote payment={p} />
                      {/* The Stripe ids and the reconciliation note are the
                          evidence `billing-trust-recovery.spec.ts` reads off
                          the row, so the phone layout carries them too — the
                          trail must not depend on screen width. #892 folds the
                          ids themselves into a disclosure: the trail stays,
                          the `pi_…` noise stops being the default reading. */}
                      {stripeSummary && (
                        <StripeIdDetails summary={stripeSummary} paymentId={p.payment_id} />
                      )}
                      {reconciliation && (
                        <div className="font-medium text-amber-700">{reconciliation}</div>
                      )}
                    </>
                  }
                />
              );
            })}
          </PhoneList>
        ) : (
          <div className="overflow-x-auto">
            {/* #861: the floor used to be 980px, which on its own was wider
                than the ~944px the admin shell leaves for the table at 1280 —
                before the five-button action column added another ~200. The
                columns still set their own natural widths; this only stops the
                table demanding room the screen does not have. */}
            <table className="w-full min-w-[720px] text-sm" data-testid="admin-payments-table">
              <thead>
                <tr className="border-b border-rally-line text-left">
                  <Th>Payment</Th>
                  <Th>Student</Th>
                  <Th>Period</Th>
                  <Th align="right">Amount due</Th>
                  <Th align="right">Discount</Th>
                  <Th align="right">Amount paid</Th>
                  <Th>Status</Th>
                  <Th>Method</Th>
                  <Th>Paid on</Th>
                  {/* #847: ten columns over a 980px minimum put the row menu
                      past the right edge at 1280 inside the admin shell, so
                      voiding or refunding an invoice needed a sideways scroll
                      first. Same sticky column the approval queues use.
                      #861: capped, because an uncapped `justify-end` strip of
                      up to five buttons was what pushed Status / Method /
                      Paid-on off the screen in the first place. */}
                  <Th className={`${actionHeaderClass} w-[232px]`}>
                    <span className="sr-only">Actions</span>
                  </Th>
                </tr>
              </thead>
              <tbody>
                {filteredPayments.map((p) => {
                  const chip = statusChip(p.status);
                  const method = methodChip(p);
                  const rowPaidCents = paidCents(p);
                  const stripeSummary = stripeIdSummary(p);
                  const reconciliation = reconciliationLabel(p);
                  return (
                    <tr
                      key={p.payment_id}
                      data-testid={`payment-row-${p.payment_id}`}
                      className="border-b border-rally-line/60 last:border-0"
                    >
                      <td className="px-4 py-3">
                        <div className="font-medium text-rally-ink">
                          {paymentRowTitle(p)}
                        </div>
                        <div className="mt-0.5 text-xs text-rally-subtle">
                          Created {formatInAcademyZone(p.created_at, academyTimezone)}
                        </div>
                        {(stripeSummary || reconciliation) && (
                          <div className="mt-1 max-w-[280px] space-y-0.5 text-xs text-rally-subtle">
                            {stripeSummary && (
                              <StripeIdDetails summary={stripeSummary} paymentId={p.payment_id} />
                            )}
                            {reconciliation && (
                              <div className="font-medium text-amber-700">
                                {reconciliation}
                              </div>
                            )}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <div className="font-display font-semibold text-rally-ink">
                          {p.student_name || "Unassigned"}
                        </div>
                        <div className="mt-0.5 text-xs text-rally-subtle">
                          {p.parent_name || "Parent on file"}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-rally-muted">
                        {formatPeriodLabel(p.period) || "—"}
                      </td>
                      <td className="px-4 py-3 text-right font-mono tabular-nums">{formatCents(p.amount_cents)}</td>
                      <td className="px-4 py-3 text-right font-mono tabular-nums text-rally-subtle">
                        {p.discount_cents ? formatCents(p.discount_cents) : "—"}
                      </td>
                      <td className="px-4 py-3 text-right font-mono font-semibold tabular-nums text-rally-ink">
                        {rowPaidCents === null ? "—" : formatCents(rowPaidCents)}
                      </td>
                      <td className="px-4 py-3">
                        <Chip variant={chip.variant} label={chip.label} />
                        {p.status === "voided" && (
                          <div
                            className="mt-1 max-w-[200px] text-xs text-rally-subtle"
                            data-testid={`payment-void-note-${p.payment_id}`}
                          >
                            {p.void_reason || "Voided"}
                            {p.voided_at
                              ? ` · ${formatInAcademyZone(p.voided_at, academyTimezone)}`
                              : ""}
                          </div>
                        )}
                        <DisputeNote payment={p} className="mt-1 max-w-[200px] text-xs" />
                      </td>
                      <td className="px-4 py-3">
                        {method ? <Chip variant={method.variant} label={method.label} /> : <span className="text-rally-subtle">—</span>}
                      </td>
                      <td className="px-4 py-3 text-rally-muted">
                        {p.paid_at ? formatInAcademyZone(p.paid_at, academyTimezone) : "—"}
                      </td>
                      <td className={`${actionCellClass} w-[232px] bg-white`}>
                        <PaymentActions
                          payment={p}
                          canGovernMoney={isOwner}
                          onDiscount={() => setDiscountTarget(p)}
                          onInvoice={() => setInvoiceTarget(p)}
                          onPaid={() => setPaidTarget(p)}
                          onRefund={() => setRefundTarget(p)}
                          onSync={() => {
                            setSyncTarget(p);
                            setSyncOpen(true);
                          }}
                          onUndo={() => undoMutation.mutate(p.payment_id)}
                          onVoid={() => setVoidTarget(p)}
                          undoPending={undoMutation.isPending}
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {statusFilter === "all" && totalCount !== null && totalCount > PAGE_SIZE && (
          <div className="flex items-center justify-between border-t border-rally-line px-4 py-3">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              disabled={offset === 0 || isLoading}
            >
              Previous
            </Button>
            <span className="text-sm text-rally-subtle">
              Page {Math.floor(offset / PAGE_SIZE) + 1} of {Math.max(1, Math.ceil(totalCount / PAGE_SIZE))}
            </span>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setOffset(offset + PAGE_SIZE)}
              disabled={offset + PAGE_SIZE >= totalCount || isLoading}
            >
              Next
            </Button>
          </div>
        )}
      </Card>

      <GenerateDialog
        open={generateOpen}
        onOpenChange={setGenerateOpen}
        onGenerated={() => {
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.payments() });
          // S34: the dashboard's "no invoice for <month>" item clears after a run.
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.attention() });
        }}
      />
      <DiscountDialog
        payment={discountTarget}
        onClose={() => setDiscountTarget(null)}
        onSaved={() => {
          setDiscountTarget(null);
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.payments() });
        }}
      />
      <MarkPaidDialog
        payment={paidTarget}
        onClose={() => setPaidTarget(null)}
        onSaved={() => {
          setPaidTarget(null);
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.payments() });
        }}
      />
      <RefundDialog
        payment={refundTarget}
        onClose={() => setRefundTarget(null)}
        onRefunded={() => {
          setRefundTarget(null);
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.payments() });
        }}
      />
      <VoidPaymentDialog
        target={
          voidTarget && {
            paymentId: voidTarget.payment_id,
            description: `${paymentDisplayLabel(voidTarget)} · ${formatCents(finalCents(voidTarget))}`,
          }
        }
        onClose={() => setVoidTarget(null)}
        onVoided={() => {
          setVoidTarget(null);
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.payments() });
        }}
      />
      <InvoiceDialog payment={invoiceTarget} canGovernMoney={isOwner} onClose={() => setInvoiceTarget(null)} />
      <SyncStripeDialog
        open={syncOpen}
        payment={syncTarget}
        onClose={() => {
          setSyncOpen(false);
          setSyncTarget(null);
        }}
        onSynced={() => {
          setSyncOpen(false);
          setSyncTarget(null);
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.payments() });
        }}
      />
    </div>
  );
}


const inputClass =
  "w-full rounded-md border border-rally-line bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30";

/**
 * #892: the Stripe object ids behind a disclosure. They are the reconciliation
 * trail `billing-trust-recovery.spec.ts` reads off a row, so they stay in the
 * row — but "pi_3QwT…" is not what an admin reads an invoice list for, and it
 * was the first thing the list said. Collapsed by default, one tap away.
 */
function StripeIdDetails({ summary, paymentId }: { summary: string; paymentId: string }) {
  return (
    <details data-testid={`stripe-ids-${paymentId}`}>
      <summary className="cursor-pointer text-xs text-rally-subtle">Stripe details</summary>
      <div className="mt-1 break-all font-mono text-[11px] text-rally-subtle" title={summary}>
        {summary}
      </div>
    </details>
  );
}

/** A Stripe dispute on this payment (#980); answered in the academy's Stripe dashboard. */
function DisputeNote({ payment, className = "" }: { payment: AdminPaymentView; className?: string }) {
  const label = disputeLabel(payment);
  if (!label) return null;
  return (
    <div
      className={`font-medium text-red-700 ${className}`}
      data-testid={`payment-dispute-note-${payment.payment_id}`}
    >
      {label}
    </div>
  );
}
