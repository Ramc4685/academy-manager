import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * S05: one timestamp rule. A bare `toLocaleString()` / `toLocaleDateString()`
 * / `toLocaleTimeString()` renders in the viewer's device zone, which is how
 * the audit log, class announcements and the inbox showed UTC or the laptop's
 * zone instead of the academy's. Instants go through `formatInAcademyZone` /
 * `formatAcademyStamp` (lib/format/academy-time), calendar dates through
 * `formatPlainDate`, counts through `formatCount`. Only lib/format may call
 * the raw APIs.
 */

const FRONTEND = path.resolve(__dirname, "..");
const ALLOWED_DIR = path.join(FRONTEND, "lib", "format") + path.sep;
const RAW_LOCALE = /\.toLocale(?:Date|Time)?String\s*\(/;

function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...sourceFiles(full));
    else if (/\.(ts|tsx)$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name)) out.push(full);
  }
  return out;
}

describe("no raw toLocale* outside lib/format (S05)", () => {
  const files = ["app", "components", "lib"]
    .flatMap((dir) => sourceFiles(path.join(FRONTEND, dir)))
    .filter((file) => !file.startsWith(ALLOWED_DIR));

  it("scans a non-trivial number of files", () => {
    expect(files.length).toBeGreaterThan(300);
  });

  it("finds none", () => {
    const offenders = files.flatMap((file) =>
      readFileSync(file, "utf8")
        .split("\n")
        .map((line, i) => ({ line, at: `${path.relative(FRONTEND, file)}:${i + 1}` }))
        .filter(({ line }) => RAW_LOCALE.test(line))
        .map(({ at, line }) => `${at}  ${line.trim()}`),
    );
    expect(offenders).toEqual([]);
  });
});
