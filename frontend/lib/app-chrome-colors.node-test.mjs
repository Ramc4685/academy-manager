import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

// Guards the app-chrome half of DS6 (#451): the PWA manifest / viewport colors
// must come from the Rally palette, and the (shared) layout must not flash bare
// "Loading..." / "Redirecting..." text before `onAuthChange` resolves.
const readFrontendFile = (relativePath) =>
  readFileSync(new URL(`../${relativePath}`, import.meta.url), "utf8");

// Mirrors frontend/tailwind.config.ts → theme.extend.colors.rally.
const RALLY = {
  ink: "#0f172a",
  paper: "#f8fafc",
  night: "#0a0f1c",
};

test("Rally tokens the app chrome pins to still exist in the Tailwind theme", () => {
  const tailwindConfig = readFrontendFile("tailwind.config.ts");

  for (const [token, hex] of Object.entries(RALLY)) {
    assert.match(
      tailwindConfig,
      new RegExp(`${token}"?:\\s*"${hex}"`),
      `rally.${token} should be ${hex} in tailwind.config.ts`
    );
  }
});

test("PWA manifest background and theme colors are Rally palette tokens", () => {
  const manifest = JSON.parse(readFrontendFile("public/manifest.webmanifest"));
  const rallyHexes = new Set(Object.values(RALLY));

  assert.ok(
    rallyHexes.has(manifest.background_color),
    `manifest background_color ${manifest.background_color} is not a Rally token`
  );
  assert.ok(
    rallyHexes.has(manifest.theme_color),
    `manifest theme_color ${manifest.theme_color} is not a Rally token`
  );
});

test("root viewport themeColor matches the manifest theme_color", () => {
  const manifest = JSON.parse(readFrontendFile("public/manifest.webmanifest"));
  const rootLayout = readFrontendFile("app/layout.tsx");

  const themeColor = rootLayout.match(/themeColor:\s*"(#[0-9a-fA-F]{3,8})"/);
  assert.ok(themeColor, "app/layout.tsx should declare a viewport themeColor");
  assert.equal(
    themeColor[1],
    manifest.theme_color,
    "viewport themeColor must not contradict the manifest theme_color"
  );
});

test("shared layout holds a neutral skeleton instead of flashing status text", () => {
  const sharedLayout = readFrontendFile("app/(shared)/layout.tsx");

  assert.doesNotMatch(
    sharedLayout,
    />\s*Loading\.\.\.\s*</,
    "shared layout should not render literal 'Loading...' copy"
  );
  assert.doesNotMatch(
    sharedLayout,
    />\s*Redirecting\.\.\.\s*</,
    "shared layout should not render literal 'Redirecting...' copy"
  );
  assert.match(
    sharedLayout,
    /bg-rally-(paper|ink|night)/,
    "shared layout surfaces should use Rally palette tokens"
  );
  assert.doesNotMatch(
    sharedLayout,
    /text-neutral-500/,
    "text-neutral-500 is not a Rally token"
  );
});
