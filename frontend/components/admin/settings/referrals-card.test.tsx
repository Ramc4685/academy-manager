import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import type { ReferralRow } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { OwnerProvider } from "@/components/admin/owner-context";
import { ReferralsCard, referralState } from "./referrals-card";

const BASE: ReferralRow = {
  referral_id: "r1",
  referral_code: "QZ7KX4MP",
  referrer_name: "Riley Ref",
  referred_name: "Nova New",
  referrer_credit_cents: 2_500,
  status: "pending",
  created_at: "2026-12-01T00:00:00Z",
};

function html(rows: ReferralRow[] | undefined, isOwner = true) {
  const client = new QueryClient();
  if (rows) client.setQueryData(queryKeys.admin.referrals(), { referrals: rows });
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <OwnerProvider isOwner={isOwner}>
        <ReferralsCard />
      </OwnerProvider>
    </QueryClientProvider>,
  );
}

describe("ReferralsCard", () => {
  it("names each state, and the reason a referral did not count", () => {
    expect(referralState(BASE)).toBe("Waiting for the first paid invoice");
    expect(
      referralState({ ...BASE, grant_due_at: "2026-12-08T12:00:00Z" }),
    ).toMatch(/^Paid; credit due /);
    expect(
      referralState({ ...BASE, status: "granted", granted_at: "2026-12-08T12:00:00Z" }),
    ).toMatch(/^Credited /);
    expect(
      referralState({ ...BASE, status: "ineligible", reason: "self_referral" }),
    ).toBe("Not eligible: Same family");
  });

  it("lists rows with names and credit, and says plainly when there are none", () => {
    const out = html([BASE]);
    expect(out).toContain("Riley Ref");
    expect(out).toContain("Nova New");
    expect(out).toContain("$25");
    expect(out).toContain("not sent; needs your sign-off");
    expect(html([])).toContain("No referrals yet");
    // An empty or stubbed response renders the empty state, not a crash.
    expect(html(undefined)).toContain("No referrals yet");
  });

  it("offers Approve on an inquiry-only referral to the owner only", () => {
    const review = { ...BASE, status: "needs_review" as const };
    expect(referralState(review)).toMatch(/^Needs your review/);
    expect(html([review])).toContain('data-testid="referral-approve"');
    expect(html([review], false)).not.toContain('data-testid="referral-approve"');
    expect(html([BASE])).not.toContain('data-testid="referral-approve"');
  });
});
