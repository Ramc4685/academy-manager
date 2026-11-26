import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/use-native-app", () => ({ useIsNativeApp: () => false }));

import { ReceiptDocument } from "./receipt-document";

// Fictional fixture: no real family or academy.
const receipt = {
  academy: { name: "Demo Academy", address: "12 Court Lane, Normal IL", phone: "(309) 555-0142", email: "hello@example.com", logo_url: null },
  invoice_id: "inv-1",
  invoice_number: "DEMO-202610-0003",
  period_label: "October 2026",
  payer_name: "Demo Parent",
  student_name: "Sam Demo",
  lines: [
    { label: "Junior Beginners tuition", amount_cents: 9000 },
    { label: "Sibling discount", amount_cents: -3000 },
  ],
  total_cents: 6000,
  currency: "usd",
  payments: [{ paid_on: "2026-10-03", method: "Cash", amount_cents: 6000 }],
  balance_cents: 0,
  paid_in_full_on: "2026-10-03",
};

describe("ReceiptDocument", () => {
  it("shows academy, child, lines, payments and balance as the backend sent them", () => {
    const html = renderToStaticMarkup(createElement(ReceiptDocument, { receipt }));
    expect(html).toContain("Demo Academy");
    expect(html).toContain("12 Court Lane, Normal IL");
    expect(html).toContain("DEMO-202610-0003");
    expect(html).toContain("Paid in full on Oct 3, 2026");
    expect(html).toContain("Sam Demo");
    expect(html).toContain("Demo Parent");
    expect(html).toContain("−$30.00");
    expect(html).toContain("Oct 3, 2026 · Cash");
    expect(html).toContain("Print or save as PDF");
    expect(html).toContain("receipt-print");
    expect(html).toContain("@media print");
  });
});
