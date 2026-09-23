"use client";

/**
 * The one coach "Retry" button.
 *
 * Seven coach screens each hand-rolled their own Retry: inherited red text on
 * a red-50 wash, a cobalt link, a bare border, and white on amber-600 in the
 * Needs-review tray, which measured 3.2:1 and failed WCAG AA. They now all
 * render this, so the contrast is decided once.
 *
 * Measured contrast (WCAG 2.x relative luminance):
 * - label: white on rally-cobalt-700 (#1d4ed8) = 6.70:1; hover
 *   rally-cobalt-900 (#1e3a8a) = 10.36:1. Both clear 4.5:1 in light and dark
 *   because the button paints its own background.
 * - focus outline (offset 2px, so it sits on the surrounding surface):
 *   rally-cobalt-700 on white 6.70:1, on red-50 6.13:1, on amber-50 6.46:1;
 *   dark mode switches to rally-cobalt-500 (#3b82f6): 4.39:1 on red-950,
 *   4.08:1 on amber-950, 5.38:1 on neutral-950. All clear 3:1.
 */

export function RetryButton({
  onClick,
  disabled = false,
  busy = false,
  testId,
  className,
}: {
  onClick: () => void;
  disabled?: boolean;
  /** Show "Retrying…" while the retry is in flight. */
  busy?: boolean;
  testId?: string;
  /** Layout only (margins). Colour lives here, not at the call site. */
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      data-testid={testId}
      className={`${RETRY_BUTTON_CLASSES}${className ? ` ${className}` : ""}`}
    >
      {busy ? "Retrying…" : "Retry"}
    </button>
  );
}

export const RETRY_BUTTON_CLASSES =
  "inline-flex min-h-touch items-center justify-center rounded-md border border-transparent bg-rally-cobalt-700 px-3 text-sm font-semibold text-white hover:bg-rally-cobalt-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rally-cobalt-700 dark:focus-visible:outline-rally-cobalt-500 disabled:cursor-not-allowed disabled:opacity-50";
