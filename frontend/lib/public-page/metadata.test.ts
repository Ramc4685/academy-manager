import { describe, expect, it } from "vitest";

import fixtures from "@/e2e/fixtures/public-academy-pages.json";

import { buildPublicPageMetadata, publicPageBrand } from "./metadata";
import type { PublicAcademyNotPublished, PublicAcademyPage } from "./types";

const ORIGIN = "https://riverside-academy.courtmastr.com";
const published = fixtures.published as PublicAcademyPage;

describe("buildPublicPageMetadata", () => {
  it("builds per-tenant title, canonical, OG card and index for a published page", () => {
    const meta = buildPublicPageMetadata({ kind: "published", page: published }, ORIGIN);
    expect(meta?.title).toBe("Riverside Shuttle Club: classes and a free trial");
    expect(meta?.description).toContain("First class free.");
    expect((meta?.description as string).length).toBeLessThanOrEqual(155);
    expect(meta?.alternates?.canonical).toBe(`${ORIGIN}/`);
    expect(meta?.robots).toEqual({ index: true, follow: true });
    expect(JSON.stringify(meta?.openGraph)).toContain(`${ORIGIN}/og-card`);
  });

  it("noindexes the empty, unpublished and unavailable states", () => {
    const empty = fixtures.empty as PublicAcademyPage;
    expect(buildPublicPageMetadata({ kind: "published", page: empty }, ORIGIN)?.robots).toEqual({
      index: false,
      follow: false,
    });
    const notPublished = fixtures.not_published as PublicAcademyNotPublished;
    expect(
      buildPublicPageMetadata({ kind: "not_published", page: notPublished }, ORIGIN)?.robots,
    ).toEqual({ index: false, follow: false });
    expect(buildPublicPageMetadata({ kind: "unavailable" }, ORIGIN)?.robots).toEqual({
      index: false,
      follow: false,
    });
  });

  it("does not claim a free class while trials are closed", () => {
    const closed = fixtures.trials_closed as PublicAcademyPage;
    const meta = buildPublicPageMetadata({ kind: "published", page: closed }, ORIGIN);
    expect(meta?.title).toBe("Riverside Shuttle Club: classes and prices");
    expect(meta?.description).not.toContain("free");
  });

  it("leaves the product host's metadata alone", () => {
    expect(buildPublicPageMetadata({ kind: "platform" }, ORIGIN)).toBeNull();
  });
});

describe("publicPageBrand", () => {
  it("returns the academy's brand for a published page", () => {
    const brand = publicPageBrand({ kind: "published", page: published });
    expect(brand?.name).toBe("Riverside Shuttle Club");
  });

  it("returns the academy's brand for a not-published page", () => {
    const notPublished = fixtures.not_published as PublicAcademyNotPublished;
    const brand = publicPageBrand({ kind: "not_published", page: notPublished });
    expect(brand?.name).toBe(notPublished.academy.name);
  });

  it("returns null on the platform host — row 15's title falls back to brand.productName", () => {
    expect(publicPageBrand({ kind: "platform" })).toBeNull();
  });

  it("returns null for unknown_host and unavailable", () => {
    expect(publicPageBrand({ kind: "unknown_host" })).toBeNull();
    expect(publicPageBrand({ kind: "unavailable" })).toBeNull();
  });
});
