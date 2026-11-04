import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

// Row 17 of the hardcoded-values sweep: the platform used two product names
// ("Academy Manager" and "CourtMastr"). Product name is CourtMastr
// everywhere now; this pins the source files that used to say otherwise.
const readFrontendFile = (relativePath) =>
  readFileSync(new URL(`../${relativePath}`, import.meta.url), "utf8");

test("admin shell sub-label reads the shared brand.productName, not a literal", () => {
  const layout = readFrontendFile("app/(admin)/layout.tsx");
  assert.doesNotMatch(layout, />\s*Academy Manager\s*</);
});

test("manifest name/short_name are CourtMastr", () => {
  const manifest = JSON.parse(readFrontendFile("public/manifest.webmanifest"));
  assert.equal(manifest.name, "CourtMastr");
  assert.equal(manifest.short_name, "CourtMastr");
});

test("marketing landing page no longer names badminton in headline copy", () => {
  const landing = readFrontendFile("components/marketing/PlatformLandingPage.tsx");
  assert.doesNotMatch(landing, /badminton/i);
});

test("login/register hero is not hotlinked from a third-party build host", () => {
  for (const page of ["app/(marketing)/login/page.tsx", "app/(marketing)/register/page.tsx"]) {
    const src = readFrontendFile(page);
    assert.doesNotMatch(src, /emergentagent\.com/);
  }
});
