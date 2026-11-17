import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { DeliveryProblemsList } from "./delivery-problems-panel";

describe("DeliveryProblemsList (L11 item 3)", () => {
  it("shows the reason for this academy's own problem and a generic line otherwise", () => {
    const html = renderToStaticMarkup(
      createElement(DeliveryProblemsList, {
        data: {
          suppressed: [
            {
              user_id: "p1",
              email: "bounce@example.test",
              reason: "hard_bounce",
              bounce_subtype: null,
              last_seen_at: "2026-11-01T00:00:00Z",
            },
            {
              user_id: "p2",
              email: "shared@example.test",
              reason: null,
              bounce_subtype: null,
              last_seen_at: null,
            },
          ],
          failed: [
            {
              delivery_id: "d1",
              campaign_id: "c1",
              recipient_user_id: "p1",
              recipient_email: "bounce@example.test",
              failed_reason: "provider 422",
            },
          ],
        },
      }),
    );
    expect(html).toContain("Bounced (mailbox does not exist)");
    expect(html).toContain("This address is not receiving email");
    expect(html).not.toContain("spam");
    expect(html).not.toContain("Try again");
    expect(html).toContain("provider 422");
  });

  it("says so when nothing is wrong", () => {
    const html = renderToStaticMarkup(
      createElement(DeliveryProblemsList, { data: { suppressed: [], failed: [] } }),
    );
    expect(html).toContain("No delivery problems");
  });
});
