"use client";

/**
 * Payments — Collections tab: the six-bucket "work the money list".
 *
 * One query (`GET /admin/payments/collections?period=`) feeds four tiles and
 * six buckets rendered in the fixed spec order. Row actions call the existing
 * write endpoints only (dues reminders, record payment, void, resume); every
 * action invalidates the collections query so the row moves buckets on the
 * next fetch. Spec: docs/superpowers/specs/2026-09-05-payments-buckets-design.md.
 */

import Link from "next/link";
import { type ReactNode, useDeferredValue, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getAdminCollections,
  resumeEnrollment,
  sendDuesReminders,
  voidAdminInvoice,
  type AdminCollectionsBucket,
  type AdminCollectionsFamily,
  type CollectionsAction,
  type CollectionsBucketKey,
} from "@/lib/api/admin";
import { formatCents } from "@/lib/money";
import { queryKeys } from "@/lib/query/keys";

import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";
import { Field } from "@/components/ds/dialog-chrome";
import { TableSkeleton } from "@/components/ds/skeleton";
import { BigNum, Overline } from "@/components/ds/typography";

import {
  ACTION_LABEL,
  BUCKET_META,
  familyChip,
  familyMatches,
  familyName,
  normalizeCollections,
  actionInvoice,
  owingInvoices,
  periodOptionsFrom,
  secondaryLine,
  studentLine,
  todayInZone,
  todayISO,
} from "./bucket-view";
import { RecordPaymentDialog, type RecordPaymentInvoiceOption } from "./RecordPaymentDialog";

const OWING_BUCKETS: CollectionsBucketKey[] = ["failed_autopay", "past_due", "awaiting"];

const inputClass =
  "w-full rounded-md border border-rally-line bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30";

type RowStatus = { tone: "ok" | "warn" | "error"; text: string };

type DialogState = {
  invoices: RecordPaymentInvoiceOption[];
  initialInvoiceId?: string;
  parentId: string | null;
} | null;

function invoiceOption(
  family: AdminCollectionsFamily,
  invoice: AdminCollectionsFamily["invoices"][number],
): RecordPaymentInvoiceOption {
  const number = invoice.invoice_number ?? invoice.invoice_id;
  return {
    invoice_id: invoice.invoice_id,
    label: `${familyName(family)} · ${number} · ${invoice.period}`,
    balance_due_cents: invoice.balance_due_cents,
  };
}

