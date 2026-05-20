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
        // Rally design palette — cobalt + volt yellow + slate
        rally: {
          ink: "#0f172a",
          paper: "#f8fafc",
          line: "#e2e8f0",
          muted: "#64748b",
          subtle: "#94a3b8",
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
