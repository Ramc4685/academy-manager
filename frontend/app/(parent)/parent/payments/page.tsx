"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import {
  createParentPauseRequest,
  listParentEnrollments,
  listParentCredits,
  listParentPayments,
  listParentPauseRequests,
  openBillingPortal,
  startAutopay,
} from "@/lib/api/parent";

const BILLING_PORTAL_PREREQUISITE =
  "Billing portal is not set up yet. Start autopay for an enrollment first to get portal access.";
const AUTOPAY_START_FAILED =
  "Autopay could not start. Please try again. If it still does not open, contact the academy.";

function money(cents: number, currency = "USD"): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(cents / 100);
}

function autopayStatusText(enrollment: { payment_mode: string | null; subscription_status: string | null }) {
  const status = enrollment.subscription_status ?? "";
  if (enrollment.payment_mode !== "monthly") return "Manual payment";
  if (["active", "trialing"].includes(status)) return `Autopay ${status}`;
  if (status === "past_due") return "Autopay active, payment issue";
  if (status === "incomplete") return "Payment setup pending";
  if (status === "incomplete_expired") return "Payment setup expired";
  if (status === "unpaid") return "Payment blocked";
  if (status === "canceled") return "Autopay off";
  return "Autopay pending";
}

function autopayHelperText(enrollment: { payment_mode: string | null; subscription_status: string | null }) {
  const status = enrollment.subscription_status ?? "";
  if (enrollment.payment_mode !== "monthly") return null;
  if (status === "incomplete") {
    return "If Checkout was completed, the account update may still be pending. You can retry without creating duplicate billing.";
  }
  if (status === "past_due" || status === "unpaid") {
    return "Open the billing portal to update the payment method.";
  }
  if (status === "incomplete_expired") {
    return "Start autopay again to create a fresh Stripe checkout.";
  }
  return null;
}

