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
  if (status === "cancelled") return "Autopay off";
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
  const [resumeOn, setResumeOn] = useState(currentDate());
  const [reviewOn, setReviewOn] = useState(dateFromOffset(14));
  const [pauseReason, setPauseReason] = useState("");
  const [portalError, setPortalError] = useState<string | null>(null);
  const [autopayError, setAutopayError] = useState<string | null>(null);
  const [invoicePaymentError, setInvoicePaymentError] = useState<string | null>(null);
  const [balancePaymentError, setBalancePaymentError] = useState<string | null>(null);
  const [selectedInvoiceId, setSelectedInvoiceId] = useState<string | null>(null);
  const [payingInvoiceId, setPayingInvoiceId] = useState<string | null>(null);
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
      return status === "active" || status === "past_due" || status === "cancelled" ? false : 3000;
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
      setPortalError(
        detail === "Request failed"
          ? "Billing portal could not open. Please try again."
          : `Billing portal could not open. ${detail}`,
      );
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
      setAutopayError(detail === "Request failed" ? AUTOPAY_START_FAILED : `Autopay could not start. ${detail}`);
    },
    onSettled: () => { setStartingAutopayEnrollmentId(null); },
  });

  const invoicePaymentMutation = useMutation({
    mutationFn: (invoiceId: string) =>
      startParentInvoicePayment(invoiceId, {
        success_url: `${window.location.origin}/parent/payments?invoice=paid`,
        cancel_url: `${window.location.origin}/parent/payments?invoice=cancelled`,
      }),
    onMutate: (invoiceId) => {
      setPortalError(null);
      setInvoicePaymentError(null);
      setPayingInvoiceId(invoiceId);
    },
    onSuccess: (res) => {
      if (!res.redirect_url) {
        setInvoicePaymentError("Payment could not start because Stripe did not return a checkout link.");
        return;
      }
      window.location.href = res.redirect_url;
    },
    onError: (error) => {
      const detail = error instanceof Error ? error.message : "Request failed";
      setInvoicePaymentError(detail === "Request failed" ? "Payment could not start." : `Payment could not start. ${detail}`);
    },
    onSettled: () => { setPayingInvoiceId(null); },
  });

  const balancePaymentMutation = useMutation({
    mutationFn: () =>
      startParentBalancePayment({
        success_url: `${window.location.origin}/parent/payments?balance=paid`,
        cancel_url: `${window.location.origin}/parent/payments?balance=cancelled`,
      }),
    onMutate: () => { setBalancePaymentError(null); },
    onSuccess: (res) => {
      if (!res.redirect_url) {
        setBalancePaymentError("Payment could not start because Stripe did not return a checkout link.");
        return;
      }
      window.location.href = res.redirect_url;
    },
    onError: (error) => {
      const detail = error instanceof Error ? error.message : "Request failed";
      setBalancePaymentError(detail === "Request failed" ? "Payment could not start." : `Payment could not start. ${detail}`);
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
      setResumeOn(currentDate());
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
          Confirming autopay with Stripe…
        </p>
      )}
      {enrollments.some((e) => e.payment_mode === "monthly" && e.subscription_status === "incomplete") && (
        <p role="status" data-testid="payment-update-pending" className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Payment received in Stripe may take a moment to update this page. If it does not update, retry autopay or contact the academy.
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
            {enrollments.some((e) => e.payment_mode === "monthly" && ["active", "trialing"].includes(e.subscription_status ?? ""))
              ? "autopay on"
              : "autopay off"}
          </p>
          <button
            type="button"
            onClick={() => balancePaymentMutation.mutate()}
            disabled={balancePaymentMutation.isPending}
            className="mt-4 w-full rounded-xl py-3 text-sm font-semibold disabled:opacity-60 active:scale-95 transition-transform"
            style={{ background: "linear-gradient(135deg,#facc15,#f59e0b)", color: "#0a0f1c" }}
          >
            {balancePaymentMutation.isPending ? "Starting…" : `Pay balance · ${money(currentBalance)}`}
          </button>
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
                      <p className="text-sm font-medium" style={{ color: "#0a0f1c" }}>{invoice.period}</p>
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
                    <div className="mt-2.5 flex gap-2">
                      <button
                        type="button"
                        disabled={invoicePaymentMutation.isPending}
                        onClick={() => invoicePaymentMutation.mutate(invoice.invoice_id)}
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
                ["active", "trialing", "past_due"].includes(enrollment.subscription_status ?? "");
              const helperText = autopayHelperText(enrollment);
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
                          : enrollment.subscription_status === "incomplete"
                            ? "Retry autopay"
                            : "Subscribe to autopay"}
                    </button>
                    <button
                      type="button"
                      onClick={() => setPauseEnrollmentId(enrollment.enrollment_id)}
                      className="rounded-xl border px-4 py-2.5 text-sm"
                      style={{ borderColor: "#d3d1c7", background: "#fff", color: "#5f5e5a" }}
                    >
                      Pause
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
          <p className="mb-3 text-sm font-semibold" style={{ color: "#0a0f1c" }}>Pause request</p>
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
                  (pauseKind === "fixed" ? !resumeOn : !reviewOn)
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
                  setResumeOn(currentDate());
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
                  {new Date(payment.created_at).toLocaleString()}
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
