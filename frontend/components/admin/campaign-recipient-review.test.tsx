import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { CampaignRecipientReview, exclusionReasonCopy } from "./campaign-recipient-review";

describe("CampaignRecipientReview (#1031)", () => {
  it("lists recipients, marks family contacts and explains each exclusion", () => {
    const html = renderToStaticMarkup(
      createElement(CampaignRecipientReview, {
        preview: {
          recipient_count: 2,
          family_count: 1,
          contact_count: 1,
          recipients: [
            { display_name: "Dana Whitfield", email: "dana@example.test", is_family_contact: false },
            { display_name: "Lee Whitfield", email: "lee@example.test", is_family_contact: true },
          ],
          exclusions: [
            { display_name: "Robin Hale", email: null, reason: "missing_email", is_family_contact: false },
            { display_name: "Pat Moreno", email: "pat@example.test", reason: "suppressed", is_family_contact: false },
          ],
          audience_fingerprint: "fp",
        },
      }),
    );
    expect(html).toContain("Recipients (2)");
    expect(html).toContain("dana@example.test");
    expect(html).toContain("Family contact");
    expect(html).toContain("Not receiving this (2)");
    expect(html).toContain("No email address on file");
    expect(html).toContain("not receiving email");
  });

  it("falls back to a neutral line for an unknown reason", () => {
    expect(exclusionReasonCopy("something_new")).toBe("Will not receive this email");
  });
});
