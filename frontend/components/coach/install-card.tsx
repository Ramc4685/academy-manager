"use client";

import { useInstallPrompt, useIsIOSSafari } from "@/lib/pwa/install-prompt";

/**
 * Shown on coach surfaces after login.
 *
 * - Android Chrome / desktop: native install prompt via `beforeinstallprompt`.
 * - iOS Safari: explicit "Add to Home Screen" instructions (no native prompt).
 */
export function CoachInstallCard() {
  const { canInstall, installed, prompt, dismiss } = useInstallPrompt();
  const isIOSSafari = useIsIOSSafari();

  if (installed) return null;
  if (!canInstall && !isIOSSafari) return null;

  return (
    <div
      data-testid="install-card"
      className="mb-4 rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm dark:border-blue-900 dark:bg-blue-950"
    >
      {canInstall ? (
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="font-semibold">Install Academy</p>
            <p className="text-neutral-700 dark:text-neutral-300">
              Get faster launches and offline today screen.
            </p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => void prompt()}
              className="min-h-touch rounded-md bg-blue-600 px-3 text-white"
            >
              Install
            </button>
            <button
              onClick={dismiss}
              className="min-h-touch rounded-md border border-blue-300 px-3 dark:border-blue-700"
            >
              Later
            </button>
          </div>
        </div>
      ) : (
        <>
          <p className="font-semibold">Add Academy to your home screen</p>
          <ol className="mt-2 list-decimal list-inside space-y-1 text-neutral-700 dark:text-neutral-300">
            <li>Tap the Share button in Safari.</li>
            <li>Scroll and tap <em>Add to Home Screen</em>.</li>
            <li>Tap <em>Add</em> in the top-right.</li>
          </ol>
          <button
            onClick={dismiss}
            className="mt-3 min-h-touch rounded-md border border-blue-300 px-3 dark:border-blue-700"
          >
            Dismiss
          </button>
        </>
      )}
    </div>
  );
}
