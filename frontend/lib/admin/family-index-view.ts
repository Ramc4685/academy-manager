/**
 * View model for the People CRM Families view (`/admin/families`,
 * engineering-spec §3.2), over `GET /admin/families` and
 * `GET /admin/families/summary`.
 *
 * Everything here is presentation: the URL <-> filter state round trip, which
 * preset chip is pressed, which way a column sorts, and how a search hit turns
 * into result rows. Filtering, sorting, paging and every money figure are the
 * backend's (`contexts/crm/application/family_index.py`); nothing in this file
 * computes or infers an amount.
 */

import type { Route } from "next";

import type {
  FamilyIndexChild,
  FamilyIndexParams,
  FamilyIndexRow,
  FamilyIndexSort,
  FamilyScope,
  FamilyStage,
  FamilyViewPreset,
} from "@/lib/api/admin-families";

export const FAMILY_SCOPES: readonly FamilyScope[] = ["active", "leaving", "left"];

export const FAMILY_STAGES: readonly FamilyStage[] = [
  "pending_cancel",
  "active",
  "at_risk",
  "on_hold",
  "paused",
  "trial",
  "never_enrolled",
  "left",
];

const SORTS: readonly FamilyIndexSort[] = ["name", "stage", "balance", "children"];
const ORDERS = ["asc", "desc"] as const;

/** The filter state the URL carries. `q` is the search box. */
export interface FamilyIndexState {
  q: string;
  scope: FamilyScope | null;
  stage: FamilyStage[];
  classId: string | null;
  cardOnFile: boolean | null;
  overdue: boolean | null;
  sort: FamilyIndexSort | null;
  order: "asc" | "desc" | null;
}

export const EMPTY_FAMILY_INDEX_STATE: FamilyIndexState = {
  q: "",
  scope: null,
  stage: [],
  classId: null,
  cardOnFile: null,
  overdue: null,
  sort: null,
  order: null,
};

/** The URL keys this view owns. Anything else (`view=`) is left untouched. */
const OWNED_KEYS = ["q", "scope", "stage", "class_id", "card_on_file", "overdue", "sort", "order"];

function parseBool(value: string | null): boolean | null {
  if (value === "true") return true;
  if (value === "false") return false;
  return null;
}

function oneOf<T extends string>(value: string | null, allowed: readonly T[]): T | null {
  return value !== null && (allowed as readonly string[]).includes(value) ? (value as T) : null;
}

function parseStages(values: readonly string[]): FamilyStage[] {
  const stages = values
    .flatMap((value) => value.split(","))
    .map((value) => value.trim())
    .filter((value): value is FamilyStage => (FAMILY_STAGES as readonly string[]).includes(value));
  return Array.from(new Set(stages));
}

/**
 * A hand-edited or stale URL must never reach the API as a 422: unknown
 * values are dropped here rather than sent.
 */
export function parseFamilyIndexState(params: URLSearchParams): FamilyIndexState {
  const classId = params.get("class_id")?.trim() ?? "";
  return {
    q: params.get("q") ?? "",
    scope: oneOf(params.get("scope"), FAMILY_SCOPES),
    stage: parseStages(params.getAll("stage")),
    classId: classId ? classId.slice(0, 64) : null,
    cardOnFile: parseBool(params.get("card_on_file")),
    overdue: parseBool(params.get("overdue")),
    sort: oneOf(params.get("sort"), SORTS),
    order: oneOf(params.get("order"), ORDERS),
  };
}

/** `base` with this view's keys replaced by `state`; other keys survive. */
export function writeFamilyIndexState(
  base: URLSearchParams,
  state: FamilyIndexState,
): URLSearchParams {
  const next = new URLSearchParams(base);
  for (const key of OWNED_KEYS) next.delete(key);
  const q = state.q.trim();
  if (q) next.set("q", q);
  if (state.scope) next.set("scope", state.scope);
  for (const stage of state.stage) next.append("stage", stage);
  if (state.classId) next.set("class_id", state.classId);
  if (state.cardOnFile !== null) next.set("card_on_file", String(state.cardOnFile));
  if (state.overdue !== null) next.set("overdue", String(state.overdue));
  if (state.sort) next.set("sort", state.sort);
  if (state.order) next.set("order", state.order);
  return next;
}

