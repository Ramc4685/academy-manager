import { contrastRatio, type ReadablePair } from "@/lib/public-page/theme";

/** Belt-order defaults, mirrored from the backend's DEFAULT_LEVEL_COLORS. */
export const LEVEL_COLOR_PRESETS: { name: string; hex: string }[] = [
  { name: "Yellow", hex: "#FDE047" },
  { name: "Orange", hex: "#FB923C" },
  { name: "Green", hex: "#16A34A" },
  { name: "Blue", hex: "#2563EB" },
  { name: "Purple", hex: "#5B21B6" },
  { name: "Black", hex: "#111827" },
];

const FALLBACK = "#2563EB";

/**
 * The level's fill, unchanged, and black or white on it, matching the
 * backend's level_label_color so the web and the emails show the same pair.
 */
export function levelSwatch(color: string | null | undefined): ReadablePair {
  const fill = color && /^#[0-9a-f]{6}$/i.test(color) ? color : FALLBACK;
  const on = contrastRatio(fill, "#000000") >= contrastRatio(fill, "#ffffff") ? "#000000" : "#ffffff";
  return { fill, on };
}

/** "Orange" for a preset colour, else null. */
export function levelColorName(color: string | null | undefined): string | null {
  return (
    LEVEL_COLOR_PRESETS.find((p) => p.hex.toLowerCase() === color?.toLowerCase())?.name ?? null
  );
}
