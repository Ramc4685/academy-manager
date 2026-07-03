import assert from "node:assert/strict";
import { test } from "node:test";

import {
  academyTimeZoneLabel,
  formatAcademyDate,
  formatAcademyDateTime,
  formatAcademyTimeRange,
  parseAcademyInstant,
  resolveAcademyTimeZone,
} from "./academy-time.ts";

// 2026-07-02 23:00 UTC == 6:00 PM CDT (America/Chicago, DST).
const START = "2026-07-02T23:00:00Z";
const END = "2026-07-02T23:45:00Z";

test("formats occurrence range in the academy timezone, not the runtime timezone", () => {
  const out = formatAcademyTimeRange(START, END, "America/Chicago");
  assert.equal(out, "Thu, Jul 2 · 6:00 PM – 6:45 PM CDT");
});

test("formats a single timestamp in the academy timezone with tz label", () => {
  const out = formatAcademyDateTime(START, "America/Chicago");
  assert.equal(out, "Thu, Jul 2 · 6:00 PM CDT");
});

test("date-only formatting uses the academy timezone (no off-by-one-day)", () => {
  // 23:00 UTC on Jul 2 is already Jul 3 in Kolkata, still Jul 2 in Chicago.
  assert.equal(formatAcademyDate(START, "America/Chicago"), "Thu, Jul 2");
  assert.equal(formatAcademyDate(START, "Asia/Kolkata"), "Fri, Jul 3");
});

test("always includes an explicit timezone label", () => {
  for (const tz of ["America/Chicago", "America/New_York", "UTC"]) {
    const out = formatAcademyDateTime(START, tz);
    const label = academyTimeZoneLabel(parseAcademyInstant(START), tz);
    assert.ok(label.length > 0, `expected a label for ${tz}`);
    assert.ok(out.endsWith(` ${label}`), `expected "${out}" to end with label "${label}"`);
  }
});

test("falls back to runtime timezone WITH label when academy tz is missing", () => {
  for (const missing of [null, undefined, "", "   "]) {
    const resolved = resolveAcademyTimeZone(missing);
    assert.equal(resolved.usedFallback, true);
    assert.equal(
      resolved.timeZone,
      Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
    );
    const out = formatAcademyDateTime(START, missing);
    const label = academyTimeZoneLabel(parseAcademyInstant(START), resolved.timeZone);
    assert.ok(out.endsWith(` ${label}`), `fallback output "${out}" must carry tz label`);
  }
});

test("falls back WITH label when academy tz is invalid", () => {
  const resolved = resolveAcademyTimeZone("Not/AZone");
  assert.equal(resolved.usedFallback, true);
  const out = formatAcademyTimeRange(START, END, "Not/AZone");
  const label = academyTimeZoneLabel(parseAcademyInstant(START), resolved.timeZone);
  assert.ok(out.endsWith(` ${label}`), `fallback output "${out}" must carry tz label`);
});

test("valid academy tz is not treated as fallback", () => {
  const resolved = resolveAcademyTimeZone("America/Chicago");
  assert.deepEqual(resolved, { timeZone: "America/Chicago", usedFallback: false });
});

test("naive timestamps are treated as UTC", () => {
  assert.equal(
    formatAcademyDateTime("2026-07-02T23:00:00", "America/Chicago"),
    "Thu, Jul 2 · 6:00 PM CDT",
  );
});

test("winter dates render the standard-time label (CST)", () => {
  const out = formatAcademyDateTime("2026-01-15T00:00:00Z", "America/Chicago");
  assert.ok(out.endsWith(" CST"), `expected CST label, got "${out}"`);
});

test("invalid input returns empty string", () => {
  assert.equal(formatAcademyDateTime("garbage", "America/Chicago"), "");
  assert.equal(formatAcademyTimeRange("garbage", END, "America/Chicago"), "");
  assert.equal(formatAcademyDate("garbage", "America/Chicago"), "");
});

test("range with invalid end still renders start", () => {
  const out = formatAcademyTimeRange(START, "garbage", "America/Chicago");
  assert.equal(out, "Thu, Jul 2 · 6:00 PM CDT");
});
