"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeftRight, RefreshCw, Tag } from "lucide-react";

import {
  listAdminBillingEnrollments,
  listAdminSessionTypes,
  moveAdminBillingEnrollment,
  overrideAdminBillingEnrollmentPrice,
  type AdminBillingEnrollmentView,
  type AdminSessionTypeView,
  type MoveBillingEnrollmentResponse,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";

import { BillingDialogActions, BillingDialogError, BillingDialogFrame } from "./billing-dialogs";
import {
  centsToDollarInput,
  dollarsToCents,
  formatCurrencyCents,
  formatDate,
  formatDateUtc,
  getErrorMessage,
} from "./format";
import { Field } from "./StudentEditForm";

type EnrollmentDialog = "move" | "override" | null;

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

/**
 * Calendar-month period for a YYYY-MM-DD move date, mirroring the backend's
 * `_default_period`: the admin move route requires the period explicitly and
 * proration is computed against it.
 */
function calendarMonthPeriod(
  moveDate: string,
): { periodStart: string; periodEnd: string } | null {
  const [year, month] = moveDate.split("-").map((part) => Number.parseInt(part, 10));
  // A cleared date input yields "" -> NaN, and toISOString() would throw while
  // the dialog is still mounted. Callers gate submission on a null return.
  if (!Number.isFinite(year) || !Number.isFinite(month)) return null;
  return {
    periodStart: new Date(Date.UTC(year, month - 1, 1)).toISOString(),
    periodEnd: new Date(Date.UTC(year, month, 1)).toISOString(),
  };
}

function BillingEnrollmentsPanel({ studentId, active }: { studentId: string; active: boolean }) {
  const queryClient = useQueryClient();
  const [dialog, setDialog] = useState<EnrollmentDialog>(null);
  const [selectedEnrollmentId, setSelectedEnrollmentId] = useState<string | null>(null);
  const [moveResult, setMoveResult] = useState<MoveBillingEnrollmentResponse | null>(null);

  const enrollmentsQuery = useQuery({
    queryKey: queryKeys.admin.billingEnrollments(studentId),
    queryFn: () => listAdminBillingEnrollments({ studentId }),
    enabled: active && Boolean(studentId),
  });
  const sessionTypesQuery = useQuery({
    queryKey: queryKeys.admin.sessionTypes(),
    queryFn: () => listAdminSessionTypes(),
    enabled: active,
  });

  const sessionTypes = useMemo(
    () => sessionTypesQuery.data?.session_types ?? [],
    [sessionTypesQuery.data],
  );
  const sessionTypeById = useMemo(
    () => new Map(sessionTypes.map((type) => [type.session_type_id, type])),
    [sessionTypes],
  );
  const enrollments = enrollmentsQuery.data?.enrollments ?? [];
  const selectedEnrollment =
    enrollments.find((row) => row.enrollment_id === selectedEnrollmentId) ?? null;

  const invalidate = () => {
    void queryClient.invalidateQueries({
      queryKey: queryKeys.admin.billingEnrollments(studentId),
    });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.admin.studentDetail(studentId),
    });
  };

  const closeDialog = () => {
    setDialog(null);
    setSelectedEnrollmentId(null);
  };

  return (
    <>
      <Card p={20} data-testid="admin-student-billing-enrollments">
        <div className="flex flex-col gap-3 border-b border-neutral-200 pb-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2">
            <Tag className="size-4 text-rally-muted" aria-hidden="true" />
            <Overline>Session-type billing</Overline>
          </div>
          <span className="font-mono text-xs tabular-nums text-rally-muted">
            {enrollments.length} {enrollments.length === 1 ? "enrollment" : "enrollments"}
          </span>
        </div>

        {getErrorMessage(enrollmentsQuery.error) && (
          <p role="alert" className="mt-3 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">
            {getErrorMessage(enrollmentsQuery.error)}
          </p>
        )}

        {moveResult && <ProrationResult result={moveResult} onDismiss={() => setMoveResult(null)} />}

        {enrollmentsQuery.isPending ? (
          <div
            className="mt-4 h-20 animate-pulse rounded-lg bg-neutral-100"
            aria-label="Loading billing enrollments"
          />
        ) : enrollments.length === 0 ? (
          <p
            className="mt-4 text-sm text-rally-muted"
            data-testid="admin-student-no-billing-enrollments"
          >
            This student has no session-type billing enrollment.
          </p>
        ) : (
          <div className="mt-4 overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="border-b border-neutral-200 text-xs uppercase tracking-overline text-rally-muted">
                <tr>
                  <th className="py-2 pr-4 font-medium">Session type</th>
                  <th className="py-2 pr-4 font-medium">Status</th>
                  <th className="py-2 pr-4 font-medium">Effective price</th>
                  <th className="py-2 pr-4 font-medium">Billing start</th>
                  <th className="py-2 font-medium" />
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100">
                {enrollments.map((enrollment) => (
                  <EnrollmentRow
                    key={enrollment.enrollment_id}
                    enrollment={enrollment}
                    sessionType={sessionTypeById.get(enrollment.session_type_id)}
                    onMove={() => {
                      setSelectedEnrollmentId(enrollment.enrollment_id);
                      setMoveResult(null);
                      setDialog("move");
                    }}
                    onOverride={() => {
                      setSelectedEnrollmentId(enrollment.enrollment_id);
                      setDialog("override");
                    }}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {dialog === "move" && selectedEnrollment && (
        <MoveEnrollmentDialog
          enrollment={selectedEnrollment}
          sessionTypes={sessionTypes}
          onCancel={closeDialog}
          onDone={(result) => {
            closeDialog();
            setMoveResult(result);
            invalidate();
          }}
        />
      )}
      {dialog === "override" && selectedEnrollment && (
        <OverridePriceDialog
          enrollment={selectedEnrollment}
          catalogPriceCents={
            sessionTypeById.get(selectedEnrollment.session_type_id)?.price_cents ?? null
          }
          onCancel={closeDialog}
          onDone={() => {
            closeDialog();
            invalidate();
          }}
        />
      )}
    </>
  );
}

function EnrollmentRow({
  enrollment,
  sessionType,
  onMove,
  onOverride,
}: {
  enrollment: AdminBillingEnrollmentView;
  sessionType: AdminSessionTypeView | undefined;
  onMove: () => void;
  onOverride: () => void;
}) {
  const hasOverride = enrollment.override_price_cents != null;
  const effectiveCents = enrollment.override_price_cents ?? sessionType?.price_cents ?? null;
  const movable = enrollment.status === "active" || enrollment.status === "paused";

  return (
    <tr data-testid={`billing-enrollment-${enrollment.enrollment_id}`}>
      {/* The catalog lists active types only, so an enrollment sitting on a
          soft-deleted type has no name to show — label it rather than leaking a raw id. */}
      <td className="py-3 pr-4 align-top text-rally-ink">
        {sessionType?.name ?? "Discontinued session type"}
      </td>
      <td className="py-3 pr-4 align-top text-rally-muted">{enrollment.status}</td>
      <td className="py-3 pr-4 align-top font-mono tabular-nums text-rally-ink">
        {effectiveCents == null ? "—" : formatCurrencyCents(effectiveCents)}
        {hasOverride && (
          <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 font-body text-[10px] font-semibold uppercase tracking-wide text-amber-800">
            Override
          </span>
        )}
      </td>
      <td className="py-3 pr-4 align-top text-rally-muted">
        {formatDate(enrollment.billing_start_date)}
      </td>
      <td className="py-3 align-top">
        <div className="flex flex-wrap justify-end gap-2">
          <Button
            size="sm"
            variant="secondary"
            icon={<ArrowLeftRight className="size-3.5" aria-hidden="true" />}
            onClick={onMove}
            disabled={!movable}
            title={movable ? undefined : "Only active or paused enrollments can be moved."}
          >
            Move
          </Button>
          <Button size="sm" variant="secondary" onClick={onOverride}>
            Override price
          </Button>
        </div>
      </td>
    </tr>
  );
}

function MoveEnrollmentDialog({
  enrollment,
  sessionTypes,
  onCancel,
  onDone,
}: {
  enrollment: AdminBillingEnrollmentView;
  sessionTypes: AdminSessionTypeView[];
  onCancel: () => void;
  onDone: (result: MoveBillingEnrollmentResponse) => void;
}) {
  const [step, setStep] = useState<"form" | "confirm">("form");
  const [toSessionTypeId, setToSessionTypeId] = useState("");
  const [moveDate, setMoveDate] = useState(todayISO);
  const [reason, setReason] = useState("");

  const targets = sessionTypes.filter(
    (type) => type.is_active && type.session_type_id !== enrollment.session_type_id,
  );
  const target = targets.find((type) => type.session_type_id === toSessionTypeId);
  const period = calendarMonthPeriod(moveDate);

  const mutation = useMutation({
    mutationFn: () => {
      if (!period) throw new Error("Pick a move date before confirming.");
      return moveAdminBillingEnrollment(enrollment.enrollment_id, {
        to_session_type_id: toSessionTypeId,
        move_date: new Date(`${moveDate}T00:00:00.000Z`).toISOString(),
        period_start: period.periodStart,
        period_end: period.periodEnd,
        reason: reason.trim() || null,
      });
    },
    onSuccess: onDone,
  });

  return (
    <BillingDialogFrame title="Move to another session type" onCancel={onCancel}>
      {getErrorMessage(mutation.error) && (
        <BillingDialogError message={getErrorMessage(mutation.error)!} />
      )}

      {step === "form" ? (
        <div className="space-y-3">
          <Field label="Target session type" htmlFor="billing-move-session-type">
            <select
              id="billing-move-session-type"
              value={toSessionTypeId}
              onChange={(event) => setToSessionTypeId(event.target.value)}
              className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
            >
              <option value="">Select a session type</option>
              {targets.map((type) => (
                <option key={type.session_type_id} value={type.session_type_id}>
                  {type.name} — {formatCurrencyCents(type.price_cents)}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Move date" htmlFor="billing-move-date">
            <input
              id="billing-move-date"
              type="date"
              value={moveDate}
              onChange={(event) => setMoveDate(event.target.value)}
              className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
            />
          </Field>
          <Field label="Reason" htmlFor="billing-move-reason">
            <textarea
              id="billing-move-reason"
              rows={3}
              maxLength={500}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              className="w-full rounded-md border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
            />
          </Field>
        </div>
      ) : (
        <div
          className="space-y-2 rounded-md bg-amber-50 px-3 py-3 text-sm text-amber-900"
          data-testid="billing-move-confirm"
        >
          <p className="font-semibold">This changes what the parent is billed.</p>
          <p>
            Moving to <span className="font-semibold">{target?.name}</span> on{" "}
            {formatDateUtc(moveDate)} switches the enrollment and records a prorated
            adjustment against the{" "}
            {period
              ? new Date(period.periodStart).toLocaleDateString(undefined, {
                  month: "long",
                  year: "numeric",
                  timeZone: "UTC",
                })
              : "selected"}{" "}
            billing period. The adjustment is recorded now; it is applied on the parent&apos;s
            next invoice rather than charged immediately.
          </p>
          <p>This cannot be undone from this screen.</p>
        </div>
      )}

      <BillingDialogActions onCancel={step === "form" ? onCancel : () => setStep("form")}>
        {step === "form" ? (
          <Button
            size="sm"
            disabled={!toSessionTypeId || !period}
            onClick={() => setStep("confirm")}
          >
            Review move
          </Button>
        ) : (
          <Button
            size="sm"
            disabled={mutation.isPending || !period}
            icon={
              mutation.isPending ? (
                <RefreshCw className="size-3.5 animate-spin" aria-hidden="true" />
              ) : undefined
            }
            onClick={() => mutation.mutate()}
            data-testid="billing-move-submit"
          >
            {mutation.isPending ? "Moving..." : "Confirm move"}
          </Button>
        )}
      </BillingDialogActions>
    </BillingDialogFrame>
  );
}

function OverridePriceDialog({
  enrollment,
  catalogPriceCents,
  onCancel,
  onDone,
}: {
  enrollment: AdminBillingEnrollmentView;
  catalogPriceCents: number | null;
  onCancel: () => void;
  onDone: () => void;
}) {
  const [amount, setAmount] = useState(() =>
    enrollment.override_price_cents == null
      ? ""
      : centsToDollarInput(enrollment.override_price_cents),
  );
  const mutation = useMutation({
    mutationFn: (overridePriceCents: number | null) =>
      overrideAdminBillingEnrollmentPrice(enrollment.enrollment_id, overridePriceCents),
    onSuccess: onDone,
  });
  const amountCents = dollarsToCents(amount);
  const canSave = amount.trim().length > 0 && amountCents >= 0;

  return (
    <BillingDialogFrame title="Override enrollment price" onCancel={onCancel}>
      {getErrorMessage(mutation.error) && (
        <BillingDialogError message={getErrorMessage(mutation.error)!} />
      )}
      <p className="text-xs text-rally-muted">
        {catalogPriceCents == null
          ? "Catalog price unavailable."
          : `Catalog price is ${formatCurrencyCents(catalogPriceCents)}. Clearing the override restores it.`}
      </p>
      <Field label="Override price" htmlFor="billing-override-amount">
        <input
          id="billing-override-amount"
          inputMode="decimal"
          value={amount}
          onChange={(event) => setAmount(event.target.value)}
          placeholder="0.00"
          className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
        />
      </Field>
      <BillingDialogActions onCancel={onCancel}>
        <Button
          size="sm"
          variant="secondary"
          disabled={enrollment.override_price_cents == null || mutation.isPending}
          onClick={() => mutation.mutate(null)}
          data-testid="billing-override-clear"
        >
          Clear override
        </Button>
        <Button
          size="sm"
          disabled={!canSave || mutation.isPending}
          icon={
            mutation.isPending ? (
              <RefreshCw className="size-3.5 animate-spin" aria-hidden="true" />
            ) : undefined
          }
          onClick={() => mutation.mutate(amountCents)}
          data-testid="billing-override-save"
        >
          {mutation.isPending ? "Saving..." : "Save override"}
        </Button>
      </BillingDialogActions>
    </BillingDialogFrame>
  );
}

function ProrationResult({
  result,
  onDismiss,
}: {
  result: MoveBillingEnrollmentResponse;
  onDismiss: () => void;
}) {
  const { proration } = result;
  const netLabel =
    proration.net_cents === 0
      ? "no net change"
      : proration.net_cents > 0
        ? `charged ${formatCurrencyCents(proration.net_cents)}`
        : `credited ${formatCurrencyCents(Math.abs(proration.net_cents))}`;

  return (
    <div
      className="mt-3 rounded-md border border-blue-200 bg-blue-50 px-3 py-3 text-xs text-blue-900"
      data-testid="billing-move-result"
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-semibold">Move applied — {netLabel}</p>
        <button type="button" onClick={onDismiss} className="text-blue-800 underline">
          Dismiss
        </button>
      </div>
      <dl className="mt-2 grid gap-x-6 gap-y-1 sm:grid-cols-2">
        <ResultRow label="Credit" value={formatCurrencyCents(proration.credit_cents)} />
        <ResultRow label="Charge" value={formatCurrencyCents(proration.charge_cents)} />
        <ResultRow
          label="Prorated days"
          value={`${proration.remaining_days} of ${proration.total_days} (${proration.proration_ratio})`}
        />
        <ResultRow label="Policy version" value={proration.policy_version} />
        {/* The move itself never creates a Stripe invoice today, so only surface
            this row if the backend ever starts returning one. */}
        {result.stripe_invoice_id && (
          <ResultRow label="Stripe invoice" value={result.stripe_invoice_id} />
        )}
      </dl>
    </div>
  );
}

function ResultRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-blue-800">{label}</dt>
      <dd className="font-mono tabular-nums">{value}</dd>
    </div>
  );
}

export { BillingEnrollmentsPanel };
