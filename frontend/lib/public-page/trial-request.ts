/**
 * The anonymous trial request form's client logic (Lane B4).
 *
 * Posts to `POST /api/v2/public/trial-requests` through the same-origin BFF
 * proxy (`app/api/v2/[...path]/route.ts`), with plain `fetch`: no auth
 * token, no `X-Academy-Id`. The academy is decided by the backend from the
 * host the visitor is on, never by anything this module sends.
 *
 * The backend answers one acknowledgement for a new request, a repeat and a
 * honeypot hit alike, so this module cannot tell them apart either, by
 * design. Client-side checks here only save a round trip; the server's
 * validation (`backend/v2/contexts/crm/application/use_cases/submit_website_inquiry.py`)
 * is the one that counts.
 */

import { formatSeatBand, formatTimeRange, formatWhen, truncate } from "./format";
import type { PublicClass } from "./types";

export const TRIAL_REQUESTS_PATH = "/api/v2/public/trial-requests";

/** Limits mirrored from the backend so the inputs can say so up front. */
export const TRIAL_LIMITS = {
  name: 120,
  email: 254,
  phone: 40,
  age: 20,
  message: 1000,
} as const;

export type TrialField =
  "name" | "email" | "phone" | "player_age" | "class_id" | "message" | "contact_about_request";

/** Order the error summary lists fields in (the visual order of the form). */
export const TRIAL_FIELD_ORDER: TrialField[] = [
  "name",
  "email",
  "phone",
  "player_age",
  "class_id",
  "message",
  "contact_about_request",
];

export const TRIAL_FIELD_LABEL: Record<TrialField, string> = {
  name: "Your name",
  email: "Email",
  phone: "Phone",
  player_age: "Player's age",
  class_id: "Class",
  message: "Anything the coach should know",
  contact_about_request: "Contact me about this request",
};

export interface TrialFormValues {
  name: string;
  email: string;
  phone: string;
  player_age: string;
  class_id: string;
  message: string;
  contact_about_request: boolean;
  marketing_opt_in: boolean;
  /** Honeypot: hidden from people and assistive technology. */
  website: string;
}

export const EMPTY_TRIAL_FORM: TrialFormValues = {
  name: "",
  email: "",
  phone: "",
  player_age: "",
  class_id: "",
  message: "",
  contact_about_request: false,
  marketing_opt_in: false,
  website: "",
};

export type TrialFieldErrors = Partial<Record<TrialField, string>>;

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/** Same rules and wording as the backend, so the two never disagree visibly. */
export function validateTrialForm(values: TrialFormValues): TrialFieldErrors {
  const errors: TrialFieldErrors = {};
  const name = values.name.trim();
  if (!name) errors.name = "Enter your name.";
  else if (name.length > TRIAL_LIMITS.name)
    errors.name = "Keep your name to 120 characters or fewer.";
  const email = values.email.trim();
  if (!email) errors.email = "Enter your email address.";
  else if (email.length > TRIAL_LIMITS.email || !EMAIL.test(email)) {
    errors.email = "Enter an email address like name@example.com.";
  }
  const phone = values.phone.trim();
  if (phone) {
    const digits = phone.replace(/\D/g, "");
    if (phone.length > TRIAL_LIMITS.phone || digits.length < 7 || digits.length > 15) {
      errors.phone = "Enter a phone number with 7 to 15 digits, or leave it blank.";
    }
  }
  const age = values.player_age.trim();
  if (!age) errors.player_age = "Enter the player's age.";
  else if (age.length > TRIAL_LIMITS.age)
    errors.player_age = "Keep the age to 20 characters or fewer.";
  if (values.message.trim().length > TRIAL_LIMITS.message) {
    errors.message = "Keep the message to 1000 characters or fewer.";
  }
  if (!values.contact_about_request) {
    errors.contact_about_request =
      "Tick this box so the academy can contact you about your request.";
  }
  return errors;
}

/** The JSON body. Blank optional fields are sent as null; no child name, ever. */
export function trialRequestBody(values: TrialFormValues): Record<string, unknown> {
  const optional = (value: string) => (value.trim() ? value.trim() : null);
  return {
    name: values.name.trim(),
    email: values.email.trim(),
    phone: optional(values.phone),
    player_age: values.player_age.trim(),
    class_id: optional(values.class_id),
    message: optional(values.message),
    contact_about_request: values.contact_about_request,
    marketing_opt_in: values.marketing_opt_in,
    website: values.website,
  };
}

export type TrialSubmitResult =
  | { kind: "received" }
  | { kind: "invalid"; fields: TrialFieldErrors; message: string | null }
  | { kind: "closed"; message: string }
  | { kind: "rate_limited" }
  | { kind: "failed" };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const KNOWN_FIELDS = new Set<string>(TRIAL_FIELD_ORDER);

/** Map any backend answer onto the five outcomes the form can show. */
export function classifyTrialResponse(status: number, body: unknown): TrialSubmitResult {
  if (status === 200 && isRecord(body) && body.state === "received") return { kind: "received" };
  const error = isRecord(body) && isRecord(body.error) ? body.error : null;
  const message = error && typeof error.message === "string" ? error.message : null;
  if (status === 409 && error?.code === "Public.TrialsClosed") {
    return {
      kind: "closed",
      message: message ?? "Free trials are paused right now.",
    };
  }
  if (status === 422 && error && isRecord(error.details) && isRecord(error.details.fields)) {
    const fields: TrialFieldErrors = {};
    let unknown: string | null = null;
    for (const [key, value] of Object.entries(error.details.fields)) {
      if (typeof value !== "string") continue;
      if (KNOWN_FIELDS.has(key)) fields[key as TrialField] = value;
      else unknown = unknown ?? value;
    }
    return {
      kind: "invalid",
      fields,
      message: unknown ?? (Object.keys(fields).length ? null : message),
    };
  }
  if (status === 429) return { kind: "rate_limited" };
  return { kind: "failed" };
}

export async function submitTrialRequest(
  values: TrialFormValues,
  fetchImpl: typeof fetch = fetch,
): Promise<TrialSubmitResult> {
  let response: Response;
  try {
    response = await fetchImpl(TRIAL_REQUESTS_PATH, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(trialRequestBody(values)),
      credentials: "omit",
      cache: "no-store",
    });
  } catch {
    return { kind: "failed" };
  }
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  return classifyTrialResponse(response.status, body);
}

export interface TrialClassOption {
  value: string;
  label: string;
}

/** Class choices for the select, in page order; a full class says so. */
export function trialClassOptions(classes: PublicClass[]): TrialClassOption[] {
  return classes.map((cls) => {
    const when = [formatWhen(cls), formatTimeRange(cls.start_time, cls.end_time)]
      .filter(Boolean)
      .join(" ");
    const full = formatSeatBand(cls.seats)?.full === true;
    const label = [truncate(cls.title, 60), when].filter(Boolean).join(", ");
    return {
      value: cls.public_id,
      label: full ? `${label} (full, join waitlist)` : label,
    };
  });
}
