/**
 * One vocabulary for the two facts every admin People page states about a
 * person (#840).
 *
 *   Login — can this person get into the app?  Not invited / Invited / Active
 *   Card  — can we charge them?                No card / Card on file / Card declined
 *
 * Before this module each page free-handed its own words, so the same fact was
 * "REGISTERED" on the families list, "Chargeable" in that list's own filter and
 * "Card on file" on the family page, while "ACTIVE" meant *attending* on
 * Students and *can log in* on Users. Every People surface now reads its labels
 * from here so they cannot drift apart again.
 *
 * The student lifecycle vocabulary ("On the books", Active, Paused, On hold,
 * Ending, Left, Trial) is a third, separate thing and is deliberately NOT
 * defined here — see admin/students/[studentId]/StatusChip.tsx.
 *
 * Pure module: no React, no fetch.
 */
import type { ChipVariant } from "@/components/ds/chip";
import type { RegistrationState } from "@/lib/api/admin-families";
import type { BillingSetupRegistrationState } from "@/lib/api/admin";

export type LoginState = "not_invited" | "invited" | "active" | "no_access";
export type CardState = "no_card" | "on_file" | "declined";

export const LOGIN_LABELS: Record<LoginState, string> = {
  not_invited: "Not invited",
  invited: "Invited",
  active: "Active",
  // Not one of the three headline states: an account that exists but has been
  // switched off. Users is the only page that can say this.
  no_access: "No access",
};

export const CARD_LABELS: Record<CardState, string> = {
  no_card: "No card",
  on_file: "Card on file",
  declined: "Card declined",
};

export interface PeopleChip {
  label: string;
  variant: ChipVariant;
}

const LOGIN_VARIANTS: Record<LoginState, ChipVariant> = {
  not_invited: "manual",
  invited: "pending",
  active: "enrolled",
  no_access: "expired",
};

const CARD_VARIANTS: Record<CardState, ChipVariant> = {
  no_card: "manual",
  on_file: "paid",
  declined: "failed",
};

export function loginChip(state: LoginState): PeopleChip {
  return { label: LOGIN_LABELS[state], variant: LOGIN_VARIANTS[state] };
}

export function cardChip(state: CardState): PeopleChip {
  return { label: CARD_LABELS[state], variant: CARD_VARIANTS[state] };
}

/**
 * The two People reads spell registration differently — billing setup knows
 * whether a *login account* exists, family billing knows whether an *invite*
 * went out — so each value is mapped onto whichever facts its backend really
 * establishes, and never onto a claim it cannot support.
 */
export type PeopleRegistrationState = BillingSetupRegistrationState | RegistrationState;

const REGISTRATION_FACTS: Record<
  PeopleRegistrationState,
  { login: LoginState; card: CardState }
> = {
  // billing_setup_registration.py: has_card / has_login_account
  no_account: { login: "not_invited", card: "no_card" },
  account_no_card: { login: "active", card: "no_card" },
  card_on_file: { login: "active", card: "on_file" },
  // family_billing.py: has_card / last_invited_at
  not_invited: { login: "not_invited", card: "no_card" },
  invited: { login: "invited", card: "no_card" },
  registered: { login: "active", card: "on_file" },
};

export function loginStateFromRegistration(state: PeopleRegistrationState): LoginState {
  return REGISTRATION_FACTS[state].login;
}

export function cardStateFromRegistration(state: PeopleRegistrationState): CardState {
  return REGISTRATION_FACTS[state].card;
}

/**
 * `AdminUserView.status` is a bare string on the wire, so unknown values get a
 * neutral chip rather than a wrong claim about whether the person can log in.
 */
const USER_STATUS_LOGIN: Record<string, LoginState> = {
  active: "active",
  invited: "invited",
  pending: "invited",
  inactive: "no_access",
  disabled: "no_access",
  suspended: "no_access",
};

export function userLoginChip(status: string | null | undefined): PeopleChip {
  const known = USER_STATUS_LOGIN[(status ?? "").trim().toLowerCase()];
  if (known) return loginChip(known);
  const raw = (status ?? "").trim();
  if (!raw) return { label: "Unknown", variant: "manual" };
  return { label: raw[0].toUpperCase() + raw.slice(1).toLowerCase(), variant: "manual" };
}

/**
 * A Stripe decline code is a developer string; an admin needs a sentence they
 * can act on. Codes that hint at fraud (lost/stolen) deliberately read as a
 * plain decline — Stripe asks that we do not tip off the cardholder.
 */
const DECLINE_SENTENCES: Record<string, string> = {
  card_declined: "The bank declined this card.",
  generic_decline: "The bank declined this card without giving a reason.",
  do_not_honor: "The bank declined this card without giving a reason.",
  lost_card: "The bank declined this card.",
  stolen_card: "The bank declined this card.",
  insufficient_funds: "The card did not have enough funds.",
  expired_card: "The card has expired.",
  incorrect_cvc: "The card's security code was wrong.",
  incorrect_number: "The card number was wrong.",
  invalid_expiry_month: "The card's expiry date was wrong.",
  invalid_expiry_year: "The card's expiry date was wrong.",
  processing_error: "The card processor hit an error while charging this card.",
  authentication_required: "The bank wants the parent to confirm this payment.",
  card_not_supported: "The bank does not allow this card for this kind of payment.",
};

const DECLINE_FALLBACK = "The last charge on this card failed.";

export function describeCardDeclineCode(code: string | null | undefined): string {
  if (!code) return DECLINE_FALLBACK;
  return DECLINE_SENTENCES[code.trim().toLowerCase()] ?? DECLINE_FALLBACK;
}