export function toFamilyIndexParams(
  state: FamilyIndexState,
  page: number,
  pageSize: number,
): FamilyIndexParams {
  const q = state.q.trim();
  return {
    search: q ? q.slice(0, 120) : undefined,
    scope: state.scope ?? undefined,
    stage: state.stage.length ? state.stage : undefined,
    class_id: state.classId ?? undefined,
    card_on_file: state.cardOnFile ?? undefined,
    overdue: state.overdue ?? undefined,
    sort: state.sort ?? undefined,
    order: state.order ?? undefined,
    page,
    page_size: pageSize,
  };
}

// ---------------------------------------------------------------------------
// Presets
// ---------------------------------------------------------------------------

/**
 * Used only when the summary cannot be read: the no-money subset of the
 * backend's `VIEW_PRESETS`, so the chips never offer a money filter to a
 * caller the server has not cleared for money.
 */
export const FALLBACK_PRESETS: readonly FamilyViewPreset[] = [
  { id: "active", label: "Active", params: { scope: "active" }, money: false },
  { id: "leaving", label: "Leaving", params: { scope: "leaving" }, money: false },
  { id: "left", label: "Left", params: { scope: "left" }, money: false },
  { id: "no_card", label: "No card", params: { card_on_file: "false" }, money: false },
];

/** The preset-relevant keys of `state`, in the shape a preset's params use. */
function presetValues(state: FamilyIndexState): Record<string, string | undefined> {
  return {
    scope: state.scope ?? undefined,
    card_on_file: state.cardOnFile === null ? undefined : String(state.cardOnFile),
    overdue: state.overdue === null ? undefined : String(state.overdue),
    class_id: state.classId ?? undefined,
    sort: state.sort ?? undefined,
    order: state.order ?? undefined,
    stage: state.stage.length ? state.stage.join(",") : undefined,
  };
}

export function isPresetActive(preset: FamilyViewPreset, state: FamilyIndexState): boolean {
  const values = presetValues(state);
  const entries = Object.entries(preset.params);
  return entries.length > 0 && entries.every(([key, value]) => values[key] === value);
}

function applyParam(state: FamilyIndexState, key: string, value: string | null): FamilyIndexState {
  switch (key) {
    case "scope":
      return { ...state, scope: oneOf(value, FAMILY_SCOPES) };
    case "card_on_file":
      return { ...state, cardOnFile: parseBool(value) };
    case "overdue":
      return { ...state, overdue: parseBool(value) };
    case "class_id":
      return { ...state, classId: value || null };
    case "sort":
      return { ...state, sort: oneOf(value, SORTS) };
    case "order":
      return { ...state, order: oneOf(value, ORDERS) };
    case "stage":
      return { ...state, stage: value ? parseStages([value]) : [] };
    default:
      // A preset key this build does not know is ignored, never guessed at.
      return state;
  }
}

/**
 * A preset chip is a toggle (`aria-pressed`), applied on click only. Pressing
 * an active one clears exactly the keys it set; pressing another sets its
 * keys and leaves the rest (search, class, other chips) as they were. Two
 * scope presets share the `scope` key, so they replace each other.
 */
export function togglePreset(state: FamilyIndexState, preset: FamilyViewPreset): FamilyIndexState {
  const active = isPresetActive(preset, state);
  return Object.entries(preset.params).reduce(
    (acc, [key, value]) => applyParam(acc, key, active ? null : value),
    state,
  );
}

/** "All families": every filter chip off; search, class and sort kept. */
export function clearFilterChips(state: FamilyIndexState): FamilyIndexState {
  return { ...state, scope: null, stage: [], cardOnFile: null, overdue: null };
}

export function hasFilterChips(state: FamilyIndexState): boolean {
  return (
    state.scope !== null ||
    state.stage.length > 0 ||
    state.cardOnFile !== null ||
    state.overdue !== null
  );
}

// ---------------------------------------------------------------------------
// Sorting
// ---------------------------------------------------------------------------

