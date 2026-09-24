/**
 * People CRM Phase 4b: the pure parts of the Details tab (family contacts and
 * family details), kept here so they are tested without rendering. Rules
 * mirror backend/v2/contexts/crm/domain/family_contacts.py; the backend stays
 * the authority and its field-level errors are shown next to the field.
 */
import type {
  ContactRelationship,
  FamilyContact,
  FamilyContactPatch,
  FamilyDetails,
  FamilyDetailsPatch,
  NewFamilyContact,
  PreferredChannel,
} from "@/lib/api/admin-family-contacts";

export const MAX_CONTACT_NAME_LEN = 120;
export const MAX_ADDRESS_LEN = 300;
export const MAX_HEARD_ABOUT_US_LEN = 200;
export const MAX_TAGS = 20;
export const MAX_TAG_LEN = 40;

export const RELATIONSHIP_OPTIONS: readonly {
  value: ContactRelationship;
  label: string;
}[] = [
  { value: "parent", label: "Parent" },
  { value: "guardian", label: "Guardian" },
  { value: "grandparent", label: "Grandparent" },
  { value: "caregiver", label: "Caregiver" },
  { value: "other", label: "Other" },
];

export const CHANNEL_OPTIONS: readonly {
  value: PreferredChannel;
  label: string;
}[] = [
  { value: "email", label: "Email" },
  { value: "phone", label: "Phone call" },
  { value: "sms", label: "Text message" },
  { value: "whatsapp", label: "WhatsApp" },
];

export function relationshipLabel(value: ContactRelationship): string {
  return RELATIONSHIP_OPTIONS.find((o) => o.value === value)?.label ?? "Other";
}

/**
 * The two opt-in switches on a contact. Both start off and only staff turn
 * them on. Invoice emails are not wired to contacts yet, so that switch says
 * so rather than implying a copy is sent.
 */
export const CONTACT_SWITCHES = [
  {
    id: "gets_notices",
    label: "Gets notices",
    description: "Class notices and announcements to this family also go to this email.",
  },
  {
    id: "gets_invoices",
    label: "Gets invoices (opted in)",
    description:
      "Saved now. Invoice emails start going to this contact once invoice email wiring ships; payment links stay with the primary parent.",
  },
] as const;

export type ContactSwitchId = (typeof CONTACT_SWITCHES)[number]["id"];

export interface ContactDraft {
  name: string;
  relationship: ContactRelationship;
  email: string;
  phone: string;
  gets_notices: boolean;
  gets_invoices: boolean;
}

export type ContactField = keyof ContactDraft;
export type ContactErrors = Partial<Record<ContactField, string>>;

export function emptyContactDraft(): ContactDraft {
  return {
    name: "",
    relationship: "parent",
    email: "",
    phone: "",
    gets_notices: false,
    gets_invoices: false,
  };
}

export function draftFromContact(contact: FamilyContact): ContactDraft {
  return {
    name: contact.name,
    relationship: contact.relationship,
    email: contact.email ?? "",
    phone: contact.phone ?? "",
    gets_notices: contact.gets_notices,
    gets_invoices: contact.gets_invoices,
  };
}

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const PHONE_CHARS = /^[0-9+()\-. ]+$/;

/** Field errors for a contact draft; empty when it can be saved. */
export function contactDraftErrors(draft: ContactDraft): ContactErrors {
  const errors: ContactErrors = {};
  const name = draft.name.trim();
  const email = draft.email.trim();
  const phone = draft.phone.trim();
  if (!name) errors.name = "Enter the contact's name.";
  else if (name.length > MAX_CONTACT_NAME_LEN) {
    errors.name = `Keep the name to ${MAX_CONTACT_NAME_LEN} characters.`;
  }
  if (email && !EMAIL.test(email)) errors.email = "Enter a valid email address.";
  if (phone) {
    const digits = phone.replace(/\D/g, "").length;
    if (!PHONE_CHARS.test(phone) || digits < 7 || digits > 15) {
      errors.phone = "Enter a valid phone number.";
    }
  }
  if (!email && !phone && !errors.name) errors.email = "Add an email or a phone number.";
  if (!email && draft.gets_notices) {
    errors.gets_notices = "Add an email before turning on Gets notices.";
  }
  if (!email && draft.gets_invoices) {
    errors.gets_invoices = "Add an email before turning on Gets invoices.";
  }
  return errors;
}

export function contactPayload(draft: ContactDraft): NewFamilyContact {
  return {
    name: draft.name.trim(),
    relationship: draft.relationship,
    email: draft.email.trim() || null,
    phone: draft.phone.trim() || null,
    gets_notices: draft.gets_notices,
    gets_invoices: draft.gets_invoices,
  };
}

