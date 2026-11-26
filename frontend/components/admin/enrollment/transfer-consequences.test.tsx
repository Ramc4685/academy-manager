import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { formatLifecycleType } from "@/app/(admin)/admin/sessions/[id]/format";

import {
  TransferConsequences,
  formatMonthlyPrice,
  transferNeedsAcknowledgement,
  type TransferSide,
} from "./transfer-consequences";

const SAT: TransferSide = { title: "Junior Beginners", schedule: "Saturdays 9:00–10:00 AM", amountCents: 8000 };
const SAT_COPY: TransferSide = { ...SAT, title: "Saturday Juniors B" };
const TUE_UNPRICED: TransferSide = { title: "Tuesday Intermediate", schedule: "Tuesdays 9:00–10:00 AM", amountCents: null, unpriced: true };
const FREE: TransferSide = { title: "Free clinic", schedule: "", amountCents: 0 };

const render = (to: TransferSide | null, acknowledged = false) =>
  renderToStaticMarkup(
    <TransferConsequences from={SAT} to={to} acknowledged={acknowledged} onAcknowledge={() => {}} />,
  );

describe("transfer consequences (S27)", () => {
  it("prices a class per month, and says when none is set", () => {
    expect(formatMonthlyPrice(SAT)).toBe("$80.00/month");
    expect(formatMonthlyPrice(TUE_UNPRICED)).toBe("No price set");
    expect(formatMonthlyPrice(FREE)).toBe("$0.00/month");
  });

  it("needs a tick when the price changes or the target has no price", () => {
    expect(transferNeedsAcknowledgement(SAT, TUE_UNPRICED)).toBe(true);
    expect(transferNeedsAcknowledgement(SAT, FREE)).toBe(true);
    expect(transferNeedsAcknowledgement(SAT, SAT_COPY)).toBe(false);
  });

  it("shows from and to with an unticked required box for an unpriced target", () => {
    const html = render(TUE_UNPRICED);
    expect(html).toContain("$80.00/month to No price set");
    expect(html).toContain('data-testid="transfer-price-ack"');
    expect(html).toMatch(/type="checkbox" required=""/);
    expect(html).not.toContain('checked=""');
    expect(html).toContain("Tuesdays 9:00–10:00 AM");
  });

  it("says the old class's remaining dates come off this month's invoice (S27 persona follow-up)", () => {
    // The move quote prices an unpriced target at $0, so the family is
    // credited for the old class's remaining dates: the dialog must say so.
    const html = render(TUE_UNPRICED);
    expect(html).toContain("drops the classes left in the old class");
    expect(html).toContain("not billed until the owner sets a price");
  });

  it("asks for no tick when the price stays the same", () => {
    expect(render(SAT_COPY)).not.toContain("transfer-price-ack");
  });

  it("names who is emailed and does not promise the invoice is adjusted", () => {
    const html = render(null);
    expect(html).toContain("coaches of both classes");
    expect(html).toContain("The family gets no transfer email");
    expect(html).toContain("they get a corrected payment notice");
    expect(html).not.toContain("The family is not emailed");
    expect(html).toContain("the failure is recorded in the enrollment history");
    expect(html).not.toContain("it is not charged again");
  });
});

describe("roster history label (S27)", () => {
  it("names a cancelled class date instead of a generic update", () => {
    expect(formatLifecycleType("occurrence_cancelled")).toBe("Class date cancelled");
    expect(formatLifecycleType("something_new")).toBe("Updated");
  });
});
