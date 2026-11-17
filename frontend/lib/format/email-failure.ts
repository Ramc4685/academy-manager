/**
 * Plain words for the public failure codes the API returns for an email
 * (`shared/comms/public_failure.py`). An unknown code falls back to a
 * readable version of itself rather than raw snake_case.
 */
const LABELS: Record<string, string> = {
  email_delivery_failed: "Delivery failed",
  recipient_unsubscribed: "They unsubscribed from these emails",
  send_gave_up: "Gave up after repeated errors",
  send_exception: "Delivery failed",
  suppressed: "This address is not receiving email",
  no_email: "No email on file",
  parent_email_missing: "No email on file",
  no_unsubscribe_link: "Not sent: unsubscribe link unavailable",
};

export function emailFailureLabel(code: string | null | undefined): string {
  if (!code) return LABELS.email_delivery_failed;
  const known = LABELS[code];
  if (known) return known;
  const words = code.replace(/_/g, " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : LABELS.email_delivery_failed;
}
