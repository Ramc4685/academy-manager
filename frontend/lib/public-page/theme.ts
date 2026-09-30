/**
 * Public page themes (Settings overhaul Phase 6): pure and deterministic, so
 * the contrast guarantees are unit tested in `theme.test.ts`.
 *
 * Three presets, no free colour picking:
 * - `floodlit`: today's look. Its CSS output is exactly what the page always
 *   had (`--brand-fill` / `--brand-on`, both computed by the backend).
 * - `daylight`: a light page whatever the visitor's colour scheme, with the
 *   academy colour as accent.
 * - `showcase`: Floodlit with a full-bleed hero photo under a dark scrim; with
 *   no photo it is Floodlit.
 *
 * Every theme adjusts the academy colour so text is always readable: text on
 * a brand-coloured surface, and brand-coloured text on the page, both clear
 * WCAG AA 4.5:1.
 */

import { safeHexColor, safeHttpsUrl } from "./format";

export type PublicPageTheme = "floodlit" | "daylight" | "showcase";

export const PUBLIC_PAGE_THEMES: readonly PublicPageTheme[] = ["floodlit", "daylight", "showcase"];

export const THEME_LABEL: Record<PublicPageTheme, string> = {
  floodlit: "Floodlit",
  daylight: "Daylight",
  showcase: "Showcase",
};

export const THEME_HINT: Record<PublicPageTheme, string> = {
  floodlit: "Dark header and hero. Today's look.",
  daylight: "Light and airy, with your colour as the accent.",
  showcase: "A full-width photo at the top of the page.",
};

export const AA_TEXT = 4.5;

const WHITE = "#ffffff";
const NEAR_BLACK = "#0a0f1c";
const FALLBACK_FILL = "#0f172a";

export function parseTheme(value: unknown): PublicPageTheme {
  return PUBLIC_PAGE_THEMES.includes(value as PublicPageTheme)
    ? (value as PublicPageTheme)
    : "floodlit";
}

// ---------- colour maths ----------

type Rgb = [number, number, number];

function expandHex(hex: string): string {
  const h = hex.trim().replace(/^#/, "").toLowerCase();
  return h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
}

function toRgb(hex: string): Rgb {
  const h = expandHex(hex);
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ];
}

function toHex([r, g, b]: Rgb): string {
  const part = (n: number) => Math.max(0, Math.min(255, Math.round(n))).toString(16).padStart(2, "0");
  return `#${part(r)}${part(g)}${part(b)}`;
}

