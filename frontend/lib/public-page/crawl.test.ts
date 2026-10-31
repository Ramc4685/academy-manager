import { describe, expect, it } from "vitest";

import fixtures from "@/e2e/fixtures/public-academy-pages.json";

import { robotsTxt, sitemapUrls, sitemapXml } from "./crawl";
import { ogCardContent } from "./og-card";
import type { PublicAcademyNotPublished, PublicAcademyPage } from "./types";

const ORIGIN = "https://riverside-academy.courtmastr.com";
const published = fixtures.published as PublicAcademyPage;

describe("robots.txt", () => {
  it("allows the page, keeps the app private and points at the host's sitemap", () => {
    const body = robotsTxt({ kind: "published", page: published }, ORIGIN);
    expect(body).toContain("Allow: /\n");
    expect(body).toContain("Disallow: /admin");
    expect(body).toContain("Disallow: /api/");
    expect(body).toContain(`Sitemap: ${ORIGIN}/sitemap.xml`);
  });

  it("offers no sitemap for a host no academy serves", () => {
    expect(robotsTxt({ kind: "unknown_host" }, ORIGIN)).not.toContain("Sitemap:");
  });
});

describe("sitemap.xml", () => {
  it("lists the root only when the page is indexable", () => {
    expect(sitemapUrls({ kind: "published", page: published }, ORIGIN)).toEqual([`${ORIGIN}/`]);
    expect(
      sitemapUrls({ kind: "published", page: fixtures.empty as PublicAcademyPage }, ORIGIN),
    ).toEqual([]);
    expect(
      sitemapUrls(
        { kind: "not_published", page: fixtures.not_published as PublicAcademyNotPublished },
        ORIGIN,
      ),
    ).toEqual([]);
    expect(sitemapUrls({ kind: "platform" }, "https://academy.courtmastr.com")).toEqual([
      "https://academy.courtmastr.com/",
    ]);
  });

  it("renders valid, escaped XML", () => {
    const xml = sitemapXml(["https://a.example/?x=1&y=2"]);
    expect(xml.startsWith('<?xml version="1.0" encoding="UTF-8"?>')).toBe(true);
    expect(xml).toContain("<loc>https://a.example/?x=1&amp;y=2</loc>");
    expect(sitemapXml([])).toContain("<urlset");
  });
});

describe("og card content", () => {
  it("uses the academy name, age span and address with the backend brand fill", () => {
    expect(ogCardContent({ kind: "published", page: published })).toEqual({
      title: "Riverside Shuttle Club",
      subtitle: "Ages 6 and up · 214 Millbrook Road, Riverside",
      lane: "#0f766e",
    });
  });

  it("never shows a coach or class detail", () => {
    const text = JSON.stringify(ogCardContent({ kind: "published", page: published }));
    expect(text).not.toContain("Coach");
    expect(text).not.toContain("$");
  });
});
