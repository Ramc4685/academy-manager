import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/admin", () => ({
  getFamilyOffers: vi.fn(),
  updateFamilyOffers: vi.fn(),
}));

import type { FamilyOffersView } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import {
  FamilyOffersCard,
  familyOffersPayload,
  referralError,
  referralFormFrom,
  siblingError,
  siblingFormFrom,
} from "./family-offers-card";

const UNSET: FamilyOffersView = {
  referral_program: { enabled: false },
  sibling_discount: { enabled: false },
};

const STORED: FamilyOffersView = {
  referral_program: {
    enabled: false,
    referrer_credit_cents: 4_000,
    referred_credit_cents: 1_550,
    hold_days: 14,
    max_rewards_per_referrer_per_year: 3,
    credit_expiry_days: 365,
    trigger: "first_paid_monthly_invoice",
  },
  sibling_discount: {
    enabled: true,
    percent_bps: 1_250,
    full_price_child: "first_enrolled",
    applies_to: "one_class_per_child",
  },
};

function html(view: FamilyOffersView) {
  const client = new QueryClient();
  client.setQueryData(queryKeys.admin.familyOffers(), view);
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <FamilyOffersCard />
    </QueryClientProvider>,
  );
}

describe("FamilyOffersCard form", () => {
  it("starts unset values at the starting values, and the sibling percent blank", () => {
    expect(referralFormFrom(UNSET.referral_program)).toEqual({
      enabled: false,
      referrerCreditDollars: "25",
      referredCreditDollars: "25",
      holdDays: "7",
      maxRewards: "10",
      expiryDays: "",
      trigger: "first_paid_invoice",
    });
    expect(siblingFormFrom(UNSET.sibling_discount)).toEqual({
      enabled: false,
      percent: "",
      fullPriceChild: "highest_tuition",
      appliesTo: "all_classes",
    });
  });

  it("shows stored values over the starting values", () => {
    expect(referralFormFrom(STORED.referral_program)).toEqual({
      enabled: false,
      referrerCreditDollars: "40",
      referredCreditDollars: "15.50",
      holdDays: "14",
      maxRewards: "3",
      expiryDays: "365",
      trigger: "first_paid_monthly_invoice",
    });
    expect(siblingFormFrom(STORED.sibling_discount).percent).toBe("12.5");
  });

  it("sends nothing until something changes, so starting values are never stored", () => {
    const sibling = siblingFormFrom(UNSET.sibling_discount);
    const referral = referralFormFrom(UNSET.referral_program);
    expect(familyOffersPayload(UNSET, sibling, referral)).toEqual({});
  });

  it("sends only the changed block, in cents and basis points", () => {
    const sibling = {
      ...siblingFormFrom(UNSET.sibling_discount),
      enabled: true,
      percent: "10",
    };
    const referral = referralFormFrom(UNSET.referral_program);
    expect(familyOffersPayload(UNSET, sibling, referral)).toEqual({
      sibling_discount: {
        enabled: true,
        percent_bps: 1_000,
        full_price_child: "highest_tuition",
        applies_to: "all_classes",
      },
    });
    const changedReferral = { ...referral, holdDays: "0", expiryDays: "" };
    expect(
      familyOffersPayload(
        UNSET,
        siblingFormFrom(UNSET.sibling_discount),
        changedReferral,
      ),
    ).toEqual({
      referral_program: {
        enabled: false,
        referrer_credit_cents: 2_500,
        referred_credit_cents: 2_500,
        hold_days: 0,
        max_rewards_per_referrer_per_year: 10,
        credit_expiry_days: null,
        trigger: "first_paid_invoice",
      },
    });
  });

  it("needs a percentage to switch the sibling discount on, within 0.01% to 100%", () => {
    const base = siblingFormFrom(UNSET.sibling_discount);
    const unset = UNSET.sibling_discount;
    expect(siblingError(base, unset)).toBeNull();
    expect(siblingError({ ...base, enabled: true }, unset)).toMatch(
      /Enter the sibling discount/,
    );
    expect(siblingError({ ...base, percent: "0" }, unset)).toMatch(
      /between 0.01 and 100/,
    );
    expect(siblingError({ ...base, percent: "100.5" }, unset)).toMatch(
      /between 0.01 and 100/,
    );
    expect(
      siblingError({ ...base, enabled: true, percent: "0.01" }, unset),
    ).toBeNull();
    expect(
      siblingError({ ...base, enabled: true, percent: "12.345" }, unset),
    ).toMatch(/at most 2 decimal places/);
  });

  it("blocks a cleared or invalid number instead of sending null over a stored value", () => {
    const sibling = {
      ...siblingFormFrom(STORED.sibling_discount),
      enabled: false,
      percent: "",
    };
    expect(siblingError(sibling, STORED.sibling_discount)).toMatch(/Enter/);

    const referral = referralFormFrom(STORED.referral_program);
    const stored = STORED.referral_program;
    expect(referralError(referral, stored)).toBeNull();
    expect(referralError({ ...referral, holdDays: "" }, stored)).toMatch(
      /Enter the days to hold/,
    );
    expect(referralError({ ...referral, holdDays: "2.5" }, stored)).toMatch(
      /whole number between 0 and 60/,
    );
    expect(referralError({ ...referral, maxRewards: "1e400" }, stored)).toMatch(
      /between 1 and 100/,
    );
    expect(
      referralError({ ...referral, referrerCreditDollars: "abc" }, stored),
    ).toMatch(/credit for the referring family/);
    expect(
      referralError({ ...referral, referredCreditDollars: "10.005" }, stored),
    ).toMatch(/at most 2 decimal places/);
    // Blank expiry means "never expires", so it may clear the stored value.
    expect(referralError({ ...referral, expiryDays: "" }, stored)).toBeNull();
    // The new family's credit may be cleared (no credit for it).
    expect(
      referralError({ ...referral, referredCreditDollars: "" }, stored),
    ).toBeNull();
    // Switching on needs the referrer credit, the hold and the cap.
    expect(
      referralError(
        { ...referral, enabled: true, referrerCreditDollars: "" },
        UNSET.referral_program,
      ),
    ).toMatch(/to switch referrals on/);
    expect(
      referralError({ ...referral, enabled: true }, UNSET.referral_program),
    ).toBeNull();
  });
});

describe("FamilyOffersCard", () => {
  it("shows the load error instead of crashing on a response missing a block", () => {
    for (const partial of [{}, { sibling_discount: { enabled: false } }]) {
      const out = html(partial as FamilyOffersView);
      expect(out).toContain("Could not load the family offers.");
      expect(out).not.toContain('data-testid="family-offers-sibling"');
    }
  });

  it("renders both offers with the referral switch usable", () => {
    const out = html(STORED);
    expect(out).toContain("Sibling discount");
    expect(out).not.toContain("Coming soon");
    expect(out).not.toMatch(
      /data-testid="family-offers-referral-enabled"[^>]*disabled|disabled[^>]*data-testid="family-offers-referral-enabled"/,
    );
    expect(out).toContain('value="12.5"');
    expect(out).toContain("Save family offers");
  });
});
