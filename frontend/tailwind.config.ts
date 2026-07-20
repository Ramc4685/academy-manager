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