/** WCAG relative luminance of a hex colour. */
export function luminance(hex: string): number {
  const channel = (v: number) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  const [r, g, b] = toRgb(hex);
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

/** WCAG contrast ratio between two hex colours (1 to 21). */
export function contrastRatio(a: string, b: string): number {
  const la = luminance(a);
  const lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

function mix(hex: string, target: Rgb, amount: number): string {
  const from = toRgb(hex);
  return toHex(from.map((v, i) => v + (target[i] - v) * amount) as Rgb);
}

/**
 * The colour nearest to `fg` (same hue, darkened or lightened) that clears
 * `min` contrast on `bg`. Returns `fg` itself when it already does.
 */
export function ensureContrast(fg: string, bg: string, min: number = AA_TEXT): string {
  if (contrastRatio(fg, bg) >= min) return toHex(toRgb(fg));
  // Move away from the background: darken on a light one, lighten on a dark one.
  const target: Rgb = luminance(bg) > 0.4 ? [0, 0, 0] : [255, 255, 255];
  for (let step = 1; step <= 40; step += 1) {
    const candidate = mix(fg, target, step / 40);
    if (contrastRatio(candidate, bg) >= min) return candidate;
  }
  return toHex(target);
}

export interface ReadablePair {
  fill: string;
  on: string;
}

/**
 * A fill and the text colour drawn on it, guaranteed >= 4.5:1. Pale fills get
 * near-black text, dark fills white. A mid tone where neither reaches 4.5:1 is
 * darkened until white does.
 */
export function readablePair(fill: string, preferredOn?: string): ReadablePair {
  const base = toHex(toRgb(fill));
  if (preferredOn && contrastRatio(base, preferredOn) >= AA_TEXT) {
    return { fill: base, on: toHex(toRgb(preferredOn)) };
  }
  const white = contrastRatio(base, WHITE);
  const dark = contrastRatio(base, NEAR_BLACK);
  if (white >= AA_TEXT || dark >= AA_TEXT) {
    return { fill: base, on: white >= dark ? WHITE : NEAR_BLACK };
  }
  return { fill: ensureContrast(base, WHITE), on: WHITE };
}

// ---------- theme output ----------

/** Alpha of the dark layer over a Showcase hero photo. */
export const SHOWCASE_SCRIM_ALPHA = 0.68;

const DAYLIGHT_TOKENS: Record<string, string> = {
  "--paper": "#f8fafc",
  "--surface": "#ffffff",
  "--line": "#e2e8f0",
  "--ink": "#0f172a",
  "--muted": "#475569",
  "--focus": "#2563eb",
  "--focus-night": "#2563eb",
  // The header, hero and footer are "night" surfaces on Floodlit; on Daylight
  // they are a soft light tint with dark text.
  "--night": "#f1f5f9",
  "--night-line": "#e2e8f0",
  "--on-night": "#0f172a",
  "--on-night-2": "#334155",
  "--on-night-3": "#475569",
  "--ok-bg": "#ecfdf5",
  "--ok-fg": "#065f46",
  "--few-bg": "#fffbeb",
  "--few-fg": "#92400e",
  "--queue-bg": "#fefce8",
  "--queue-fg": "#854d0e",
  "--err": "#b91c1c",
  "--field-line": "#64748b",
};

/** Text on the Showcase photo hero: near-white, checked against the scrim. */
const SHOWCASE_TEXT: Record<string, string> = {
  "--on-night-2": "#f1f5f9",
  "--on-night-3": "#e2e8f0",
};

export interface PageThemeInput {
  theme: PublicPageTheme | string | null | undefined;
  /** The academy's own colour (validated hex) or null. */
  brandColor?: string | null;
  /** Backend-computed button fill and text pair (today's page). */
  brandFill: string;
  brandOn: string;
  logoUrl?: string | null;
  heroPhotoUrl?: string | null;
}

export interface PageTheme {
  /** The look actually drawn: Showcase without a usable photo is Floodlit. */
  theme: PublicPageTheme;
  /** Inline CSS custom properties for the page root. */
  vars: Record<string, string>;
  /** Https photo for the Showcase hero, else null. */
  heroPhoto: string | null;
  /** Https logo, else null (the page shows a monogram). */
  logo: string | null;
}

/** Floodlit's output, byte for byte what the page always set. */
function floodlitVars(input: PageThemeInput): Record<string, string> {
  return {
    "--brand-fill": safeHexColor(input.brandFill, FALLBACK_FILL),
    "--brand-on": safeHexColor(input.brandOn, WHITE),
  };
}

export function buildPageTheme(input: PageThemeInput): PageTheme {
  const requested = parseTheme(input.theme);
  const logo = safeHttpsUrl(input.logoUrl);
  const photo = requested === "showcase" ? safeHttpsUrl(input.heroPhotoUrl) : null;
  const theme: PublicPageTheme = requested === "showcase" && !photo ? "floodlit" : requested;

  if (theme === "floodlit") {
    return { theme, vars: floodlitVars(input), heroPhoto: null, logo };
  }

  const fillSource = safeHexColor(input.brandFill, FALLBACK_FILL);
  const pair = readablePair(fillSource, safeHexColor(input.brandOn, WHITE));

  if (theme === "showcase") {
    return {
      theme,
      vars: { "--brand-fill": pair.fill, "--brand-on": pair.on, ...SHOWCASE_TEXT },
      heroPhoto: photo,
      logo,
    };
  }

  // Daylight: brand-coloured TEXT must also clear 4.5:1 on the palest and
  // darkest light surface it can sit on.
  const brand = safeHexColor(input.brandColor, fillSource);
  const accent = ensureContrast(
    ensureContrast(brand, DAYLIGHT_TOKENS["--night"]),
    DAYLIGHT_TOKENS["--paper"],
  );
  return {
    theme,
    vars: {
      ...DAYLIGHT_TOKENS,
      "--brand-fill": pair.fill,
      "--brand-on": pair.on,
      "--brand-accent": accent,
    },
    heroPhoto: null,
    logo,
  };
}

/** Worst-case colour of a pure white photo pixel under the scrim. */
export function scrimmedWhite(): string {
  return mix(WHITE, toRgb(NEAR_BLACK), SHOWCASE_SCRIM_ALPHA);
}

/** The academy's own colour is missing: the product's cobalt, like the page. */
const FALLBACK_BRAND = "#2563eb";

export interface ThemePreview {
  /** Page background. */
  page: string;
  /** Header and hero band. */
  band: string;
  /** Text on the band. */
  text: string;
  /** Button fill and the text on it (always >= 4.5:1). */
  fill: string;
  on: string;
  /** Brand-coloured text on the page (Daylight only). */
  accent: string | null;
  /** Showcase draws a photo under a scrim in the band. */
  photo: boolean;
}

/** Swatch colours for the admin theme picker, from the academy's own colour. */
export function themePreview(theme: PublicPageTheme, brandColor: string | null): ThemePreview {
  const brand = safeHexColor(brandColor, FALLBACK_BRAND);
  const pair = readablePair(brand);
  const built = buildPageTheme({
    theme,
    brandColor: brand,
    brandFill: pair.fill,
    brandOn: pair.on,
    // Only to pick Showcase's colours; the picker draws a stand-in picture.
    heroPhotoUrl: theme === "showcase" ? "https://preview.invalid/hero.jpg" : null,
  });
  const light = built.theme === "daylight";
  return {
    page: light ? built.vars["--paper"] : "#f8fafc",
    band: light ? built.vars["--night"] : NEAR_BLACK,
    text: light ? built.vars["--on-night"] : WHITE,
    fill: built.vars["--brand-fill"],
    on: built.vars["--brand-on"],
    accent: light ? built.vars["--brand-accent"] : null,
    photo: built.theme === "showcase",
  };
}
