/**
 * Pure gating logic for `DepartureActions`, split out from the `.tsx` file so
 * it can be unit-tested by vitest without a JSX/DOM transform — this repo's
 * `vitest.config.ts` runs a plain `node` environment (see
 * `screen-meta.ts`/`screen-meta.test.ts` for the same pattern).
 */

export type DepartureAction =
  | "transfer"
  | "hold"
  | "return"
  | "drop"
  | "delete"
  | "pause"
  | "resume"
  | "stop_all_classes"
  // Issue #820: undo a drop that was scheduled for the end of the period and
  // has not fired yet. Offered only on rows that actually have one. Named
  // "Undo", never "Cancel": in this interface Cancel belongs to classes and
  // dates, and enrollments are Dropped (see the label test).
  | "undo_scheduled_drop"
  // Issue #827: put a student who already left back into this class. Offered
  // only on a terminal row — there is no live seat to act on, so this opens
  // the ordinary "Add to roster" flow pre-filled with that student rather
  // than mutating the dead enrollment.
  | "re_enroll";

export const DEPARTURE_ACTION_LABEL: Record<DepartureAction, string> = {
  transfer: "Transfer",
  hold: "Hold",
  return: "Return",
  drop: "Drop",
  delete: "Delete",
  pause: "Pause",
  resume: "Resume",
  stop_all_classes: "Stop all classes",
  undo_scheduled_drop: "Undo scheduled drop",
  re_enroll: "Re-enroll",
};

/**
 * One line per action, shown under its label in the row's overflow menu
 * (#859). Before this, the roster kebab listed Pause, Hold, Drop and Delete as
 * bare words and an admin had to already know which of them keeps the seat,
 * which stops the invoice and which reaches the family.
 *
 * Each line answers the same three questions in the same order — seat,
 * billing, family email — so the items can be compared by scanning down the
 * column rather than by reading each one.
 *
 * The email clauses are read off the backend, NOT guessed:
 * - `WithdrawEnrollment` (Drop, and `StopAllClasses`, which composes over it),
 *   `StartHold` and `ReturnFromHold` call `HoldNotifier`, documented in
 *   `enrollment/application/ports.py` as the *family* email.
 * - `CancelEnrollment` (Delete), `TransferEnrollment`, `PauseEnrollment` and
 *   `ResumeEnrollment` call only `RosterChangeNotifier`, which tells the
 *   people who run the session, not the family.
 * Change the backend's notifications and these lines must move with them.
 *
 * No line may contain another action's label: the description is part of the
 * menu item's accessible name, and Playwright matches that name by substring,
 * so a stray "Pause" inside Resume's line would make every
 * `getByRole("menuitem", { name: "Pause" })` ambiguous. A unit test pins this.
 */
export const DEPARTURE_ACTION_DESCRIPTION: Record<DepartureAction, string> = {
  transfer:
    "Moves the student to another class; the seat and the invoice go with them. The family is not emailed.",
  hold: "Keeps the seat and stops billing until the agreed date. The family is emailed.",
  return: "Puts the student back in class and starts billing again. The family is emailed.",
  drop: "Ends the enrollment, frees the seat and stops billing. The family is emailed.",
  delete:
    "Takes the row off this roster and frees the seat, for one added in error. The family is not emailed.",
  pause:
    "Frees the seat and stops billing while the student is away; they join the waitlist. The family is not emailed.",
  resume:
    "Takes a seat back when one is free and starts billing again. The family is not emailed.",
  stop_all_classes:
    "Ends every enrollment this student has, across all their classes. The family is emailed.",
  undo_scheduled_drop:
    "Calls off the departure booked for the end of the period; seat and billing carry on. The family is not emailed.",
  re_enroll:
    "Opens the add-to-roster form with this student filled in; nothing changes, and the family is not emailed, until you confirm it.",
};