export function CollectionsTab() {
  // "" = let the backend pick the academy's current month (its timezone, not
  // the viewer's); the picker then anchors on the period the backend returned.
  const [period, setPeriod] = useState("");
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);
  const [rowStatus, setRowStatus] = useState<Record<string, RowStatus>>({});
  const [dialog, setDialog] = useState<DialogState>(null);
  const [dialogNonce, setDialogNonce] = useState(0);
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: queryKeys.admin.collections(period || "current"),
    queryFn: () => getAdminCollections(period || undefined),
  });
  const view = useMemo(() => normalizeCollections(query.data), [query.data]);
  const effectivePeriod = view.period || period || todayISO().slice(0, 7);
  const periods = useMemo(() => periodOptionsFrom(effectivePeriod), [effectivePeriod]);
  const today = useMemo(() => todayInZone(view.timezone), [view.timezone]);

  // Every collections view (any period, the dashboard's "current") shares the
  // same facts, so a row action refreshes all of them.
  const invalidate = () =>
    void queryClient.invalidateQueries({ queryKey: queryKeys.admin.collectionsAll() });

  const setStatus = (parentId: string, status: RowStatus) =>
    setRowStatus((prev) => ({ ...prev, [parentId]: status }));

  const reminderMutation = useMutation({
    mutationFn: (parentId: string) => sendDuesReminders({ parent_ids: [parentId] }),
    onSuccess: (result, parentId) => {
      if (result.blocked) {
        setStatus(parentId, { tone: "warn", text: `Blocked: ${result.reason ?? "not eligible"}` });
      } else if (result.sent > 0) {
        setStatus(parentId, { tone: "ok", text: "Reminder sent" });
      } else {
        setStatus(parentId, { tone: "warn", text: "No reminder sent" });
      }
      invalidate();
    },
    onError: (error: Error, parentId) =>
      setStatus(parentId, { tone: "error", text: error.message || "Reminder failed." }),
  });

  const skipMutation = useMutation({
    mutationFn: ({ invoiceId }: { parentId: string; invoiceId: string }) =>
      voidAdminInvoice(invoiceId, { reason: "skipped_by_admin" }),
    onSuccess: (_result, { parentId }) => {
      setStatus(parentId, { tone: "ok", text: "Skipped this month" });
      invalidate();
    },
    onError: (error: Error, { parentId }) =>
      setStatus(parentId, { tone: "error", text: error.message || "Could not skip this month." }),
  });

  const resumeMutation = useMutation({
    mutationFn: ({ enrollmentId }: { parentId: string; enrollmentId: string }) =>
      resumeEnrollment(enrollmentId),
    onSuccess: (_result, { parentId }) => {
      setStatus(parentId, { tone: "ok", text: "Enrollment resumed" });
      invalidate();
    },
    onError: (error: Error, { parentId }) =>
      setStatus(parentId, { tone: "error", text: error.message || "Could not resume." }),
  });

  const allOwingOptions = useMemo(
    () =>
      view.buckets
        .filter((bucket) => OWING_BUCKETS.includes(bucket.key))
        .flatMap((bucket) =>
          bucket.families.flatMap((family) =>
            owingInvoices(family).map((invoice) => invoiceOption(family, invoice)),
          ),
        ),
    [view.buckets],
  );

  // The nonce keys the dialog so every open remounts it with fresh fields and
  // a fresh idempotency key.
  const openDialog = (state: NonNullable<DialogState>) => {
    setDialogNonce((n) => n + 1);
    setDialog(state);
  };

  const openRecordPaymentForFamily = (family: AdminCollectionsFamily) => {
    const owing = owingInvoices(family);
    openDialog({
      invoices: owing.map((invoice) => invoiceOption(family, invoice)),
      initialInvoiceId: actionInvoice(family)?.invoice_id ?? owing[0]?.invoice_id,
      parentId: family.parent_id,
    });
  };

  const handleAction = (
    action: CollectionsAction,
    family: AdminCollectionsFamily,
  ) => {
    switch (action) {
      case "send_reminder":
        reminderMutation.mutate(family.parent_id);
        return;
      case "record_payment":
        openRecordPaymentForFamily(family);
        return;
      case "skip_month": {
        const invoice = actionInvoice(family);
        if (!invoice) return;
        const label = invoice.invoice_number ?? invoice.invoice_id;
        if (
          window.confirm(
            `Void ${label} for ${familyName(family)}? The family will not be charged this month.`,
          )
        ) {
          skipMutation.mutate({ parentId: family.parent_id, invoiceId: invoice.invoice_id });
        }
        return;
      }
      case "resume":
        if (family.pause) {
          resumeMutation.mutate({
            parentId: family.parent_id,
            enrollmentId: family.pause.enrollment_id,
          });
        }
        return;
      case "message":
        // Rendered as a Link; nothing to do here.
        return;
    }
  };

  const busyParent = (parentId: string) =>
    (reminderMutation.isPending && reminderMutation.variables === parentId) ||
    (skipMutation.isPending && skipMutation.variables?.parentId === parentId) ||
    (resumeMutation.isPending && resumeMutation.variables?.parentId === parentId);

  return (
    <div className="space-y-5" data-testid="payments-collections">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div className="grid flex-1 gap-3 sm:grid-cols-2 md:max-w-xl">
          <Field label="Month">
            <select
              value={effectivePeriod}
              onChange={(event) => setPeriod(event.target.value)}
              className={inputClass}
              data-testid="collections-period"
            >
              {periods.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Search family or student">
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Parent, student or class"
              className={inputClass}
              data-testid="collections-search"
            />
          </Field>
        </div>
        <Button
          variant="primary"
          size="md"
          onClick={() =>
            openDialog({
              invoices: allOwingOptions,
              parentId: null,
            })
          }
          data-testid="collections-record-payment"
        >
          Record payment
        </Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Tile
          testKey="owed"
          label="Owed this month"
          value={formatCents(view.totals.owed_cents)}
          hint="past due + awaiting + failed autopay"
          loading={query.isLoading}
        />
        <Tile
          testKey="autopay"
          label="Autopay scheduled"
          value={formatCents(view.totals.autopay_scheduled_cents)}
          hint={`${view.totals.autopay_scheduled_count} ${view.totals.autopay_scheduled_count === 1 ? "family" : "families"}`}
          loading={query.isLoading}
        />
        <Tile
          testKey="needs-action"
          label="Needs action"
          value={String(view.totals.needs_action_count)}
          hint="failed autopay · past due"
          loading={query.isLoading}
        />
        <Tile
          testKey="collected"
          label="Collected"
          value={formatCents(view.totals.collected_cents)}
          hint="paid this month"
          loading={query.isLoading}
        />
      </div>

      {query.isError && (
        <Card p={16} style={{ borderColor: "#fecaca", background: "#fef2f2" }}>
          <div
            role="alert"
            data-testid="collections-error"
            className="flex items-center justify-between gap-3"
          >
            <p className="text-sm text-red-800">Could not load the collections list.</p>
            <Button variant="secondary" size="sm" onClick={() => void query.refetch()}>
              Retry
            </Button>
          </div>
        </Card>
      )}

      {view.buckets.map((bucket) => (
        <BucketSection
          key={bucket.key}
          bucket={bucket}
          loading={query.isLoading}
          search={deferredSearch}
          today={today}
          rowStatus={rowStatus}
          busyParent={busyParent}
          onAction={handleAction}
        />
      ))}

      {dialog && (
        <RecordPaymentDialog
          key={dialogNonce}
          open
          invoices={dialog.invoices}
          initialInvoiceId={dialog.initialInvoiceId}
          onClose={() => setDialog(null)}
          onSaved={() => {
            if (dialog.parentId) setStatus(dialog.parentId, { tone: "ok", text: "Payment recorded" });
            setDialog(null);
            invalidate();
            void queryClient.invalidateQueries({ queryKey: queryKeys.admin.payments() });
          }}
        />
      )}
    </div>
  );
}

