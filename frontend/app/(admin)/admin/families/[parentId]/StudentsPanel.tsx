"use client";

import { useState } from "react";
import type { Route } from "next";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { Card, Chip, Overline, PhoneList, PhoneListRow, type ChipVariant } from "@/components/ds";
import { useIsPhone } from "@/lib/use-is-phone";
import type { FamilyStudent } from "@/lib/api/admin-families";
import { formatCents } from "@/lib/money";
import { getDeparturePolicy } from "@/lib/api/v2/departure-policy";
import { StopAllClassesDialog } from "@/components/admin/enrollment/stop-all-classes-dialog";

import { shortDate } from "./family-view";

const STATUS_CHIP: Record<string, { variant: ChipVariant; label: string }> = {
  active: { variant: "enrolled", label: "Active" },
  paused: { variant: "paused", label: "Paused" },
  cancelled: { variant: "expired", label: "Cancelled" },
  withdrawn: { variant: "expired", label: "Withdrawn" },
};

function studentHref(studentId: string): Route {
  return `/admin/students/${encodeURIComponent(studentId)}` as Route;
}

export function StudentsPanel({
  students,
  isOwner,
  onBillPeriod,
}: {
  students: FamilyStudent[];
  isOwner: boolean;
  onBillPeriod: (enrollmentId: string) => void;
}) {
  const isPhone = useIsPhone();
  const [stopAllClassesFor, setStopAllClassesFor] = useState<{
    studentId: string;
    studentName: string;
  } | null>(null);
  const departurePolicyQuery = useQuery({
    queryKey: ["admin", "enrollment", "departure-policy"],
    queryFn: getDeparturePolicy,
    enabled: stopAllClassesFor !== null,
  });

  /**
   * #857: "Bill this month", "Recurring discount" and "Stop all classes" were
   * bare 16px-tall text links in the fourth cell of a four-column grid. They
   * keep their ids — `admin-family-billing.spec.ts` clicks
   * `enrollment-bill-period-<id>` and `stop-all-classes-<id>` directly, and a
   * row-menu item carries no `data-testid` — and gain a 44px target.
   */
  function enrollmentLinks(
    s: FamilyStudent,
    e: FamilyStudent["enrollments"][number],
    idx: number,
    phone: boolean,
  ) {
    const linkClass = phone ? "inline-flex min-h-touch items-center" : "";
    return (
      <>
        {e.status === "active" && (
          <button
            type="button"
            onClick={() => onBillPeriod(e.enrollment_id)}
            className={`${linkClass} text-rally-cobalt-700 hover:underline`}
            data-testid={`enrollment-bill-period-${e.enrollment_id}`}
          >
            Bill this month
          </button>
        )}
        {isOwner && e.actions.includes("recurring_discount") && (
          <Link
            href={studentHref(s.student_id)}
            className={`${linkClass} text-rally-cobalt-700 hover:underline`}
            data-testid={`enrollment-discount-${e.enrollment_id}`}
          >
            Recurring discount
          </Link>
        )}
        {idx === 0 && (
          <button
            type="button"
            onClick={() => setStopAllClassesFor({ studentId: s.student_id, studentName: s.name })}
            className={`${linkClass} text-rally-red-700 hover:underline`}
            data-testid={`stop-all-classes-${s.student_id}`}
          >
            Stop all classes
          </button>
        )}
      </>
    );
  }

  function autopayChip(e: FamilyStudent["enrollments"][number]) {
    return e.autopay_status === "active" ? (
      <Chip variant="autopayOn" label="Autopay" />
    ) : (
      <Chip variant="manual" label={e.autopay_status === "paused" ? "Autopay off" : "Manual"} />
    );
  }

  if (isPhone) {
    return (
      <Card p={20} data-testid="family-students">
        <Overline>Students and classes</Overline>
        {students.length === 0 ? (
          <p className="mt-2 text-sm text-rally-muted">No students on this family yet.</p>
        ) : (
          <PhoneList className="mt-2" aria-label="Students and classes">
            {students.flatMap((s) =>
              s.enrollments.length === 0
                ? [
                    <PhoneListRow
                      key={s.student_id}
                      title={s.name}
                      href={studentHref(s.student_id)}
                      secondary={<div>No classes</div>}
                    />,
                  ]
                : s.enrollments.map((e, idx) => {
                    const chip = STATUS_CHIP[e.status] ?? {
                      variant: "pending" as const,
                      label: e.status,
                    };
                    const price = e.override_price_cents ?? e.monthly_price_cents;
                    return (
                      <PhoneListRow
                        key={e.enrollment_id}
                        data-testid={`enrollment-row-${e.enrollment_id}`}
                        title={s.name}
                        href={studentHref(s.student_id)}
                        primary={
                          <span className="font-mono text-sm font-semibold tabular-nums text-rally-ink">
                            {price != null ? `${formatCents(price)}/mo` : "—"}
                          </span>
                        }
                        secondary={
                          <>
                            <div className="flex flex-wrap items-center gap-2">
                              <Chip variant={chip.variant} label={chip.label} />
                              {autopayChip(e)}
                            </div>
                            <div className="break-words">
                              {e.session_title ?? "Class"}
                              {e.schedule ? ` · ${e.schedule}` : ""}
                              {e.status === "paused" && e.resume_on
                                ? ` · resumes ${shortDate(e.resume_on)}`
                                : ""}
                            </div>
                            {(e.override_price_cents != null || e.recurring_discount) && (
                              <div>
                                {e.override_price_cents != null ? "Override price" : ""}
                                {e.override_price_cents != null && e.recurring_discount
                                  ? " · "
                                  : ""}
                                {e.recurring_discount ? "Recurring discount" : ""}
                              </div>
                            )}
                            <div className="flex flex-wrap items-center gap-3">
                              {enrollmentLinks(s, e, idx, true)}
                            </div>
                          </>
                        }
                      />
                    );
                  }),
            )}
          </PhoneList>
        )}
        {stopAllClassesFor && (
          <StopAllClassesDialog
            studentId={stopAllClassesFor.studentId}
            studentName={stopAllClassesFor.studentName}
            policyDefaultOutcome={departurePolicyQuery.data?.drop_default_outcome}
            onClose={() => setStopAllClassesFor(null)}
          />
        )}
      </Card>
    );
  }

  return (
    <Card p={20} data-testid="family-students">
      <Overline>Students and classes</Overline>
      {students.length === 0 ? (
        <p className="mt-2 text-sm text-rally-muted">No students on this family yet.</p>
      ) : (
        <ul className="mt-2 divide-y divide-rally-line">
          {students.flatMap((s) =>
            s.enrollments.length === 0
              ? [
                  <li
                    key={s.student_id}
                    className="flex items-center justify-between py-2 text-sm"
                  >
                    <Link
                      href={studentHref(s.student_id)}
                      className="font-semibold text-rally-ink hover:underline"
                    >
                      {s.name}
                    </Link>
                    <span className="text-rally-muted">no classes</span>
                  </li>,
                ]
              : s.enrollments.map((e, idx) => {
                  const chip = STATUS_CHIP[e.status] ?? {
                    variant: "pending" as const,
                    label: e.status,
                  };
                  const price = e.override_price_cents ?? e.monthly_price_cents;
                  return (
                    <li
                      key={e.enrollment_id}
                      data-testid={`enrollment-row-${e.enrollment_id}`}
                      className="grid gap-1 py-2 text-sm md:grid-cols-[minmax(0,1fr)_auto_auto_auto] md:items-center md:gap-4"
                    >
                      <div className="min-w-0">
                        <Link
                          href={studentHref(s.student_id)}
                          className="font-semibold text-rally-ink hover:underline"
                        >
                          {s.name}
                        </Link>
                        <span className="text-rally-muted">
                          {" "}
                          · {e.session_title ?? "Class"}
                          {e.schedule ? ` · ${e.schedule}` : ""}
                        </span>
                        {e.status === "paused" && e.resume_on && (
                          <span className="text-rally-muted">
                            {" "}
                            · resumes {shortDate(e.resume_on)}
                          </span>
                        )}
                      </div>
                      <Chip variant={chip.variant} label={chip.label} />
                      <span className="text-rally-ink">
                        {price != null ? `${formatCents(price)}/mo` : "—"}
                        {e.override_price_cents != null && (
                          <span className="text-xs text-rally-muted"> (override)</span>
                        )}
                        {e.recurring_discount && (
                          <span className="text-xs text-rally-muted"> · discount</span>
                        )}
                      </span>
                      <span className="flex items-center gap-2 text-xs text-rally-muted">
                        {autopayChip(e)}
                        {enrollmentLinks(s, e, idx, false)}
                      </span>
                    </li>
                  );
                }),
          )}
        </ul>
      )}
      {stopAllClassesFor && (
        <StopAllClassesDialog
          studentId={stopAllClassesFor.studentId}
          studentName={stopAllClassesFor.studentName}
          policyDefaultOutcome={departurePolicyQuery.data?.drop_default_outcome}
          onClose={() => setStopAllClassesFor(null)}
        />
      )}
    </Card>
  );
}
