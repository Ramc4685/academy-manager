/**
 * WCAG 2.1 relative-luminance / contrast-ratio math.
 *
 * Used by the a11y guard tests so "this token pair passes AA" is an
 * executable claim rather than a comment. Dependency-free (.mjs) so it runs
 * under `pnpm test:node` without a bundler.
 *
 * Reference: WCAG 2.1 SC 1.4.3 — normal text needs >= 4.5:1; large text
 * (>= 18.66px bold or >= 24px) and non-text UI need >= 3:1.
 */

export const AA_TEXT = 4.5;
export const AA_LARGE_TEXT = 3;

/** Parse `#rgb` / `#rrggbb` into 0-255 channels. */
export function parseHex(hex) {
  const raw = String(hex).trim().replace(/^#/, "");
  const full =
    raw.length === 3
      ? raw
          .split("")
          .map((c) => c + c)
          .join("")
      : raw;
  if (!/^[0-9a-fA-F]{6}$/.test(full)) {
    throw new Error(`not a hex color: ${hex}`);
  }
  return [
    Number.parseInt(full.slice(0, 2), 16),
    Number.parseInt(full.slice(2, 4), 16),
    Number.parseInt(full.slice(4, 6), 16),
  ];
}

/** WCAG relative luminance of an sRGB hex color. */
export function relativeLuminance(hex) {
  const [r, g, b] = parseHex(hex).map((channel) => {
    const s = channel / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** Contrast ratio between two hex colors, 1..21, order-independent. */
export function contrastRatio(a, b) {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  const lighter = Math.max(la, lb);
  const darker = Math.min(la, lb);
  return (lighter + 0.05) / (darker + 0.05);
}

/** True when the pair clears the AA threshold for normal-size text. */
export function meetsAaText(a, b) {
  return contrastRatio(a, b) >= AA_TEXT;
}
