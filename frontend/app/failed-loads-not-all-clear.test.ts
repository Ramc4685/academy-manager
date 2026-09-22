import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Issue #837: a failed load must not render as zero / all clear, and every
 * error box must offer a retry.
 *
 * Each of these screens feeds its stat tiles through a normalizer that
 * zero-fills an absent payload (`normalizeCollections(undefined)`,
 * `normalizeMonthClose(undefined)`, `?? {}`, `?? []`). A 500 therefore used to
 * paint "$0.00 owed · 0 needs action · No failed autopay" — a screen that says
 * the money is in. The pages need auth and a live query client to render, so
 * this guards the source text the way `shell-safe-area.test.ts` does.
 */

const APP = path.resolve(__dirname);

function source(rel: string): string {
  return readFileSync(path.join(APP, rel), "utf8");
}

/**
 * Every surface named in #837. `tileState` is the identifier its stat tiles
 * must consult before printing a number; the two surfaces without tiles (the
 * families table's summary already dashed out, parent Home has none) only owe
 * the retry.
 */
const SURFACES: Array<{ name: string; file: string; tileState: string }> = [
  { name: "admin dashboard", file: "(admin)/admin/page.tsx", tileState: "collectionsQuery" },
  {
    name: "admin payments collections",
    file: "(admin)/admin/payments/buckets/CollectionsTab.tsx",
    tileState: "query",
  },
  { name: "admin students", file: "(admin)/admin/students/page.tsx", tileState: "state" },
  { name: "admin families", file: "(admin)/admin/families/page.tsx", tileState: "" },
  { name: "admin reports", file: "(admin)/admin/reports/page.tsx", tileState: "monthCloseQuery" },
  { name: "parent home", file: "(parent)/parent/dashboard/page.tsx", tileState: "" },
];

describe("failed loads own the failure (#837)", () => {
  it.each(SURFACES)("$name shows an error notice with a working retry", ({ file }) => {
    const src = source(file);
    expect(src).toContain("ErrorNotice");
    // The retry must re-issue the request, not just reload copy.
    expect(src).toMatch(/onRetry=\{\(\) => void [A-Za-z.]*refetch\(\)\}/);
  });

  it.each(SURFACES.filter((surface) => surface.tileState))(
    "$name gates its stat tiles on the query state, not just isLoading",
    ({ file, tileState }) => {
      const src = source(file);
      expect(src).toContain(`statText(${tileState},`);
      // The old shape — a ternary on isLoading alone — left the error case
      // printing the normalizer's zero.
      expect(src).not.toMatch(
        new RegExp(`${tileState}\\.isLoading\\s*\\n?\\s*\\?\\s*"—"\\s*:\\s*(formatCents|String)`),
      );
    },
  );
});

describe("admin dashboard money tiles (#837)", () => {
  const src = source("(admin)/admin/page.tsx");

  it("reads owed / needs action through statText so a 500 cannot say $0.00", () => {
    expect(src).toContain("statText(collectionsQuery, () => formatCents(collectionsTotals.owed_cents))");
    expect(src).toContain(
      "statText(collectionsQuery, () => String(collectionsTotals.needs_action_count))",
    );
  });

  it("does not claim 'No payments received yet' when the feed failed", () => {
    expect(src).toContain("paymentFeedQuery.isError");
  });
});

describe("payments collections buckets (#837)", () => {
  const src = source("(admin)/admin/payments/buckets/CollectionsTab.tsx");

  it("withholds the six empty buckets instead of asserting them on error", () => {
    // `query.isError ? <ErrorNotice …/> : view.buckets.map(…)` — the bucket
    // list is the "all clear" claim, so it must sit on the success branch.
    expect(src).toMatch(/query\.isError \? \(\s*<ErrorNotice/);
    expect(src).toMatch(/\) : \(\s*view\.buckets\.map\(/);
  });
});

describe("admin students summary cards (#837)", () => {
  const src = source("(admin)/admin/students/page.tsx");

  it("dashes out the five counts until rows actually arrived", () => {
    expect(src).toContain("const stat = (value: () => number) => statText(state, () => String(value()));");
    // No card may print a bare count expression any more.
    expect(src).not.toMatch(/<BigNum size=\{32\}>\{counts\./);
    expect(src).not.toMatch(/<BigNum size=\{32\}>\{total\}/);
  });

  it("offers Clear filters on a filtered empty state", () => {
    expect(src).toContain("admin-students-clear-filters");
    expect(src).toContain("Clear filters");
  });
});

describe("reports analytics never render NaN (#837)", () => {
  const src = source("(admin)/admin/reports/page.tsx");

  it("routes every money figure through the finite-guarded formatter", () => {
    // formatCents survives only inside the guards at the bottom of the file.
    const rendered = src.slice(0, src.indexOf("function formatMoney"));
    expect(rendered).not.toContain("formatCents(");
    expect(src).toContain("function formatMoney(");
    expect(src).toContain("finiteText(");
  });

  it("guards counts and percentages too", () => {
    expect(src).toMatch(/function formatInteger\(value: number \| null \| undefined\)/);
    expect(src).toMatch(/function formatNullablePercent\(value: number \| null \| undefined\)/);
  });
});
