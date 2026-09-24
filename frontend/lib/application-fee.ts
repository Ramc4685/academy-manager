/**
 * Platform application fee (roadmap L9b) — basis points <-> percent.
 *
 * The API stores the fee as integer basis points (100 bps = 1%); operators
 * think in percent. Parsing is strict so a typo never silently becomes a fee.
 */

/** "2.5%" style label for a basis-point value. */
export function formatApplicationFee(bps: number): string {
  const percent = bps / 100;
  return `${Number.isInteger(percent) ? percent.toFixed(0) : String(percent)}%`;
}

/** Percent text shown in an edit field for a basis-point value. */
export function bpsToPercentInput(bps: number): string {
  return String(bps / 100);
}

/**
 * Parse an operator-entered percent into basis points, or null when it is not
 * a valid fee: empty, non-numeric, negative, finer than 0.01%, or above the
 * API's maximum.
 */
export function percentInputToBps(value: string, maxBps: number): number | null {
  const trimmed = value.trim().replace(/%$/, "").trim();
  if (!/^\d+(\.\d{1,2})?$/.test(trimmed)) return null;
  const bps = Math.round(Number(trimmed) * 100);
  if (!Number.isFinite(bps) || bps < 0 || bps > maxBps) return null;
  return bps;
}
