/**
 * Step 6 — Post-checkout status polling page.
 * Stripe redirects here with ?checkout=success|cancel.
 *
 * Polling rules (from spec):
 *   - Every 3 seconds
 *   - For at most 2 minutes (40 polls)
 *   - Stop immediately on any terminal status
 *   - NEVER poll faster than 3s or beyond the 2-minute cap
 *
 * Terminal statuses:
 *   pending_approval, refunded, capacity_failed_refund_failed,
 *   checkout_expired, failed
 *
 * Phase 5 Slice 5.
 */
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../../lib/api";

const TERMINAL_STATUSES = new Set([
  "pending_approval",
  "refunded",
  "capacity_failed_refund_failed",
  "checkout_expired",
  "failed",
]);

const POLL_INTERVAL_MS = 3000;
const MAX_POLLS = 40; // 40 * 3s = 120s = 2 minutes

function StatusContent({ status, onRetry, onRestartOnboarding }) {
  if (status === "pending_approval") {
    return (
      <div data-testid="status-pending-approval">
        <h2 className="text-xl font-display font-bold text-slate-900 mb-2">
          Payment confirmed
        </h2>
        <p className="text-slate-600 text-sm mb-5">
          We're reviewing your application and you'll hear from us within 2
          business days.
        </p>
        <Link
          to="/parent/dashboard"
          className="inline-flex items-center justify-center min-h-[44px] px-5 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700"
          data-testid="status-go-to-dashboard"
        >
          Go to parent portal
        </Link>
      </div>
    );
  }

  if (status === "refunded") {
    return (
      <div data-testid="status-refunded">
        <h2 className="text-xl font-display font-bold text-slate-900 mb-2">
          Session filled — you're on the waitlist
        </h2>
        <p className="text-slate-600 text-sm mb-5">
          The session filled up and your payment was refunded. We've added you
          to the waitlist and will contact you when a spot opens.
        </p>
        <a
          href="mailto:info@blnobadminton.com"
          className="inline-flex items-center justify-center min-h-[44px] px-5 rounded-lg border border-slate-200 text-sm font-medium text-slate-700 hover:bg-slate-50"
          data-testid="status-contact-us"
        >
          Contact us
        </a>
      </div>
    );
  }

  if (status === "capacity_failed_refund_failed") {
    return (
      <div data-testid="status-capacity-failed-refund-failed">
        <h2 className="text-xl font-display font-bold text-slate-900 mb-2">
          Payment issue — our team will reach out
        </h2>
        <p className="text-slate-600 text-sm mb-5">
          Something went wrong refunding your payment. Our team has been
          notified and will reach out within 1 business day.
        </p>
        <a
          href="mailto:info@blnobadminton.com"
          className="inline-flex items-center justify-center min-h-[44px] px-5 rounded-lg border border-slate-200 text-sm font-medium text-slate-700 hover:bg-slate-50"
          data-testid="status-contact-team"
        >
          Email our team
        </a>
      </div>
    );
  }

  if (status === "checkout_expired") {
    return (
      <div data-testid="status-checkout-expired">
        <h2 className="text-xl font-display font-bold text-slate-900 mb-2">
          Checkout window expired
        </h2>
        <p className="text-slate-600 text-sm mb-5">
          Your checkout session timed out before payment was completed. Start a
          new application to try again.
        </p>
        <button
          type="button"
          onClick={onRestartOnboarding}
          className="inline-flex items-center justify-center min-h-[44px] px-5 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700"
          data-testid="status-restart"
        >
          Start again
        </button>
      </div>
    );
  }

  if (status === "failed") {
    return (
      <div data-testid="status-failed">
        <h2 className="text-xl font-display font-bold text-slate-900 mb-2">
          Payment failed
        </h2>
        <p className="text-slate-600 text-sm mb-5">
          Your payment was not processed. Please try again.
        </p>
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex items-center justify-center min-h-[44px] px-5 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700"
          data-testid="status-retry"
        >
          Try again
        </button>
      </div>
    );
  }

  return null;
}