/** Only what changed, so a save never rewrites a field nobody touched. */
export function contactPatch(original: FamilyContact, draft: ContactDraft): FamilyContactPatch {
  const next = contactPayload(draft);
  const patch: FamilyContactPatch = {};
  if (next.name !== original.name) patch.name = next.name;
  if (next.relationship !== original.relationship) patch.relationship = next.relationship;
  if ((next.email ?? null) !== (original.email ?? null)) patch.email = next.email;
  if ((next.phone ?? null) !== (original.phone ?? null)) patch.phone = next.phone;
  if (next.gets_notices !== original.gets_notices) patch.gets_notices = next.gets_notices;
  if (next.gets_invoices !== original.gets_invoices) patch.gets_invoices = next.gets_invoices;
  return patch;
}

export function isContactDraftDirty(draft: ContactDraft, original: ContactDraft): boolean {
  return (Object.keys(draft) as ContactField[]).some((k) => draft[k] !== original[k]);
}

// ---------------------------------------------------------------------------
// Family details
// ---------------------------------------------------------------------------

export interface DetailsDraft {
  address: string;
  preferred_channel: PreferredChannel | "";
  heard_about_us: string;
  /** Comma-separated in the form. */
  tags: string;
}

export type DetailsField = keyof DetailsDraft;
export type DetailsErrors = Partial<Record<DetailsField, string>>;

export function detailsDraftFrom(details: FamilyDetails | null | undefined): DetailsDraft {
  return {
    address: details?.address ?? "",
    preferred_channel: details?.preferred_channel ?? "",
    heard_about_us: details?.heard_about_us ?? "",
    tags: (details?.tags ?? []).join(", "),
  };
}

/** Trimmed, blank-free, de-duplicated ignoring case (first spelling wins). */
export function parseTags(text: string): string[] {
  const seen = new Set<string>();
  const tags: string[] = [];
  for (const raw of text.split(",")) {
    const tag = raw.replace(/\s+/g, " ").trim();
    if (!tag || seen.has(tag.toLowerCase())) continue;
    seen.add(tag.toLowerCase());
    tags.push(tag);
  }
  return tags;
}

export function detailsDraftErrors(draft: DetailsDraft): DetailsErrors {
  const errors: DetailsErrors = {};
  if (draft.address.trim().length > MAX_ADDRESS_LEN) {
    errors.address = `Keep the address to ${MAX_ADDRESS_LEN} characters.`;
  }
  if (draft.heard_about_us.trim().length > MAX_HEARD_ABOUT_US_LEN) {
    errors.heard_about_us = `Keep the answer to ${MAX_HEARD_ABOUT_US_LEN} characters.`;
  }
  const tags = parseTags(draft.tags);
  if (tags.some((t) => t.length > MAX_TAG_LEN)) {
    errors.tags = `Keep each tag to ${MAX_TAG_LEN} characters.`;
  } else if (tags.length > MAX_TAGS) {
    errors.tags = `Use at most ${MAX_TAGS} tags.`;
  }
  return errors;
}

export function isDetailsDirty(draft: DetailsDraft, original: DetailsDraft): boolean {
  return (
    draft.address.trim() !== original.address.trim() ||
    draft.preferred_channel !== original.preferred_channel ||
    draft.heard_about_us.trim() !== original.heard_about_us.trim() ||
    parseTags(draft.tags).join("\u0000") !== parseTags(original.tags).join("\u0000")
  );
}

/** Only the changed fields; a cleared text field is sent as `null`. */
export function detailsPatch(original: DetailsDraft, draft: DetailsDraft): FamilyDetailsPatch {
  const patch: FamilyDetailsPatch = {};
  if (draft.address.trim() !== original.address.trim()) {
    patch.address = draft.address.trim() || null;
  }
  if (draft.preferred_channel !== original.preferred_channel) {
    patch.preferred_channel = draft.preferred_channel || null;
  }
  if (draft.heard_about_us.trim() !== original.heard_about_us.trim()) {
    patch.heard_about_us = draft.heard_about_us.trim() || null;
  }
  const tags = parseTags(draft.tags);
  if (tags.join("\u0000") !== parseTags(original.tags).join("\u0000")) patch.tags = tags;
  return patch;
}

/** The backend's field-level error (`error.details.field`), if it named one. */
export function apiFieldError(error: unknown): {
  field: string | null;
  message: string;
} {
  const err = error as {
    message?: string;
    details?: Record<string, unknown>;
  } | null;
  const field = typeof err?.details?.field === "string" ? (err.details.field as string) : null;
  return { field, message: err?.message || "Something went wrong. Try again." };
}
