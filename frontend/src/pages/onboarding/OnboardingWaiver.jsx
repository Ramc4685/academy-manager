/**
 * Step 3 — Waiver acceptance.
 * Fetches waiver text from GET /api/onboarding/waiver/current.
 * If the fetch fails, surfaces a non-blocking notice and disables the
 * accept button — a parent must see the actual text before accepting.
 * PATCHes waiver_acceptance: {version, accepted: true} using the version
 * returned by the API, then advances to /session.
 *
 * Phase 5 Slice 5 / waiver-current follow-up.
 */
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { toast } from "sonner";
import OnboardingLayout from "./OnboardingLayout";

export default function OnboardingWaiver() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [waiverText, setWaiverText] = useState(null);
  const [waiverVersion, setWaiverVersion] = useState(null);
  const [fetchError, setFetchError] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const [busy, setBusy] = useState(false);

  const waiverReady =
    !fetchError &&
    typeof waiverVersion === "string" &&
    waiverVersion.trim().length > 0 &&
    typeof waiverText === "string" &&
    waiverText.trim().length > 0;

  useEffect(() => {
    api
      .get("/onboarding/waiver/current")
      .then((r) => {
        setWaiverText(r.data.content);
        setWaiverVersion(r.data.version);
        setFetchError(false);
      })
      .catch(() => {
        setFetchError(true);
      });
  }, []);

  const submit = async () => {
    if (!accepted) {
      toast.error("Please accept the waiver to continue");
      return;
    }
    if (!waiverReady) {
      toast.error("Waiver text could not be loaded. Please refresh and try again.");
      return;
    }
    setBusy(true);
    try {
      await api.patch(`/onboarding/${id}`, {
        waiver_acceptance: {
          version: waiverVersion,
          accepted: true,
        },
      });
      navigate(`/onboarding/${id}/session`);
    } catch (e) {
      toast.error(
        e?.response?.data?.detail ||
          e?.response?.data?.error ||
          "Failed to save. Please try again."
      );
    } finally {
      setBusy(false);
    }
  };

  // Submit is disabled until the waiver loads successfully AND is accepted.
  const submitDisabled = !accepted || busy || !waiverReady;

  return (
    <OnboardingLayout step={3}>
      <h1 className="text-2xl sm:text-3xl font-display font-bold tracking-tighter text-slate-900 mb-2">
        Liability waiver
      </h1>
      <p className="text-slate-600 text-sm mb-6">
        Please read the waiver below and confirm your acceptance.
      </p>

      <div
        className="bg-white border border-slate-200 rounded-xl p-5 sm:p-6 space-y-5"
        data-testid="waiver-step"
      >
        {/* Fetch-error notice */}
        {fetchError && (
          <div
            className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800"
            data-testid="waiver-fetch-error"
            role="alert"
          >
            Could not load the waiver text right now. Please try again or contact
            us.
          </div>
        )}

        {/* Waiver text */}
        <div
          className="h-64 overflow-y-auto rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700 whitespace-pre-wrap leading-relaxed"
          data-testid="waiver-text"
          aria-label="Waiver text"
          tabIndex={0}
        >
          {fetchError
            ? null
            : waiverText ?? "Loading waiver…"}
        </div>

        {/* Version badge */}
        <div className="text-xs text-slate-500">
          Waiver version:{" "}
          <span className="font-semibold" data-testid="waiver-version">
            {waiverVersion ?? "—"}
          </span>
        </div>

        {/* Acceptance checkbox — disabled until text loaded */}
        <label className="flex items-start gap-3 p-3 rounded-lg border border-slate-200 cursor-pointer">
          <input
            type="checkbox"
            checked={accepted}
            onChange={(e) => setAccepted(e.target.checked)}
            disabled={!waiverReady}
            className="mt-0.5 h-4 w-4 rounded border-slate-300 text-blue-600"
            data-testid="waiver-checkbox"
          />
          <div className="text-sm text-slate-700">
            <div className="font-medium">
              I have read and accept the waiver dated {waiverVersion ?? "—"}
            </div>
            <div className="text-xs text-slate-500 mt-0.5">
              This acceptance is legally binding.
            </div>
          </div>
        </label>

        <div className="flex justify-between pt-2">
          <Button
            variant="outline"
            onClick={() => navigate(`/onboarding/${id}/child`)}
            className="min-h-[44px]"
            data-testid="waiver-back"
          >
            Back
          </Button>
          <Button
            onClick={submit}
            disabled={submitDisabled}
            className="min-h-[44px] bg-blue-600 hover:bg-blue-500 text-white"
            data-testid="waiver-submit"
          >
            {busy ? "Saving…" : "Accept and continue"}
          </Button>
        </div>
      </div>
    </OnboardingLayout>
  );
}
