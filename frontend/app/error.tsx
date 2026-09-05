"use client";

import Link from "next/link";
import { useEffect } from "react";

import { captureError } from "@/lib/observability/sentry";

/**
 * Route-segment error boundary. Renders a friendly recovery screen and logs the
 * real error to the console for diagnostics — the raw error text (which may
 * carry internal details) is never shown to the user.
 */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
    captureError(error, { digest: error.digest, tags: { boundary: "route" } });
  }, [error]);

  return (
    <main className="flex min-h-dvh items-center justify-center bg-slate-50 p-6 font-body text-slate-950">
      <div className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-8 text-center shadow-sm">
        <h1 className="font-display text-2xl font-bold text-slate-900">Something went wrong</h1>
        <p className="mt-2 text-sm text-slate-600">
          We hit an unexpected problem loading this page. Your data is safe. Try
          again, and if it keeps happening, contact your academy.
        </p>
        <div className="mt-6 flex items-center justify-center gap-3">
          <button
            type="button"
            onClick={reset}
            className="flex min-h-touch items-center justify-center rounded-md bg-blue-600 px-4 text-sm font-medium text-white shadow-sm transition hover:bg-blue-500"
          >
            Try again
          </button>
          <Link
            href="/"
            className="flex min-h-touch items-center justify-center rounded-md border border-slate-200 bg-white px-4 text-sm font-medium text-slate-800 shadow-sm transition hover:bg-slate-50"
          >
            Go home
          </Link>
        </div>
      </div>
    </main>
  );
}
