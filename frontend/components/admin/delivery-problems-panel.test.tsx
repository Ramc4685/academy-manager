import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { DeliveryProblemsList } from "./delivery-problems-panel";

describe("DeliveryProblemsList (L11 item 3)", () => {
  it("lists blocked addresses with a generic line and no reason or date", () => {
    const html = renderToStaticMarkup(
      createElement(DeliveryProblemsList, {
        data: {
          suppressed_emails: ["bounce@example.test"],
          failed: [
            {
              delivery_id: "d1",
              recipient_email: "bounce@example.test",
              failed_reason: "email_delivery_failed",
            },
            {
              delivery_id: "d2",
              recipient_email: "slow@example.test",
              failed_reason: "send_gave_up",
            },
            {
              delivery_id: "d3",
              recipient_email: "optout@example.test",
              failed_reason: "recipient_unsubscribed",
            },
          ],
        },
      }),
    );
    expect(html).toContain("This address is not receiving email");
    expect(html).not.toMatch(/bounced|spam|since/i);
    expect(html).toContain("Delivery failed");
    expect(html).toContain("Gave up after repeated errors");
    expect(html).toContain("They unsubscribed from these emails");
  });

  it("says so when nothing is wrong", () => {
    const html = renderToStaticMarkup(
      createElement(DeliveryProblemsList, { data: { suppressed_emails: [], failed: [] } }),
    );
    expect(html).toContain("No delivery problems");
  });
});
