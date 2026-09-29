/**
 * Pure branding validators, kept standalone so `academy-panel.tsx` (the
 * merged "Academy profile" tab, Settings overhaul Phase 3 PR 9) and its
 * tests can import them without pulling in a component.
 *
 * The old `BrandingPanel` component and its "Branding" tab are retired: the
 * Academy and Branding panels merged into one Academy profile tab (key
 * stays "academy"); `?panel=branding` now maps there via
 * `RETIRED_SETTINGS_PANELS`. See `academy-panel.tsx`.
 */

export const SENDER_NAME_MAX_LENGTH = 80;

/** Client-side mirror of the server rule (the server re-validates). */
export function senderNameError(value: string): string | null {
  if (/[\u0000-\u001f\u007f<>]/.test(value)) {
    return "Sender name cannot contain line breaks or angle brackets.";
  }
  if (value.trim().length > SENDER_NAME_MAX_LENGTH) {
    return `Sender name must be ${SENDER_NAME_MAX_LENGTH} characters or fewer.`;
  }
  return null;
}

const HEX_COLOR_RE = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;

/** Client-side mirror of the brand-colour shape check. Blank is valid (unset). */
export function brandColorError(value: string): string | null {
  if (!value.trim()) return null;
  return HEX_COLOR_RE.test(value.trim())
    ? null
    : "Brand colour must be a hex value like #2563EB.";
}
