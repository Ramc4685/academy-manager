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
    return <p className="text-red-600">Missing application id.</p>;
  }
  if (isError) return <p className="text-red-600">Could not load status.</p>;
  if (!data) return <p>Loading…</p>;

  const summary = STATUS_SUMMARIES[data.status] ?? STATUS_SUMMARIES.UNKNOWN;
  return (
    <section data-testid="parent-checkout-return">
      <h1 className="text-2xl font-semibold">{summary.title}</h1>
      <p className="mt-2 text-neutral-700 dark:text-neutral-300" data-testid="status-text">
        {summary.body(data)}
      </p>
      {data.status === "PENDING_APPROVAL" && <CheckoutSuccessActions />}
    </section>
  );
}

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

function CheckoutSuccessActions() {
  const { canInstall, prompt, dismiss } = useInstallPrompt();
  const ios = useIsIOSSafari();
  if (!canInstall && !ios) return null;
  return (
    <div data-testid="install-card" className="mt-6 rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm dark:border-blue-900 dark:bg-blue-950">
      <p className="font-semibold">Install Academy</p>
      <p className="text-neutral-700 dark:text-neutral-300">
        Get faster access from your home screen.
      </p>
      <div className="mt-2 flex gap-2">
        {canInstall ? (
          <button onClick={() => void prompt()} className="min-h-touch rounded-md bg-blue-600 px-3 text-white">
            Install
          </button>
        ) : (
          <p>Use Share → Add to Home Screen in Safari.</p>
        )}
        <button onClick={dismiss} className="min-h-touch rounded-md border border-blue-300 px-3 dark:border-blue-700">
          Later
        </button>
      </div>
    </div>
  );
}
