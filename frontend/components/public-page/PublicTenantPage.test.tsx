import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import fixtures from "@/e2e/fixtures/public-academy-pages.json";
import type { PublicAcademyPage } from "@/lib/public-page/types";

import { PublicTenantPage } from "./PublicTenantPage";

const riverside = fixtures.published as PublicAcademyPage;
const lakeside = fixtures.lakeside as PublicAcademyPage;

function render(page: PublicAcademyPage): string {
  return renderToStaticMarkup(
    <PublicTenantPage page={page} jsonLd={{}} trialForm={<div data-testid="trial-stub" />} />,
  );
}

describe("PublicTenantPage without content (today's page)", () => {
  const html = render(riverside);

  it("is Floodlit with today's two brand properties and nothing else", () => {
    expect(html).toContain('data-theme="floodlit"');
    expect(html).toContain("--brand-fill:#0f766e;--brand-on:#ffffff");
    expect(html).not.toContain("--brand-accent");
  });

  it("renders no content sections and keeps the built-in FAQ", () => {
    for (const id of ["public-about", "public-gallery", "public-coach-card", "public-hero-photo"]) {
      expect(html).not.toContain(id);
    }
    expect(html).toContain("What happens at a free trial?");
  });

  it("keeps today's seat chips", () => {
    expect(html).toContain("Only 2 seats left");
    expect(html).toContain("Full, join waitlist");
  });

  it("shows the support email as the only contact", () => {
    expect(html).toContain("mailto:hello@riverside.example.test");
    expect(html).not.toContain("tel:");
  });
});

describe("PublicTenantPage with content on Daylight", () => {
  const html = render(lakeside);

  it("draws the academy's own content", () => {
    expect(html).toContain('data-theme="daylight"');
    expect(html).toContain("Lakeside opened in 2019");
    expect(html).toContain("Small groups");
    expect(html).toContain("Former state champion");
    expect(html).toContain("Do you loan rackets?");
    expect(html).not.toContain("What happens at a free trial?");
  });

  it("gallery photos are lazy, captioned and alt-texted", () => {
    expect(html).toContain('alt="Juniors warming up"');
    expect(html).toContain("<figcaption>Juniors warming up</figcaption>");
    expect((html.match(/loading="lazy"/g) ?? []).length).toBeGreaterThanOrEqual(2);
  });

  it("applies the academy's seat threshold of 5", () => {
    expect(html).toContain("Only 4 seats left");
  });

  it("uses only this academy's support email", () => {
    expect(html).toContain("mailto:front-desk@lakeside.example.test");
    expect(html).not.toContain("riverside");
  });
});

describe("PublicTenantPage on Showcase", () => {
  it("draws the hero photo and skips the court drawing", () => {
    const html = render({
      ...riverside,
      hero_photo_url: "https://firebasestorage.googleapis.com/v0/b/x/o/hero.jpg",
      page: { ...riverside.page, theme: "showcase" },
    });
    expect(html).toContain('data-theme="showcase"');
    expect(html).toContain('src="https://firebasestorage.googleapis.com/v0/b/x/o/hero.jpg"');
    expect(html).not.toMatch(/class="_court_/);
  });

  it("falls back to Floodlit and its court drawing with no photo", () => {
    const html = render({ ...riverside, page: { ...riverside.page, theme: "showcase" } });
    expect(html).toContain('data-theme="floodlit"');
    expect(html).not.toContain("public-hero-photo");
    expect(html).toMatch(/class="_court_/);
  });

  it("threshold 0 hides the few-seats chip", () => {
    const html = render({ ...riverside, page: { ...riverside.page, seats_left_threshold: 0 } });
    expect(html).not.toContain("seats left");
  });
});
