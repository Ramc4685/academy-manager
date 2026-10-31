import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { AdminPublicPageSettingsView, AdminUserList } from "@/lib/api/admin";
import { GALLERY_CONSENT_LABEL, GALLERY_MAX } from "@/lib/public-page/content-settings";
import { queryKeys } from "@/lib/query/keys";

import { PublicPageContentCard } from "./public-page-content-card";

const BASE: AdminPublicPageSettingsView = {
  published: true,
  show_price: true,
  show_availability: true,
  price_period_default: "month",
  trials_open: true,
  privacy_notice_url: null,
  public_url: null,
};

function render(
  settings: Partial<AdminPublicPageSettingsView> = {},
  coaches: AdminUserList["users"] = [],
): string {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(queryKeys.admin.publicPage(), { ...BASE, ...settings });
  client.setQueryData(queryKeys.admin.users("coaches"), { users: coaches });
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <PublicPageContentCard />
    </QueryClientProvider>,
  );
}

/** React renders a disabled control as ` disabled=""` (class names also say "disabled:"). */
const DISABLED = /\sdisabled=""/;

/** The opening tag of the first element carrying this test id. */
function tag(html: string, testId: string): string {
  const match = new RegExp(`<[^>]*data-testid="${testId}"[^>]*>`).exec(html);
  if (!match) throw new Error(`no element with data-testid=${testId}`);
  return match[0];
}

describe("PublicPageContentCard markup", () => {
  it("shows every section with today's defaults and the FAQ helper", () => {
    const html = render();
    expect(html).toContain("Photos &amp; details");
    expect(html).toContain("Hero photo");
    expect(html).toContain("About us");
    expect(html).toContain("Highlights");
    expect(html).toContain("Gallery");
    expect(html).toContain("Coaches shown");
    expect(html).toContain("Leave empty to use the standard questions.");
    expect(html).not.toContain("public-page-hero-preview");
    expect(html).toContain("0 / 1200");
  });

  it("gates the gallery upload behind the parents-agreed checkbox", () => {
    const html = render();
    expect(html).toContain(GALLERY_CONSENT_LABEL);
    expect(tag(html, "public-page-gallery-consent")).not.toMatch(/\schecked=""/);
    // Neither the button nor the file input can open the picker yet.
    expect(tag(html, "public-page-gallery-upload-button")).toMatch(DISABLED);
    expect(tag(html, "public-page-gallery-upload-file")).toMatch(DISABLED);
    expect(html).toContain("Tick the box above first.");
  });

  it("does not gate the hero photo upload on consent", () => {
    const html = render();
    expect(tag(html, "public-page-hero-upload-button")).not.toMatch(DISABLED);
  });

  it("blocks the gallery upload at the 12 photo cap", () => {
    const gallery = Array.from({ length: GALLERY_MAX }, (_, i) => ({
      url: `https://cdn.example/g${i}.jpg`,
      caption: "",
      consent_confirmed: true,
    }));
    const html = render({ gallery });
    expect(html).toContain(`(${GALLERY_MAX} of ${GALLERY_MAX})`);
    expect(tag(html, "public-page-gallery-upload-button")).toMatch(DISABLED);
    expect(html).toContain("The gallery is full");
  });

  it("previews a saved hero photo with replace and remove", () => {
    const html = render({ hero_photo_url: "https://cdn.example/hero.jpg" });
    expect(html).toContain("https://cdn.example/hero.jpg");
    expect(html).toContain("Replace photo");
    expect(html).toContain("public-page-hero-remove");
  });

  it("lists each academy coach with photo, bio counter and shown switch", () => {
    const html = render(
      {
        coach_profiles: [{ coach_id: "c1", photo_url: null, bio: "Level 2 BWF", shown: true }],
      },
      [
        { user_id: "c1", email: "a@x.test", display_name: "Alex Morgan", role: "coach", status: "active" },
        { user_id: "c2", email: "s@x.test", display_name: "Sam Lee", role: "coach", status: "active" },
      ],
    );
    expect(html).toContain("Alex Morgan");
    expect(html).toContain("Sam Lee");
    expect(html).toContain("11 / 280");
    expect(html).toContain("0 / 280");
    expect(html.match(/data-testid="public-page-coach-row"/g)).toHaveLength(2);
    expect(tag(html, "public-page-coach-shown")).toMatch(/\schecked=""/);
  });

  it("renders saved FAQs with reorder controls disabled at the ends", () => {
    const html = render({
      faqs: [
        { question: "Do I need a racket?", answer: "We lend one." },
        { question: "Where do we park?", answer: "Behind the hall." },
      ],
    });
    expect(html.match(/data-testid="public-page-faq-row"/g)).toHaveLength(2);
    expect(html).toContain("Do I need a racket?");
    // First row's Move up and last row's Move down are disabled.
    const buttons = html.match(/<button[^>]*data-testid="public-page-faq-(?:up|down)"[^>]*>/g) ?? [];
    expect(buttons).toHaveLength(4);
    const disabled = buttons.filter((b) => DISABLED.test(b));
    expect(disabled).toHaveLength(2);
    expect(disabled.some((b) => b.includes("Move question 1 up"))).toBe(true);
    expect(disabled.some((b) => b.includes("Move question 2 down"))).toBe(true);
  });

  it("starts with Save off because nothing changed", () => {
    expect(tag(render(), "public-page-content-save")).toMatch(DISABLED);
  });
});