export default function ParentPaymentsPage() {
  const [pauseEnrollmentId, setPauseEnrollmentId] = useState("");
  const [pauseKind, setPauseKind] = useState<"fixed" | "indefinite">("fixed");
  const [resumeOn, setResumeOn] = useState(currentDate());
  const [pauseReason, setPauseReason] = useState("");
  const [portalError, setPortalError] = useState<string | null>(null);
  const [autopayError, setAutopayError] = useState<string | null>(null);
  const [startingAutopayEnrollmentId, setStartingAutopayEnrollmentId] = useState<string | null>(
    null,
  );
  const paymentsQuery = useQuery({
    queryKey: ["parent", "payments"],
    queryFn: listParentPayments,
  });
  const enrollmentsQuery = useQuery({
    queryKey: ["parent", "enrollments"],
    queryFn: listParentEnrollments,
  });
  const pauseRequestsQuery = useQuery({
    queryKey: ["parent", "pause-requests"],
    queryFn: listParentPauseRequests,
  });
  const creditsQuery = useQuery({
    queryKey: ["parent", "credits"],
    queryFn: listParentCredits,
  });
  const portalMutation = useMutation({
    mutationFn: () => openBillingPortal({ return_url: window.location.href }),
    onMutate: () => {
      setPortalError(null);
    },
    onSuccess: (res) => {
      if (!res.redirect_url) {
        setPortalError("Billing portal could not open because Stripe did not return a portal URL.");
        return;
      }
      window.location.href = res.redirect_url;
    },
    onError: (error) => {
      const detail = error instanceof Error ? error.message : "Request failed";
      if (detail.includes("Stripe customer") || detail.includes("autopay setup")) {
        setPortalError(BILLING_PORTAL_PREREQUISITE);
        return;
      }
      if (detail === "Request failed") {
        setPortalError(BILLING_PORTAL_PREREQUISITE);
        return;
      }
      setPortalError(`Billing portal could not open. ${detail}`);
    },
  });
  const autopayMutation = useMutation({
    mutationFn: (enrollmentId: string) =>
      startAutopay({
        enrollment_id: enrollmentId,
        success_url: `${window.location.origin}/parent/payments?autopay=success`,
        cancel_url: `${window.location.origin}/parent/payments?autopay=cancelled`,
      }),
    onMutate: (enrollmentId) => {
      setPortalError(null);
      setAutopayError(null);
      setStartingAutopayEnrollmentId(enrollmentId);
    },
    onSuccess: (res) => {
      if (!res.redirect_url) {
        setAutopayError("Autopay could not start because Stripe did not return a checkout link.");
        return;
      }
      window.location.href = res.redirect_url;
    },
    onError: (error) => {
      const detail = error instanceof Error ? error.message : "Request failed";
      setAutopayError(
        detail === "Request failed" ? AUTOPAY_START_FAILED : `Autopay could not start. ${detail}`,
      );
    },
    onSettled: () => {
      setStartingAutopayEnrollmentId(null);
    },
  });
  const pauseMutation = useMutation({
    mutationFn: () =>
      createParentPauseRequest({
        enrollment_id: pauseEnrollmentId,
        period: pauseKind === "fixed" ? resumeOn.slice(0, 7) : undefined,
        pause_kind: pauseKind,
        resume_on: pauseKind === "fixed" ? resumeOn : null,
        reason: pauseReason || undefined,
      }),
    onSuccess: () => {
      setPauseEnrollmentId("");
      setPauseKind("fixed");
      setResumeOn(currentDate());
      setPauseReason("");
      void pauseRequestsQuery.refetch();
    },
  });

  const payments = paymentsQuery.data?.payments ?? [];
  const enrollments = enrollmentsQuery.data?.enrollments ?? [];
  const pauseRequests = pauseRequestsQuery.data?.requests ?? [];
  const creditBalance = creditsQuery.data?.balance_cents ?? 0;
  const credits = creditsQuery.data?.credits ?? [];
  const loading =
    paymentsQuery.isLoading ||
    enrollmentsQuery.isLoading ||
    pauseRequestsQuery.isLoading ||
    creditsQuery.isLoading;
  const error =
    paymentsQuery.isError ||
    enrollmentsQuery.isError ||
    pauseRequestsQuery.isError ||
    creditsQuery.isError;

  if (loading) return <p>Loading...</p>;
  if (error) return <p className="text-red-600">Could not load payments.</p>;

  return (
    <section data-testid="parent-payments" className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Payments</h1>
          <p className="mt-1 text-sm text-neutral-500">
            Payment history and monthly autopay settings.
          </p>
        </div>
        <button
          type="button"
          onClick={() => portalMutation.mutate()}
          disabled={portalMutation.isPending}
          className="min-h-touch rounded-md bg-blue-600 px-4 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
        >
          {portalMutation.isPending ? "Opening..." : "Billing portal"}
        </button>
      </div>
      {enrollments.some(
        (enrollment) =>
          enrollment.payment_mode === "monthly" &&
          enrollment.subscription_status === "incomplete",
      ) && (
        <p
          role="status"
          data-testid="payment-update-pending"
          className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100"
        >
          Payment received in Stripe may take a moment to update this page. If it does not update,
          retry autopay or contact the academy.
        </p>
      )}
      {portalError && (
        <p
          role="alert"
          data-testid="billing-portal-error"
          className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-100"
        >
          {portalError}
        </p>
      )}

      {creditBalance > 0 && (
        <section className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 dark:border-emerald-900 dark:bg-emerald-950/30">
          <h2 className="text-lg font-semibold text-emerald-950 dark:text-emerald-100">
            Available credit
          </h2>
          <p className="mt-1 text-sm text-emerald-800 dark:text-emerald-200">
            {money(creditBalance)} applies automatically to your next invoice.
          </p>
          {credits.length > 0 && (
            <ul className="mt-3 space-y-1 text-xs text-emerald-800 dark:text-emerald-200">
              {credits.map((credit) => (
                <li key={credit.credit_id}>
                  {credit.reason}: {money(credit.remaining_amount_cents, credit.currency.toUpperCase())}
                  {credit.expires_at
                    ? ` · expires ${new Date(credit.expires_at).toLocaleDateString()}`
                    : ""}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      <section>
        <h2 className="mb-3 text-lg font-semibold">Autopay</h2>
        {autopayError && (
          <p
            role="alert"
            data-testid="autopay-error"
            className="mb-3 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-100"
          >
            {autopayError}
          </p>
        )}
        {enrollments.length === 0 ? (
          <p className="text-sm text-neutral-500">No active enrollments.</p>
        ) : (
          <div className="space-y-3">
            {enrollments.map((enrollment) => {
              // "incomplete" means Checkout was started but never finished
              // (abandoned, or the webhook hasn't confirmed yet) — the parent
              // must be able to retry, so it does NOT count as enabled.
              const enabled =
                enrollment.payment_mode === "monthly" &&
                ["active", "trialing", "past_due"].includes(
                  enrollment.subscription_status ?? ""
                );
              const helperText = autopayHelperText(enrollment);
              const starting = startingAutopayEnrollmentId === enrollment.enrollment_id;
              return (
                <div
                  key={enrollment.enrollment_id}
                  className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900"
                >
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <p className="font-medium">{enrollment.student_name}</p>
                      <p className="text-sm text-neutral-500">{enrollment.session_title}</p>
                      <p className="mt-1 text-xs text-neutral-500">
                        {autopayStatusText(enrollment)}
                      </p>
                      {helperText && (
                        <p className="mt-1 max-w-xl text-xs text-amber-700 dark:text-amber-300">
                          {helperText}
                        </p>
                      )}
                    </div>
                    <button
                      type="button"
                      disabled={enabled || autopayMutation.isPending}
                      onClick={() => autopayMutation.mutate(enrollment.enrollment_id)}
                      className="min-h-touch rounded-md border border-blue-300 px-3 text-sm font-medium text-blue-700 hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-blue-700 dark:text-blue-300"
                    >
                      {enabled
                        ? "Autopay on"
                        : starting
                          ? "Starting..."
                          : enrollment.subscription_status === "incomplete"
                            ? "Retry autopay"
                            : "Start autopay"}
                    </button>
                    <button
                      type="button"
                      onClick={() => setPauseEnrollmentId(enrollment.enrollment_id)}
                      className="min-h-touch rounded-md border border-neutral-300 px-3 text-sm font-medium text-neutral-700 hover:bg-neutral-50 dark:border-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-800"
                    >
                      Request pause
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {pauseEnrollmentId && (
        <section className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900">
          <h2 className="text-lg font-semibold">Pause request</h2>
          <div className="mt-4 space-y-3">
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">Pause type</legend>
              <div className="grid gap-2 sm:grid-cols-2">
                <label className="flex min-h-touch items-center gap-2 rounded-md border border-neutral-300 px-3 text-sm dark:border-neutral-700">
                  <input
                    type="radio"
                    name="pause-kind"
                    value="fixed"
                    checked={pauseKind === "fixed"}
                    onChange={() => setPauseKind("fixed")}
                  />
                  Fixed date
                </label>
                <label className="flex min-h-touch items-center gap-2 rounded-md border border-neutral-300 px-3 text-sm dark:border-neutral-700">
                  <input
                    type="radio"
                    name="pause-kind"
                    value="indefinite"
                    checked={pauseKind === "indefinite"}
                    onChange={() => setPauseKind("indefinite")}
                  />
                  Indefinite
                </label>
              </div>
            </fieldset>
            {pauseKind === "fixed" && (
              <label className="block text-sm font-medium">
                Requested resume date
                <input
                  type="date"
                  value={resumeOn}
                  onChange={(event) => setResumeOn(event.target.value)}
                  className="mt-1 h-11 w-full rounded-md border border-neutral-300 bg-white px-3 text-sm dark:border-neutral-700 dark:bg-neutral-950"
                />
              </label>
            )}
            <p className="text-xs text-neutral-500">
              {pauseKind === "fixed"
                ? "We will attempt to resume this enrollment on the requested date if a seat is available."
                : "This will stay paused until you or an admin choose a resume date or cancel the enrollment."}
            </p>
            <label className="block text-sm font-medium">
              Reason
              <textarea
                value={pauseReason}
                onChange={(event) => setPauseReason(event.target.value)}
                rows={3}
                className="mt-1 w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm dark:border-neutral-700 dark:bg-neutral-950"
              />
            </label>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => pauseMutation.mutate()}
                disabled={pauseMutation.isPending || (pauseKind === "fixed" && !resumeOn)}
                className="min-h-touch rounded-md bg-blue-600 px-4 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
              >
                {pauseMutation.isPending ? "Sending..." : "Submit"}
              </button>
              <button
                type="button"
                onClick={() => {
                  setPauseEnrollmentId("");
                  setPauseKind("fixed");
                  setResumeOn(currentDate());
                  setPauseReason("");
                }}
                className="min-h-touch rounded-md border border-neutral-300 px-4 text-sm dark:border-neutral-700"
              >
                Cancel
              </button>
            </div>
          </div>
        </section>
      )}

      <section>
        <h2 className="mb-3 text-lg font-semibold">Pause requests</h2>
        {pauseRequests.length === 0 ? (
          <p className="text-sm text-neutral-500">No pause requests.</p>
        ) : (
          <ul className="space-y-2">
            {pauseRequests.map((request) => (
              <li
                key={request.pause_request_id}
                className="rounded-lg border border-neutral-200 bg-white p-3 text-sm dark:border-neutral-800 dark:bg-neutral-900"
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="font-medium">
                    {request.pause_kind === "indefinite"
                      ? "Indefinite pause"
                      : `Resume ${formatDate(request.resume_on)}`}
                  </span>
                  <StatusBadge status={request.status} />
                </div>
                {request.reason && <p className="mt-1 text-neutral-500">{request.reason}</p>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">History</h2>
        {payments.length === 0 ? (
          <p className="text-neutral-500">No payments yet.</p>
        ) : (
          <ul className="space-y-3" data-testid="payments-list">
            {payments.map((payment) => (
              <li
                key={payment.payment_id}
                data-testid={`payment-${payment.payment_id}`}
                className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900"
              >
                <div className="flex items-center justify-between">
                  <p className="font-medium">
                    {money(payment.amount_cents, payment.currency.toUpperCase())}
                  </p>
                  <StatusBadge status={payment.status} />
                </div>
                <p className="mt-1 text-xs text-neutral-500">
                  {new Date(payment.created_at).toLocaleString()}
                </p>
                {payment.refunded_cents > 0 && (
                  <p className="text-xs text-amber-700 dark:text-amber-300">
                    Refunded {money(payment.refunded_cents, payment.currency.toUpperCase())}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </section>
  );
}

function currentDate(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(
    now.getDate(),
  ).padStart(2, "0")}`;
}

function formatDate(value: string | null): string {
  if (!value) return "date pending";
  return new Date(`${value}T00:00:00`).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function StatusBadge({ status }: { status: string }) {
  const palette: Record<string, string> = {
    succeeded: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-100",
    pending: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-100",
    failed: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-100",
    refunded: "bg-neutral-100 text-neutral-800 dark:bg-neutral-800 dark:text-neutral-100",
    partially_refunded: "bg-neutral-100 text-neutral-800 dark:bg-neutral-800 dark:text-neutral-100",
    expired: "bg-neutral-100 text-neutral-800 dark:bg-neutral-800 dark:text-neutral-100",
  };
  const cls = palette[status] ?? palette.expired;
  return <span className={`rounded-full px-2 py-0.5 text-xs ${cls}`}>{status}</span>;
}
