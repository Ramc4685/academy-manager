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
  | "stop_all_classes";

export const DEPARTURE_ACTION_LABEL: Record<DepartureAction, string> = {
  transfer: "Transfer",
  hold: "Hold",
  return: "Return",
  drop: "Drop",
  delete: "Delete",
  pause: "Pause",
  resume: "Resume",
  stop_all_classes: "Stop all classes",
};

/** Actions that require the owner scope regardless of who supplied them. */
const OWNER_ONLY_ACTIONS = new Set<DepartureAction>(["delete"]);

/**
 * Actions that always render inside the overflow menu, never as an inline
 * button — "Delete leaves the row: put it in an overflow menu."
 */
const ALWAYS_OVERFLOW_ACTIONS = new Set<DepartureAction>(["delete"]);

const DANGER_ACTIONS = new Set<DepartureAction>(["drop", "delete", "stop_all_classes"]);

export interface ResolvedDepartureAction {
  action: DepartureAction;
  label: string;
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
 */
export function resolveDepartureActions(
  actions: readonly DepartureAction[],
  { isOwner, layout }: { isOwner: boolean; layout: "menu" | "inline" },
): ResolvedDepartureAction[] {
  return actions.map((action) => {
    const ownerGated = OWNER_ONLY_ACTIONS.has(action) && !isOwner;
    return {
      action,
      label: DEPARTURE_ACTION_LABEL[action],
      disabled: ownerGated,
      ownerGated,
      inOverflow: layout === "menu" || ALWAYS_OVERFLOW_ACTIONS.has(action),
      danger: DANGER_ACTIONS.has(action),
    };
  });
}
