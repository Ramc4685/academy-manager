"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  listCoachBillingEnrollments,
  previewCoachBillingMove,
  type CoachBillingEnrollment,
} from "@/lib/api/coach";
import { queryKeys } from "@/lib/query/keys";

function formatCents(cents: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(cents / 100);
}

function isForbidden(error: unknown): boolean {
  return (error as { status?: number } | null)?.status === 403;
}

/**
 * Read-only proration preview for a roster student.
 *
 * Coaches can see what a session-type change would cost but cannot apply it —
 * the coach move endpoint is 403 by design, so this panel deliberately has no
 * submit affordance.
 */
export function BillingPreviewDrawer({
  sessionId,
  studentId,
  studentName,
  onClose,
}: {
  sessionId: string;
  studentId: string;
  studentName: string;
  onClose: () => void;
}) {
  const [toSessionTypeId, setToSessionTypeId] = useState("");

  const enrollmentsQuery = useQuery({
    queryKey: queryKeys.coach.billingEnrollments(sessionId),
    queryFn: () => listCoachBillingEnrollments(sessionId),
  });

  const enrollments: CoachBillingEnrollment[] = enrollmentsQuery.data ?? [];
  const enrollment = enrollments.find((row) => row.student_id === studentId) ?? null;
  const currentSessionTypeId = enrollment?.session_type_id;

  // Coaches have no session-types route, so the target list is limited to the
  // types already present on this roster. Left unmemoized deliberately: the
  // React Compiler handles it, and a manual useMemo here defeats compilation.
  const seenTargets = new Map<string, string>();
  for (const row of enrollments) {
    if (row.session_type_id !== currentSessionTypeId) {
      seenTargets.set(row.session_type_id, row.session_type_name);
    }
  }
  const targets = [...seenTargets.entries()].map(([id, name]) => ({ id, name }));

  const previewQuery = useQuery({
    queryKey: queryKeys.coach.billingMovePreview(
      enrollment?.enrollment_id ?? "",
      toSessionTypeId,
    ),
    queryFn: () => previewCoachBillingMove(enrollment!.enrollment_id, toSessionTypeId),
    enabled: Boolean(enrollment && toSessionTypeId),
  });

  const accessDenied = isForbidden(enrollmentsQuery.error) || isForbidden(previewQuery.error);

  return (
    <div
      className="mt-3 rounded-lg border p-3"
      style={{ borderColor: "var(--rally-line)", background: "var(--rally-paper)" }}
      data-testid={`billing-preview-${studentId}`}
    >
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-sm font-semibold" style={{ color: "var(--rally-ink)" }}>
          Billing preview — {studentName}
        </h3>
        <button
          type="button"
          onClick={onClose}
          className="text-xs underline"
          style={{ color: "var(--rally-muted)" }}
        >
          Close
        </button>
      </div>

      {accessDenied ? (
        <p className="mt-2 text-xs text-red-700" data-testid="billing-preview-denied">
          You don&apos;t have access to this student&apos;s billing.
        </p>
      ) : enrollmentsQuery.isPending ? (
        <p className="mt-2 text-xs" style={{ color: "var(--rally-muted)" }}>
          Loading billing…
        </p>
      ) : !enrollment ? (
        <p className="mt-2 text-xs" style={{ color: "var(--rally-muted)" }}>
          No session-type billing enrollment for this student.
        </p>
      ) : (
        <div className="mt-2 space-y-3">
          <dl className="space-y-1 text-xs" style={{ color: "var(--rally-muted)" }}>
            <div className="flex justify-between gap-3">
              <dt>Current type</dt>
              <dd style={{ color: "var(--rally-ink)" }}>{enrollment.session_type_name}</dd>
            </div>
            {enrollment.override_price_cents != null && (
              <div className="flex justify-between gap-3">
                <dt>Price override</dt>
                <dd style={{ color: "var(--rally-ink)" }}>
                  {formatCents(enrollment.override_price_cents)}
                </dd>
              </div>
            )}
          </dl>

          <label className="block text-xs" style={{ color: "var(--rally-muted)" }}>
            Preview move to
            <select
              value={toSessionTypeId}
              onChange={(event) => setToSessionTypeId(event.target.value)}
              className="mt-1 h-9 w-full rounded-md border px-2 text-sm"
              style={{ borderColor: "var(--rally-line)", background: "#fff" }}
              data-testid="billing-preview-target"
            >
              <option value="">Select a session type</option>
              {targets.map((target) => (
                <option key={target.id} value={target.id}>
                  {target.name}
                </option>
              ))}
            </select>
          </label>

          {targets.length === 0 && (
            <p className="text-xs" style={{ color: "var(--rally-muted)" }}>
              No other session types appear on this roster.
            </p>
          )}

          {toSessionTypeId && previewQuery.isPending && (
            <p className="text-xs" style={{ color: "var(--rally-muted)" }}>
              Calculating proration…
            </p>
          )}

          {previewQuery.data && (
            <dl className="space-y-1 text-xs" data-testid="billing-preview-result">
              <div className="flex justify-between gap-3">
                <dt style={{ color: "var(--rally-muted)" }}>Credit</dt>
                <dd className="font-mono tabular-nums">
                  {formatCents(previewQuery.data.credit_cents)}
                </dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt style={{ color: "var(--rally-muted)" }}>Charge</dt>
                <dd className="font-mono tabular-nums">
                  {formatCents(previewQuery.data.charge_cents)}
                </dd>
              </div>
              <div className="flex justify-between gap-3 font-semibold">
                <dt>{previewQuery.data.net_cents >= 0 ? "Parent owes" : "Parent credited"}</dt>
                <dd className="font-mono tabular-nums">
                  {formatCents(Math.abs(previewQuery.data.net_cents))}
                </dd>
              </div>
            </dl>
          )}

          {/* The preview route defaults move_date to "now", so the numbers are
              only valid for a move happening today — say so rather than implying
              they hold for any future move date. */}
          <p className="text-xs" style={{ color: "var(--rally-muted)" }}>
            Estimate as of today — billing changes are applied by an admin.
          </p>
        </div>
      )}
    </div>
  );
}
