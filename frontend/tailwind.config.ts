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
      },
    },
  },
  plugins: [],
};

export default config;
