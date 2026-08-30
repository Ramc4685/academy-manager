"use client";

/**
 * Full-screen fallback for a transient /me outage (issue #515).
 *
 * Shown by the persona/platform layouts when the identity check failed for a
 * non-auth reason (backend 5xx, network blip, timeout) after retries. The
 * Firebase session is still valid, so this deliberately does NOT redirect to
 * /login or clear any identity state — it just lets the user try again.
 */
export function AuthUnavailableScreen({ onRetry }: { onRetry: () => void }) {
  return (
    <div
      data-testid="auth-unavailable"
      className="min-h-screen flex items-center justify-center px-4"
      style={{ background: "var(--rally-paper)" }}
    >
      <div className="flex max-w-sm flex-col items-center gap-3 text-center">
        <p className="text-base font-semibold text-neutral-800">
          We can&apos;t reach the server right now
        </p>
        <p className="text-sm text-neutral-500">
          You&apos;re still signed in — this is usually a brief connection
          hiccup. Check your connection and try again.
        </p>
        <button
          type="button"
          onClick={onRetry}
          data-testid="auth-unavailable-retry"
          className="min-h-touch mt-1 rounded-lg px-4 py-2 text-sm font-semibold text-white transition-all duration-150 active:scale-95"
          style={{ background: "var(--rally-cobalt)" }}
        >
          Retry
        </button>
      </div>
    </div>
  );
}
