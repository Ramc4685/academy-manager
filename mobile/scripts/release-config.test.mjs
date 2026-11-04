// Release-build guards for the shell: `pnpm test` (macOS only: PlistBuddy, plutil).
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { copyFileSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

const here = new URL(".", import.meta.url).pathname;
const mobile = join(here, "..");
const sourcePlist = join(mobile, "ios/App/App/Info.plist");

const boundDomains = (plist) =>
  JSON.parse(execFileSync("plutil", ["-extract", "WKAppBoundDomains", "json", "-o", "-", plist]));

test("strip-dev-bound-domains drops localhost and keeps every real host", () => {
  const plist = join(mkdtempSync(join(tmpdir(), "bound-")), "Info.plist");
  copyFileSync(sourcePlist, plist);
  // Built products are binary plists; the script must handle that form.
  execFileSync("plutil", ["-convert", "binary1", plist]);
  const before = boundDomains(plist);
  assert.ok(before.includes("localhost"), "dev Info.plist should still list localhost");

  execFileSync("sh", [join(here, "strip-dev-bound-domains.sh"), plist]);

  assert.deepEqual(
    boundDomains(plist),
    before.filter((host) => host !== "localhost"),
  );
});

test("the Xcode project runs the strip script for Release only", () => {
  const pbxproj = readFileSync(join(mobile, "ios/App/App.xcodeproj/project.pbxproj"), "utf8");
  assert.match(pbxproj, /\/\* Strip dev App-Bound Domains \*\/,\n\t\t\t\);/, "phase must be last");
  assert.match(pbxproj, /\[ \\"\$CONFIGURATION\\" = Release \].*strip-dev-bound-domains\.sh/);
});

test("sync:release forces the release guard and an https server", () => {
  const { scripts } = JSON.parse(readFileSync(join(mobile, "package.json"), "utf8"));
  assert.match(scripts["sync:release"], /MOBILE_RELEASE=1/);
  assert.match(scripts["sync:release"], /MOBILE_SERVER_URL=\$\{MOBILE_SERVER_URL:-https:\/\//);
});
