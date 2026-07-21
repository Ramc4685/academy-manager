import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      // Touch-target minimums per WCAG 2.5.5 (44pt iOS / 48dp Android).
      // Use these utilities for any interactive element on coach/parent surfaces.
      minHeight: {
        touch: "44px",
        "touch-android": "48px",
      },
      minWidth: {
        touch: "44px",
        "touch-android": "48px",
      },
      fontFamily: {
        sans: ["var(--font-manrope)", "system-ui", "sans-serif"],
        body: ["var(--font-manrope)", "system-ui", "sans-serif"],
        display: ["var(--font-outfit)", "var(--font-manrope)", "system-ui", "sans-serif"],
        mono: ["var(--font-jetbrains-mono)", "ui-monospace", "monospace"],
      },
      colors: {
        // Rally design palette — cobalt + volt yellow + slate.
        // Single source of truth: globals.css derives --rally-* from these
        // via theme(); never hand-copy hex values elsewhere.
        rally: {
          ink: "#0f172a",
          paper: "#f8fafc",
          line: "#e2e8f0",
          muted: "#64748b",
          // AA on white (4.76:1) and paper (4.6:1); the old #94a3b8 was 2.9:1.
          subtle: "#64748b",
          // Decorative marks and text on night surfaces only (7.1:1 on night);
          // fails AA as text on light — use `subtle` there instead.
          "subtle-ink": "#94a3b8",
          // Dark admin-shell surfaces
          night: "#0a0f1c",
          "night-line": "#1e293b",
          "night-panel": "#101a2e",
          "night-card": "#0b1220",
          bright: "#cbd5e1",
          cobalt: {
            50: "#eff6ff",
            100: "#dbeafe",
            500: "#3b82f6",
            600: "#2563eb",
            700: "#1d4ed8",
            900: "#1e3a8a",
          },
          volt: {
            100: "#fef9c3",
            300: "#fde047",
            400: "#facc15",
            500: "#eab308",
            700: "#a16207",
          },
        },
        // Status hues for DS chips/buttons, frozen at the Tailwind v3 hex the
        // app shipped with — the v4 default palette moved to OKLCH and no
        // longer matches, so `bg-emerald-50` etc. would drift these surfaces.
        status: {
          green: { 50: "#ecfdf5", 500: "#10b981", 800: "#065f46" },
          amber: { 50: "#fffbeb", 500: "#f59e0b", 800: "#92400e" },
          red: { 50: "#fef2f2", 200: "#fecaca", 500: "#ef4444", 600: "#dc2626", 800: "#991b1b" },
          yellow: { 50: "#fefce8", 800: "#854d0e" },
          blue: { 400: "#60a5fa", 800: "#1e40af" },
          slate: { 100: "#f1f5f9", 600: "#475569", 700: "#334155" },
        },
      },
      letterSpacing: {
        chip: "0.08em",
        overline: "0.2em",
        lane: "0.18em",
      },
    },
  },
  plugins: [],
};

export default config;
