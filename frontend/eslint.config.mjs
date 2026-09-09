import nextVitals from "eslint-config-next/core-web-vitals";

const eslintConfig = [
  ...nextVitals,
  {
    rules: {
      "@next/next/no-img-element": "off",
      "react-hooks/set-state-in-effect": "off",
    },
  },
  {
    ignores: [
      "node_modules/**",
      ".next/**",
      // Cloudflare build output: generated bundles, not source. Only present
      // after `pnpm deploy:cloudflare`/`opennextjs-cloudflare build` locally;
      // CI lints before any deploy build, which is why this never surfaced there.
      ".open-next/**",
      "out/**",
      "build/**",
      "next-env.d.ts",
      "public/sw.js",
      "lib/api/generated/**",
      "e2e/**",
      "playwright-report/**",
      "test-results/**",
    ],
  },
];

export default eslintConfig;