function Tile({
  testKey,
  label,
  value,
  hint,
  loading,
}: {
  testKey: string;
  label: string;
  value: string;
  hint: string;
  loading: boolean;
}) {
  return (
    <div data-testid={`collections-tile-${testKey}`}>
      <Card p={20}>
        <Overline>{label}</Overline>
        {loading ? (
          <div className="mt-2 h-9 w-28 animate-pulse rounded bg-rally-line/40" aria-hidden="true" />
        ) : (
          <div className="mt-1.5">
            <BigNum size={28}>
              <span data-testid={`collections-tile-${testKey}-value`}>{value}</span>
            </BigNum>
            <p className="mt-1 text-xs text-rally-muted">{hint}</p>
          </div>
        )}
      </Card>
    </div>
  );
}

function BucketSection({
  bucket,
  loading,
  search,
  today,
  rowStatus,
  busyParent,
  onAction,
}: {
  bucket: AdminCollectionsBucket;
  loading: boolean;
  search: string;
  today: string;
  rowStatus: Record<string, RowStatus>;
  busyParent: (parentId: string) => boolean;
  onAction: (action: CollectionsAction, family: AdminCollectionsFamily) => void;
}) {
  const meta = BUCKET_META[bucket.key];
  const families = bucket.families.filter((family) => familyMatches(family, search));
  const hidden = bucket.families.length - families.length;

  const header = (
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
      <div className="flex items-baseline gap-3">
        <h2 className="font-display text-lg font-semibold text-rally-ink">{meta.title}</h2>
        <span
          className="font-mono text-sm font-bold tabular-nums text-rally-muted"
          data-testid={`bucket-${bucket.key}-count`}
        >
          {bucket.count}
        </span>
      </div>
      {bucket.total_cents > 0 && (
        <span
          className="font-mono text-sm tabular-nums text-rally-muted"
          data-testid={`bucket-${bucket.key}-total`}
        >
          {formatCents(bucket.total_cents)}
        </span>
      )}
    </div>
  );

  const body = loading ? (
    <div className="pt-3">
      <TableSkeleton rows={2} />
    </div>
  ) : bucket.families.length === 0 ? (
    <p className="pt-3 text-sm text-rally-subtle" data-testid={`bucket-${bucket.key}-empty`}>
      {meta.emptyLine}
    </p>
  ) : families.length === 0 ? (
    <p className="pt-3 text-sm text-rally-subtle" data-testid={`bucket-${bucket.key}-filter-empty`}>
      No families match “{search.trim()}”.
    </p>
  ) : (
    <ul className="mt-3 divide-y divide-rally-line">
      {families.map((family) => (
        <FamilyRow
          key={family.parent_id}
          bucket={bucket.key}
          family={family}
          today={today}
          status={rowStatus[family.parent_id]}
          busy={busyParent(family.parent_id)}
          onAction={onAction}
        />
      ))}
      {hidden > 0 && (
        <li className="py-2 text-xs text-rally-subtle">{hidden} more hidden by search</li>
      )}
    </ul>
  );

  return (
    <section id={`bucket-${bucket.key}`} data-testid={`bucket-${bucket.key}`}>
      <Card p={0} className="flex">
        <div className={`w-1.5 shrink-0 ${meta.stripe}`} aria-hidden="true" />
        <div className="min-w-0 flex-1 p-4">
          {bucket.key === "paid" ? (
            <details>
              <summary
                className="cursor-pointer list-none [&::-webkit-details-marker]:hidden"
                data-testid="bucket-paid-toggle"
              >
                {header}
                <p className="mt-1 text-sm text-rally-subtle">{meta.hint} Click to expand.</p>
              </summary>
              {body}
            </details>
          ) : (
            <>
              {header}
              <p className="mt-1 text-sm text-rally-subtle">{meta.hint}</p>
              {body}
            </>
          )}
        </div>
      </Card>
    </section>
  );
}

