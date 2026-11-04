import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

const shell = vi.hoisted(() => ({ native: false }));
vi.mock("@/lib/use-native-app", () => ({ useIsNativeApp: () => shell.native }));

import { formatSignedAt, SignedWaiverDocument } from "./signed-waiver-document";

// Fictional fixture: no real family or academy.
const copy = {
  waiver_signature_id: "ws-1",
  student_name: "Kid One",
  title: "Participation agreement",
  version: "3",
  body: "Line one.\nLine two.",
  content_hash: "abc123",
  signed_at: "2026-11-02T18:30:00Z",
  signer_name: "Pat Parent",
  signer_email: "pat@example.com",
  consent_text: "I agree to sign electronically.",
  ip_address: "203.0.113.10",
  user_agent: null,
};

describe("SignedWaiverDocument", () => {
  it("shows the exact text and the full audit trail", () => {
    const html = renderToStaticMarkup(createElement(SignedWaiverDocument, { copy }));
    expect(html).toContain("Line one.\nLine two.");
    expect(html).toContain("whitespace-pre-wrap");
    for (const value of ["Pat Parent", "203.0.113.10", "abc123", "ws-1", "Version 3"]) {
      expect(html).toContain(value);
    }
    expect(html).toContain("I agree to sign electronically.");
    // A field the server did not record says so instead of rendering blank.
    expect(html).toContain("Not recorded");
  });

  it("shows each section with the initials and path it was signed with", () => {
    const html = renderToStaticMarkup(
      createElement(SignedWaiverDocument, {
        copy: {
          ...copy,
          body: "Intro.\n## Assumption of risk [initials]\nRisky.\n## Parent release [minor]\nFor kids.",
          initials: { s2: "PP" },
          signing_path: "minor" as const,
        },
      }),
    );
    expect(html).toContain("Assumption of risk");
    expect(html).toContain("Initialled: PP");
    expect(html).toContain("Participants under 18");
    expect(html).toContain("Parent or guardian");
    expect(html).not.toContain("<input");
  });

  it("offers print on the web but not in the app shell, where it goes nowhere", () => {
    expect(renderToStaticMarkup(createElement(SignedWaiverDocument, { copy }))).toContain(
      "Print or save as PDF",
    );
    shell.native = true;
    try {
      expect(renderToStaticMarkup(createElement(SignedWaiverDocument, { copy }))).not.toContain(
        "Print or save as PDF",
      );
    } finally {
      shell.native = false;
    }
  });

  it("keeps the UTC instant next to the local time", () => {
    expect(formatSignedAt("2026-11-02T18:30:00Z")).toContain("(2026-11-02T18:30:00Z)");
    expect(formatSignedAt(null)).toBeNull();
  });
});
