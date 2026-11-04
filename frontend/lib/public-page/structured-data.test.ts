import { describe, expect, it } from "vitest";

import fixtures from "@/e2e/fixtures/public-academy-pages.json";

import { buildPublicPageJsonLd, serializeJsonLd } from "./structured-data";
import type { PublicAcademyPage } from "./types";

const published = fixtures.published as PublicAcademyPage;
const ORIGIN = "https://riverside-academy.courtmastr.com";

describe("buildPublicPageJsonLd", () => {
  it("describes the academy as a SportsActivityLocation", () => {
    const [location] = buildPublicPageJsonLd(published, ORIGIN);
    expect(location).toMatchObject({
      "@type": "SportsActivityLocation",
      name: "Riverside Shuttle Club",
      url: `${ORIGIN}/`,
      address: "214 Millbrook Road, Riverside",
    });
  });

  it("lists every class as a Course with its weekly schedule and offer", () => {
    const graph = buildPublicPageJsonLd(published, ORIGIN);
    const list = graph.find((node) => node["@type"] === "ItemList") as {
      itemListElement: Array<{ item: Record<string, unknown> }>;
    };
    expect(list.itemListElement).toHaveLength(4);
    const first = list.itemListElement[0].item as {
      hasCourseInstance: { courseSchedule: Record<string, unknown> };
      offers: Record<string, unknown>;
    };
    expect(first.hasCourseInstance.courseSchedule).toMatchObject({
      byDay: ["https://schema.org/Monday", "https://schema.org/Wednesday"],
      startTime: "16:30",
      endTime: "17:30",
      scheduleTimezone: "America/Chicago",
    });
    expect(first.offers).toEqual({
      "@type": "Offer",
      price: "120.00",
      priceCurrency: "USD",
      category: "month",
    });
  });

  it("leaves offers out when prices are hidden", () => {
    const hidden = { ...published, page: { ...published.page, show_price: false } };
    expect(JSON.stringify(buildPublicPageJsonLd(hidden, ORIGIN))).not.toContain("Offer");
  });

  it("carries no personal data or availability", () => {
    const text = JSON.stringify(buildPublicPageJsonLd(published, ORIGIN));
    expect(text).not.toContain("Coach");
    expect(text).not.toContain("coach_name");
    expect(text).not.toContain("@riverside");
    const courses = JSON.stringify(
      buildPublicPageJsonLd(published, ORIGIN).find((node) => node["@type"] === "ItemList"),
    );
    expect(courses).not.toMatch(/waitlist|seats|spots left|availability/i);
  });

  it("adds an FAQPage", () => {
    const graph = buildPublicPageJsonLd(published, ORIGIN);
    expect(graph.some((node) => node["@type"] === "FAQPage")).toBe(true);
  });
});

describe("serializeJsonLd", () => {
  it("cannot be closed by tenant text", () => {
    const out = serializeJsonLd({ name: "</script><script>alert(1)</script> & co" });
    expect(out).not.toContain("<");
    expect(out).not.toContain(">");
    expect(JSON.parse(out)).toEqual({ name: "</script><script>alert(1)</script> & co" });
  });
});
