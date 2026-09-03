import { defineConfig } from "vitest/config";
import path from "path";

export default defineConfig({
  test: {
    environment: "node",
    globals: false,
    include: ["**/*.test.{ts,tsx}"],
    // Playwright specs live under e2e/ and must not be collected by vitest.
    exclude: ["e2e/**", "node_modules/**", ".next/**", ".open-next/**"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
});
