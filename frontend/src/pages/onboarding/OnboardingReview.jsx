/**
 * Step 5 — Review and proceed to Stripe Checkout.
 * Fetches current application status for display, then POSTs /checkout.
 *   200  → window.location.href = checkout_url
 *   409 {error: "session_full"} → banner + back to session step
 *   Other errors → friendly message
 *
 * Phase 5 Slice 5.
 */
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../../lib/api";
import { Button } from "../../components/ui/button";
import OnboardingLayout from "./OnboardingLayout";

export default function OnboardingReview() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .get(`/onboarding/${id}/status`)
      .then((r) => setStatus(r.data))
      .catch(() => setStatus(null))
      .finally(() => setLoading(false));
  }, [id]);

  const checkout = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await api.post(`/onboarding/${id}/checkout`);
      // 200 — redirect to Stripe
      if (r.data?.checkout_url) {
        window.location.href = r.data.checkout_url;
      } else {
        setError("Something went wrong. Please try again.");
        setBusy(false);
      }
    } catch (e) {
      const status409 = e?.response?.status === 409;
      const body = e?.response?.data;
      const isSessionFull =
        status409 && (body?.error === "session_full" || body?.detail === "session_full");

      if (isSessionFull) {
        // Route back to session selection with a banner
        navigate(`/onboarding/${id}/session?reason=session_full`);
        return;
      }

      setError(
        body?.detail ||
          body?.error ||
          "Something went wrong, please try again."
      );
      setBusy(false);
    }
  };

  return (
    <OnboardingLayout step={5}>
      <h1 className="text-2xl sm:text-3xl font-display font-bold tracking-tighter text-slate-900 mb-2">
        Review your application
      </h1>
      <p className="text-slate-600 text-sm mb-6">
        Check everything looks right before proceeding to payment.
      </p>

      {loading && (
        <div className="text-sm text-slate-500">Loading…</div>
      )}

      {!loading && (
        <div
          className="bg-white border border-slate-200 rounded-xl p-5 sm:p-6 space-y-5"
          data-testid="review-step"
        >
          {status && (
            <dl className="space-y-3 text-sm">
              {status.child_name && (
                <div className="flex justify-between gap-4">
                  <dt className="text-slate-500 font-medium">Child</dt>
                  <dd className="text-slate-900 text-right">{status.child_name}</dd>
                </div>
              )}
              {status.selected_session_id && (
                <div className="flex justify-between gap-4">
                  <dt className="text-slate-500 font-medium">Session</dt>
                  <dd className="text-slate-900 text-right">{status.selected_session_id}</dd>
                </div>
              )}
              <div className="flex justify-between gap-4">
                <dt className="text-slate-500 font-medium">Application status</dt>
                <dd className="text-slate-900 text-right capitalize">{status.status || "draft"}</dd>
              </div>
            </dl>
          )}

          {!status && !loading && (
            <div className="text-sm text-slate-500">
              Could not load application details.
            </div>
          )}

          {error && (
            <div
              className="p-4 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm"
              data-testid="checkout-error"
              role="alert"
            >
              {error}
            </div>
          )}

          <div className="border-t border-slate-100 pt-5">
            <p className="text-xs text-slate-500 mb-4">
              Clicking "Continue to payment" will take you to Stripe's secure
              checkout. Your payment is processed by Stripe and is not stored
              on our servers.
            </p>
            <div className="flex justify-between gap-3">
              <Button
                variant="outline"
                onClick={() => navigate(`/onboarding/${id}/session`)}
                className="min-h-[44px]"
                data-testid="review-back"
                disabled={busy}
              >
                Back
              </Button>
              <Button
                onClick={checkout}
                disabled={busy}
                className="min-h-[44px] bg-blue-600 hover:bg-blue-500 text-white font-semibold px-6"
                data-testid="checkout-button"
              >
                {busy ? "Redirecting…" : "Continue to payment"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </OnboardingLayout>
  );
}
