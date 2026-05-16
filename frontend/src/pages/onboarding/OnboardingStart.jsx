/**
 * /onboarding/start — auto-creates or resumes a draft application,
 * then redirects to step 1 (profile).
 *
 * Phase 5 Slice 5.
 */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../lib/api";
import { useAuth } from "../../contexts/AuthContext";

export default function OnboardingStart() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [error, setError] = useState(null);

  useEffect(() => {
    // Redirect non-parents away immediately
    if (user && user.role !== "parent") {
      navigate("/", { replace: true });
      return;
    }
    if (!user) return;

    api
      .post("/onboarding/start", {})
      .then((r) => {
        const id = r.data._id || r.data.id;
        navigate(`/onboarding/${id}/profile`, { replace: true });
      })
      .catch((e) => {
        setError(
          e?.response?.data?.detail ||
            e?.response?.data?.error ||
            "Failed to start onboarding. Please try again."
        );
      });
  }, [user, navigate]);

  if (error) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center p-6">
        <div className="max-w-sm w-full bg-white border border-slate-200 rounded-xl p-6 text-center">
          <div className="text-red-600 font-medium mb-3">{error}</div>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="min-h-[44px] px-4 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700"
          >
            Try again
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center p-6">
      <div className="text-slate-500 text-sm">Starting your application…</div>
    </div>
  );
}
