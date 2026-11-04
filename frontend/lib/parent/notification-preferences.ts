/**
 * The parent-facing shape of `GET/PUT /api/v2/parent/email-preferences` (#778).
 *
 * The API stores *opt-OUTs* because that is what an emailed one-click
 * unsubscribe link writes (CAN-SPAM, #555). A preferences card reads the
 * other way round — a family switches a kind of email ON — so the inversion
 * lives here, once, instead of being re-derived at each checkbox.
 *
 * Transactional mail (invoices, receipts, dunning, "your child was moved")
 * is deliberately absent: the request model on the backend forbids unknown
 * keys and has no transactional field, so it cannot be switched off from the
 * portal at all. `ALWAYS_ON_NOTICE` says so to the parent rather than leaving
 * them hunting for a switch that does not exist.
 */

export interface ParentEmailPreferences {
  campaigns_opted_out: boolean;
  digests_opted_out: boolean;
  /** Optional on the wire for deploy-order reasons (#612): absent means "on". */
  notifications_opted_out?: boolean;
}

export type NotificationChannelKey = "notifications" | "digests" | "campaigns";

export interface NotificationChannel {
  key: NotificationChannelKey;
  label: string;
  description: string;
}

/** Ordered most-useful first, so the switch a family came to find is at the top. */
export const NOTIFICATION_CHANNELS: readonly NotificationChannel[] = [
  {
    key: "notifications",
    label: "Class and roster updates",
    description: "A coach cancels a class, your child moves off the waitlist, a seat opens.",
  },
  {
    key: "digests",
    label: "Weekly summary",
    description: "One email a week with the coming week's classes and anything outstanding.",
  },
  {
    key: "campaigns",
    label: "News and offers",
    description: "Camps, holiday programmes and occasional academy news.",
  },
] as const;

export const ALWAYS_ON_NOTICE =
  "Invoices, receipts and payment reminders are always sent — they are part of your account, not marketing.";

const OPT_OUT_FIELD: Record<NotificationChannelKey, keyof ParentEmailPreferences> = {
  notifications: "notifications_opted_out",
  digests: "digests_opted_out",
  campaigns: "campaigns_opted_out",
};

/** True when the family still receives this kind of email. */
export function isChannelOn(
  preferences: ParentEmailPreferences,
  key: NotificationChannelKey,
): boolean {
  return preferences[OPT_OUT_FIELD[key]] !== true;
}

/** A new preferences object with one channel switched on or off. */
export function setChannel(
  preferences: ParentEmailPreferences,
  key: NotificationChannelKey,
  on: boolean,
): ParentEmailPreferences {
  return { ...preferences, [OPT_OUT_FIELD[key]]: !on };
}