function amountFor(bucket: CollectionsBucketKey, family: AdminCollectionsFamily): number {
  switch (bucket) {
    case "paid":
      return family.paid?.amount_cents ?? 0;
    case "paused":
      return family.leftover_balance_cents;
    default:
      // What is owed / what the worker will charge — the backend's balance,
      // which is also what the bucket header sums.
      return family.balance_cents;
  }
}

function FamilyRow({
  bucket,
  family,
  today,
  status,
  busy,
  onAction,
}: {
  bucket: CollectionsBucketKey;
  family: AdminCollectionsFamily;
  today: string;
  status: RowStatus | undefined;
  busy: boolean;
  onAction: (action: CollectionsAction, family: AdminCollectionsFamily) => void;
}) {
  const chip = familyChip(bucket, family, today);
  const line = secondaryLine(bucket, family, today);
  const firstStudent = family.students[0];
  const name = familyName(family);
  const amount = amountFor(bucket, family);

  return (
    <li className="py-3" data-testid={`family-row-${family.parent_id}`}>
      <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_auto_auto] md:items-center md:gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            {firstStudent ? (
              <Link
                href={`/admin/students/${encodeURIComponent(firstStudent.student_id)}`}
                className="font-display font-semibold text-rally-ink hover:underline"
              >
                {name}
              </Link>
            ) : (
              <span className="font-display font-semibold text-rally-ink">{name}</span>
            )}
            <Chip variant={chip.variant} label={chip.label} />
          </div>
          {family.students.length > 0 && (
            <p className="mt-0.5 truncate text-sm text-rally-muted">{studentLine(family)}</p>
          )}
          {line && <p className="mt-0.5 text-xs text-rally-subtle">{line}</p>}
          {status && (
            <p
              className={`mt-1 text-xs ${
                status.tone === "ok"
                  ? "text-status-green-800"
                  : status.tone === "warn"
                    ? "text-status-amber-800"
                    : "text-red-700"
              }`}
              data-testid={`row-status-${family.parent_id}`}
            >
              {status.text}
            </p>
          )}
        </div>
        <div className="font-mono text-base font-semibold tabular-nums text-rally-ink md:text-right">
          {formatCents(amount)}
        </div>
        <div className="flex flex-wrap gap-2 md:justify-end">
          {family.actions.map((action) => (
            <ActionControl
              key={action}
              action={action}
              family={family}
              busy={busy}
              onAction={onAction}
            />
          ))}
        </div>
      </div>
    </li>
  );
}

function ActionControl({
  action,
  family,
  busy,
  onAction,
}: {
  action: CollectionsAction;
  family: AdminCollectionsFamily;
  busy: boolean;
  onAction: (action: CollectionsAction, family: AdminCollectionsFamily) => void;
}): ReactNode {
  const label = ACTION_LABEL[action];
  const testId = `action-${action}-${family.parent_id}`;
  if (action === "message") {
    return (
      <Link
        href={`/admin/messages?dm=${encodeURIComponent(family.parent_id)}`}
        className="inline-flex h-[30px] items-center rounded-md border border-rally-line bg-white px-3 text-xs font-semibold text-rally-ink hover:bg-rally-paper"
        data-testid={testId}
      >
        {label}
      </Link>
    );
  }
  const primary = action === "record_payment" || action === "resume";
  return (
    <Button
      variant={primary ? "primary" : "secondary"}
      size="sm"
      disabled={busy}
      onClick={() => onAction(action, family)}
      data-testid={testId}
    >
      {label}
    </Button>
  );
}
