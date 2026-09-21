"use client";

import { useEffect, useState } from "react";
import type { Route } from "next";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  listAdminSessions,
  type AdminSessionView,
} from "@/lib/api/admin";
import {
  overrideEnrollmentFee,
  removeTuitionDiscount,
  setTuitionDiscount,
  transferEnrollment,
  type AdminStudentSessionSummary,
  type TuitionDiscountCategory,
  type TuitionDiscountKind,
} from "@/lib/api/v2/students";
import { queryKeys } from "@/lib/query/keys";
import { useIsPhone } from "@/lib/use-is-phone";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";
import type { MenuItem } from "@/components/ds/menu";
import { PhoneList, PhoneListRow } from "@/components/ds/phone-row";
import { Overline } from "@/components/ds/typography";
import { useIsOwner } from "@/components/admin/owner-context";
import {
  DepartureActions,
  type DepartureAction,
} from "@/components/admin/enrollment/departure-actions";
import {
  HoldEnrollmentDialog,
  ReturnFromHoldDialog,
} from "@/components/admin/enrollment/hold-dialogs";

import {
  centsToDollarInput,
  dollarsToCents,
  formatCurrencyCents,
  formatDateTimeRange,
  getErrorMessage,
  previewNetCents,
} from "./format";
import {
  autopayChip,
  enrolledSessionActions,
  familyBillingHref,
  pastEnrollmentRow,
  sessionRosterHref,
  type EnrolledSessionActionKey,
} from "./session-rows";
import { StatusChip } from "./StatusChip";

const DISCOUNT_CATEGORIES: { value: TuitionDiscountCategory; label: string }[] = [
  { value: "owner_child", label: "Owner child" },
  { value: "coach_child", label: "Coach child" },
  { value: "scholarship", label: "Scholarship" },
  { value: "sibling", label: "Sibling" },
  { value: "other", label: "Other" },
];

const DISCOUNT_KINDS: { value: TuitionDiscountKind; label: string }[] = [
  { value: "waiver", label: "Waive fully" },
  { value: "percent", label: "% off" },
  { value: "amount_off", label: "$ off" },
  { value: "fixed_net", label: "Set final price" },
];

