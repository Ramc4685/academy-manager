/**
 * The save steps behind the class form's Create and Edit dialogs.
 *
 * Kept out of the React component (and given its API calls as arguments) so
 * the money order can be unit tested: the class fee is written first, then the
 * plan link, because the link endpoint refuses a plan whose price is not the
 * class fee (409).
 */
import type {
  AdminSessionView,
  CreateSessionRequest,
  EditSessionRequest,
} from "@/lib/api/admin";

import {
  buildClassEditPayload,
  planLinkToWrite,
  priceChanges,
  type ClassFormValues,
} from "./class-form-logic";

export interface ClassSaveApi {
  updateSession: (
    sessionId: string,
    payload: EditSessionRequest,
  ) => Promise<AdminSessionView>;
  createSession: (payload: CreateSessionRequest) => Promise<AdminSessionView>;
  setClassPlan: (sessionId: string, planId: string | null) => Promise<unknown>;
}

function messageOf(err: unknown, fallback: string): string {
  const message = err instanceof Error ? err.message.trim() : "";
  return message || fallback;
}

export interface ClassEditSaveResult {
  /** The class as stored after the PATCH (always written when this returns). */
  saved: AdminSessionView;
  /** Whether a fee or plan link was written (pricing caches are stale). */
  pricingTouched: boolean;
  /** Set when the class saved but the plan link write failed. */
  linkError: string | null;
}

/**
 * PATCH the class, then write the plan link when the owner changed it.
 *
 * `pricingLoaded` is false until the Pricing overview is read: the class's
 * current link is unknown then, so no link is written.
 */
export async function saveClassEdit(
  params: {
    session: AdminSessionView;
    values: ClassFormValues;
    isOwner: boolean;
    pricingLoaded: boolean;
    initialChoice: string;
    choice: string;
  },
  api: Pick<ClassSaveApi, "updateSession" | "setClassPlan">,
): Promise<ClassEditSaveResult> {
  const { session, values, isOwner, pricingLoaded, initialChoice, choice } =
    params;
  const payload = buildClassEditPayload({ session, values, isOwner });
  const saved = await api.updateSession(session.session_id, payload);
  const link =
    isOwner && pricingLoaded
      ? planLinkToWrite(initialChoice, choice)
      : undefined;
  let linkError: string | null = null;
  if (link !== undefined) {
    try {
      await api.setClassPlan(saved.session_id, link);
    } catch (err) {
      linkError = `The class was saved, but the price plan was not updated: ${messageOf(
        err,
        "try again.",
      )}`;
    }
  }
  const feeWritten =
    "amount_cents" in payload &&
    priceChanges(session.amount_cents, payload.amount_cents);
  return { saved, pricingTouched: link !== undefined || feeWritten, linkError };
}

export interface ClassCreateSaveResult {
  created: AdminSessionView;
  /** Whether a plan link was attempted (pricing caches are stale). */
  pricingTouched: boolean;
  /** Set when the class was created but its plan link failed. */
  warning?: string;
}

/**
 * Create the class (fee included), then link it to the picked plan. A link
 * failure never throws: the class exists, and retrying Create would duplicate it.
 */
export async function saveClassCreate(
  params: {
    payload: CreateSessionRequest;
    isOwner: boolean;
    choice: string;
    customChoice: string;
  },
  api: Pick<ClassSaveApi, "createSession" | "setClassPlan">,
): Promise<ClassCreateSaveResult> {
  const { payload, isOwner, choice, customChoice } = params;
  const created = await api.createSession(payload);
  const link = isOwner ? planLinkToWrite(customChoice, choice) : undefined;
  if (!link) return { created, pricingTouched: false };
  try {
    await api.setClassPlan(created.session_id, link);
    return { created, pricingTouched: true };
  } catch (err) {
    return {
      created,
      pricingTouched: true,
      warning: `The class was created, but it was not linked to the plan: ${messageOf(
        err,
        "link it on Pricing.",
      )}`,
    };
  }
}
