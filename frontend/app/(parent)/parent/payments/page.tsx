"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createParentPauseRequest,
  getParentInvoice,
  getCheckoutStatus,
  listParentEnrollments,
  listParentCredits,
  listParentInvoices,
  listParentPayments,
  listParentPauseRequests,
  openBillingPortal,
  startAutopay,
  startParentBalancePayment,
  startParentInvoicePayment,
} from "@/lib/api/parent";
import { toPaymentErrorMessage, toPortalErrorMessage } from "@/lib/api/payment-error";
import {
  AUTOPAY_OPTIN_LABEL,
  resolveEnrollAutopayChecked,
  showAutopayOptinForBalance,
  showAutopayOptinForInvoice,
} from "@/lib/parent-autopay-optin";

const AUTOPAY_START_FAILED =
  "Something went wrong starting autopay. Please try again or contact the academy.";
const PORTAL_OPEN_FAILED =
  "Billing portal could not open. Please try again or contact the academy.";
const PAYMENT_START_FAILED =
  "Payment could not start. Please try again or contact the academy.";

// Checkout-status polling: stop on terminal statuses ("active" plus the ACH
// micro-deposit verification states and dead Stripe sessions), and hard-cap
// at ~5 minutes so a never-terminal status can't poll forever.
const CHECKOUT_POLL_TERMINAL_STATUSES = new Set([
  "active",
  "past_due",
  "cancelled",
  "verification_required",
  "verification_pending",
  "expired",
]);
const CHECKOUT_POLL_INTERVAL_MS = 3000;
const CHECKOUT_POLL_MAX_ATTEMPTS = 100; // 100 × 3s ≈ 5 minutes

/** "2026-04" -> "Apr 2026"; unknown formats render as-is. */
function formatPeriodLabel(period: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(period);
  if (!match) return period;
  const date = new Date(Number(match[1]), Number(match[2]) - 1, 1);
  return date.toLocaleDateString("en-US", { month: "short", year: "numeric" });
}

function money(cents: number, currency = "USD"): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(cents / 100);
}

function autopayStatusText(enrollment: {
  payment_mode: string | null;
  autopay_enrollment_status?: string | null;
  last_attempt_outcome?: string | null;
}) {
  const status = enrollment.autopay_enrollment_status ?? "";
  if (enrollment.payment_mode !== "monthly") return "Manual payment";
  if (status === "active" && enrollment.last_attempt_outcome === "declined") {
    return "Autopay active, payment issue";
  }
  if (status === "active" && enrollment.last_attempt_outcome === "requires_action") {
    return "Autopay active, action needed";
  }
  if (status === "active") return "Autopay active";
  if (status === "paused") return "Autopay paused";
  if (status === "setup_started") return "Payment setup pending";
  if (status === "offered") return "Autopay available";
  if (status === "disabled") return "Autopay off";
  if (status === "not_offered") return "Autopay not set up";
  return "Autopay pending";
}

function autopayMethodText(enrollment: {
  payment_mode: string | null;
  autopay_enrollment_status?: string | null;
  autopay_payment_method_type?: string | null;
  autopay_payment_method_label?: string | null;
  autopay_payment_method_last4?: string | null;
  autopay_setup_status?: string | null;
}): string | null {
  const autopayStatus = enrollment.autopay_enrollment_status ?? "";
  if (enrollment.payment_mode !== "monthly") return null;
  if (!["active", "paused", "setup_started"].includes(autopayStatus)) return null;
  if (enrollment.autopay_setup_status && enrollment.autopay_setup_status !== "active") {
    return "Payment method setup is still pending.";
  }
  if (enrollment.autopay_payment_method_type === "us_bank_account") {
    return methodDetail("Bank account autopay", enrollment);
  }
  if (enrollment.autopay_payment_method_type === "card") {
    return methodDetail("Card autopay", enrollment);
  }
  return null;
}

function methodDetail(
  prefix: string,
  enrollment: {
    autopay_payment_method_label?: string | null;
    autopay_payment_method_last4?: string | null;
  },
): string {
  const label = enrollment.autopay_payment_method_label?.trim();
  const last4 = enrollment.autopay_payment_method_last4?.trim();
  if (label && last4) return `${prefix} - ${label} ending in ${last4}`;
  if (label) return `${prefix} - ${label}`;
  if (last4) return `${prefix} ending in ${last4}`;
  return prefix;
}