function SessionsPanel({
  sessions,
  pastEnrollments = [],
  parentId,
  studentId,
  studentName,
  queryClient,
}: {
  sessions: AdminStudentSessionSummary[];
  /** Issue #674: cancelled / withdrawn rows, newest ended first. */
  pastEnrollments?: AdminStudentSessionSummary[];
  /** Autopay lives on the family page; the chip links there when a parent is on file. */
  parentId?: string | null;
  studentId: string;
  studentName: string;
  queryClient: ReturnType<typeof useQueryClient>;
}) {
  const billingHref = familyBillingHref(parentId);
  const isOwner = useIsOwner();
  // #865: one layout at a time, like every other admin list since #847.
  const isPhone = useIsPhone();
  const [moving, setMoving] = useState<AdminStudentSessionSummary | null>(null);
  const [holding, setHolding] = useState<AdminStudentSessionSummary | null>(
    null,
  );
  const [returning, setReturning] =
    useState<AdminStudentSessionSummary | null>(null);
  const [billingOverride, setBillingOverride] =
    useState<AdminStudentSessionSummary | null>(null);
  const [overrideAmount, setOverrideAmount] = useState("");
  const [targetSessionId, setTargetSessionId] = useState("");
  const [effectiveDate, setEffectiveDate] = useState(() =>
    new Date().toISOString().slice(0, 10),
  );
  const [reason, setReason] = useState("");

  // Recurring tuition discount editor (#244)
  const [discounting, setDiscounting] =
    useState<AdminStudentSessionSummary | null>(null);
  const [discountCategory, setDiscountCategory] =
    useState<TuitionDiscountCategory>("scholarship");
  const [discountLabel, setDiscountLabel] = useState("");
  const [discountKind, setDiscountKind] =
    useState<TuitionDiscountKind>("waiver");
  const [discountValue, setDiscountValue] = useState("");
  const [discountStart, setDiscountStart] = useState(() =>
    new Date().toISOString().slice(0, 10),
  );
  const [discountNote, setDiscountNote] = useState("");

  const discountGross =
    discounting?.discount?.gross_cents ?? discounting?.amount_cents ?? 0;
  const discountPreviewNet = previewNetCents(
    discountGross,
    discountKind,
    discountValue,
  );

  const setDiscountMutation = useMutation({
    mutationFn: () =>
      setTuitionDiscount(discounting!.enrollment_id, {
        student_id: studentId,
        category: discountCategory,
        category_label: discountCategory === "other" ? discountLabel : null,
        kind: discountKind,
        percent_bps:
          discountKind === "percent"
            ? Math.round(Number(discountValue) * 100)
            : null,
        amount_off_cents:
          discountKind === "amount_off"
            ? Math.round(Number(discountValue) * 100)
            : null,
        fixed_net_cents:
          discountKind === "fixed_net"
            ? Math.round(Number(discountValue) * 100)
            : null,
        effective_start: discountStart,
        note: discountNote || null,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.studentDetail(studentId),
      });
      setDiscounting(null);
    },
  });

  const removeDiscountMutation = useMutation({
    mutationFn: () => removeTuitionDiscount(discounting!.enrollment_id),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.studentDetail(studentId),
      });
      setDiscounting(null);
    },
  });

  const sessionsQuery = useQuery({
    queryKey: queryKeys.admin.sessions("upcoming"),
    queryFn: () => listAdminSessions(undefined, { window: "upcoming" }),
    enabled: Boolean(moving),
  });

  const transferMutation = useMutation({
    mutationFn: () =>
      transferEnrollment(moving!.enrollment_id, {
        target_session_id: targetSessionId,
        effective_date: effectiveDate,
        reason: reason || null,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.studentDetail(studentId),
      });
      setMoving(null);
      setTargetSessionId("");
      setReason("");
    },
  });

  const overrideMutation = useMutation({
    mutationFn: (amountCents: number | null) =>
      overrideEnrollmentFee(billingOverride!.enrollment_id, {
        amount_cents: amountCents,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.studentDetail(studentId),
      });
      setBillingOverride(null);
      setOverrideAmount("");
    },
  });

  const availableSessions: AdminSessionView[] = (
    sessionsQuery.data?.sessions ?? []
  ).filter((s) => s.session_id !== moving?.session_id);

  useEffect(() => {
    if (!moving && !billingOverride) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !transferMutation.isPending) {
        setMoving(null);
      }
      if (event.key === "Escape" && !overrideMutation.isPending) {
        setBillingOverride(null);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [
    billingOverride,
    moving,
    overrideMutation.isPending,
    transferMutation.isPending,
  ]);

  const overridePriceCents = dollarsToCents(overrideAmount);
  const overrideAmountInvalid =
    Boolean(billingOverride) &&
    (overrideAmount.trim() === "" || overridePriceCents < 0);

  /**
   * #865: the ONE place an action on an enrolled session is carried out.
   * The desktop table's buttons, its `DepartureActions` menu and the phone
   * row's 44px menu all call this — so the layouts cannot drift into opening
   * different dialogs, or pre-filling them differently, for the same row.
   */
  const runSessionAction = (
    session: AdminStudentSessionSummary,
    key: EnrolledSessionActionKey,
  ) => {
    switch (key) {
      case "hold":
        setHolding(session);
        return;
      case "return":
        setReturning(session);
        return;
      case "transfer":
        setMoving(session);
        setTargetSessionId("");
        setReason("");
        setEffectiveDate(new Date().toISOString().slice(0, 10));
        return;
      case "fee":
        setBillingOverride(session);
        setOverrideAmount(
          session.amount_cents == null ? "" : centsToDollarInput(session.amount_cents),
        );
        return;
      case "discount": {
        setDiscounting(session);
        const d = session.discount;
        setDiscountCategory(d?.category ?? "scholarship");
        setDiscountLabel(d?.category_label ?? "");
        setDiscountKind(d?.kind ?? "waiver");
        setDiscountValue("");
        setDiscountStart(d?.effective_start ?? new Date().toISOString().slice(0, 10));
        setDiscountNote("");
        return;
      }
    }
  };

  const phoneMenuItems = (session: AdminStudentSessionSummary): MenuItem[] =>
    enrolledSessionActions(session).map((action) => ({
      key: action.key,
      label: action.label,
      description: action.description,
      onSelect: () => runSessionAction(session, action.key),
    }));

  return (
    <>
      <Card p={20} className="lg:col-span-2">
        <div className="flex items-center justify-between gap-3">
          <Overline>Enrolled sessions</Overline>
          <span className="font-mono text-xs text-rally-muted tabular-nums">
            {sessions.filter((s) => s.status === "active").length} active
          </span>
        </div>
        {sessions.length === 0 ? (
          <p
            className="mt-3 text-sm text-rally-muted"
            data-testid="admin-student-no-sessions"
          >
            No session enrollments.
          </p>
        ) : isPhone ? (
          <div className="-mx-5 mt-3" data-testid="admin-student-enrolled-sessions">
            <PhoneList aria-label="Enrolled sessions">
              {sessions.map((session) => (
                <PhoneListRow
                  key={session.enrollment_id}
                  data-testid={`admin-student-enrollment-${session.enrollment_id}`}
                  title={session.session_title}
                  primary={<StatusChip status={session.status} />}
                  actionsLabel={`Actions for ${session.session_title}`}
                  actionsTestId={`admin-student-enrollment-actions-${session.enrollment_id}`}
                  actions={phoneMenuItems(session)}
                  secondary={
                    <>
                      <div>{session.location ?? session.session_id}</div>
                      <div>{formatDateTimeRange(session.start_at, session.end_at)}</div>
                      {/* The table's derived money, not a second derivation. */}
                      <div className="flex flex-wrap items-center gap-2">
                        {session.discount ? (
                          <>
                            <span className="font-mono tabular-nums text-rally-ink">
                              {formatCurrencyCents(session.discount.net_cents)}
                            </span>
                            {session.discount.discount_cents > 0 && (
                              <span className="font-mono text-xs tabular-nums line-through">
                                {formatCurrencyCents(session.discount.gross_cents)}
                              </span>
                            )}
                            <span className="inline-flex items-center rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">
                              {session.discount.label}
                            </span>
                          </>
                        ) : (
                          <>
                            <span className="font-mono tabular-nums text-rally-ink">
                              {session.amount_cents == null
                                ? "—"
                                : formatCurrencyCents(session.amount_cents)}
                            </span>
                            <span>
                              {session.payment_mode ?? session.subscription_status ?? "—"}
                            </span>
                          </>
                        )}
                      </div>
                      <div className="flex flex-wrap items-center gap-1.5">
                        {session.subscription_status &&
                          session.subscription_status !== session.status && (
                            <StatusChip status={session.subscription_status} />
                          )}
                        <AutopayChipLink
                          status={session.autopay_status}
                          href={billingHref}
                          enrollmentId={session.enrollment_id}
                        />
                      </div>
                    </>
                  }
                />
              ))}
            </PhoneList>
          </div>
        ) : (
          <div
            className="mt-3 overflow-x-auto"
            data-testid="admin-student-enrolled-sessions"
          >
            <table className="min-w-full text-left text-sm">
              <thead className="border-b border-neutral-200 text-xs uppercase tracking-overline text-rally-muted">
                <tr>
                  <th className="py-2 pr-4 font-medium">Session</th>
                  <th className="py-2 pr-4 font-medium">Schedule</th>
                  <th className="py-2 pr-4 font-medium">Billing</th>
                  <th className="py-2 pr-4 font-medium">Status</th>
                  <th className="py-2 font-medium" />
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100">
                {sessions.map((session) => (
                  <tr
                    key={session.enrollment_id}
                    // #865: the same row id the phone row carries, so a spec
                    // names one enrollment at either width.
                    data-testid={`admin-student-enrollment-${session.enrollment_id}`}
                  >
                    <td className="py-3 pr-4 align-top">
                      <div className="font-medium text-rally-ink">
                        {session.session_title}
                      </div>
                      <div className="text-xs text-rally-muted">
                        {session.location ?? session.session_id}
                      </div>
                    </td>
                    <td className="py-3 pr-4 align-top text-rally-muted">
                      {formatDateTimeRange(session.start_at, session.end_at)}
                    </td>
                    <td className="py-3 pr-4 align-top">
                      {session.discount ? (
                        <>
                          <div className="flex items-center gap-2">
                            <span className="font-mono tabular-nums text-rally-ink">
                              {formatCurrencyCents(session.discount.net_cents)}
                            </span>
                            {session.discount.discount_cents > 0 && (
                              <span className="font-mono text-xs tabular-nums text-rally-muted line-through">
                                {formatCurrencyCents(session.discount.gross_cents)}
                              </span>
                            )}
                          </div>
                          <span className="mt-1 inline-flex items-center rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">
                            {session.discount.label}
                          </span>
                        </>
                      ) : (
                        <>
                          <div className="font-mono tabular-nums text-rally-ink">
                            {session.amount_cents == null
                              ? "—"
                              : formatCurrencyCents(session.amount_cents)}
                          </div>
                          <div className="text-xs text-rally-muted">
                            {session.payment_mode ??
                              session.subscription_status ??
                              "—"}
                          </div>
                        </>
                      )}
                    </td>
                    <td className="py-3 pr-4 align-top">
                      <div className="flex flex-col items-start gap-1.5">
                        <StatusChip status={session.status} />
                        {session.subscription_status &&
                          session.subscription_status !== session.status && (
                            <StatusChip status={session.subscription_status} />
                          )}
                        <AutopayChipLink
                          status={session.autopay_status}
                          href={billingHref}
                          enrollmentId={session.enrollment_id}
                        />
                      </div>
                    </td>
                    <td className="py-3 align-top">
                      <div className="flex items-center justify-end gap-3">
                        {/* #865: the same list the phone menu renders, so the
                            two layouts offer one set of actions. */}
                        {enrolledSessionActions(session)
                          .filter(
                            (action) => action.key === "fee" || action.key === "discount",
                          )
                          .map((action) => (
                            <button
                              key={action.key}
                              className="text-xs font-medium text-rally-cobalt-600 hover:underline"
                              onClick={() => runSessionAction(session, action.key)}
                            >
                              {action.label}
                            </button>
                          ))}
                        <DepartureActions
                          enrollmentId={session.enrollment_id}
                          studentName={session.session_title}
                          status={session.status}
                          layout="inline"
                          isOwner={isOwner}
                          actions={enrolledSessionActions(session)
                            .filter(
                              (action) => action.key !== "fee" && action.key !== "discount",
                            )
                            .map((action) => action.key as DepartureAction)}
                          onAction={(action: DepartureAction) =>
                            runSessionAction(session, action as EnrolledSessionActionKey)
                          }
                        />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <PastEnrollmentsPanel rows={pastEnrollments} />

      <HoldEnrollmentDialog
        enrollmentId={holding?.enrollment_id ?? null}
        studentName={studentName}
        onClose={() => setHolding(null)}
        onHeld={() => {
          setHolding(null);
          void queryClient.invalidateQueries({
            queryKey: queryKeys.admin.studentDetail(studentId),
          });
        }}
      />
      <ReturnFromHoldDialog
        enrollmentId={returning?.enrollment_id ?? null}
        studentName={studentName}
        onClose={() => setReturning(null)}
        onReturned={() => {
          setReturning(null);
          void queryClient.invalidateQueries({
            queryKey: queryKeys.admin.studentDetail(studentId),
          });
        }}
      />

      {moving && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="move-session-title"
            className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl dark:bg-neutral-900"
          >
            <h2
              id="move-session-title"
              className="mb-1 text-base font-semibold text-rally-ink"
            >
              Move student session
            </h2>
            <p className="mb-4 text-sm text-rally-muted">
              Moving <span className="font-medium">{moving.session_title}</span>
            </p>

            {transferMutation.isError && (
              <p className="mb-3 rounded bg-red-50 px-3 py-2 text-xs text-red-600">
                {String(transferMutation.error)}
              </p>
            )}

            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-overline text-rally-muted">
                  New session
                </label>
                <select
                  className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-ink focus:outline-none focus:ring-2 focus:border-rally-cobalt-600 focus:ring-rally-cobalt-600/15 dark:bg-neutral-800"
                  value={targetSessionId}
                  onChange={(e) => setTargetSessionId(e.target.value)}
                  disabled={sessionsQuery.isPending}
                >
                  <option value="">
                    {sessionsQuery.isPending ? "Loading…" : "Select a session"}
                  </option>
                  {availableSessions.map((s) => (
                    <option key={s.session_id} value={s.session_id}>
                      {s.title} {s.coach_name ? `— ${s.coach_name}` : ""}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-overline text-rally-muted">
                  Effective date
                </label>
                <input
                  type="date"
                  className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-ink focus:outline-none focus:ring-2 focus:border-rally-cobalt-600 focus:ring-rally-cobalt-600/15 dark:bg-neutral-800"
                  value={effectiveDate}
                  onChange={(e) => setEffectiveDate(e.target.value)}
                />
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-overline text-rally-muted">
                  Reason (optional)
                </label>
                <textarea
                  className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-ink focus:outline-none focus:ring-2 focus:border-rally-cobalt-600 focus:ring-rally-cobalt-600/15 dark:bg-neutral-800"
                  rows={2}
                  placeholder="e.g. schedule conflict"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
              </div>
            </div>

            <div className="mt-5 flex justify-end gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setMoving(null)}
                disabled={transferMutation.isPending}
              >
                Cancel
              </Button>
              <Button
                size="sm"
                onClick={() => transferMutation.mutate()}
                disabled={!targetSessionId || transferMutation.isPending}
              >
                {transferMutation.isPending ? "Moving…" : "Move student"}
              </Button>
            </div>
          </div>
        </div>
      )}

      {discounting && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="discount-title"
            className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl dark:bg-neutral-900"
          >
            <h2
              id="discount-title"
              className="mb-1 text-base font-semibold text-rally-ink"
            >
              Tuition discount
            </h2>
            <p className="mb-4 text-sm text-rally-muted">
              {discounting.session_title}
            </p>

            {(setDiscountMutation.isError || removeDiscountMutation.isError) && (
              <p className="mb-3 rounded bg-red-50 px-3 py-2 text-xs text-red-600">
                {String(
                  setDiscountMutation.error ?? removeDiscountMutation.error,
                )}
              </p>
            )}

            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-overline text-rally-muted">
                  Category
                </label>
                <select
                  className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-ink focus:outline-none focus:ring-2 focus:border-rally-cobalt-600 focus:ring-rally-cobalt-600/15 dark:bg-neutral-800"
                  value={discountCategory}
                  onChange={(e) =>
                    setDiscountCategory(e.target.value as TuitionDiscountCategory)
                  }
                >
                  {DISCOUNT_CATEGORIES.map((c) => (
                    <option key={c.value} value={c.value}>
                      {c.label}
                    </option>
                  ))}
                </select>
              </div>

              {discountCategory === "other" && (
                <div>
                  <label className="mb-1 block text-xs font-medium uppercase tracking-overline text-rally-muted">
                    Custom label
                  </label>
                  <input
                    className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-ink focus:outline-none focus:ring-2 focus:border-rally-cobalt-600 focus:ring-rally-cobalt-600/15 dark:bg-neutral-800"
                    placeholder="e.g. Founding family rate"
                    value={discountLabel}
                    onChange={(e) => setDiscountLabel(e.target.value)}
                  />
                </div>
              )}

              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-overline text-rally-muted">
                  Type
                </label>
                <select
                  className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-ink focus:outline-none focus:ring-2 focus:border-rally-cobalt-600 focus:ring-rally-cobalt-600/15 dark:bg-neutral-800"
                  value={discountKind}
                  onChange={(e) =>
                    setDiscountKind(e.target.value as TuitionDiscountKind)
                  }
                >
                  {DISCOUNT_KINDS.map((k) => (
                    <option key={k.value} value={k.value}>
                      {k.label}
                    </option>
                  ))}
                </select>
              </div>

              {discountKind !== "waiver" && (
                <div>
                  <label className="mb-1 block text-xs font-medium uppercase tracking-overline text-rally-muted">
                    {discountKind === "percent"
                      ? "Percent off"
                      : discountKind === "amount_off"
                        ? "Amount off ($)"
                        : "Final monthly price ($)"}
                  </label>
                  <input
                    type="number"
                    min="0"
                    className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-ink focus:outline-none focus:ring-2 focus:border-rally-cobalt-600 focus:ring-rally-cobalt-600/15 dark:bg-neutral-800"
                    value={discountValue}
                    onChange={(e) => setDiscountValue(e.target.value)}
                  />
                </div>
              )}

              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-overline text-rally-muted">
                  Effective start
                </label>
                <input
                  type="date"
                  className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-ink focus:outline-none focus:ring-2 focus:border-rally-cobalt-600 focus:ring-rally-cobalt-600/15 dark:bg-neutral-800"
                  value={discountStart}
                  onChange={(e) => setDiscountStart(e.target.value)}
                />
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-overline text-rally-muted">
                  Private note (optional)
                </label>
                <textarea
                  className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-ink focus:outline-none focus:ring-2 focus:border-rally-cobalt-600 focus:ring-rally-cobalt-600/15 dark:bg-neutral-800"
                  rows={2}
                  value={discountNote}
                  onChange={(e) => setDiscountNote(e.target.value)}
                />
              </div>

              <div className="rounded-lg bg-neutral-50 px-3 py-2 text-sm dark:bg-neutral-800">
                <span className="text-rally-muted">Gross </span>
                <span className="font-mono tabular-nums">
                  {formatCurrencyCents(discountGross)}
                </span>
                <span className="text-rally-muted"> → Net </span>
                <span className="font-mono font-semibold tabular-nums text-rally-ink">
                  {formatCurrencyCents(discountPreviewNet)}
                </span>
              </div>
            </div>

            <div className="mt-5 flex justify-between gap-2">
              <div>
                {discounting.discount && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => removeDiscountMutation.mutate()}
                    disabled={removeDiscountMutation.isPending}
                  >
                    {removeDiscountMutation.isPending ? "Removing…" : "Remove"}
                  </Button>
                )}
              </div>
              <div className="flex gap-2">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setDiscounting(null)}
                  disabled={setDiscountMutation.isPending}
                >
                  Cancel
                </Button>
                <Button
                  size="sm"
                  onClick={() => setDiscountMutation.mutate()}
                  disabled={
                    setDiscountMutation.isPending ||
                    (discountCategory === "other" && !discountLabel.trim()) ||
                    (discountKind !== "waiver" && !discountValue.trim())
                  }
                >
                  {setDiscountMutation.isPending ? "Saving…" : "Save discount"}
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {billingOverride && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="session-fee-title"
            className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl dark:bg-neutral-900"
          >
            <h2
              id="session-fee-title"
              className="mb-1 text-base font-semibold text-rally-ink"
            >
              Update session fee
            </h2>
            <p className="mb-4 text-sm text-rally-muted">
              {billingOverride.session_title}
            </p>

            {overrideMutation.isError && (
              <p className="mb-3 rounded bg-red-50 px-3 py-2 text-xs text-red-600">
                {getErrorMessage(overrideMutation.error)}
              </p>
            )}

            <div className="space-y-3">
              <div className="rounded-lg border border-neutral-200 p-3">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-rally-muted">Current fee</span>
                  <span className="font-mono text-rally-ink tabular-nums">
                    {billingOverride.amount_cents == null
                      ? "—"
                      : formatCurrencyCents(billingOverride.amount_cents)}
                  </span>
                </div>
              </div>

              <div>
                <label
                  className="mb-1 block text-xs font-medium uppercase tracking-overline text-rally-muted"
                  htmlFor="session-fee-amount"
                >
                  Monthly fee
                </label>
                <input
                  id="session-fee-amount"
                  type="number"
                  min="0"
                  step="0.01"
                  className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-ink focus:outline-none focus:ring-2 focus:border-rally-cobalt-600 focus:ring-rally-cobalt-600/15 dark:bg-neutral-800"
                  value={overrideAmount}
                  onChange={(event) => setOverrideAmount(event.target.value)}
                />
                <p className="mt-1 text-xs text-rally-muted">
                  Use 0.00 to waive this student&apos;s session fee.
                </p>
                {overrideAmountInvalid && (
                  <p className="mt-1 text-xs text-red-600">
                    Enter a valid amount.
                  </p>
                )}
              </div>
            </div>

            <div className="mt-5 flex flex-wrap justify-end gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setBillingOverride(null)}
                disabled={overrideMutation.isPending}
              >
                Cancel
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => overrideMutation.mutate(null)}
                disabled={overrideMutation.isPending}
              >
                Use default fee
              </Button>
              <Button
                size="sm"
                onClick={() => overrideMutation.mutate(overridePriceCents)}
                disabled={overrideAmountInvalid || overrideMutation.isPending}
              >
                {overrideMutation.isPending ? "Saving…" : "Save fee"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

/**
 * Issue #674: the autopay state of one enrollment, wording from
 * `autopayChip`. Wrapped in a link to the family billing page (where autopay
 * is actually managed) whenever the student has a parent on file.
 */
function AutopayChipLink({
  status,
  href,
  enrollmentId,
}: {
  status: string | null | undefined;
  href: string | null;
  enrollmentId: string;
}) {
  const chip = autopayChip(status);
  const testId = `admin-student-autopay-${enrollmentId}`;
  if (!href) {
    return (
      <span data-testid={testId} data-autopay-status={status ?? "none"}>
        <Chip variant={chip.variant} label={chip.label} />
      </span>
    );
  }
  return (
    <Link
      href={href as Route}
      className="rounded-full focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600"
      title="Manage autopay on the family billing page"
      data-testid={testId}
      data-autopay-status={status ?? "none"}
    >
      <Chip variant={chip.variant} label={chip.label} />
    </Link>
  );
}

/**
 * Issue #674: enrollments that ended (cancelled / withdrawn) with when, by
 * whom and why, so a cancelled student no longer looks
 * like one who was never enrolled. Read-only: nothing here can be edited.
 */
function PastEnrollmentsPanel({ rows }: { rows: AdminStudentSessionSummary[] }) {
  return (
    <Card p={20} className="lg:col-span-2" data-testid="admin-student-past-enrollments">
      <div className="flex items-center justify-between gap-3">
        <Overline>Past enrollments</Overline>
        <span className="font-mono text-xs text-rally-muted tabular-nums">
          {rows.length} ended
        </span>
      </div>
      {rows.length === 0 ? (
        <p className="mt-3 text-sm text-rally-muted" data-testid="admin-student-no-past-enrollments">
          No cancelled or withdrawn enrollments.
        </p>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-neutral-200 text-xs uppercase tracking-overline text-rally-muted">
              <tr>
                <th className="py-2 pr-4 font-medium">Session</th>
                <th className="py-2 pr-4 font-medium">Status</th>
                <th className="py-2 pr-4 font-medium">Ended</th>
                <th className="py-2 pr-4 font-medium">Ended by</th>
                <th className="py-2 pr-4 font-medium">Reason</th>
                <th className="py-2 font-medium">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-100">
              {rows.map((raw) => {
                const row = pastEnrollmentRow(raw);
                return (
                  <tr
                    key={row.enrollmentId}
                    data-testid={`admin-student-past-enrollment-${row.enrollmentId}`}
                  >
                    <td className="py-3 pr-4 align-top">
                      <div className="font-medium text-rally-ink">{row.sessionTitle}</div>
                      {row.location && (
                        <div className="text-xs text-rally-muted">{row.location}</div>
                      )}
                    </td>
                    <td className="py-3 pr-4 align-top">
                      <Chip variant={row.statusVariant} label={row.statusLabel} />
                    </td>
                    <td className="py-3 pr-4 align-top text-rally-muted tabular-nums">
                      {row.endedOn}
                    </td>
                    <td className="py-3 pr-4 align-top text-rally-muted">{row.endedBy}</td>
                    <td className="py-3 pr-4 align-top text-rally-muted">{row.reason}</td>
                    {/* #827: Past was read-only, so putting a student back
                        meant finding the class by hand. The roster owns the
                        Re-enroll action (and the seat check that goes with
                        it); this is the way there. */}
                    <td className="py-3 align-top text-right">
                      <Link
                        href={sessionRosterHref(row.sessionId) as Parameters<typeof Link>[0]["href"]}
                        data-testid={`admin-student-re-enroll-${row.enrollmentId}`}
                        className="text-xs font-medium text-rally-cobalt-600 hover:underline"
                      >
                        Re-enroll
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

export { SessionsPanel };
