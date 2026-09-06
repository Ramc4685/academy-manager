"use client";

import type { Route } from "next";
import Link from "next/link";

import { Card, Chip, Overline, type ChipVariant } from "@/components/ds";
import type { FamilyStudent } from "@/lib/api/admin-families";
import { formatCents } from "@/lib/money";

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
}: {
  students: FamilyStudent[];
  isOwner: boolean;
}) {
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
              : s.enrollments.map((e) => {
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
                        {e.autopay_status === "active" ? (
                          <Chip variant="autopayOn" label="Autopay" />
                        ) : (
                          <Chip
                            variant="manual"
                            label={e.autopay_status === "paused" ? "Autopay off" : "Manual"}
                          />
                        )}
                        {isOwner && e.actions.includes("recurring_discount") && (
                          <Link
                            href={studentHref(s.student_id)}
                            className="text-rally-cobalt-700 hover:underline"
                            data-testid={`enrollment-discount-${e.enrollment_id}`}
                          >
                            Recurring discount
                          </Link>
                        )}
                      </span>
                    </li>
                  );
                }),
          )}
        </ul>
      )}
    </Card>
  );
}
