import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { DeliveryProblemsList } from "./delivery-problems-panel";

const NOOP = () => {};

describe("DeliveryProblemsList (L11 item 3)", () => {
  it("offers a retry only on a releasable hard bounce, never on a complaint", () => {
    const html = renderToStaticMarkup(
      createElement(DeliveryProblemsList, {
        onClear: NOOP,
        data: {
          suppressed: [
            {
              user_id: "p1",
              email: "bounce@example.test",
              reason: "hard_bounce",
              bounce_subtype: null,
              last_seen_at: "2026-11-01T00:00:00Z",
              releasable: true,
            },
            {
              user_id: "p2",
              email: "spam@example.test",
              reason: "complaint",
              bounce_subtype: null,
              last_seen_at: "2026-11-01T00:00:00Z",
              releasable: false,
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
    expect(html.match(/Try again/g)).toHaveLength(1);
    expect(html).toContain("Marked our email as spam");
    expect(html).toContain("provider 422");
  });

  it("says so when nothing is wrong", () => {
    const html = renderToStaticMarkup(
      createElement(DeliveryProblemsList, { onClear: NOOP, data: { suppressed: [], failed: [] } }),
    );
    expect(html).toContain("No delivery problems");
  });
});
