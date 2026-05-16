/**
 * Step 3 — Waiver acceptance.
 * Tries GET /api/onboarding/waiver/current; falls back to placeholder.
 * PATCHes waiver_acceptance: {version, accepted: true}, then advances to /session.
 *
 * Phase 5 Slice 5.
 */
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { toast } from "sonner";
import OnboardingLayout from "./OnboardingLayout";

const FALLBACK_VERSION = "2026.1";
const FALLBACK_TEXT =
  // TODO: serve waiver text from GET /api/onboarding/waiver/current once that endpoint exists.
  "Liability Waiver — Version 2026.1\n\n" +
  "By enrolling your child in BLno Badminton Academy programs, you acknowledge that:\n\n" +
  "1. Badminton is a physical activity that carries inherent risks of injury.\n" +
  "2. You confirm your child is physically fit to participate.\n" +
  "3. You release BLno Badminton Academy, its coaches, and staff from liability for " +
  "injuries arising from normal participation in academy activities, except in cases of " +
  "gross negligence.\n" +
  "4. You authorize academy staff to seek emergency medical treatment for your child " +
  "if you are unreachable.\n" +
  "5. This waiver is governed by applicable state law.\n\n" +
  "Please read this waiver carefully before accepting. If you have questions, contact " +
  "us at info@blnobadminton.com before proceeding.";

export default function OnboardingWaiver() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [waiverText, setWaiverText] = useState(null);
  const [waiverVersion, setWaiverVersion] = useState(FALLBACK_VERSION);
  const [accepted, setAccepted] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .get("/onboarding/waiver/current")
      .then((r) => {
        setWaiverText(r.data.text || FALLBACK_TEXT);
        setWaiverVersion(r.data.version || FALLBACK_VERSION);
      })
      .catch(() => {
        // 404 or network error — use static placeholder. The version is still
        // accepted server-side as long as it exists in waiver_versions.
        setWaiverText(FALLBACK_TEXT);
        setWaiverVersion(FALLBACK_VERSION);
      });
  }, []);

  const submit = async () => {
    if (!accepted) {
      toast.error("Please accept the waiver to continue");
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
        {/* Waiver text */}
        <div
          className="h-64 overflow-y-auto rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700 whitespace-pre-wrap leading-relaxed"
          data-testid="waiver-text"
          aria-label="Waiver text"
          tabIndex={0}
        >
          {waiverText ?? "Loading waiver…"}
        </div>

        {/* Version badge */}
        <div className="text-xs text-slate-500">
          Waiver version:{" "}
          <span className="font-semibold" data-testid="waiver-version">
            {waiverVersion}
          </span>
        </div>

        {/* Acceptance checkbox */}
        <label className="flex items-start gap-3 p-3 rounded-lg border border-slate-200 cursor-pointer">
          <input
            type="checkbox"
            checked={accepted}
            onChange={(e) => setAccepted(e.target.checked)}
            className="mt-0.5 h-4 w-4 rounded border-slate-300 text-blue-600"
            data-testid="waiver-checkbox"
          />
          <div className="text-sm text-slate-700">
            <div className="font-medium">
              I have read and accept the waiver dated {waiverVersion}
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
            disabled={!accepted || busy}
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
