/**
 * People CRM Phase 6 (L4c): the pure parts of the family Messages tab, kept
 * here so they are tested without rendering. Rules mirror
 * backend/v2/contexts/crm/domain/family_messages.py.
 *
 * The app never sends SMS or WhatsApp. A handoff opens the staff member's own
 * app (wa.me, sms:, mailto:) and the contact is then logged by hand.
 */
import type { ChipVariant } from "@/components/ds";
import type {
  FamilyMessage,
  MessageChannel,
  MessageSource,
  MessageStatus,
} from "@/lib/api/admin-family-crm";
import { mailtoHref, whatsappHref } from "@/lib/contact-links";

export const MAX_CONTACT_LOG_NOTE_LEN = 2000;

/** Channels a staff member hands off to their own app. */
export type HandoffChannel = Extract<MessageChannel, "whatsapp" | "sms" | "email">;
/** Contacts that are logged when they happened, with no handoff. */
export type DirectChannel = Extract<MessageChannel, "call" | "in_person">;

const CHANNEL_LABEL: Record<MessageChannel, string> = {
  email: "Email",
  whatsapp: "WhatsApp",
  sms: "SMS",
  call: "Call",
  in_person: "In person",
};

export function channelLabel(channel: MessageChannel): string {
  return CHANNEL_LABEL[channel];
}

const SOURCE_LABEL: Record<MessageSource, string> = {
  campaign: "Academy email",
  digest: "Parent digest",
  absence_notice: "Absence notice",
  invoice_copy: "Invoice copy",
  staff_log: "Logged by staff",
};

export function sourceLabel(source: MessageSource): string {
  return SOURCE_LABEL[source];
}

const STATUS_LABEL: Record<MessageStatus, string> = {
  queued: "Queued",
  sent: "Sent",
  opened: "Opened",
  failed: "Failed",
  logged: "Logged",
  not_logged: "Not confirmed",
};

export function statusLabel(status: MessageStatus): string {
  return STATUS_LABEL[status];
}

const STATUS_CHIP: Record<MessageStatus, ChipVariant> = {
  queued: "pending",
  sent: "approved",
  opened: "approved",
  failed: "failed",
  logged: "approved",
  not_logged: "draft",
};

export function statusVariant(status: MessageStatus): ChipVariant {
  return STATUS_CHIP[status];
}

/** `sms:` link from a stored number; digits and a leading `+` only. */
export function smsHref(phone?: string | null): string | undefined {
  const raw = (phone ?? "").trim();
  const digits = raw.replace(/\D/g, "");
  if (!digits) return undefined;
  return `sms:${raw.startsWith("+") ? "+" : ""}${digits}`;
}

/** Where a handoff button opens, or undefined when the family has no number/email. */
export function handoffHref(
  channel: HandoffChannel,
  contact: { phone?: string | null; email?: string | null },
): string | undefined {
  if (channel === "whatsapp") return whatsappHref(contact.phone);
  if (channel === "sms") return smsHref(contact.phone);
  return mailtoHref(contact.email);
}

/** The error to show for a contact-log note, or null when it can be saved. */
export function contactNoteError(note: string): string | null {
  if (note.trim().length > MAX_CONTACT_LOG_NOTE_LEN) {
    return `A note can be at most ${MAX_CONTACT_LOG_NOTE_LEN} characters.`;
  }
  return null;
}

/** Plain-language names for the `<source>_unavailable` warnings. */
const WARNING_LABEL: Record<string, string> = {
  campaigns_unavailable: "academy emails",
  digest_unavailable: "parent digests",
  absence_notices_unavailable: "absence notices",
  invoice_copies_unavailable: "invoice copies",
  contact_log_unavailable: "logged contacts",
  parent_aliases_unavailable: "older account links",
};

export function warningText(warnings: readonly string[]): string | null {
  if (warnings.length === 0) return null;
  const names = warnings.map((w) => WARNING_LABEL[w] ?? w.replace(/_unavailable$/, ""));
  return `Some messages could not be loaded right now (${names.join(", ")}). The list may be incomplete.`;
}

/** Count of handoffs still waiting for "Did you send it?". */
export function unconfirmedCount(entries: readonly FamilyMessage[]): number {
  return entries.filter((e) => e.status === "not_logged").length;
}
