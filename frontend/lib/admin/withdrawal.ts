/**
 * Withdraw-dialog rules (issue #670).
 *
 * There is ONE withdraw path: every outcome goes through
 * `POST /admin/enrollments/{id}/withdraw`. The backend issues the account
 * credit itself for `outcome: "credit"` and refuses that outcome to anyone
 * without the `owner` scope (404, mirroring `require_owner`), so the option is
 * hidden from plain admins here rather than shown and then refused.
 */

import type { WithdrawEnrollmentRequest } from "@/lib/api/admin";
import type { DropDefaultOutcome } from "@/lib/api/v2/departure-policy";

export type WithdrawalOutcome = NonNullable<WithdrawEnrollmentRequest["outcome"]>;

export interface WithdrawalOutcomeOption {
  value: WithdrawalOutcome;
  label: string;
  /** Present when the option cannot be chosen by this user. */
  disabledReason?: string;
}

export const OWNER_ONLY_CREDIT_HINT = "Only the academy owner can issue an account credit.";

export function withdrawalOutcomeOptions(isOwner: boolean): WithdrawalOutcomeOption[] {
  return [
    {
      value: "credit",
      label: "Account credit",
      ...(isOwner ? {} : { disabledReason: OWNER_ONLY_CREDIT_HINT }),
    },
    { value: "refund", label: "Refund" },
    { value: "adjustment", label: "Admin adjustment" },
  ];
}

/** The fallback the dialog opens on when the academy has no departure policy
 * loaded yet: credit for owners, refund for admins. */
export function defaultWithdrawalOutcome(isOwner: boolean): WithdrawalOutcome {
  return isOwner ? "credit" : "refund";
}

/**
 * The academy's configured `drop_default_outcome`, translated into the
 * money-side outcome this dialog submits (design contract §1.2). The single
 * source of that mapping — `stop-all-classes-outcome.ts`'s `defaultOutcomeFor`
 * delegates here so the two drop paths can never drift apart.
 *
 * KNOWN GAP (issue #742): `no_credit_end_of_period` maps to `"adjustment"`,
 * i.e. attendance stops on the chosen date rather than at the period end.
 * No admin-side deferred drop exists yet — the only end-of-period mechanism
 * in the codebase is the parent self-cancel scheduled action — so the timing
 * half of that policy value is still not honoured anywhere. Tracked as the
 * follow-up on #742; this module only fixes the outcome half.
 */
export function policyWithdrawalOutcome(policyDefault: DropDefaultOutcome): WithdrawalOutcome {
  return policyDefault === "credit_mid_month" ? "credit" : "adjustment";
}

/**
 * The outcome the Drop dialog opens on (issue #742).
 *
 * Before this, the single-enrollment dialog ignored the departure policy and
 * always opened on credit/refund by role, so an academy whose configured
 * default was "no credit" silently dropped with a credit whenever the admin
 * did not touch the dropdown — unlike Stop all classes, which has honoured
 * the policy since #698.
 *
 * Two guards: with no policy loaded (still fetching, or the request failed)
 * the previous role-based default stands, so nothing changes for an academy
 * that never configured one; and a default of `credit` for a viewer without
 * the owner scope falls back to that role default rather than pre-selecting
 * the option `withdrawalOutcomeOptions` renders disabled.
 */
export function initialWithdrawalOutcome(
  policyDefault: DropDefaultOutcome | undefined,
  isOwner: boolean,
): WithdrawalOutcome {
  if (policyDefault === undefined) return defaultWithdrawalOutcome(isOwner);
  const outcome = policyWithdrawalOutcome(policyDefault);
  if (outcome === "credit" && !isOwner) return defaultWithdrawalOutcome(isOwner);
  return outcome;
}

/** The one request body both dialog paths used to build separately. */
export function buildWithdrawRequest(input: {
  withdrawalDate: string;
  outcome: WithdrawalOutcome;
  adminNote: string;
}): WithdrawEnrollmentRequest {
  const note = input.adminNote.trim();
  return {
    effective_date: input.withdrawalDate,
    outcome: input.outcome,
    reason: note || `Withdrawal ${input.outcome}`,
  };
}

const ALREADY_MOVED_ON_CODE = "Enrollment.NotWithdrawable";

export const OWNER_GATE_404_MESSAGE =
  "You do not have permission for that outcome. Ask the academy owner to issue the credit.";

export const NO_PAID_TUITION_MESSAGE =
  "There is no paid tuition on this enrollment to credit from. Withdraw with a refund or admin adjustment instead.";

/**
 * What the dialog shows when the withdraw fails. A 409 means the row already
 * moved on (withdrawn or cancelled in another tab); the server's message says
 * which, so surface it verbatim rather than a generic failure.
 *
 * 404 is overloaded on this route, so the copy is keyed off the error CODE,
 * not the status: the owner gate raises a bare `HTTPException(404, "Not
 * found")` with no code, while `Billing.PaymentNotFound` and
 * `Enrollment.NotFound` are domain errors that carry one. Telling the academy
 * owner to "ask the academy owner" hid the real cause (issue #670 review).
 */
export function withdrawErrorMessage(
  err: { status?: number; code?: string; message?: string } | null | undefined,
): string {
  if (!err) return "Could not withdraw enrollment.";
  if (err.status === 409 || err.code === ALREADY_MOVED_ON_CODE) {
    return err.message?.trim() || "This enrollment was already withdrawn or cancelled.";
  }
  if (err.status === 404) {
    if (!err.code) return OWNER_GATE_404_MESSAGE;
    if (err.code === "Billing.PaymentNotFound") return NO_PAID_TUITION_MESSAGE;
    return err.message?.trim() || "That enrollment could not be found.";
  }
  return err.message?.trim() || "Could not withdraw enrollment.";
}
