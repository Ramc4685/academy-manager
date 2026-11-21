/**
 * #1029: the campaign audience label comes from the server's resolved audience
 * (`POST /admin/campaigns/preview`), never from a session's enrolled count.
 * Siblings share a parent, so students are not families, and opted-in family
 * contacts add addresses without adding families.
 */
export interface CampaignAudienceCounts {
  recipient_count: number;
  family_count: number;
  contact_count: number;
}

export type CampaignAudienceState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; counts: CampaignAudienceCounts };

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

export function campaignAudienceLabel(state: CampaignAudienceState, scope: string): string {
  if (state.status === "loading") return `${scope} (counting recipients…)`;
  if (state.status === "error") return `${scope} (recipient count unavailable)`;
  const { recipient_count, family_count, contact_count } = state.counts;
  const families = plural(family_count, "family", "families");
  const contacts = contact_count > 0 ? ` + ${plural(contact_count, "family contact", "family contacts")}` : "";
  return `${plural(recipient_count, "email recipient", "email recipients")} ${scope} (${families}${contacts})`;
}
