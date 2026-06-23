"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { getOnboardingStatus, type OnboardingApplication } from "@/lib/api/parent";
import { useInstallPrompt, useIsIOSSafari } from "@/lib/pwa/install-prompt";

/**
 * Parent checkout-return page.
 *
 * Polls onboarding status until terminal: PENDING_APPROVAL (success path)
 * or REFUNDED / CAPACITY_FAILED_REFUND_FAILED / CHECKOUT_EXPIRED.
 */

const TERMINAL = new Set([
  "PENDING_APPROVAL",
  "CHECKOUT_EXPIRED",
  "REFUNDED",
  "CAPACITY_FAILED_REFUND_FAILED",
]);

export default function CheckoutReturnPage() {
  const params = useSearchParams();
  const applicationId = params.get("application_id");
  const [done, setDone] = useState(false);

  const { data, isError } = useQuery<OnboardingApplication>({
    queryKey: ["parent", "onboarding", "status", applicationId],
    queryFn: () => getOnboardingStatus(applicationId!),
    enabled: !!applicationId && !done,
    refetchInterval: (q) =>
      q.state.data && TERMINAL.has(q.state.data.status) ? false : 1500,
  });

  useEffect(() => {
    if (data && TERMINAL.has(data.status)) setDone(true);
  }, [data]);

  if (!applicationId) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center px-4">
        <div
          className="w-full max-w-sm rounded-2xl p-6 animate-fade-in-up"
          style={{ background: "white", border: "1px solid var(--rally-line)" }}
        >
          <div
            className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full"
            style={{ background: "#fcebeb" }}
          >
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#a32d2d" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
          </div>
          <p className="text-center text-sm font-semibold" style={{ color: "#a32d2d" }}>
            Missing application id.
          </p>
        </div>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center px-4">
        <div
          className="w-full max-w-sm rounded-2xl p-6 animate-fade-in-up"
          style={{ background: "white", border: "1px solid var(--rally-line)" }}
        >
          <div
            className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full"
            style={{ background: "#fcebeb" }}
          >
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#a32d2d" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
          </div>
          <p className="text-center text-sm font-semibold" style={{ color: "#a32d2d" }}>
            Could not load status.
          </p>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center px-4">
        <div
          className="w-full max-w-sm rounded-2xl overflow-hidden"
          style={{ background: "white", border: "1px solid var(--rally-line)" }}
        >
          <div className="h-2 shimmer" />
          <div className="p-6 space-y-3">
            <div className="mx-auto h-12 w-12 rounded-full shimmer" />
            <div className="mx-auto h-4 w-40 rounded shimmer" />
            <div className="mx-auto h-3 w-56 rounded shimmer" />
          </div>
        </div>
      </div>
    );
  }

  const summary = STATUS_SUMMARIES[data.status] ?? STATUS_SUMMARIES.UNKNOWN;
  const variant = STATUS_VARIANTS[data.status] ?? STATUS_VARIANTS.UNKNOWN;

  return (
    <section data-testid="parent-checkout-return" className="flex min-h-[40vh] items-center justify-center px-4">
      <div
        className="w-full max-w-sm rounded-2xl p-6 animate-fade-in-up"
        style={{ background: "white", border: "1px solid var(--rally-line)" }}
      >
        {/* Status icon */}
        <div
          className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-full"
          style={{ background: variant.iconBg }}
        >
          {variant.icon}
        </div>

        {/* Heading */}
        <h1
          className="text-center font-display text-xl font-bold tracking-tight"
          style={{ color: "var(--rally-ink)" }}
        >
          {summary.title}
        </h1>

        {/* Body */}
        <p
          data-testid="status-text"
          className="mt-2 text-center text-sm leading-relaxed"
          style={{ color: "var(--rally-muted)" }}
        >
          {summary.body(data)}
        </p>

        {/* PWA install prompt (success only) */}
        {data.status === "PENDING_APPROVAL" && <CheckoutSuccessActions />}
      </div>
    </section>
  );
}

/* ── Icon sets per status ─────────────────────────────────────────────────── */

const SuccessIcon = (
  <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#0f6e56" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
    <polyline points="22 4 12 14.01 9 11.01" />
  </svg>
);

const AlertIcon = (
  <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#a32d2d" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
  </svg>
);

const ClockIcon = (
  <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#854f0b" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
  </svg>
);

const RefundIcon = (
  <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#5f5e5a" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <polyline points="1 4 1 10 7 10" /><path d="M3.51 15a9 9 0 1 0 .49-3.79" />
  </svg>
);

const STATUS_VARIANTS: Record<string, { iconBg: string; icon: React.ReactNode }> = {
  PENDING_APPROVAL:              { iconBg: "#e1f5ee", icon: SuccessIcon },
  CHECKOUT_EXPIRED:              { iconBg: "#faeeda", icon: ClockIcon },
  REFUNDED:                      { iconBg: "#f1efe8", icon: RefundIcon },
  CAPACITY_FAILED_REFUND_FAILED: { iconBg: "#fcebeb", icon: AlertIcon },
  UNKNOWN:                       { iconBg: "#faeeda", icon: ClockIcon },
};

/* ── Copy per status ──────────────────────────────────────────────────────── */

const STATUS_SUMMARIES: Record<string, { title: string; body: (a: OnboardingApplication) => string }> = {
  PENDING_APPROVAL: {
    title: "Payment received",
    body: () => "We received your payment. An admin will confirm the enrollment shortly.",
  },
  CHECKOUT_EXPIRED: {
    title: "Checkout expired",
    body: () => "The Stripe checkout session expired. Restart onboarding to try again.",
  },
  REFUNDED: {
    title: "Refunded",
    body: () => "The class filled up before your payment cleared. Your card was automatically refunded.",
  },
  CAPACITY_FAILED_REFUND_FAILED: {
    title: "Refund needs attention",
    body: () =>
      "The class filled up before your payment cleared and the automatic refund failed. An admin has been alerted; we'll reach out by email.",
  },
  UNKNOWN: {
    title: "Processing",
    body: () => "Please hold tight while we finish processing your payment.",
  },
};

/* ── PWA install prompt (success state only) ──────────────────────────────── */

function CheckoutSuccessActions() {
  const { canInstall, prompt, dismiss } = useInstallPrompt();
  const ios = useIsIOSSafari();
  if (!canInstall && !ios) return null;
  return (
    <div
      data-testid="install-card"
      className="mt-5 rounded-xl p-4"
      style={{ background: "var(--rally-cobalt-soft)", border: "1px solid var(--rally-line)" }}
    >
      <p className="text-sm font-semibold" style={{ color: "var(--rally-ink)" }}>
        Install Academy
      </p>
      <p className="mt-0.5 text-xs" style={{ color: "var(--rally-muted)" }}>
        Get faster access from your home screen.
      </p>
      <div className="mt-3 flex gap-2">
        {canInstall ? (
          <button
            onClick={() => void prompt()}
            className="min-h-touch flex-1 rounded-xl text-sm font-semibold active:scale-95 transition-transform"
            style={{
              background: "linear-gradient(135deg,#facc15,#f59e0b)",
              color: "#0a0f1c",
            }}
          >
            Install
          </button>
        ) : (
          <p className="text-xs" style={{ color: "var(--rally-muted)" }}>
            Use Share → Add to Home Screen in Safari.
          </p>
        )}
        <button
          onClick={dismiss}
          className="min-h-touch rounded-xl border px-4 text-sm active:scale-95 transition-transform"
          style={{ borderColor: "var(--rally-line)", background: "white", color: "var(--rally-muted)" }}
        >
          Later
        </button>
      </div>
    </div>
  );
}