export default function OnboardingStatus() {
  const { id } = useParams();
  const navigate = useNavigate();
  const params = new URLSearchParams(
    typeof window !== "undefined" ? window.location.search : ""
  );
  const checkoutParam = params.get("checkout"); // "success" | "cancel" | null

  const [statusVal, setStatusVal] = useState(null);
  const [pollsExhausted, setPollsExhausted] = useState(false);
  const pollCount = useRef(0);
  const timerRef = useRef(null);
  const stopped = useRef(false);

  const stopPolling = () => {
    stopped.current = true;
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  const poll = () => {
    if (stopped.current) return;

    api
      .get(`/onboarding/${id}/status`)
      .then((r) => {
        const s = r.data?.status;
        setStatusVal(s);
        pollCount.current += 1;

        if (TERMINAL_STATUSES.has(s)) {
          stopPolling();
          return;
        }

        if (pollCount.current >= MAX_POLLS) {
          stopPolling();
          setPollsExhausted(true);
          return;
        }

        // Schedule next poll after 3 seconds
        timerRef.current = setTimeout(poll, POLL_INTERVAL_MS);
      })
      .catch(() => {
        pollCount.current += 1;
        if (pollCount.current >= MAX_POLLS) {
          stopPolling();
          setPollsExhausted(true);
          return;
        }
        if (!stopped.current) {
          timerRef.current = setTimeout(poll, POLL_INTERVAL_MS);
        }
      });
  };

  useEffect(() => {
    // Only auto-poll if Stripe redirect was "success"
    if (checkoutParam === "cancel") {
      // Don't poll on cancel, just show the cancel state
      return;
    }

    poll();
    return () => stopPolling();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const handleRetry = () => {
    navigate(`/onboarding/${id}/review`);
  };

  const handleRestartOnboarding = () => {
    navigate("/onboarding/start");
  };

  const handleManualRefresh = () => {
    // Reset and poll once more (not auto, just a single manual hit)
    api
      .get(`/onboarding/${id}/status`)
      .then((r) => {
        const s = r.data?.status;
        setStatusVal(s);
        if (TERMINAL_STATUSES.has(s)) {
          setPollsExhausted(false); // we got a real terminal state now
        }
      })
      .catch(() => {});
  };

  // Checkout was cancelled before payment
  if (checkoutParam === "cancel") {
    return (
      <div
        className="min-h-screen bg-slate-50 flex items-center justify-center p-6"
        data-testid="status-page-cancel"
      >
        <div className="max-w-sm w-full bg-white border border-slate-200 rounded-xl p-6 text-center space-y-4">
          <h2 className="text-xl font-display font-bold text-slate-900">
            Checkout canceled
          </h2>
          <p className="text-slate-600 text-sm">
            You left the checkout without completing payment. Your application
            is saved — you can come back and try again.
          </p>
          <button
            type="button"
            onClick={() => navigate(`/onboarding/${id}/review`)}
            className="inline-flex items-center justify-center min-h-[44px] px-5 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 w-full"
            data-testid="status-resume-checkout"
          >
            Return to review
          </button>
        </div>
      </div>
    );
  }

  const isTerminal = statusVal && TERMINAL_STATUSES.has(statusVal);

  return (
    <div
      className="min-h-screen bg-slate-50 flex items-center justify-center p-6"
      data-testid="status-page"
    >
      <div className="max-w-sm w-full bg-white border border-slate-200 rounded-xl p-6 space-y-4">
        {/* Logo mark */}
        <div className="w-10 h-10 rounded-lg bg-yellow-400 flex items-center justify-center text-slate-900 font-display font-bold text-xl mx-auto">
          B
        </div>

        {/* Success banner (shown when Stripe returns with success) */}
        {checkoutParam === "success" && !isTerminal && !pollsExhausted && (
          <div
            className="text-center text-sm text-blue-700 bg-blue-50 rounded-lg p-3"
            data-testid="status-processing-banner"
          >
            Payment received — processing…
          </div>
        )}

        {/* Terminal state content */}
        {isTerminal && (
          <div className="text-center">
            <StatusContent
              status={statusVal}
              onRetry={handleRetry}
              onRestartOnboarding={handleRestartOnboarding}
            />
          </div>
        )}

        {/* Polling not yet terminal */}
        {!isTerminal && !pollsExhausted && (
          <div className="text-center space-y-3" data-testid="status-polling">
            <div className="text-slate-500 text-sm">
              Checking payment status…
            </div>
            <div
              className="w-8 h-8 border-2 border-slate-200 border-t-blue-600 rounded-full animate-spin mx-auto"
              aria-label="Loading"
            />
          </div>
        )}

        {/* 2-minute cap reached without terminal status */}
        {pollsExhausted && !isTerminal && (
          <div className="text-center space-y-4" data-testid="status-timed-out">
            <p className="text-slate-600 text-sm">
              Payment processing — refresh in a moment if this page doesn't
              update automatically.
            </p>
            <button
              type="button"
              onClick={handleManualRefresh}
              className="inline-flex items-center justify-center min-h-[44px] px-5 rounded-lg border border-slate-200 text-sm font-medium text-slate-700 hover:bg-slate-50 w-full"
              data-testid="status-manual-refresh"
            >
              Refresh status
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