function autopayHelperText(enrollment: {
  payment_mode: string | null;
  autopay_enrollment_status?: string | null;
  last_attempt_outcome?: string | null;
  last_failure_code?: string | null;
}) {
  const status = enrollment.autopay_enrollment_status ?? "";
  if (enrollment.payment_mode !== "monthly") return null;
  if (status === "setup_started") {
    return "If Checkout was completed, the account update may still be pending. You can retry without creating duplicate billing.";
  }
  if (status === "active" && enrollment.last_attempt_outcome === "declined") {
    return enrollment.last_failure_code
      ? `The latest autopay attempt failed: ${enrollment.last_failure_code}.`
      : "The latest autopay attempt failed.";
  }
  if (status === "active" && enrollment.last_attempt_outcome === "requires_action") {
    return "Open the billing portal to update the payment method.";
  }
  if (status === "disabled") {
    return "Start autopay again to create a fresh checkout.";
  }
  return null;
}

function initials(name: string): string {
  return name
    .split(" ")
    .map((w) => w[0] ?? "")
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

export default function ParentPaymentsPage() {
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const autopayReturn = searchParams.get("autopay");
  const checkoutSessionId = searchParams.get("checkout_session_id");
  const returnedFromAutopayCheckout = autopayReturn === "success";
  const [pauseEnrollmentId, setPauseEnrollmentId] = useState("");
  const [pauseKind, setPauseKind] = useState<"fixed" | "indefinite">("fixed");
  // Blank by default: resuming "today" is never a valid pause, so force an
  // explicit future choice (the submit button stays disabled until set).
  const [resumeOn, setResumeOn] = useState("");
  const [reviewOn, setReviewOn] = useState(dateFromOffset(14));
  const [pauseReason, setPauseReason] = useState("");
  const [portalError, setPortalError] = useState<string | null>(null);
  const [autopayError, setAutopayError] = useState<string | null>(null);
  const [invoicePaymentError, setInvoicePaymentError] = useState<string | null>(null);
  const [balancePaymentError, setBalancePaymentError] = useState<string | null>(null);
  const [selectedInvoiceId, setSelectedInvoiceId] = useState<string | null>(null);
  const [payingInvoiceId, setPayingInvoiceId] = useState<string | null>(null);
  // Autopay opt-in checkboxes default to checked; only explicit unchecks are stored.
  const [invoiceAutopayOptins, setInvoiceAutopayOptins] = useState<Record<string, boolean>>({});
  const [balanceAutopayOptin, setBalanceAutopayOptin] = useState(true);
  const [startingAutopayEnrollmentId, setStartingAutopayEnrollmentId] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [showPauseRequests, setShowPauseRequests] = useState(false);

  const paymentsQuery = useQuery({
    queryKey: ["parent", "payments"],
    queryFn: listParentPayments,
    staleTime: returnedFromAutopayCheckout ? 0 : undefined,
    refetchOnMount: returnedFromAutopayCheckout ? "always" : undefined,
  });
  const enrollmentsQuery = useQuery({
    queryKey: ["parent", "enrollments"],
    queryFn: listParentEnrollments,
    staleTime: returnedFromAutopayCheckout ? 0 : undefined,
    refetchOnMount: returnedFromAutopayCheckout ? "always" : undefined,
  });
  const invoicesQuery = useQuery({
    queryKey: ["parent", "invoices"],
    queryFn: listParentInvoices,
    staleTime: returnedFromAutopayCheckout ? 0 : undefined,
    refetchOnMount: returnedFromAutopayCheckout ? "always" : undefined,
  });
  const invoiceDetailQuery = useQuery({
    queryKey: ["parent", "invoice-detail", selectedInvoiceId],
    queryFn: () => getParentInvoice(selectedInvoiceId ?? ""),
    enabled: Boolean(selectedInvoiceId),
  });
  const checkoutStatusQuery = useQuery({
    queryKey: ["parent", "checkout-status", checkoutSessionId],
    queryFn: () => getCheckoutStatus(checkoutSessionId ?? ""),
    enabled: returnedFromAutopayCheckout && Boolean(checkoutSessionId),
    staleTime: 0,
    refetchOnMount: "always",
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status && CHECKOUT_POLL_TERMINAL_STATUSES.has(status)) return false;
      if (
        query.state.dataUpdateCount + query.state.errorUpdateCount >=
        CHECKOUT_POLL_MAX_ATTEMPTS
      ) {
        return false;
      }
      return CHECKOUT_POLL_INTERVAL_MS;
    },
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
    onMutate: () => { setPortalError(null); },
    onSuccess: (res) => {
      if (!res.redirect_url) {
        setPortalError("Billing portal could not open right now. Please try again, or contact the academy.");
        return;
      }
      window.location.href = res.redirect_url;
    },
    onError: (error) => {
      setPortalError(toPortalErrorMessage(error, PORTAL_OPEN_FAILED));
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
        setAutopayError("Autopay could not start right now. Please try again, or contact the academy.");
        return;
      }
      window.location.href = res.redirect_url;
    },
    onError: (error) => {
      setAutopayError(toPaymentErrorMessage(error, AUTOPAY_START_FAILED));
    },
    onSettled: () => { setStartingAutopayEnrollmentId(null); },
  });

  const invoicePaymentMutation = useMutation({
    mutationFn: ({ invoiceId, enrollAutopay }: { invoiceId: string; enrollAutopay: boolean }) =>
      startParentInvoicePayment(invoiceId, {
        success_url: `${window.location.origin}/parent/payments?invoice=paid`,
        cancel_url: `${window.location.origin}/parent/payments?invoice=cancelled`,
        enroll_autopay: enrollAutopay,
      }),
    onMutate: ({ invoiceId }) => {
      setPortalError(null);
      setInvoicePaymentError(null);
      setPayingInvoiceId(invoiceId);
    },
    onSuccess: (res) => {
      if (!res.redirect_url) {
        setInvoicePaymentError("Payment could not start right now. Please try again, or contact the academy.");
        return;
      }
      window.location.href = res.redirect_url;
    },
    onError: (error) => {
      setInvoicePaymentError(toPaymentErrorMessage(error, PAYMENT_START_FAILED));
    },
    onSettled: () => { setPayingInvoiceId(null); },
  });

  const balancePaymentMutation = useMutation({
    mutationFn: ({ enrollAutopay }: { enrollAutopay: boolean }) =>
      startParentBalancePayment({
        success_url: `${window.location.origin}/parent/payments?balance=paid`,
        cancel_url: `${window.location.origin}/parent/payments?balance=cancelled`,
        enroll_autopay: enrollAutopay,
      }),
    onMutate: () => { setBalancePaymentError(null); },
    onSuccess: (res) => {
      if (!res.redirect_url) {
        setBalancePaymentError("Payment could not start right now. Please try again, or contact the academy.");
        return;
      }
      window.location.href = res.redirect_url;
    },
    onError: (error) => {
      setBalancePaymentError(toPaymentErrorMessage(error, PAYMENT_START_FAILED));
    },
  });

  const pauseMutation = useMutation({
    mutationFn: () =>
      createParentPauseRequest({
        enrollment_id: pauseEnrollmentId,
        period: pauseKind === "fixed" ? resumeOn.slice(0, 7) : undefined,
        pause_kind: pauseKind,
        resume_on: pauseKind === "fixed" ? resumeOn : null,
        review_on: pauseKind === "indefinite" ? reviewOn : null,
        reason: pauseReason || undefined,
      }),
    onSuccess: () => {
      setPauseEnrollmentId("");
      setPauseKind("fixed");
      setResumeOn("");
      setReviewOn(dateFromOffset(14));
      setPauseReason("");
      void pauseRequestsQuery.refetch();
    },
  });

  useEffect(() => {
    if (!returnedFromAutopayCheckout) return;
    void queryClient.invalidateQueries({ queryKey: ["parent", "payments"] });
    void queryClient.invalidateQueries({ queryKey: ["parent", "enrollments"] });
    void queryClient.invalidateQueries({ queryKey: ["parent", "invoices"] });
  }, [queryClient, returnedFromAutopayCheckout]);

  useEffect(() => {
    if (!checkoutStatusQuery.data?.status) return;
    void queryClient.invalidateQueries({ queryKey: ["parent", "payments"] });
    void queryClient.invalidateQueries({ queryKey: ["parent", "enrollments"] });
    void queryClient.invalidateQueries({ queryKey: ["parent", "invoices"] });
  }, [checkoutStatusQuery.data?.status, queryClient]);

  const payments = paymentsQuery.data?.payments ?? [];
  const enrollments = enrollmentsQuery.data?.enrollments ?? [];
  const invoices = invoicesQuery.data?.invoices ?? [];
  const pauseRequests = pauseRequestsQuery.data?.requests ?? [];
  const creditBalance = creditsQuery.data?.balance_cents ?? 0;
  const credits = creditsQuery.data?.credits ?? [];
  const currentBalance = invoices
    .filter((inv) => inv.status !== "void")
    .reduce((total, inv) => total + inv.balance_due_cents, 0);

  const loading =
    paymentsQuery.isLoading ||
    enrollmentsQuery.isLoading ||
    invoicesQuery.isLoading ||
    pauseRequestsQuery.isLoading ||
    creditsQuery.isLoading;
  const error =
    paymentsQuery.isError ||
    enrollmentsQuery.isError ||
    invoicesQuery.isError ||
    pauseRequestsQuery.isError ||
    creditsQuery.isError;

  if (loading) return <p className="p-4 text-sm text-neutral-500">Loading...</p>;
  if (error) return <p className="p-4 text-sm text-red-600">Could not load payments.</p>;

  return (
    <section data-testid="parent-payments" className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold" style={{ color: "#0a0f1c" }}>Payments</h1>
        <button
          type="button"
          onClick={() => portalMutation.mutate()}
          disabled={portalMutation.isPending}
          className="flex items-center gap-1.5 text-sm font-medium disabled:opacity-60"
          style={{ color: "#185fa5" }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
            <polyline points="15 3 21 3 21 9" />
            <line x1="10" y1="14" x2="21" y2="3" />
          </svg>
          {portalMutation.isPending ? "Opening…" : "Billing portal"}
        </button>
      </div>

      {/* Status banners */}
      {returnedFromAutopayCheckout && checkoutStatusQuery.isFetching && (
        <p role="status" data-testid="autopay-checkout-confirming" className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-900">
          Confirming autopay…
        </p>
      )}
      {enrollments.some((e) => e.payment_mode === "monthly" && e.autopay_enrollment_status === "setup_started") && (
        <p role="status" data-testid="payment-update-pending" className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Your payment may take a moment to update this page. If it does not update, retry autopay or contact the academy.
        </p>
      )}
      {portalError && (
        <p role="alert" data-testid="billing-portal-error" className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          {portalError}
        </p>
      )}
      {invoicePaymentError && (
        <p role="alert" data-testid="invoice-payment-error" className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          {invoicePaymentError}
        </p>
      )}
      {balancePaymentError && (
        <p role="alert" data-testid="balance-payment-error" className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          {balancePaymentError}
        </p>
      )}

      {/* Credit card */}
      {creditBalance > 0 && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
          <p className="text-sm font-medium text-emerald-900">
            {money(creditBalance)} credit applies automatically to your next invoice.
          </p>
          {credits.length > 0 && (
            <ul className="mt-2 space-y-0.5 text-xs text-emerald-800">
              {credits.map((credit) => (
                <li key={credit.credit_id}>
                  {credit.reason}: {money(credit.remaining_amount_cents, credit.currency.toUpperCase())}
                  {credit.expires_at ? ` · expires ${new Date(credit.expires_at).toLocaleDateString()}` : ""}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Balance hero */}
      {currentBalance > 0 && (
        <div className="rounded-2xl p-4" style={{ background: "#0a0f1c" }}>
          <p className="text-xs" style={{ color: "#94a3b8" }}>Balance due</p>
          <p className="mt-1 text-3xl font-semibold text-white">{money(currentBalance)}</p>
          <p className="mt-1.5 inline-block rounded-full px-2.5 py-0.5 text-xs font-medium" style={{ background: "rgba(251,191,36,0.12)", color: "#fbbf24" }}>
            {invoices.filter((i) => i.balance_due_cents > 0 && i.status !== "void").length} open invoice
            {invoices.filter((i) => i.balance_due_cents > 0 && i.status !== "void").length === 1 ? "" : "s"}
            {" · "}
            {enrollments.some((e) => e.payment_mode === "monthly" && e.autopay_enrollment_status === "active")
              ? "autopay on"
              : "autopay off"}
          </p>
          <button
            type="button"
            onClick={() =>
              balancePaymentMutation.mutate({
                enrollAutopay:
                  showAutopayOptinForBalance(invoices, enrollments) && balanceAutopayOptin,
              })
            }
            disabled={balancePaymentMutation.isPending}
            className="mt-4 w-full rounded-xl py-3 text-sm font-semibold disabled:opacity-60 active:scale-95 transition-transform"
            style={{ background: "linear-gradient(135deg,#facc15,#f59e0b)", color: "#0a0f1c" }}
          >
            {balancePaymentMutation.isPending ? "Starting…" : `Pay balance · ${money(currentBalance)}`}
          </button>
          {showAutopayOptinForBalance(invoices, enrollments) && (
            <label
              data-testid="balance-autopay-optin"
              className="mt-2.5 flex items-center gap-2 text-xs"
              style={{ color: "#94a3b8" }}
            >
              <input
                type="checkbox"
                checked={balanceAutopayOptin}
                onChange={(e) => setBalanceAutopayOptin(e.target.checked)}
                className="h-4 w-4 shrink-0 accent-amber-400"
              />
              {AUTOPAY_OPTIN_LABEL}
            </label>
          )}
        </div>
      )}

      {/* Invoices */}
      <div>
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide" style={{ color: "#888780" }}>Invoices</p>
        {invoices.length === 0 ? (
          <p className="text-sm text-neutral-500">No invoices yet.</p>
        ) : (
          <div className="space-y-2">
            {invoices.map((invoice) => {
              const paid = Math.max(invoice.total_cents - invoice.balance_due_cents, 0);
              const payable =
                invoice.balance_due_cents > 0 &&
                (invoice.status === "open" || invoice.status === "partially_paid");
              const isPaid = invoice.status === "paid" || invoice.status === "void";
              return (
                <div
                  key={invoice.invoice_id}
                  className="rounded-2xl border p-3"
                  style={{ background: "#fff", borderColor: "#e6e3da", opacity: isPaid ? 0.75 : 1 }}
                >
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium" style={{ color: "#0a0f1c" }}>{formatPeriodLabel(invoice.period)}</p>
                      <StatusPill status={invoice.status} />
                    </div>
                    <p className="text-base font-semibold tabular-nums" style={{ color: "#0a0f1c" }}>
                      {money(
                        invoice.balance_due_cents > 0 ? invoice.balance_due_cents : paid,
                        invoice.currency.toUpperCase(),
                      )}
                    </p>
                  </div>
                  {payable && (
                    <>
                      <div className="mt-2.5 flex gap-2">
                        <button
                          type="button"
                          disabled={invoicePaymentMutation.isPending}
                          onClick={() =>
                            invoicePaymentMutation.mutate({
                              invoiceId: invoice.invoice_id,
                              enrollAutopay:
                                showAutopayOptinForInvoice(invoice, enrollments) &&
                                resolveEnrollAutopayChecked(invoiceAutopayOptins[invoice.invoice_id]),
                            })
                          }
                          className="flex-1 rounded-xl border py-2 text-sm font-medium disabled:opacity-60 active:scale-95 transition-transform"
                          style={{ borderColor: "#facc15", background: "#fffbe9", color: "#854f0b" }}
                        >
                          {payingInvoiceId === invoice.invoice_id
                            ? "Starting…"
                            : `Pay ${money(invoice.balance_due_cents, invoice.currency.toUpperCase())}`}
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            setSelectedInvoiceId(selectedInvoiceId === invoice.invoice_id ? null : invoice.invoice_id)
                          }
                          className="rounded-xl border px-4 py-2 text-sm"
                          style={{ borderColor: "#d3d1c7", background: "#fff", color: "#5f5e5a" }}
                        >
                          {selectedInvoiceId === invoice.invoice_id ? "Close" : "View"}
                        </button>
                      </div>
                      {showAutopayOptinForInvoice(invoice, enrollments) && (
                        <label
                          data-testid={`invoice-autopay-optin-${invoice.invoice_id}`}
                          className="mt-2 flex items-center gap-2 text-xs"
                          style={{ color: "#5f5e5a" }}
                        >
                          <input
                            type="checkbox"
                            checked={resolveEnrollAutopayChecked(invoiceAutopayOptins[invoice.invoice_id])}
                            onChange={(e) =>
                              setInvoiceAutopayOptins((prev) => ({
                                ...prev,
                                [invoice.invoice_id]: e.target.checked,
                              }))
                            }
                            className="h-4 w-4 shrink-0 accent-amber-400"
                          />
                          {AUTOPAY_OPTIN_LABEL}
                        </label>
                      )}
                    </>
                  )}
                  {!payable && (
                    <button
                      type="button"
                      onClick={() =>
                        setSelectedInvoiceId(selectedInvoiceId === invoice.invoice_id ? null : invoice.invoice_id)
                      }
                      className="mt-2 text-xs font-medium"
                      style={{ color: "#888780" }}
                    >
                      {selectedInvoiceId === invoice.invoice_id ? "Hide detail" : "View detail"}
                    </button>
                  )}
                  {selectedInvoiceId === invoice.invoice_id && (
                    <div className="mt-3 border-t pt-3" style={{ borderColor: "#e6e3da" }}>
                      {invoiceDetailQuery.isLoading ? (
                        <p className="text-xs text-neutral-500">Loading…</p>
                      ) : invoiceDetailQuery.isError ? (
                        <p className="text-xs text-red-600">Could not load detail.</p>
                      ) : invoiceDetailQuery.data ? (
                        <ul className="space-y-1.5">
                          {invoiceDetailQuery.data.lines.map((line) => (
                            <li
                              key={`${line.label ?? line.description}-${line.amount_cents}`}
                              className="flex items-center justify-between gap-3 text-xs"
                              style={{ color: "#5f5e5a" }}
                            >
                              <span>{line.label ?? `${line.description} × ${line.quantity}`}</span>
                              <span className="tabular-nums">
                                {money(line.amount_cents, invoiceDetailQuery.data.currency.toUpperCase())}
                              </span>
                            </li>
                          ))}
                        </ul>
                      ) : null}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Autopay */}
      <div>
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide" style={{ color: "#888780" }}>Autopay</p>
        {autopayError && (
          <p role="alert" data-testid="autopay-error" className="mb-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
            {autopayError}
          </p>
        )}
        {enrollments.length === 0 ? (
          <p className="text-sm text-neutral-500">No active enrollments.</p>
        ) : (
          <div className="space-y-2">
            {enrollments.map((enrollment) => {
              const enabled =
                enrollment.payment_mode === "monthly" &&
                enrollment.autopay_enrollment_status === "active";
              const helperText = autopayHelperText(enrollment);
              const methodText = autopayMethodText(enrollment);
              const starting = startingAutopayEnrollmentId === enrollment.enrollment_id;
              return (
                <div
                  key={enrollment.enrollment_id}
                  className="rounded-2xl border p-3"
                  style={{ background: "#fff", borderColor: "#e6e3da" }}
                >
                  <div className="flex items-center gap-3">
                    <div
                      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold"
                      style={{ background: "#e6f1fb", color: "#185fa5" }}
                    >
                      {initials(enrollment.student_name)}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="truncate text-sm font-medium" style={{ color: "#0a0f1c" }}>
                        {enrollment.student_name}
                      </p>
                      <p className="truncate text-xs" style={{ color: "#888780" }}>{enrollment.session_title}</p>
                      <p className="mt-0.5 text-xs" style={{ color: enabled ? "#0f6e56" : "#888780" }}>
                        {autopayStatusText(enrollment)}
                      </p>
                      {methodText && (
                        <p className="mt-0.5 text-xs" style={{ color: "#5f5e5a" }}>{methodText}</p>
                      )}
                    </div>
                  </div>
                  {helperText && (
                    <p className="mt-2 text-xs" style={{ color: "#854f0b" }}>{helperText}</p>
                  )}
                  <div className="mt-3 flex gap-2">
                    <button
                      type="button"
                      disabled={enabled || autopayMutation.isPending}
                      onClick={() => autopayMutation.mutate(enrollment.enrollment_id)}
                      className="flex-1 rounded-xl py-2.5 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50 active:scale-95 transition-transform"
                      style={{
                        background: enabled ? "#e6e3da" : "#0a0f1c",
                        color: enabled ? "#888780" : "#fff",
                      }}
                    >
                      {enabled
                        ? "Autopay on"
                        : starting
                          ? "Starting…"
                          : enrollment.autopay_enrollment_status === "setup_started"
                            ? "Retry autopay"
                            : "Set up autopay"}
                    </button>
                    <button
                      type="button"
                      onClick={() => setPauseEnrollmentId(enrollment.enrollment_id)}
                      className="rounded-xl border px-4 py-2.5 text-sm"
                      style={{ borderColor: "#d3d1c7", background: "#fff", color: "#5f5e5a" }}
                    >
                      Pause enrollment
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Pause form */}
      {pauseEnrollmentId && (
        <div className="rounded-2xl border p-4" style={{ background: "#fff", borderColor: "#e6e3da" }}>
          <p className="mb-3 text-sm font-semibold" style={{ color: "#0a0f1c" }}>Pause enrollment</p>
          <p className="mb-3 text-xs" style={{ color: "#5f5e5a" }}>
            This pauses your child&apos;s class enrollment (and its billing) — it does not change your autopay payment method.
          </p>
          <div className="space-y-3">
            <fieldset className="space-y-2">
              <legend className="text-xs font-medium" style={{ color: "#5f5e5a" }}>Pause type</legend>
              <div className="grid grid-cols-2 gap-2">
                <label
                  className="flex min-h-touch items-center gap-2 rounded-xl border px-3 text-sm"
                  style={{ borderColor: pauseKind === "fixed" ? "#facc15" : "#d3d1c7" }}
                >
                  <input type="radio" name="pause-kind" value="fixed" checked={pauseKind === "fixed"} onChange={() => setPauseKind("fixed")} />
                  Fixed date
                </label>
                <label
                  className="flex min-h-touch items-center gap-2 rounded-xl border px-3 text-sm"
                  style={{ borderColor: pauseKind === "indefinite" ? "#facc15" : "#d3d1c7" }}
                >
                  <input type="radio" name="pause-kind" value="indefinite" checked={pauseKind === "indefinite"} onChange={() => setPauseKind("indefinite")} />
                  Indefinite
                </label>
              </div>
            </fieldset>
            {pauseKind === "fixed" ? (
              <label className="block text-xs font-medium" style={{ color: "#5f5e5a" }}>
                Resume date
                <input
                  type="date"
                  value={resumeOn}
                  min={dateFromOffset(1)}
                  onChange={(e) => setResumeOn(e.target.value)}
                  className="mt-1 h-11 w-full rounded-xl border px-3 text-sm"
                  style={{ borderColor: "#d3d1c7" }}
                />
              </label>
            ) : (
              <label className="block text-xs font-medium" style={{ color: "#5f5e5a" }}>
                Review date
                <input
                  type="date"
                  value={reviewOn}
                  onChange={(e) => setReviewOn(e.target.value)}
                  className="mt-1 h-11 w-full rounded-xl border px-3 text-sm"
                  style={{ borderColor: "#d3d1c7" }}
                />
              </label>
            )}
            <p className="text-xs" style={{ color: "#888780" }}>
              {pauseKind === "fixed"
                ? "We will attempt to resume this enrollment on the requested date if a seat is available."
                : "The academy will review this pause on the selected date so billing cannot remain deferred without follow-up."}
            </p>
            <label className="block text-xs font-medium" style={{ color: "#5f5e5a" }}>
              Reason
              <textarea
                value={pauseReason}
                onChange={(e) => setPauseReason(e.target.value)}
                rows={3}
                className="mt-1 w-full rounded-xl border px-3 py-2 text-sm"
                style={{ borderColor: "#d3d1c7" }}
              />
            </label>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => pauseMutation.mutate()}
                disabled={
                  pauseMutation.isPending ||
                  (pauseKind === "fixed" ? !resumeOn || resumeOn <= currentDate() : !reviewOn)
                }
                className="min-h-touch flex-1 rounded-xl text-sm font-semibold text-white disabled:opacity-60"
                style={{ background: "#0a0f1c" }}
              >
                {pauseMutation.isPending ? "Sending…" : "Submit"}
              </button>
              <button
                type="button"
                onClick={() => {
                  setPauseEnrollmentId("");
                  setPauseKind("fixed");
                  setResumeOn("");
                  setReviewOn(dateFromOffset(14));
                  setPauseReason("");
                }}
                className="min-h-touch rounded-xl border px-4 text-sm"
                style={{ borderColor: "#d3d1c7" }}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Pause requests (collapsible) */}
      <CollapsibleSection
        title="Pause requests"
        badge={pauseRequests.length > 0 ? String(pauseRequests.length) : undefined}
        open={showPauseRequests}
        onToggle={() => setShowPauseRequests((v) => !v)}
      >
        {pauseRequests.length === 0 ? (
          <p className="text-sm text-neutral-500">No pause requests.</p>
        ) : (
          <ul className="space-y-2">
            {pauseRequests.map((request) => (
              <li
                key={request.pause_request_id}
                className="rounded-xl border p-3 text-sm"
                style={{ borderColor: "#e6e3da" }}
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="font-medium" style={{ color: "#0a0f1c" }}>
                    {request.pause_kind === "indefinite"
                      ? `Review ${formatDate(request.review_on)}`
                      : `Resume ${formatDate(request.resume_on)}`}
                  </span>
                  <StatusPill status={request.status} />
                </div>
                {request.reason && (
                  <p className="mt-1 text-xs" style={{ color: "#888780" }}>{request.reason}</p>
                )}
              </li>
            ))}
          </ul>
        )}
      </CollapsibleSection>

      {/* Payment history (collapsible) */}
      <CollapsibleSection
        title="Payment history"
        open={showHistory}
        onToggle={() => setShowHistory((v) => !v)}
      >
        {payments.length === 0 ? (
          <p className="text-sm text-neutral-500">No payments yet.</p>
        ) : (
          <ul className="space-y-2" data-testid="payments-list">
            {payments.map((payment) => (
              <li
                key={payment.payment_id}
                data-testid={`payment-${payment.payment_id}`}
                className="rounded-xl border p-3"
                style={{ background: "#fff", borderColor: "#e6e3da" }}
              >
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium" style={{ color: "#0a0f1c" }}>
                    {money(payment.amount_cents, payment.currency.toUpperCase())}
                  </p>
                  <StatusPill status={payment.status} />
                </div>
                <p className="mt-1 text-xs" style={{ color: "#888780" }}>
                  {payment.invoice_period
                    ? `Tuition · ${formatPeriodLabel(payment.invoice_period)} · ${new Date(payment.created_at).toLocaleDateString()}`
                    : new Date(payment.created_at).toLocaleString()}
                </p>
                {payment.refunded_cents > 0 && (
                  <p className="text-xs" style={{ color: "#854f0b" }}>
                    Refunded {money(payment.refunded_cents, payment.currency.toUpperCase())}
                  </p>
                )}
                {(payment.stripe_invoice_id || payment.stripe_payment_intent_id) && (
                  <p className="mt-1 truncate font-mono text-xs" style={{ color: "#b4b2a9" }}>
                    {payment.stripe_invoice_id
                      ? `Invoice ${payment.stripe_invoice_id}`
                      : `PaymentIntent ${payment.stripe_payment_intent_id}`}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </CollapsibleSection>
    </section>
  );
}

function CollapsibleSection({
  title,
  badge,
  open,
  onToggle,
  children,
}: {
  title: string;
  badge?: string;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <div>
      <button type="button" onClick={onToggle} className="flex w-full items-center justify-between py-1">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide" style={{ color: "#888780" }}>
            {title}
          </span>
          {badge && (
            <span
              className="rounded-full px-1.5 py-0.5 text-[10px] font-semibold"
              style={{ background: "#e6e3da", color: "#5f5e5a" }}
            >
              {badge}
            </span>
          )}
        </div>
        <svg
          width="14" height="14" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
          style={{ color: "#888780", transform: open ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.2s" }}
          aria-hidden="true"
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>
      {open && <div className="mt-2">{children}</div>}
    </div>
  );
}

function currentDate(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function dateFromOffset(days: number): string {
  const value = new Date();
  value.setDate(value.getDate() + days);
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}

function formatDate(value: string | null): string {
  if (!value) return "date pending";
  return new Date(`${value}T00:00:00`).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function StatusPill({ status }: { status: string }) {
  const palette: Record<string, { bg: string; color: string }> = {
    succeeded:          { bg: "#e1f5ee", color: "#0f6e56" },
    paid:               { bg: "#e1f5ee", color: "#0f6e56" },
    pending:            { bg: "#faeeda", color: "#854f0b" },
    approved:           { bg: "#faeeda", color: "#854f0b" },
    open:               { bg: "#fcebeb", color: "#a32d2d" },
    past_due:           { bg: "#fcebeb", color: "#a32d2d" },
    failed:             { bg: "#fcebeb", color: "#a32d2d" },
    partially_paid:     { bg: "#faeeda", color: "#854f0b" },
    refunded:           { bg: "#f1efe8", color: "#5f5e5a" },
    partially_refunded: { bg: "#f1efe8", color: "#5f5e5a" },
    expired:            { bg: "#f1efe8", color: "#5f5e5a" },
    void:               { bg: "#f1efe8", color: "#5f5e5a" },
    rejected:           { bg: "#fcebeb", color: "#a32d2d" },
  };
  const { bg, color } = palette[status] ?? palette.expired;
  return (
    <span
      className="mt-0.5 inline-block rounded-full px-2 py-0.5 text-xs font-medium"
      style={{ background: bg, color }}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}
