import { describe, expect, it } from "vitest";

import {
  AA_TEXT,
  buildPageTheme,
  contrastRatio,
  ensureContrast,
  parseTheme,
  readablePair,
  scrimmedWhite,
  themePreview,
} from "./theme";

const PALE = "#facc15";
const DARK = "#0a0f1c";
const MID = "#797979";
const BRANDS = [PALE, DARK, MID, "#0f766e", "#ef4444", "#22c55e", "#3b82f6", "#ffffff", "#000000"];

describe("contrast maths", () => {
  it("matches the WCAG reference values", () => {
    expect(contrastRatio("#000000", "#ffffff")).toBeCloseTo(21, 1);
    expect(contrastRatio("#777777", "#ffffff")).toBeCloseTo(4.48, 1);
  });

  it("ensureContrast keeps a colour that already passes", () => {
    expect(ensureContrast("#0f172a", "#ffffff")).toBe("#0f172a");
  });

  it("ensureContrast darkens a pale colour on a light background", () => {
    const fixed = ensureContrast(PALE, "#f8fafc");
    expect(contrastRatio(fixed, "#f8fafc")).toBeGreaterThanOrEqual(AA_TEXT);
  });

  it("ensureContrast lightens a dark colour on a dark background", () => {
    const fixed = ensureContrast("#1e293b", DARK);
    expect(contrastRatio(fixed, DARK)).toBeGreaterThanOrEqual(AA_TEXT);
  });
});

describe("readablePair", () => {
  it.each(BRANDS)("text on %s clears 4.5:1", (brand) => {
    const { fill, on } = readablePair(brand);
    expect(contrastRatio(fill, on)).toBeGreaterThanOrEqual(AA_TEXT);
  });

  it("gives a pale brand dark text and a dark brand white text", () => {
    expect(readablePair(PALE).on).toBe(DARK);
    expect(readablePair(DARK).on).toBe("#ffffff");
  });

  it("keeps a passing backend pair untouched", () => {
    expect(readablePair("#0f766e", "#ffffff")).toEqual({ fill: "#0f766e", on: "#ffffff" });
  });

  it("repairs a failing backend pair", () => {
    const { fill, on } = readablePair(PALE, "#ffffff");
    expect(contrastRatio(fill, on)).toBeGreaterThanOrEqual(AA_TEXT);
  });

  it("darkens a mid tone where neither white nor black reaches 4.5:1", () => {
    const { fill, on } = readablePair(MID);
    expect(on).toBe("#ffffff");
    expect(contrastRatio(fill, on)).toBeGreaterThanOrEqual(AA_TEXT);
  });
});

