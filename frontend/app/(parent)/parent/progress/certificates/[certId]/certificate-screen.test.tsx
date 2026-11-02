import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { certificateAccent } from "@/components/progress/level-certificate";
import type { CertificateDetail } from "@/lib/api/curriculum";

import { CertificateScreen, shareCertificate } from "./certificate-screen";

function detail(overrides: Partial<CertificateDetail> = {}): CertificateDetail {
  return {
    certificate: {
      cert_id: "c1",
      student_id: "s1",
      cert_number: "ACM-L1-A1B2-1793452800000",
      student_name: "Aarav Test",
      level_name: "Grip and Control",
      program_name: "Badminton Pathway",
      // 8:30 PM in Chicago on Oct 30, stored as naive UTC (already Oct 31 in UTC).
      completed_at: "2026-10-31T01:30:00",
      issued_at: "2026-10-31T01:30:00",
    },
    level_number: 1,
    skills: ["Thumb grip", "V grip"],
    next_level: { level_id: "l2", name: "Net and Movement", number: 2 },
    ...overrides,
  };
}

const academy = {
  name: "Test Academy",
  logoUrl: "https://cdn.example.test/logo.png",
  brandColor: "#0f766e",
  timezone: "America/Chicago",
};

function render(d: CertificateDetail = detail(), a = academy): string {
  return renderToStaticMarkup(
    createElement(CertificateScreen, {
      detail: d,
      academy: a,
      progressHref: "/parent/progress?child=s1",
      onPrint: () => {},
      onShare: () => {},
    }),
  );
}

const text = (markup: string) =>
  markup
    .replace(/<style>[\s\S]*?<\/style>/g, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ");

describe("CertificateScreen", () => {
  it("shows the level-complete header in the academy's timezone", () => {
    const out = text(render());
    expect(out).toContain("Level 1 certificate");
    expect(out).toContain("Aarav finished Grip and Control");
    expect(out).toContain("All 2 skills mastered on October 30, 2026.");
  });

  it("renders the certificate with name, level, program, skills and number", () => {
    const html = render();
    const out = text(html);
    expect(out).toContain("Certificate of achievement");
    expect(out).toContain("Aarav Test");
    expect(out).toContain("Level 1 · Grip and Control");
    expect(out).toContain("Badminton Pathway");
    expect(out).toContain("Thumb grip");
    expect(out).toContain("V grip");
    expect(out).toContain("ACM-L1-A1B2-1793452800000");
    expect(out).toContain("Awarded by");
    expect(html).toContain('src="https://cdn.example.test/logo.png"');
  });

  it("prints only the certificate, on Letter landscape", () => {
    const html = render();
    expect(html).toContain("size: letter landscape");
    expect(html).toContain("certificate-print");
    expect(text(html)).toContain("Print or save as PDF");
    expect(text(html)).toContain("Share with family");
  });

  it("links up next to the child's progress", () => {
    const html = render();
    expect(text(html)).toContain("Up next Level 2 · Net and Movement");
    expect(html).toContain('href="/parent/progress?child=s1"');
  });

  it("drops up next on the last level and never shows a non-https logo", () => {
    const html = render(detail({ next_level: null }), {
      ...academy,
      logoUrl: "http://insecure.example.test/logo.png",
    });
    expect(text(html)).not.toContain("Up next");
    expect(html).not.toContain("insecure.example.test");
  });
});

describe("certificateAccent", () => {
  it("keeps a dark brand colour, darkens a pale one, defaults a bad one", () => {
    expect(certificateAccent("#0f766e")).toBe("#0f766e");
    expect(certificateAccent("#facc15")).not.toBe("#facc15");
    expect(certificateAccent("red; background:url(x)")).toBe("#1e3a8a");
  });
});

describe("shareCertificate", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shares a note and the page link from the share sheet", async () => {
    vi.stubGlobal("window", {
      location: { href: "https://app.test/parent/progress/certificates/c1" },
    });
    const share = vi.fn().mockResolvedValue(undefined);
    const print = vi.fn();
    await shareCertificate(detail(), "Test Academy", { share }, print);
    expect(share).toHaveBeenCalledWith({
      title: "Aarav Test: Level 1 · Grip and Control",
      text: "Aarav Test finished Level 1 · Grip and Control at Test Academy!",
      url: "https://app.test/parent/progress/certificates/c1",
    });
    expect(print).not.toHaveBeenCalled();
  });

  it("falls back to print without a share sheet", async () => {
    const print = vi.fn();
    await shareCertificate(detail(), "Test Academy", {} as Pick<Navigator, "share">, print);
    expect(print).toHaveBeenCalledOnce();
  });
});
