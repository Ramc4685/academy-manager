/**
 * Truthful stat rendering for a query-backed screen (issue #837).
 *
 * A stat tile fed by a normalizer ("coerce anything, never throw") prints the
 * normalizer's zero when the request failed — `$0.00 owed`, `0 needs action`,
 * `0 students` — which is indistinguishable from "all clear". These helpers
 * make "we do not know" render as a dash, so the only zero on screen is a
 * zero the backend actually sent.
 *
 * Pair them with `ErrorNotice` (components/ds/error-notice.tsx), which gives
 * the failure a visible message and a Try again button.
 */

/** What a tile shows when the number is not known yet (or not at all). */
export const UNKNOWN_TEXT = "—";

/** What a detail row shows when a field is missing from the payload. */
export const NO_DATA_TEXT = "No data";

/**
 * The slice of a react-query result these helpers read. Accepting a plain
 * object (rather than the query itself) keeps this module pure and testable:
 * `useQuery` and `useInfiniteQuery` results both satisfy it.
 */
export type LoadState = {
  isLoading?: boolean;
  isError?: boolean;
  isPending?: boolean;
};

/** True only when the data actually arrived — not loading, not failed. */
export function isSettled(state: LoadState): boolean {
  return !state.isLoading && !state.isPending && !state.isError;
}

/**
 * A stat's display text. Returns a dash — never the caller's formatted zero —
 * while the query is in flight or after it failed. The formatter is not even
 * called in those cases, so it may read straight off an empty normalizer.
 */
export function statText(state: LoadState, value: () => string): string {
  return isSettled(state) ? value() : UNKNOWN_TEXT;
}

/**
 * A stat's supporting line ("2 families", "failed autopay · past due"). Hidden
 * until the data arrived, because a hint under a dash asserts a fact too.
 */
export function statHint(state: LoadState, hint: () => string): string | undefined {
  return isSettled(state) ? hint() : undefined;
}

/**
 * Format a number that an incomplete payload may have left out. A missing
 * field reaching `Intl.NumberFormat` renders "$NaN" / "NaN%" on screen; this
 * renders the fallback instead.
 */
export function finiteText(
  value: number | null | undefined,
  format: (value: number) => string,
  fallback: string = NO_DATA_TEXT,
): string {
  return typeof value === "number" && Number.isFinite(value) ? format(value) : fallback;
}
