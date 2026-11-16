import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import type { ParentReferral } from "@/lib/api/parent";
import { queryKeys } from "@/lib/query/keys";
import { ReferralCard } from "./referral-card";

function html(data: ParentReferral) {
  const client = new QueryClient();
  client.setQueryData(queryKeys.parent.referral(), data);
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <ReferralCard />
    </QueryClientProvider>,
  );
}

describe("ReferralCard", () => {
  it("renders nothing while the academy has referrals off", () => {
    expect(
      html({ enabled: false, referral_code: null, rewards_earned: 0 }),
    ).toBe("");
  });

  it("shows the code, the credit and the rewards earned", () => {
    const out = html({
      enabled: true,
      referral_code: "QZ7KX4MP",
      share_url: "https://blno.courtmastr.com/?ref=QZ7KX4MP",
      rewards_earned: 2,
      referrer_credit_cents: 2_500,
      referred_credit_cents: 1_000,
    });
    expect(out).toContain("QZ7KX4MP");
    expect(out).toContain("$25");
    expect(out).toContain("$10");
    expect(out).toContain("Rewards earned: 2");
    expect(out).toContain("Copy link");
  });

  it("offers no copy button without a server-built link", () => {
    const out = html({ enabled: true, referral_code: "QZ7KX4MP", rewards_earned: 0 });
    expect(out).toContain("QZ7KX4MP");
    expect(out).not.toContain("Copy link");
  });
});
