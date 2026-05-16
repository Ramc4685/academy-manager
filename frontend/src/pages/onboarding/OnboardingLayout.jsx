/**
 * Shared layout wrapper for onboarding steps.
 * Shows academy logo, step indicator, and a consistent container.
 *
 * Phase 5 Slice 5.
 */
import { Link } from "react-router-dom";

const STEPS = [
  { num: 1, label: "Your profile" },
  { num: 2, label: "Child details" },
  { num: 3, label: "Waiver" },
  { num: 4, label: "Pick a session" },
  { num: 5, label: "Review" },
];

export default function OnboardingLayout({ step, children }) {
  return (
    <div className="min-h-screen bg-slate-50 font-body">
      <div className="max-w-2xl mx-auto p-4 sm:p-6 lg:p-10">
        {/* Logo */}
        <Link to="/" className="flex items-center gap-3 mb-8">
          <div className="w-10 h-10 rounded-lg bg-yellow-400 flex items-center justify-center text-slate-900 font-display font-bold text-xl">
            B
          </div>
          <div>
            <div className="font-display font-bold tracking-tight text-slate-900">
              BLno Badminton Academy
            </div>
            <div className="text-[11px] text-slate-500 uppercase tracking-[0.18em]">
              Enrollment
            </div>
          </div>
        </Link>

        {/* Step indicator */}
        <div className="mb-6" data-testid="onboarding-steps">
          <div className="flex items-center gap-1.5">
            {STEPS.map((s) => (
              <div
                key={s.num}
                className={`flex-1 h-1.5 rounded-full transition-colors ${
                  s.num <= step ? "bg-blue-600" : "bg-slate-200"
                }`}
              />
            ))}
          </div>
          <div className="text-xs text-slate-500 mt-2" data-testid="step-indicator">
            Step {step} of {STEPS.length} —{" "}
            {STEPS.find((s) => s.num === step)?.label}
          </div>
        </div>

        {children}
      </div>
    </div>
  );
}