/**
 * Actions whose owner requirement is settable by the academy owner — today
 * only Delete, governed by `EnrollmentDeparturePolicy
 * .delete_enrollment_requires_owner` and passed in as `deleteRequiresOwner`
 * (#741).
 *
 * Delete used to be a hardcoded owner-only action here, which made the
 * Settings toggle (`delete_enrollment_requires_owner`, #701) inert in both
 * directions: turning it OFF still showed admins a disabled button. Every
 * other action is unconditionally open to admins.
 */
const POLICY_GATED_ACTIONS = new Set<DepartureAction>(["delete"]);

/**
 * Actions that always render inside the overflow menu, never as an inline
 * button — "Delete leaves the row: put it in an overflow menu."
 */
const ALWAYS_OVERFLOW_ACTIONS = new Set<DepartureAction>(["delete"]);

const DANGER_ACTIONS = new Set<DepartureAction>(["drop", "delete", "stop_all_classes"]);

export interface ResolvedDepartureAction {
  action: DepartureAction;
  label: string;
  /** One-line explanation of seat, billing and family email (#859). */
  description: string;
  disabled: boolean;
  /** True when disabled because the action needs the owner scope. */
  ownerGated: boolean;
  inOverflow: boolean;
  danger: boolean;
}

/**
 * - Renders only what `actions` lists — never infers availability from
 *   status.
 * - `delete` always lands in the overflow menu.
 * - An owner-only action a non-owner is given still renders (disabled, with
 *   a reason) rather than vanishing, so an admin can see the capability
 *   exists and who to ask.
 * - `layout: "inline"` keeps everything else as inline buttons; `"menu"`
 *   pushes every action into the overflow menu.
 * - `deleteRequiresOwner` is the academy's policy value (#741). Omitted or
 *   `undefined` — the policy has not loaded, or the caller has none — means
 *   the domain default, owner-only, which is also what the backend enforces
 *   for an unset policy. The backend re-checks this on every DELETE; this
 *   only decides whether the button reads as available.
 */
export function resolveDepartureActions(
  actions: readonly DepartureAction[],
  {
    isOwner,
    layout,
    deleteRequiresOwner = true,
  }: { isOwner: boolean; layout: "menu" | "inline"; deleteRequiresOwner?: boolean },
): ResolvedDepartureAction[] {
  return actions.map((action) => {
    const ownerGated = POLICY_GATED_ACTIONS.has(action) && deleteRequiresOwner && !isOwner;
    return {
      action,
      label: DEPARTURE_ACTION_LABEL[action],
      description: DEPARTURE_ACTION_DESCRIPTION[action],
      disabled: ownerGated,
      ownerGated,
      inOverflow: layout === "menu" || ALWAYS_OVERFLOW_ACTIONS.has(action),
      danger: DANGER_ACTIONS.has(action),
    };
  });
}

/**
 * Hold/Return availability for one enrollment row (#714 follow-up).
 *
 * Shared by the class roster and the student profile Sessions panel so both
 * surfaces answer "can this row be held / returned?" the same way. Kept
 * status-shaped and additive: it returns ONLY the hold pair, never the rest
 * of a surface's menu, so a caller splices it into whatever list it already
 * builds. Takes `string`, not `EnrollmentStatus`, because the student page's
 * `AdminStudentSessionSummary.status` is an untyped `string`.
 *
 * `active` and `held` are the only statuses that gained anything: #714 made
 * held rows visible on the roster but left Return unreachable, and holding is
 * only meaningful for a row still attending. Every other status falls through
 * to `[]`, so its menu stays exactly what it is today — `paused` keeps
 * Pause/Resume untouched.
 *
 * `reclaim_pending` (#697's second hold state) is deliberately absent: the
 * backend return route accepts `held`, and nothing in this slice establishes
 * what Return means mid-reclaim.
 */
export function holdActionsFor(status: string): DepartureAction[] {
  if (status === "active") return ["hold"];
  if (status === "held") return ["return"];
  return [];
}
