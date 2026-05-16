/**
 * Step 4 — Session selection.
 * Fetches parent-facing sessions. Greys out full sessions.
 * PATCHes selected_session_id, then advances to /review.
 *
 * Phase 5 Slice 5.
 */
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { toast } from "sonner";
import OnboardingLayout from "./OnboardingLayout";

export default function OnboardingSession() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [sessions, setSessions] = useState([]);
  const [loadingSession, setLoadingSession] = useState(true);
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(false);
  // Banner shown when coming back from /review due to session_full 409
  const [sessionFullBanner, setSessionFullBanner] = useState(false);

  useEffect(() => {
    // Check if redirected from checkout due to session_full
    const params = new URLSearchParams(window.location.search);
    if (params.get("reason") === "session_full") {
      setSessionFullBanner(true);
    }

    // Reuse the public sessions endpoint that RegisterStudent uses.
    api
      .get("/auth/public-sessions")
      .then((r) => setSessions(r.data || []))
      .catch(() => setSessions([]))
      .finally(() => setLoadingSession(false));
  }, []);

  const isFull = (s) =>
    s.is_full ||
    (typeof s.enrolled_count === "number" &&
      typeof s.capacity === "number" &&
      s.enrolled_count >= s.capacity);

  const submit = async () => {
    if (!selected) {
      toast.error("Please select a session");
      return;
    }
    setBusy(true);
    try {
      await api.patch(`/onboarding/${id}`, {
        selected_session_id: selected,
      });
      navigate(`/onboarding/${id}/review`);
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
    <OnboardingLayout step={4}>
      <h1 className="text-2xl sm:text-3xl font-display font-bold tracking-tighter text-slate-900 mb-2">
        Pick a session
      </h1>
      <p className="text-slate-600 text-sm mb-6">
        Choose the training session you'd like your child to join.
      </p>

      {/* Session-full redirect banner */}
      {sessionFullBanner && (
        <div
          className="mb-4 p-4 rounded-lg bg-amber-50 border border-amber-200 text-amber-800 text-sm"
          data-testid="session-full-banner"
          role="alert"
        >
          This session filled up while you were checking out — please pick
          another.
        </div>
      )}

      <div
        className="bg-white border border-slate-200 rounded-xl p-5 sm:p-6 space-y-4"
        data-testid="session-step"
      >
        {loadingSession && (
          <div className="text-sm text-slate-500">Loading sessions…</div>
        )}

        {!loadingSession && sessions.length === 0 && (
          <div className="text-sm text-slate-500">
            No sessions are currently open for enrollment. Please contact us.
          </div>
        )}

        <div className="grid grid-cols-1 gap-3">
          {sessions.map((s) => {
            const full = isFull(s);
            const isSelected = selected === s.id;
            return (
              <button
                key={s.id}
                type="button"
                disabled={full}
                onClick={() => !full && setSelected(s.id)}
                data-testid={`session-option-${s.id}`}
                data-full={full ? "true" : "false"}
                className={[
                  "text-left w-full p-4 rounded-xl border-2 transition-all min-h-[44px]",
                  full
                    ? "border-slate-100 bg-slate-50 opacity-50 cursor-not-allowed"
                    : isSelected
                    ? "border-blue-600 bg-blue-50"
                    : "border-slate-200 hover:border-slate-300 cursor-pointer",
                ].join(" ")}
              >
                <div className="font-medium text-slate-900 text-sm">
                  {s.name}
                </div>
                <div className="text-xs text-slate-500 mt-1 capitalize">
                  {[s.skill_level, s.day_of_week, s.start_time && s.end_time ? `${s.start_time}–${s.end_time}` : s.start_time]
                    .filter(Boolean)
                    .join(" · ")}
                </div>
                <div className="mt-1.5">
                  {full ? (
                    <span
                      className="text-xs font-semibold text-amber-600"
                      data-testid={`session-option-${s.id}-full`}
                    >
                      Session full
                    </span>
                  ) : (
                    <span className="text-xs font-semibold text-emerald-600">
                      {typeof s.available_seats === "number"
                        ? `${s.available_seats} spots left`
                        : "Open"}
                    </span>
                  )}
                </div>
              </button>
            );
          })}
        </div>

        <div className="flex justify-between pt-2">
          <Button
            variant="outline"
            onClick={() => navigate(`/onboarding/${id}/waiver`)}
            className="min-h-[44px]"
            data-testid="session-back"
          >
            Back
          </Button>
          <Button
            onClick={submit}
            disabled={!selected || busy}
            className="min-h-[44px] bg-blue-600 hover:bg-blue-500 text-white"
            data-testid="session-next"
          >
            {busy ? "Saving…" : "Review application"}
          </Button>
        </div>
      </div>
    </OnboardingLayout>
  );
}
