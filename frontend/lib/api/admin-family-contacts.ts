/**
 * People CRM Phase 4b: family contacts (second parent, guardian, ...) and the
 * family's editable details. Shapes mirror
 * backend/v2/interfaces/admin/family_contacts_routes.py.
 *
 * - `GET/POST /admin/families/{parentId}/contacts`
 * - `PATCH/DELETE /admin/families/{parentId}/contacts/{contactId}`
 * - `GET/PATCH /admin/families/{parentId}/details`
 *
 * No request carries an academy: the backend uses the caller's tenant.
 */
import { apiFetch } from "./client";

export type ContactRelationship = "parent" | "guardian" | "grandparent" | "caregiver" | "other";
export type PreferredChannel = "email" | "phone" | "sms" | "whatsapp";

export interface FamilyContact {
  contact_id: string;
  parent_id: string;
  name: string;
  relationship: ContactRelationship;
  email: string | null;
  phone: string | null;
  /** On: this contact's email joins the family's notice audience. */
  gets_notices: boolean;
  /** Stored and shown; invoice emails do not use it yet. */
  gets_invoices: boolean;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface FamilyContactList {
  family_id: string;
  contacts: FamilyContact[];
}

export interface NewFamilyContact {
  name: string;
  relationship: ContactRelationship;
  email: string | null;
  phone: string | null;
  gets_notices: boolean;
  gets_invoices: boolean;
}

/** Only the fields sent change; `null` email or phone clears it. */
export type FamilyContactPatch = Partial<NewFamilyContact>;

export interface FamilyDetails {
  family_id: string;
  address: string | null;
  preferred_channel: PreferredChannel | null;
  heard_about_us: string | null;
  tags: string[];
  updated_by: string | null;
  updated_at: string | null;
}

export type FamilyDetailsPatch = Partial<
  Pick<FamilyDetails, "address" | "preferred_channel" | "heard_about_us" | "tags">
>;

const family = (parentId: string) => `/admin/families/${encodeURIComponent(parentId)}`;

/** Query keys for the Details tab (kept here, next to the calls they cache). */
export const familyContactKeys = {
  contacts: (parentId: string) => ["admin", "families", parentId, "contacts"] as const,
  details: (parentId: string) => ["admin", "families", parentId, "details"] as const,
};

export function fetchFamilyContacts(parentId: string): Promise<FamilyContactList> {
  return apiFetch<FamilyContactList>(`${family(parentId)}/contacts`, {
    method: "GET",
  });
}

export function addFamilyContact(
  parentId: string,
  contact: NewFamilyContact,
): Promise<FamilyContact> {
  return apiFetch<FamilyContact>(`${family(parentId)}/contacts`, {
    method: "POST",
    body: JSON.stringify(contact),
  });
}

export function updateFamilyContact(
  parentId: string,
  contactId: string,
  patch: FamilyContactPatch,
): Promise<FamilyContact> {
  return apiFetch<FamilyContact>(`${family(parentId)}/contacts/${encodeURIComponent(contactId)}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function deleteFamilyContact(parentId: string, contactId: string): Promise<void> {
  return apiFetch<void>(`${family(parentId)}/contacts/${encodeURIComponent(contactId)}`, {
    method: "DELETE",
  });
}

export function fetchFamilyDetails(parentId: string): Promise<FamilyDetails> {
  return apiFetch<FamilyDetails>(`${family(parentId)}/details`, {
    method: "GET",
  });
}

export function updateFamilyDetails(
  parentId: string,
  patch: FamilyDetailsPatch,
): Promise<FamilyDetails> {
  return apiFetch<FamilyDetails>(`${family(parentId)}/details`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}