/** Mirrors `query_family_index`: balance runs high-to-low by default, the rest A-Z. */
export function effectiveOrder(state: FamilyIndexState, moneyVisible: boolean): "asc" | "desc" {
  if (state.order) return state.order;
  return (state.sort ?? "name") === "balance" && moneyVisible ? "desc" : "asc";
}

/** Clicking a header: the same column flips direction; a new column starts on its default. */
export function nextSort(
  state: FamilyIndexState,
  column: FamilyIndexSort,
  moneyVisible: boolean,
): FamilyIndexState {
  const current = state.sort ?? "name";
  if (current === column) {
    return {
      ...state,
      sort: column === "name" ? null : column,
      order: effectiveOrder(state, moneyVisible) === "asc" ? "desc" : "asc",
    };
  }
  return { ...state, sort: column === "name" ? null : column, order: null };
}

export function ariaSort(
  state: FamilyIndexState,
  column: FamilyIndexSort,
  moneyVisible: boolean,
): "ascending" | "descending" | "none" {
  if ((state.sort ?? "name") !== column) return "none";
  return effectiveOrder(state, moneyVisible) === "asc" ? "ascending" : "descending";
}

// ---------------------------------------------------------------------------
// Rows
// ---------------------------------------------------------------------------

export type FamilyResultRow =
  | { kind: "family"; key: string; family: FamilyIndexRow }
  | { kind: "child"; key: string; family: FamilyIndexRow; child: FamilyIndexChild };

/**
 * Spec §3.2: when the search matched a child (and not the parent), that child
 * is the result row, with the parent as secondary text, linking straight to
 * the child's page. A parent match, or no search at all, keeps the family row.
 */
export function familyResultRows(
  families: readonly FamilyIndexRow[],
  searching: boolean,
): FamilyResultRow[] {
  const rows: FamilyResultRow[] = [];
  for (const family of families) {
    const matchedChildren = searching ? family.children.filter((child) => child.matched) : [];
    if (matchedChildren.length > 0 && !family.matched_parent) {
      for (const child of matchedChildren) {
        rows.push({
          kind: "child",
          key: `child-${family.family_id}-${child.student_id}`,
          family,
          child,
        });
      }
    } else {
      rows.push({ kind: "family", key: `family-${family.family_id}`, family });
    }
  }
  return rows;
}

/**
 * The family record is the Billing page today, and it 404s for a parent id no
 * users document answers to (`has_account = false`). Those rows get no link.
 */
export function familyHref(family: FamilyIndexRow): Route | null {
  if (!family.has_account) return null;
  return `/admin/families/${encodeURIComponent(family.family_id)}` as Route;
}

export function studentHref(studentId: string): Route {
  return `/admin/students/${encodeURIComponent(studentId)}` as Route;
}

export function familyDisplayName(family: FamilyIndexRow): string {
  return family.parent_name?.trim() || family.email?.trim() || "Unnamed family";
}

/** Distinct classes across a family's children, in first-seen order. */
export function familyClasses(family: FamilyIndexRow): { session_id: string; title: string }[] {
  const seen = new Map<string, string>();
  for (const child of family.children) {
    for (const cls of child.classes) {
      if (!seen.has(cls.session_id)) seen.set(cls.session_id, cls.title);
    }
  }
  return Array.from(seen, ([session_id, title]) => ({ session_id, title }));
}

/**
 * Options for the Class filter: the academy's sessions plus any class a
 * loaded family already carries, de-duplicated and sorted by title. A class
 * id from the URL that neither source knows stays selectable, so a shared
 * link never silently shows a filtered list under a blank picker.
 */
export function classOptions(
  sessions: readonly { session_id: string; title: string }[],
  families: readonly FamilyIndexRow[],
  selectedId: string | null,
): { value: string; label: string }[] {
  const byId = new Map<string, string>();
  const add = (id: string, title: string) => {
    if (id && !byId.has(id)) byId.set(id, title.trim() || "Untitled class");
  };
  for (const session of sessions) add(session.session_id, session.title);
  for (const family of families) {
    for (const cls of familyClasses(family)) add(cls.session_id, cls.title);
  }
  if (selectedId) add(selectedId, "Selected class");
  return Array.from(byId, ([value, label]) => ({ value, label })).sort((a, b) =>
    a.label.localeCompare(b.label),
  );
}
