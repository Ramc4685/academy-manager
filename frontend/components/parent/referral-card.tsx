"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ds/button";
import { getParentReferral } from "@/lib/api/parent";
import { formatCents } from "@/lib/money";
import { queryKeys } from "@/lib/query/keys";

/**
 * Parent profile -> Refer a family (L9 C2). Hidden while the academy has the
 * referral programme off; the backend mints no code until it is on.
 */
export function ReferralCard() {
  const { data } = useQuery({
    queryKey: queryKeys.parent.referral(),
    queryFn: getParentReferral,
  });
  const [copied, setCopied] = useState(false);
  if (!data?.enabled || !data.referral_code) return null;
  const code = data.referral_code;
  // Built by the server on the academy's own host, never this page's address.
  const shareUrl = data.share_url;

  async function copy() {
    if (!shareUrl) return;
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div
      className="rounded-2xl border border-rally-line bg-white p-4 animate-fade-in-up"
      data-testid="parent-referral-card"
    >
      <h2 className="mb-2 font-bold text-rally-ink text-[15px]">Refer a family</h2>
      <p className="text-sm text-rally-muted">
        Share your link. When a family you refer pays its first invoice
        {data.referrer_credit_cents
          ? `, you get a ${formatCents(data.referrer_credit_cents)} account credit`
          : ", you get an account credit"}
        {data.referred_credit_cents
          ? ` and they get ${formatCents(data.referred_credit_cents)}`
          : ""}
        .
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <code
          className="rounded bg-rally-paper px-2 py-1 font-mono text-sm text-rally-ink"
          data-testid="parent-referral-code"
        >
          {code}
        </code>
        {shareUrl && (
          <Button type="button" variant="secondary" size="sm" onClick={copy}>
            {copied ? "Link copied" : "Copy link"}
          </Button>
        )}
      </div>
      <p className="mt-2 text-sm text-rally-muted" data-testid="parent-referral-rewards">
        Rewards earned: {data.rewards_earned}
      </p>
    </div>
  );
}