describe("buildPageTheme", () => {
  const base = { brandFill: "#0f766e", brandOn: "#ffffff", brandColor: "#0f766e" };

  it("Floodlit output is exactly today's two properties", () => {
    const theme = buildPageTheme({ ...base, theme: "floodlit" });
    expect(theme.vars).toEqual({ "--brand-fill": "#0f766e", "--brand-on": "#ffffff" });
    expect(theme.theme).toBe("floodlit");
  });

  it("an unknown or missing theme is Floodlit", () => {
    expect(parseTheme(undefined)).toBe("floodlit");
    expect(parseTheme("neon")).toBe("floodlit");
    expect(buildPageTheme({ ...base, theme: undefined }).vars).toEqual(
      buildPageTheme({ ...base, theme: "floodlit" }).vars,
    );
  });

  it("Floodlit ignores the hero photo", () => {
    expect(
      buildPageTheme({ ...base, theme: "floodlit", heroPhotoUrl: "https://x.test/a.jpg" }).heroPhoto,
    ).toBeNull();
  });

  it.each(BRANDS)("Daylight with brand %s: fill pair and accent text are readable", (brand) => {
    const pair = readablePair(brand);
    const theme = buildPageTheme({
      theme: "daylight",
      brandColor: brand,
      brandFill: pair.fill,
      brandOn: pair.on,
    });
    const v = theme.vars;
    expect(contrastRatio(v["--brand-fill"], v["--brand-on"])).toBeGreaterThanOrEqual(AA_TEXT);
    for (const surface of ["--paper", "--surface", "--night"]) {
      expect(contrastRatio(v["--brand-accent"], v[surface])).toBeGreaterThanOrEqual(AA_TEXT);
    }
    // Light page, whatever the visitor's colour scheme.
    expect(v["--paper"]).toBe("#f8fafc");
    for (const pairing of [
      ["--ink", "--paper"],
      ["--muted", "--paper"],
      ["--on-night", "--night"],
      ["--on-night-2", "--night"],
      ["--on-night-3", "--night"],
    ]) {
      expect(contrastRatio(v[pairing[0]], v[pairing[1]])).toBeGreaterThanOrEqual(AA_TEXT);
    }
  });

  it("Daylight darkens a pale brand for text but keeps a dark text pair on the button", () => {
    const theme = buildPageTheme({
      theme: "daylight",
      brandColor: PALE,
      brandFill: PALE,
      brandOn: DARK,
    });
    expect(theme.vars["--brand-fill"]).toBe(PALE);
    expect(theme.vars["--brand-on"]).toBe(DARK);
    expect(theme.vars["--brand-accent"]).not.toBe(PALE);
  });

  it("Showcase with a photo keeps text readable on the worst-case photo pixel", () => {
    const theme = buildPageTheme({
      ...base,
      theme: "showcase",
      heroPhotoUrl: "https://cdn.example.test/hero.jpg",
    });
    expect(theme.theme).toBe("showcase");
    expect(theme.heroPhoto).toBe("https://cdn.example.test/hero.jpg");
    const worst = scrimmedWhite();
    expect(contrastRatio("#ffffff", worst)).toBeGreaterThanOrEqual(AA_TEXT);
    expect(contrastRatio(theme.vars["--on-night-2"], worst)).toBeGreaterThanOrEqual(AA_TEXT);
    expect(contrastRatio(theme.vars["--on-night-3"], worst)).toBeGreaterThanOrEqual(AA_TEXT);
  });

  it("Showcase with no photo, or an unsafe one, is Floodlit", () => {
    const floodlit = buildPageTheme({ ...base, theme: "floodlit" });
    for (const heroPhotoUrl of [null, undefined, "", "http://x.test/a.jpg", "javascript:alert(1)"]) {
      const theme = buildPageTheme({ ...base, theme: "showcase", heroPhotoUrl });
      expect(theme.theme).toBe("floodlit");
      expect(theme.vars).toEqual(floodlit.vars);
      expect(theme.heroPhoto).toBeNull();
    }
  });

  it("only passes an https logo through", () => {
    expect(buildPageTheme({ ...base, theme: "daylight", logoUrl: "https://x.test/l.png" }).logo).toBe(
      "https://x.test/l.png",
    );
    expect(buildPageTheme({ ...base, theme: "daylight", logoUrl: "javascript:1" }).logo).toBeNull();
  });
});

describe("themePreview", () => {
  it.each(BRANDS)("every swatch for %s keeps its button text readable", (brand) => {
    for (const theme of ["floodlit", "daylight", "showcase"] as const) {
      const p = themePreview(theme, brand);
      expect(contrastRatio(p.fill, p.on)).toBeGreaterThanOrEqual(AA_TEXT);
      expect(contrastRatio(p.text, p.band)).toBeGreaterThanOrEqual(AA_TEXT);
      if (p.accent) expect(contrastRatio(p.accent, p.page)).toBeGreaterThanOrEqual(AA_TEXT);
    }
  });

  it("falls back to the product blue when the academy set no colour", () => {
    expect(themePreview("floodlit", null).fill).toBe("#2563eb");
  });

  it("Daylight is light and Showcase carries a photo stand-in", () => {
    expect(themePreview("daylight", PALE).band).toBe("#f1f5f9");
    expect(themePreview("showcase", PALE).photo).toBe(true);
    expect(themePreview("floodlit", PALE).photo).toBe(false);
  });
});
