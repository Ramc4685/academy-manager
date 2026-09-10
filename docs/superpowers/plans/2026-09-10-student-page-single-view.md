# Student Page Single View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the five-tab admin student detail page with one scrolling page (sticky rail + collapsible sections) so an admin can see status, enrollments, training, billing and compliance without clicking through tabs.

**Architecture:** `page.tsx` keeps its three top-level queries (student, departure policy, parents-for-ChangeParentPanel-until-the-last-task) and stops gating panel content behind a tab switch; every section mounts and fetches its own data, same as today. A new pure `section-state.ts` module decides each section's open/closed default (static per spec, except Compliance which is computed from the loaded student) and is wrapped by a small in-page hook that persists the viewer's own toggles to `localStorage` and honors a `#section` deep link. The Enrollments section gets a new `EnrollmentsSection.tsx` orchestrator that fetches session-type billing (moved out of the now-decommissioned standalone `BillingEnrollmentsPanel`) and feeds it into `SessionsPanel`'s existing table as extra columns/actions, joined on the `enrollment_id` the two data sources already share.

**Tech Stack:** Next.js 16 (webpack build) app router, TanStack Query, Tailwind, `frontend/components/ds` design system, Vitest (`environment: "node"`, no DOM — component behavior is verified by Playwright, not RTL), Playwright e2e.

## Global Constraints

- Tab-based navigation (`role="tab"`, `STUDENT_TABS`, `StudentTabs`, `TabPanel`) is removed entirely; sections are always mounted.
- Section ids, in column order: `enrollments`, `training`, `billing`, `profile`, `compliance`.
- Default open state: `enrollments` open, `training` open, `billing` closed (its one-line summary is always visible regardless), `profile` closed, `compliance` computed — open only when `student.waiver_status !== "signed"`, closed otherwise. This is the one "something outstanding" signal the page's existing data supports (see Self-review).
- Once a viewer toggles a section, their choice is persisted to `localStorage` key `admin-student-sections-v1` and wins over the computed/static default on every later visit.
- A `#<sectionId>` URL hash on load force-opens that section and scrolls it into view, regardless of stored/default state, and does not overwrite the stored preference for other sections.
- `StudentEditForm`'s `mode` prop is removed; one form holds identity fields, DOB, status, notes, previous experience, medical notes, emergency contact name/phone, and t-shirt size.
- `ChangeParentPanel` and the `parentsQuery` that feeds it are removed from this page as the last task, gated on the family page already shipping "Move child to another family" (spec 2 §6) — verified by inspection, not assumed. **Plan 2 (`docs/superpowers/plans/2026-09-10-families-directory-consolidation.md`) does NOT build that control** — its Self-review §6 row defers "Move child to another family" to a follow-on. In the agreed build order (plan 1 → plan 2 → this plan → plan 3) Task 11's gate therefore fails and Task 11 is skipped; `ChangeParentPanel` stays on this page until the follow-on ships. Task 13's release note is worded for that outcome.
- No backend change, no new endpoint. `getAdminUser` (existing `/admin/users/{id}` route) is a new *call site* on this page (rail login badge), not a new endpoint.
- `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json` is untouched — no new `app/` route is added. Every new file in `app/(admin)/admin/students/[studentId]/` is a co-located component, not a route segment (same as the existing `SessionsPanel.tsx`, `StatusChip.tsx`, …), so the route count and the four backend inventory tests are unaffected.
  - OPEN QUESTION (owner): that manifest's entry for `/admin/students/[studentId]` (lines ~1665-1735) names workflows **"Billing tab"** and **"Family tab"**, the risk edge **"Selected invoice stale after tab switch"**, the input **"Parent selector"** and the modal **"Parent change"** — all of which this change deletes. Leaving it untouched keeps CI green (`test_inventory_acceptance_coverage.py` only checks manifest-internal consistency) but leaves the audit artifact describing a page that no longer exists. Decide: (a) leave it as a point-in-time 2026-06-28 record, or (b) rename those workflows/controls in the same PR — option (b) means editing the matching `acceptance` strings too, or the coverage test fails.
- Frontend Vitest specs run in **no CI job** in this repo, so Tasks 1/3/4's unit tests are a local-only gate. Run them yourself (`pnpm test:unit` or the per-file commands below); do not assume CI will catch a red one.
- Cross-plan dependency: spec §3.1 says the Enrollments table carries "the spec-1 action set". That action set (Hold / Return / Drop / Delete via `DepartureActions`' overflow menu, computed per row by `departureActionsFor(session.status)` from `@/components/admin/enrollment/departure-actions`) is delivered by the **sibling plan** `docs/superpowers/plans/2026-09-10-departure-actions-from-student-page.md` (plan 1), which lands **before** this plan in the agreed order (1 → 2 → 4 → 3). This plan must not re-implement it: by the time Task 5 runs, `SessionsPanel.tsx`'s action `<td>` already renders `actions={departureActionsFor(session.status)}` and mounts `HoldEnrollmentDialog` / `ReturnFromHoldDialog` / `WithdrawalCreditDialog` / `RemoveEnrollmentDialog` from `@/components/admin/enrollment/*`, and `SessionsPanel` already takes the **required** `studentName: string` and optional `familyLabel?: string | null` props (plan 1 Task 9). Task 5 leaves that `<DepartureActions>` block and those props untouched and only adds the billing cell / Move-Override buttons around them; Task 7's `EnrollmentsSection` must forward `studentName` and `familyLabel` (plan 1's `page.tsx` wiring is replaced wholesale by Task 10). Line numbers quoted in Task 5 are pre-plan-1 — locate by landmark, not by line.

## File structure

| File | Responsibility |
|---|---|
| `frontend/app/(admin)/admin/students/[studentId]/section-state.ts` | New. Pure section-id list, default-open rule, localStorage parse/serialize, hash → section-id parsing. |
| `frontend/app/(admin)/admin/students/[studentId]/section-state.test.ts` | New. Unit tests for the above. |
| `frontend/app/(admin)/admin/students/[studentId]/CollapsibleSection.tsx` | New. One disclosure `Card` used for every section; owns the toggle button, anchor id, `aria-expanded`. |
| `frontend/app/(admin)/admin/students/[studentId]/StudentRail.tsx` | New. Sticky left rail: avatar/name/status/level/DOB-age, Stop all classes, family card with login badge, section jump links. |
| `frontend/app/(admin)/admin/students/[studentId]/session-rows.ts` | Modified. Adds `billingFactsByEnrollmentId` (joins session-type billing into session rows) and `billingSummaryFacts`/`billingSummaryLine` (Billing section's always-visible line). |
| `frontend/app/(admin)/admin/students/[studentId]/session-rows.test.ts` | Modified. New `describe` blocks for the two additions. |
| `frontend/app/(admin)/admin/students/[studentId]/format.ts` | Modified. Adds `formatAgeFromDob` for the rail. |
| `frontend/app/(admin)/admin/students/[studentId]/format.test.ts` | Modified. Tests `formatAgeFromDob`. |
| `frontend/app/(admin)/admin/students/[studentId]/SessionsPanel.tsx` | Modified. Enrolled-sessions table gains a session-type billing cell + Move/Override-price actions per row (via new optional props); `PastEnrollmentsPanel` collapses after 5 rows. |
| `frontend/app/(admin)/admin/students/[studentId]/BillingEnrollmentsPanel.tsx` | Modified. Standalone panel/table removed; keeps and exports `MoveEnrollmentDialog`, `OverridePriceDialog`, `ProrationResult` for reuse by `EnrollmentsSection`. |
| `frontend/app/(admin)/admin/students/[studentId]/EnrollmentsSection.tsx` | New. Fetches billing enrollments + session types, owns the move/override dialog state, renders `SessionsPanel` + the shared dialogs. |
| `frontend/app/(admin)/admin/students/[studentId]/BillingSummaryLine.tsx` | New. Renders the always-visible Billing summary line from `session-rows.ts` facts. |
| `frontend/app/(admin)/admin/students/[studentId]/StudentEditForm.tsx` | Modified. `StudentEditForm` loses its `mode` prop and becomes one form; `ChangeParentPanel` stays defined, unused by this page after the last task. |
| `frontend/app/(admin)/admin/students/[studentId]/page.tsx` | Modified. Tabs removed; renders `StudentRail` + 5 `CollapsibleSection`s. |
| `frontend/e2e/specs/admin-students.spec.ts` | Modified. Tab clicks/testids replaced with section ids; assertions re-sequenced to match the new default-open state; adds the `GET /admin/users/{parentId}` stub the rail's family card now needs. |
| `frontend/e2e/specs/tuition-discounts.spec.ts` | Modified. Also drives `/admin/students/[studentId]` and clicks the Sessions and Billing tabs (lines 458, 497); same de-tabbing + the new parent-detail stub. |
| `docs/release-notes/2026-09-10-student-page-single-view.md` | New. Release note (final task). |

---

### Task 1: Section-state pure helpers

**Files:**
- Create: `frontend/app/(admin)/admin/students/[studentId]/section-state.ts`
- Test: `frontend/app/(admin)/admin/students/[studentId]/section-state.test.ts`

**Interfaces:**
- Produces: `SectionId` type, `SECTION_IDS: SectionId[]`, `SECTION_STORAGE_KEY: string`, `isValidSectionId(value: string): value is SectionId`, `defaultSectionOpen(id: SectionId, complianceOutstanding: boolean): boolean`, `parseStoredSections(raw: string | null): Partial<Record<SectionId, boolean>>`, `serializeSections(state: Partial<Record<SectionId, boolean>>): string`, `sectionIdFromHash(hash: string): SectionId | null`.
- Consumes: nothing (pure).

- [ ] Write the failing test file:

```ts
import { describe, expect, it } from "vitest";

import {
  SECTION_IDS,
  defaultSectionOpen,
  isValidSectionId,
  parseStoredSections,
  sectionIdFromHash,
  serializeSections,
} from "./section-state";

describe("SECTION_IDS", () => {
  it("lists the five sections in column order", () => {
    expect(SECTION_IDS).toEqual(["enrollments", "training", "billing", "profile", "compliance"]);
  });
});

describe("isValidSectionId", () => {
  it("accepts known ids and rejects everything else", () => {
    expect(isValidSectionId("billing")).toBe(true);
    expect(isValidSectionId("sessions")).toBe(false);
    expect(isValidSectionId("")).toBe(false);
  });
});

describe("defaultSectionOpen", () => {
  it("opens enrollments and training, keeps billing and profile closed", () => {
    expect(defaultSectionOpen("enrollments", false)).toBe(true);
    expect(defaultSectionOpen("training", false)).toBe(true);
    expect(defaultSectionOpen("billing", false)).toBe(false);
    expect(defaultSectionOpen("profile", false)).toBe(false);
  });

  it("opens compliance only when something is outstanding", () => {
    expect(defaultSectionOpen("compliance", true)).toBe(true);
    expect(defaultSectionOpen("compliance", false)).toBe(false);
  });
});

describe("parseStoredSections", () => {
  it("returns an empty object for null, malformed json, or a non-object", () => {
    expect(parseStoredSections(null)).toEqual({});
    expect(parseStoredSections("not json")).toEqual({});
    expect(parseStoredSections("42")).toEqual({});
  });

  it("keeps only known section ids with boolean values", () => {
    const raw = JSON.stringify({ billing: true, profile: "yes", unknown: false, training: false });
    expect(parseStoredSections(raw)).toEqual({ billing: true, training: false });
  });

  it("round-trips through serializeSections", () => {
    const state = { enrollments: false, compliance: true };
    expect(parseStoredSections(serializeSections(state))).toEqual(state);
  });
});

describe("sectionIdFromHash", () => {
  it("parses a #section hash", () => {
    expect(sectionIdFromHash("#billing")).toBe("billing");
  });

  it("returns null for no hash or an unknown id", () => {
    expect(sectionIdFromHash("")).toBeNull();
    expect(sectionIdFromHash("#")).toBeNull();
    expect(sectionIdFromHash("#nope")).toBeNull();
  });
});
```

- [ ] Run it and confirm it fails on the missing module:

```
cd frontend && pnpm vitest run app/\(admin\)/admin/students/\[studentId\]/section-state.test.ts
```

Expected: fails with `Cannot find module './section-state'`.

- [ ] Implement `section-state.ts`:

```ts
/**
 * Pure helpers for the student single-view page's collapsible sections.
 * No React, no localStorage access — kept testable under Vitest's node
 * environment. `page.tsx` wraps these with the actual localStorage/hash
 * reads, which only run in the browser.
 */

export type SectionId = "enrollments" | "training" | "billing" | "profile" | "compliance";

export const SECTION_IDS: SectionId[] = ["enrollments", "training", "billing", "profile", "compliance"];

export const SECTION_STORAGE_KEY = "admin-student-sections-v1";

const STATIC_DEFAULTS: Record<Exclude<SectionId, "compliance">, boolean> = {
  enrollments: true,
  training: true,
  billing: false,
  profile: false,
};

export function isValidSectionId(value: string): value is SectionId {
  return (SECTION_IDS as string[]).includes(value);
}

/** Compliance auto-opens only when the waiver isn't signed — see plan Self-review. */
export function defaultSectionOpen(id: SectionId, complianceOutstanding: boolean): boolean {
  if (id === "compliance") return complianceOutstanding;
  return STATIC_DEFAULTS[id];
}

/** Parses the per-browser persisted toggle state; anything malformed reads as "nothing stored". */
export function parseStoredSections(raw: string | null): Partial<Record<SectionId, boolean>> {
  if (!raw) return {};
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return {};
  }
  if (!parsed || typeof parsed !== "object") return {};
  const result: Partial<Record<SectionId, boolean>> = {};
  for (const id of SECTION_IDS) {
    const value = (parsed as Record<string, unknown>)[id];
    if (typeof value === "boolean") result[id] = value;
  }
  return result;
}

export function serializeSections(state: Partial<Record<SectionId, boolean>>): string {
  return JSON.stringify(state);
}

/** `"#enrollments"` -> `"enrollments"`; no hash or an unknown id -> `null`. */
export function sectionIdFromHash(hash: string): SectionId | null {
  const bare = hash.replace(/^#/, "");
  return isValidSectionId(bare) ? bare : null;
}
```

- [ ] Run it again, expect PASS:

```
cd frontend && pnpm vitest run app/\(admin\)/admin/students/\[studentId\]/section-state.test.ts
```

- [ ] Commit:

```
git add frontend/app/\(admin\)/admin/students/\[studentId\]/section-state.ts frontend/app/\(admin\)/admin/students/\[studentId\]/section-state.test.ts
git commit -m "feat(admin-students): add pure section-state helpers for the single-view page

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: `CollapsibleSection` component

**Files:**
- Create: `frontend/app/(admin)/admin/students/[studentId]/CollapsibleSection.tsx`

**Interfaces:**
- Consumes: `Card` (`@/components/ds/card`), `Overline` (`@/components/ds/typography`), `ChevronDown` (`lucide-react`).
- Produces: `CollapsibleSection({ id, title, icon, open, onToggle, children, headExtra }): JSX.Element`.

No unit test (this project has no RTL/DOM harness — component behavior is exercised end-to-end in Task 12's Playwright spec). Verify by typecheck only.

- [ ] Implement:

```tsx
"use client";

import type { ReactNode } from "react";
import { ChevronDown } from "lucide-react";

import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";

/**
 * One disclosure card shared by every section on the student single-view
 * page. `headExtra` renders next to the chevron even while collapsed — the
 * Billing section uses it for the always-visible summary line.
 */
export function CollapsibleSection({
  id,
  title,
  icon,
  open,
  onToggle,
  children,
  headExtra,
}: {
  id: string;
  title: string;
  icon?: ReactNode;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
  headExtra?: ReactNode;
}) {
  return (
    <Card p={0} data-testid={`admin-student-section-${id}`}>
      <div id={`section-${id}`} className="scroll-mt-24">
        <button
          type="button"
          className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600"
          aria-expanded={open}
          aria-controls={`section-${id}-body`}
          onClick={onToggle}
          data-testid={`admin-student-section-${id}-toggle`}
        >
          <span className="flex items-center gap-2">
            {icon}
            <Overline>{title}</Overline>
          </span>
          <span className="flex items-center gap-3">
            {headExtra}
            <ChevronDown
              className={`size-4 shrink-0 text-rally-muted transition-transform ${open ? "rotate-180" : ""}`}
              aria-hidden="true"
            />
          </span>
        </button>
        {open && (
          <div id={`section-${id}-body`} className="border-t border-neutral-200 px-5 pb-5 pt-4">
            {children}
          </div>
        )}
      </div>
    </Card>
  );
}
```

- [ ] Typecheck:

```
cd frontend && pnpm typecheck
```

Expected: PASS (file is not imported anywhere yet, but must compile standalone — `pnpm typecheck` runs `tsc --noEmit` over the whole project).

- [ ] Commit:

```
git add frontend/app/\(admin\)/admin/students/\[studentId\]/CollapsibleSection.tsx
git commit -m "feat(admin-students): add CollapsibleSection for the single-view page

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: `formatAgeFromDob` for the rail

**Files:**
- Modify: `frontend/app/(admin)/admin/students/[studentId]/format.ts` (append function + export)
- Modify: `frontend/app/(admin)/admin/students/[studentId]/format.test.ts` (append `describe` block)

**Interfaces:**
- Produces: `formatAgeFromDob(dob: string | null | undefined, now?: Date): string | null`.

- [ ] Add the failing test. Append to `format.test.ts`:

```ts
describe("formatAgeFromDob", () => {
  const now = new Date("2026-09-10T12:00:00.000Z");

  it("returns null without a date of birth", () => {
    expect(formatAgeFromDob(null, now)).toBeNull();
    expect(formatAgeFromDob(undefined, now)).toBeNull();
  });

  it("returns the age in whole years as of now, after this year's birthday", () => {
    expect(formatAgeFromDob("2015-04-10", now)).toBe("11y");
  });

  it("does not count this year's birthday before it happens", () => {
    expect(formatAgeFromDob("2015-12-25", now)).toBe("10y");
  });

  it("counts the birthday itself as already happened", () => {
    expect(formatAgeFromDob("2015-09-10", now)).toBe("11y");
  });
});
```

Add `formatAgeFromDob` to the existing top import line in `format.test.ts` (find the `import { ... } from "./format";` line and add it to the list).

- [ ] Run and confirm the new tests fail on the missing export:

```
cd frontend && pnpm vitest run app/\(admin\)/admin/students/\[studentId\]/format.test.ts
```

Expected: fails — `formatAgeFromDob is not defined` / TS error.

- [ ] Implement. Append to `format.ts` before the final `export { ... };` block:

```ts
// DOB is a date-only string ("2015-04-10"); parsed at UTC midnight and
// compared in UTC calendar fields so the rail's age never flips a day early
// or late depending on the viewer's timezone.
function formatAgeFromDob(dob: string | null | undefined, now: Date = new Date()): string | null {
  if (!dob) return null;
  const parsed = new Date(`${dob}T00:00:00.000Z`);
  if (Number.isNaN(parsed.getTime())) return null;
  let age = now.getUTCFullYear() - parsed.getUTCFullYear();
  const hadBirthdayThisYear =
    now.getUTCMonth() > parsed.getUTCMonth() ||
    (now.getUTCMonth() === parsed.getUTCMonth() && now.getUTCDate() >= parsed.getUTCDate());
  if (!hadBirthdayThisYear) age -= 1;
  return age >= 0 ? `${age}y` : null;
}
```

Then update the trailing export list to include `formatAgeFromDob`:

```ts
export {
  formatCurrencyCents,
  centsToDollarInput,
  dollarsToCents,
  getErrorMessage,
  formatDate,
  formatDateUtc,
  formatInvoiceDate,
  formatDateTime,
  formatDateTimeRange,
  formatAgeFromDob,
  previewNetCents,
};
```

- [ ] Run again, expect PASS:

```
cd frontend && pnpm vitest run app/\(admin\)/admin/students/\[studentId\]/format.test.ts
```

- [ ] Commit:

```
git add frontend/app/\(admin\)/admin/students/\[studentId\]/format.ts frontend/app/\(admin\)/admin/students/\[studentId\]/format.test.ts
git commit -m "feat(admin-students): add formatAgeFromDob for the student rail

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Session-type billing merge + Billing summary facts

**Files:**
- Modify: `frontend/app/(admin)/admin/students/[studentId]/session-rows.ts`
- Modify: `frontend/app/(admin)/admin/students/[studentId]/session-rows.test.ts`

**Interfaces:**
- Consumes: `AdminBillingEnrollmentView`, `AdminSessionTypeView` (`@/lib/api/admin`); `AdminStudentDetail` (`@/lib/api/v2/students`); `OPEN_BILLING_STATUSES` (`./StatusChip`); `formatCurrencyCents` (`./format`).
- Produces: `EnrollmentBillingFacts` type, `billingFactsByEnrollmentId(billingEnrollments, sessionTypeById): Map<string, EnrollmentBillingFacts>`, `BillingSummaryFacts` type, `billingSummaryFacts(student): BillingSummaryFacts`, `billingSummaryLine(facts): string`.

- [ ] Add failing tests. Append to `session-rows.test.ts` (add new imports alongside the existing `import { autopayChip, familyBillingHref, pastEnrollmentRow } from "./session-rows";` line — extend it to also import `billingFactsByEnrollmentId, billingSummaryFacts, billingSummaryLine`):

```ts
describe("billingFactsByEnrollmentId", () => {
  const sessionTypeById = new Map([
    ["type-a", { session_type_id: "type-a", name: "Group Class", price_cents: 15000 } as any],
  ]);

  it("joins a billing enrollment onto its enrollment_id with the catalog price", () => {
    const facts = billingFactsByEnrollmentId(
      [
        {
          enrollment_id: "enr-1",
          student_id: "student-1",
          parent_id: "parent-1",
          session_type_id: "type-a",
          stripe_subscription_id: null,
          billing_start_date: "2026-06-01",
          status: "active",
          override_price_cents: null,
          enrolled_at: "2026-06-01T00:00:00Z",
          updated_at: "2026-06-01T00:00:00Z",
        },
      ],
      sessionTypeById,
    );
    expect(facts.get("enr-1")).toEqual({
      billingEnrollmentId: "enr-1",
      sessionTypeId: "type-a",
      sessionTypeName: "Group Class",
      effectivePriceCents: 15000,
      hasPriceOverride: false,
      billingStartDate: "2026-06-01",
      billingStatus: "active",
      movable: true,
    });
  });

  it("prefers the override price and flags it", () => {
    const facts = billingFactsByEnrollmentId(
      [
        {
          enrollment_id: "enr-1",
          student_id: "student-1",
          parent_id: "parent-1",
          session_type_id: "type-a",
          stripe_subscription_id: null,
          billing_start_date: "2026-06-01",
          status: "paused",
          override_price_cents: 5000,
          enrolled_at: "2026-06-01T00:00:00Z",
          updated_at: "2026-06-01T00:00:00Z",
        },
      ],
      sessionTypeById,
    );
    expect(facts.get("enr-1")?.effectivePriceCents).toBe(5000);
    expect(facts.get("enr-1")?.hasPriceOverride).toBe(true);
    // Paused billing enrollments can still be moved to another session type.
    expect(facts.get("enr-1")?.movable).toBe(true);
  });

  it("labels a discontinued session type and marks a cancelled row not movable", () => {
    const facts = billingFactsByEnrollmentId(
      [
        {
          enrollment_id: "enr-2",
          student_id: "student-1",
          parent_id: "parent-1",
          session_type_id: "gone",
          stripe_subscription_id: null,
          billing_start_date: "2026-06-01",
          status: "cancelled",
          override_price_cents: null,
          enrolled_at: "2026-06-01T00:00:00Z",
          updated_at: "2026-06-01T00:00:00Z",
        },
      ],
      sessionTypeById,
    );
    expect(facts.get("enr-2")?.sessionTypeName).toBe("Discontinued session type");
    expect(facts.get("enr-2")?.effectivePriceCents).toBeNull();
    expect(facts.get("enr-2")?.movable).toBe(false);
  });

  it("has no entry for a session enrollment with no billing record", () => {
    const facts = billingFactsByEnrollmentId([], sessionTypeById);
    expect(facts.get("enr-3")).toBeUndefined();
  });
});

describe("billingSummaryFacts / billingSummaryLine", () => {
  const student = {
    enrolled_sessions: [
      { enrollment_id: "e1", status: "active", amount_cents: 15000, autopay_status: "active" },
      {
        enrollment_id: "e2",
        status: "active",
        amount_cents: 12000,
        discount: { net_cents: 9000, gross_cents: 12000, discount_cents: 3000, label: "Sibling" },
        autopay_status: "not_offered",
      },
      { enrollment_id: "e3", status: "cancelled", amount_cents: 8000, autopay_status: "active" },
    ],
    payment_history: [
      { status: "partially_paid", balance_due_cents: 11000 },
      { status: "paid", balance_due_cents: 0 },
    ],
  } as any;

  it("sums active enrollments' net price, counts active classes, and detects any autopay-on", () => {
    const facts = billingSummaryFacts(student);
    expect(facts).toEqual({
      monthlyTotalCents: 24000, // 15000 + 9000 (discounted net), the cancelled row excluded
      activeClassCount: 2,
      overdueCount: 1,
      autopayOn: true,
    });
  });

  it("renders the summary line", () => {
    expect(billingSummaryLine(billingSummaryFacts(student))).toBe(
      "$240/mo across 2 classes · 1 overdue · autopay on",
    );
  });

  it("reads cleanly with nothing outstanding and autopay off", () => {
    const clean = {
      enrolled_sessions: [{ enrollment_id: "e1", status: "active", amount_cents: 10000, autopay_status: "manual" }],
      payment_history: [],
    } as any;
    expect(billingSummaryLine(billingSummaryFacts(clean))).toBe(
      "$100/mo across 1 class · nothing overdue · autopay off",
    );
  });
});
```

- [ ] Run and confirm failure:

```
cd frontend && pnpm vitest run app/\(admin\)/admin/students/\[studentId\]/session-rows.test.ts
```

Expected: fails — the three new names are not exported.

- [ ] Implement. The new **function bodies** are appended to the end of `session-rows.ts`; the four `import` lines below are **edits to the existing import block at the top of the file**, not appended text — appending a second `import { formatInvoiceDate } from "./format";` is a duplicate-identifier error. Concretely: add one new `import type … from "@/lib/api/admin";` line; extend the existing `import type { AdminStudentSessionSummary } from "@/lib/api/v2/students";` to also bring in `AdminStudentDetail`; extend the existing `import { formatInvoiceDate } from "./format";` to `{ formatCurrencyCents, formatInvoiceDate }`; add the new `./StatusChip` import.

Caution on the `./StatusChip` import: `session-rows.ts`'s file docstring says it is "kept free of React", and its Vitest suite runs under `environment: "node"`. `StatusChip.tsx` is a JSX module that pulls in `@/components/ds/chip`. Verify with the Task 4 test run that Vitest still resolves it (it should — esbuild transpiles `.tsx` and neither module imports CSS or touches `document`). If it does not, move `OPEN_BILLING_STATUSES` out of `StatusChip.tsx` into a plain `.ts` module and re-point both call sites (`page.tsx` and `session-rows.ts`) rather than duplicating the set.

```ts
import type { AdminBillingEnrollmentView, AdminSessionTypeView } from "@/lib/api/admin";
// (AdminStudentSessionSummary import already present — extend it:)
import type { AdminStudentDetail, AdminStudentSessionSummary } from "@/lib/api/v2/students";

// (formatInvoiceDate import already present — extend it, do not add a second line:)
import { formatCurrencyCents, formatInvoiceDate } from "./format";
import { OPEN_BILLING_STATUSES } from "./StatusChip";

export interface EnrollmentBillingFacts {
  billingEnrollmentId: string;
  sessionTypeId: string;
  sessionTypeName: string;
  effectivePriceCents: number | null;
  hasPriceOverride: boolean;
  billingStartDate: string;
  billingStatus: string;
  /** Only an active or paused billing enrollment can be moved to another session type. */
  movable: boolean;
}

/**
 * Joins each session-type billing enrollment onto the per-session enrollment
 * row it prices, sharing the same `enrollment_id` (spec
 * 2026-09-10-student-page-single-view-design §3.1: "one table, not two"). A
 * session enrollment never put on session-type billing simply has no entry.
 */
export function billingFactsByEnrollmentId(
  billingEnrollments: AdminBillingEnrollmentView[],
  sessionTypeById: Map<string, AdminSessionTypeView>,
): Map<string, EnrollmentBillingFacts> {
  const result = new Map<string, EnrollmentBillingFacts>();
  for (const enrollment of billingEnrollments) {
    const sessionType = sessionTypeById.get(enrollment.session_type_id);
    result.set(enrollment.enrollment_id, {
      billingEnrollmentId: enrollment.enrollment_id,
      sessionTypeId: enrollment.session_type_id,
      sessionTypeName: sessionType?.name ?? "Discontinued session type",
      effectivePriceCents: enrollment.override_price_cents ?? sessionType?.price_cents ?? null,
      hasPriceOverride: enrollment.override_price_cents != null,
      billingStartDate: enrollment.billing_start_date,
      billingStatus: enrollment.status,
      movable: enrollment.status === "active" || enrollment.status === "paused",
    });
  }
  return result;
}

export interface BillingSummaryFacts {
  monthlyTotalCents: number;
  activeClassCount: number;
  overdueCount: number;
  autopayOn: boolean;
}

/** Facts behind the Billing section's always-visible one-line summary. */
export function billingSummaryFacts(student: AdminStudentDetail): BillingSummaryFacts {
  const activeSessions = (student.enrolled_sessions ?? []).filter((s) => s.status === "active");
  const monthlyTotalCents = activeSessions.reduce(
    (sum, s) => sum + (s.discount ? s.discount.net_cents : (s.amount_cents ?? 0)),
    0,
  );
  const overdueCount = (student.payment_history ?? []).filter(
    (p) => OPEN_BILLING_STATUSES.has(p.status) && p.balance_due_cents > 0,
  ).length;
  const autopayOn = activeSessions.some((s) => s.autopay_status === "active");
  return { monthlyTotalCents, activeClassCount: activeSessions.length, overdueCount, autopayOn };
}

export function billingSummaryLine(facts: BillingSummaryFacts): string {
  const amount = formatCurrencyCents(facts.monthlyTotalCents);
  const classes = `${facts.activeClassCount} ${facts.activeClassCount === 1 ? "class" : "classes"}`;
  const overdue = facts.overdueCount === 0 ? "nothing overdue" : `${facts.overdueCount} overdue`;
  const autopay = facts.autopayOn ? "autopay on" : "autopay off";
  return `${amount}/mo across ${classes} · ${overdue} · ${autopay}`;
}
```

Note: `AdminStudentSessionSummary` is already imported at the top of the real file — do not duplicate the import, extend the existing `import type { ... AdminStudentSessionSummary } from "@/lib/api/v2/students";` line to also bring in `AdminStudentDetail`.

- [ ] Run again, expect PASS:

```
cd frontend && pnpm vitest run app/\(admin\)/admin/students/\[studentId\]/session-rows.test.ts
```

- [ ] Typecheck:

```
cd frontend && pnpm typecheck
```

- [ ] Commit:

```
git add frontend/app/\(admin\)/admin/students/\[studentId\]/session-rows.ts frontend/app/\(admin\)/admin/students/\[studentId\]/session-rows.test.ts
git commit -m "feat(admin-students): join session-type billing onto enrollment rows

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: `SessionsPanel` gains merged billing cell/actions + past-enrollments collapse

**Files:**
- Modify: `frontend/app/(admin)/admin/students/[studentId]/SessionsPanel.tsx`

**Interfaces:**
- Consumes: `EnrollmentBillingFacts` (`./session-rows`).
- Produces: `SessionsPanel` gains three new optional props: `billingFactsByEnrollmentId?: Map<string, EnrollmentBillingFacts>`, `onMoveBilling?: (session: AdminStudentSessionSummary) => void`, `onOverrideBilling?: (session: AdminStudentSessionSummary) => void`.

No new unit test — this is JSX wiring exercised by the Task 12 e2e spec. Verify with typecheck + the e2e run in Task 12.

**OPEN QUESTION (owner): where do "Move type" and "Override type price" live in the row?**
This task as written adds two more *inline* buttons to the action cell, which already
holds Fee, Discount and `DepartureActions`. That collides with the sibling spec
`2026-09-10-departure-actions-from-student-page-design.md` §3, whose owner decision is
explicit: "Hold/Return and Drop go into the row's overflow menu … Fee and Discount links
stay where they are. **Nothing new is inline**, so the row does not wrap on tablet
widths." Spec 4 §3.1 only asks for the billing *facts* (fee, discount, autopay chip) to be
merged into the row — it does not say the two session-type *actions* must be inline; they
just have to go somewhere once `BillingEnrollmentsPanel`'s own table is deleted in Task 6.
Pick one before implementing:
  - (a) put both into `DepartureActions`' overflow menu (needs a new action kind in that
    shared component — cross-plan coupling with spec 1, and that component is being
    reworked by spec 1's plan right now);
  - (b) keep them inline as written and accept the tablet wrap spec 1 was avoiding;
  - (c) render them as a second, smaller line under the merged billing cell (no new
    columns, no extra width in the action cell).
The code block below implements (b). If the owner picks (a) or (c), only the second and
third edit steps change; everything else in this task stands.

**Sequencing with the sibling plan:** plan 1 (`2026-09-10-departure-actions-from-student-page.md`, Task 9)
has ALREADY rewritten this action `<td>` — it renders `actions={departureActionsFor(session.status)}`
with a `switch` over `transfer | hold | return | drop | delete` and mounts the four
`@/components/admin/enrollment/*` dialogs at the bottom of the component. Do not touch that
`<DepartureActions>` block, its `onAction` switch, the four dialog mounts, or the
`studentName` / `familyLabel` props — this task only adds around them.

- [ ] Edit the props destructure (function signature, formerly line 55) to add the three new props. `studentName` and `familyLabel` below are plan 1's — keep them exactly as plan 1 left them, they are shown only so this snippet is copy-safe:

```tsx
function SessionsPanel({
  sessions,
  pastEnrollments = [],
  parentId,
  studentId,
  studentName,
  familyLabel,
  queryClient,
  billingFactsByEnrollmentId,
  onMoveBilling,
  onOverrideBilling,
}: {
  sessions: AdminStudentSessionSummary[];
  /** Issue #674: cancelled / withdrawn rows, newest ended first. */
  pastEnrollments?: AdminStudentSessionSummary[];
  /** Autopay lives on the family page; the chip links there when a parent is on file. */
  parentId?: string | null;
  studentId: string;
  /** Plan 1 (departure actions): the Hold/Return/Drop/Delete dialogs' copy and email-toggle label. */
  studentName: string;
  familyLabel?: string | null;
  queryClient: ReturnType<typeof useQueryClient>;
  /** Session-type billing facts, keyed by the same `enrollment_id` (spec §3.1). */
  billingFactsByEnrollmentId?: Map<string, EnrollmentBillingFacts>;
  onMoveBilling?: (session: AdminStudentSessionSummary) => void;
  onOverrideBilling?: (session: AdminStudentSessionSummary) => void;
}) {
```

- [ ] Add the import (top of file, alongside the `./session-rows` import):

```ts
import { autopayChip, familyBillingHref, pastEnrollmentRow, type EnrollmentBillingFacts } from "./session-rows";
```

- [ ] In the row map (the `sessions.map((session) => (...))` block, currently starting at line 241), compute the facts for this row right after `<tr key={session.enrollment_id}>`:

```tsx
{sessions.map((session) => {
  const facts = billingFactsByEnrollmentId?.get(session.enrollment_id);
  return (
    <tr key={session.enrollment_id}>
```

(This changes the arrow function from an implicit-return `(session) => (<tr>...)` to a block body — close it with `);\n})` instead of the existing `))}`.)

- [ ] Inside the existing Billing `<td>` (the block rendering `session.discount ? (...) : (...)`, ending just before `</td>` at line 285), append the session-type billing facts as a second line:

```tsx
                    </td>
```
becomes
```tsx
                      {facts && (
                        <div className="mt-2 border-t border-neutral-100 pt-2">
                          <div className="text-[10px] font-semibold uppercase tracking-overline text-rally-muted">
                            {facts.sessionTypeName}
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-xs tabular-nums text-rally-ink">
                              {facts.effectivePriceCents == null
                                ? "—"
                                : formatCurrencyCents(facts.effectivePriceCents)}
                            </span>
                            {facts.hasPriceOverride && (
                              <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-800">
                                Override
                              </span>
                            )}
                          </div>
                        </div>
                      )}
                    </td>
```

- [ ] In the action `<td>` (the `<div className="flex items-center justify-end gap-3">` block, currently lines 300-350), append two buttons right before the closing `</div>` of that flex row, after `<DepartureActions .../>`:

```tsx
                        {facts && (
                          <>
                            <button
                              className="text-xs font-medium text-rally-blue hover:underline disabled:cursor-not-allowed disabled:opacity-40"
                              onClick={() => onMoveBilling?.(session)}
                              disabled={!facts.movable}
                              title={
                                facts.movable
                                  ? undefined
                                  : "Only active or paused session-type billing can be moved."
                              }
                            >
                              Move type
                            </button>
                            <button
                              className="text-xs font-medium text-rally-blue hover:underline"
                              onClick={() => onOverrideBilling?.(session)}
                            >
                              Override type price
                            </button>
                          </>
                        )}
```

- [ ] Close the row's block body: change the trailing `))}` after `</tr>` (end of the map) to:

```tsx
                  </tr>
                );
              })}
```

- [ ] Update `PastEnrollmentsPanel` to collapse after 5 rows. Replace its body (currently lines 763-819) with:

```tsx
function PastEnrollmentsPanel({ rows }: { rows: AdminStudentSessionSummary[] }) {
  const [showAll, setShowAll] = useState(false);
  const visibleRows = showAll ? rows : rows.slice(0, 5);
  const hiddenCount = rows.length - visibleRows.length;

  return (
    <Card p={20} className="lg:col-span-2" data-testid="admin-student-past-enrollments">
      <div className="flex items-center justify-between gap-3">
        <Overline>Past enrollments</Overline>
        <span className="font-mono text-xs text-rally-muted tabular-nums">
          {rows.length} ended
        </span>
      </div>
      {rows.length === 0 ? (
        <p className="mt-3 text-sm text-rally-muted" data-testid="admin-student-no-past-enrollments">
          No cancelled or withdrawn enrollments.
        </p>
      ) : (
        <>
          <div className="mt-3 overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="border-b border-neutral-200 text-xs uppercase tracking-overline text-rally-muted">
                <tr>
                  <th className="py-2 pr-4 font-medium">Session</th>
                  <th className="py-2 pr-4 font-medium">Status</th>
                  <th className="py-2 pr-4 font-medium">Ended</th>
                  <th className="py-2 pr-4 font-medium">Ended by</th>
                  <th className="py-2 font-medium">Reason</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100">
                {visibleRows.map((raw) => {
                  const row = pastEnrollmentRow(raw);
                  return (
                    <tr
                      key={row.enrollmentId}
                      data-testid={`admin-student-past-enrollment-${row.enrollmentId}`}
                    >
                      <td className="py-3 pr-4 align-top">
                        <div className="font-medium text-rally-ink">{row.sessionTitle}</div>
                        {row.location && (
                          <div className="text-xs text-rally-muted">{row.location}</div>
                        )}
                      </td>
                      <td className="py-3 pr-4 align-top">
                        <Chip variant={row.statusVariant} label={row.statusLabel} />
                      </td>
                      <td className="py-3 pr-4 align-top text-rally-muted tabular-nums">
                        {row.endedOn}
                      </td>
                      <td className="py-3 pr-4 align-top text-rally-muted">{row.endedBy}</td>
                      <td className="py-3 align-top text-rally-muted">{row.reason}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {hiddenCount > 0 && (
            <button
              type="button"
              className="mt-3 text-xs font-medium text-rally-blue hover:underline"
              onClick={() => setShowAll(true)}
              data-testid="admin-student-past-enrollments-show-more"
            >
              Show {hiddenCount} more
            </button>
          )}
        </>
      )}
    </Card>
  );
}
```

- [ ] Add the `formatCurrencyCents` import if not already present (it already is, via the existing `./format` import line — no change needed there).

- [ ] Typecheck:

```
cd frontend && pnpm typecheck
```

- [ ] Commit:

```
git add frontend/app/\(admin\)/admin/students/\[studentId\]/SessionsPanel.tsx
git commit -m "feat(admin-students): merge session-type billing into the enrollments table

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Strip `BillingEnrollmentsPanel` down to shared dialogs

**Files:**
- Modify: `frontend/app/(admin)/admin/students/[studentId]/BillingEnrollmentsPanel.tsx`

**Interfaces:**
- Produces (exported, was previously module-private): `MoveEnrollmentDialog`, `OverridePriceDialog`, `ProrationResult`. Removes the `BillingEnrollmentsPanel` component and `EnrollmentRow` (no longer used — the row rendering moved into `SessionsPanel` in Task 5).

- [ ] Replace the whole file content with:

```tsx
"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";

import {
  moveAdminBillingEnrollment,
  overrideAdminBillingEnrollmentPrice,
  type AdminBillingEnrollmentView,
  type AdminSessionTypeView,
  type MoveBillingEnrollmentResponse,
} from "@/lib/api/admin";
import { Button } from "@/components/ds/button";

import { BillingDialogActions, BillingDialogError, BillingDialogFrame } from "./billing-dialogs";
import { centsToDollarInput, dollarsToCents, formatCurrencyCents, formatDateUtc, getErrorMessage } from "./format";
import { Field } from "./StudentEditForm";

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

/**
 * Calendar-month period for a YYYY-MM-DD move date, mirroring the backend's
 * `_default_period`: the admin move route requires the period explicitly and
 * proration is computed against it.
 */
function calendarMonthPeriod(
  moveDate: string,
): { periodStart: string; periodEnd: string } | null {
  const [year, month] = moveDate.split("-").map((part) => Number.parseInt(part, 10));
  // A cleared date input yields "" -> NaN, and toISOString() would throw while
  // the dialog is still mounted. Callers gate submission on a null return.
  if (!Number.isFinite(year) || !Number.isFinite(month)) return null;
  return {
    periodStart: new Date(Date.UTC(year, month - 1, 1)).toISOString(),
    periodEnd: new Date(Date.UTC(year, month, 1)).toISOString(),
  };
}

function MoveEnrollmentDialog({
  enrollment,
  sessionTypes,
  onCancel,
  onDone,
}: {
  enrollment: AdminBillingEnrollmentView;
  sessionTypes: AdminSessionTypeView[];
  onCancel: () => void;
  onDone: (result: MoveBillingEnrollmentResponse) => void;
}) {
  const [step, setStep] = useState<"form" | "confirm">("form");
  const [toSessionTypeId, setToSessionTypeId] = useState("");
  const [moveDate, setMoveDate] = useState(todayISO);
  const [reason, setReason] = useState("");

  const targets = sessionTypes.filter(
    (type) => type.is_active && type.session_type_id !== enrollment.session_type_id,
  );
  const target = targets.find((type) => type.session_type_id === toSessionTypeId);
  const period = calendarMonthPeriod(moveDate);

  const mutation = useMutation({
    mutationFn: () => {
      if (!period) throw new Error("Pick a move date before confirming.");
      return moveAdminBillingEnrollment(enrollment.enrollment_id, {
        to_session_type_id: toSessionTypeId,
        move_date: new Date(`${moveDate}T00:00:00.000Z`).toISOString(),
        period_start: period.periodStart,
        period_end: period.periodEnd,
        reason: reason.trim() || null,
      });
    },
    onSuccess: onDone,
  });

  return (
    <BillingDialogFrame title="Move to another session type" onCancel={onCancel}>
      {getErrorMessage(mutation.error) && (
        <BillingDialogError message={getErrorMessage(mutation.error)!} />
      )}

      {step === "form" ? (
        <div className="space-y-3">
          <Field label="Target session type" htmlFor="billing-move-session-type">
            <select
              id="billing-move-session-type"
              value={toSessionTypeId}
              onChange={(event) => setToSessionTypeId(event.target.value)}
              className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
            >
              <option value="">Select a session type</option>
              {targets.map((type) => (
                <option key={type.session_type_id} value={type.session_type_id}>
                  {type.name} — {formatCurrencyCents(type.price_cents)}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Move date" htmlFor="billing-move-date">
            <input
              id="billing-move-date"
              type="date"
              value={moveDate}
              onChange={(event) => setMoveDate(event.target.value)}
              className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
            />
          </Field>
          <Field label="Reason" htmlFor="billing-move-reason">
            <textarea
              id="billing-move-reason"
              rows={3}
              maxLength={500}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              className="w-full rounded-md border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
            />
          </Field>
        </div>
      ) : (
        <div
          className="space-y-2 rounded-md bg-amber-50 px-3 py-3 text-sm text-amber-900"
          data-testid="billing-move-confirm"
        >
          <p className="font-semibold">This changes what the parent is billed.</p>
          <p>
            Moving to <span className="font-semibold">{target?.name}</span> on{" "}
            {formatDateUtc(moveDate)} switches the enrollment and records a prorated
            adjustment against the{" "}
            {period
              ? new Date(period.periodStart).toLocaleDateString(undefined, {
                  month: "long",
                  year: "numeric",
                  timeZone: "UTC",
                })
              : "selected"}{" "}
            billing period. The adjustment is recorded now; it is applied on the parent&apos;s
            next invoice rather than charged immediately.
          </p>
          <p>This cannot be undone from this screen.</p>
        </div>
      )}

      <BillingDialogActions onCancel={step === "form" ? onCancel : () => setStep("form")}>
        {step === "form" ? (
          <Button
            size="sm"
            disabled={!toSessionTypeId || !period}
            onClick={() => setStep("confirm")}
          >
            Review move
          </Button>
        ) : (
          <Button
            size="sm"
            disabled={mutation.isPending || !period}
            icon={
              mutation.isPending ? (
                <RefreshCw className="size-3.5 animate-spin" aria-hidden="true" />
              ) : undefined
            }
            onClick={() => mutation.mutate()}
            data-testid="billing-move-submit"
          >
            {mutation.isPending ? "Moving..." : "Confirm move"}
          </Button>
        )}
      </BillingDialogActions>
    </BillingDialogFrame>
  );
}

function OverridePriceDialog({
  enrollment,
  catalogPriceCents,
  onCancel,
  onDone,
}: {
  enrollment: AdminBillingEnrollmentView;
  catalogPriceCents: number | null;
  onCancel: () => void;
  onDone: () => void;
}) {
  const [amount, setAmount] = useState(() =>
    enrollment.override_price_cents == null
      ? ""
      : centsToDollarInput(enrollment.override_price_cents),
  );
  const mutation = useMutation({
    mutationFn: (overridePriceCents: number | null) =>
      overrideAdminBillingEnrollmentPrice(enrollment.enrollment_id, overridePriceCents),
    onSuccess: onDone,
  });
  const amountCents = dollarsToCents(amount);
  const canSave = amount.trim().length > 0 && amountCents >= 0;

  return (
    <BillingDialogFrame title="Override enrollment price" onCancel={onCancel}>
      {getErrorMessage(mutation.error) && (
        <BillingDialogError message={getErrorMessage(mutation.error)!} />
      )}
      <p className="text-xs text-rally-muted">
        {catalogPriceCents == null
          ? "Catalog price unavailable."
          : `Catalog price is ${formatCurrencyCents(catalogPriceCents)}. Clearing the override restores it.`}
      </p>
      <Field label="Override price" htmlFor="billing-override-amount">
        <input
          id="billing-override-amount"
          inputMode="decimal"
          value={amount}
          onChange={(event) => setAmount(event.target.value)}
          placeholder="0.00"
          className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
        />
      </Field>
      <BillingDialogActions onCancel={onCancel}>
        <Button
          size="sm"
          variant="secondary"
          disabled={enrollment.override_price_cents == null || mutation.isPending}
          onClick={() => mutation.mutate(null)}
          data-testid="billing-override-clear"
        >
          Clear override
        </Button>
        <Button
          size="sm"
          disabled={!canSave || mutation.isPending}
          icon={
            mutation.isPending ? (
              <RefreshCw className="size-3.5 animate-spin" aria-hidden="true" />
            ) : undefined
          }
          onClick={() => mutation.mutate(amountCents)}
          data-testid="billing-override-save"
        >
          {mutation.isPending ? "Saving..." : "Save override"}
        </Button>
      </BillingDialogActions>
    </BillingDialogFrame>
  );
}

function ProrationResult({
  result,
  onDismiss,
}: {
  result: MoveBillingEnrollmentResponse;
  onDismiss: () => void;
}) {
  const { proration } = result;
  const netLabel =
    proration.net_cents === 0
      ? "no net change"
      : proration.net_cents > 0
        ? `charged ${formatCurrencyCents(proration.net_cents)}`
        : `credited ${formatCurrencyCents(Math.abs(proration.net_cents))}`;

  return (
    <div
      className="mt-3 rounded-md border border-blue-200 bg-blue-50 px-3 py-3 text-xs text-blue-900"
      data-testid="billing-move-result"
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-semibold">Move applied — {netLabel}</p>
        <button type="button" onClick={onDismiss} className="text-blue-800 underline">
          Dismiss
        </button>
      </div>
      <dl className="mt-2 grid gap-x-6 gap-y-1 sm:grid-cols-2">
        <ResultRow label="Credit" value={formatCurrencyCents(proration.credit_cents)} />
        <ResultRow label="Charge" value={formatCurrencyCents(proration.charge_cents)} />
        <ResultRow
          label="Prorated days"
          value={`${proration.remaining_days} of ${proration.total_days} (${proration.proration_ratio})`}
        />
        <ResultRow label="Policy version" value={proration.policy_version} />
        {/* The move itself never creates a Stripe invoice today, so only surface
            this row if the backend ever starts returning one. */}
        {result.stripe_invoice_id && (
          <ResultRow label="Stripe invoice" value={result.stripe_invoice_id} />
        )}
      </dl>
    </div>
  );
}

function ResultRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-blue-800">{label}</dt>
      <dd className="font-mono tabular-nums">{value}</dd>
    </div>
  );
}

export { MoveEnrollmentDialog, OverridePriceDialog, ProrationResult };
```

- [ ] Typecheck. **Expect exactly one failure, and only this one:** `page.tsx` still has
`import { BillingEnrollmentsPanel } from "./BillingEnrollmentsPanel";` and still renders
`<BillingEnrollmentsPanel studentId={studentId} active={activeTab === "billing"} />` — that
export no longer exists, so `tsc` reports `TS2305: Module './BillingEnrollmentsPanel' has
no exported member 'BillingEnrollmentsPanel'`. Task 10 removes that import and that render.
(The unused *new* exports are fine — unused exports never fail `tsc`; that was not the
error to expect here.) If any error other than the `TS2305` above appears, stop and fix it
before moving on.

```
cd frontend && pnpm typecheck
```

- [ ] Commit:

```
git add frontend/app/\(admin\)/admin/students/\[studentId\]/BillingEnrollmentsPanel.tsx
git commit -m "refactor(admin-students): reduce BillingEnrollmentsPanel to shared dialogs

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: `EnrollmentsSection` orchestrator

**Files:**
- Create: `frontend/app/(admin)/admin/students/[studentId]/EnrollmentsSection.tsx`

**Interfaces:**
- Consumes: `listAdminBillingEnrollments`, `listAdminSessionTypes` (`@/lib/api/admin`); `queryKeys.admin.billingEnrollments`, `queryKeys.admin.sessionTypes`, `queryKeys.admin.studentDetail` (`@/lib/query/keys`); `SessionsPanel` (`./SessionsPanel`); `MoveEnrollmentDialog`, `OverridePriceDialog`, `ProrationResult` (`./BillingEnrollmentsPanel`); `billingFactsByEnrollmentId` (`./session-rows`).
- Produces: `EnrollmentsSection({ student, studentId, queryClient }): JSX.Element`.

- [ ] Implement:

```tsx
"use client";

import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  listAdminBillingEnrollments,
  listAdminSessionTypes,
  type MoveBillingEnrollmentResponse,
} from "@/lib/api/admin";
import type { AdminStudentDetail, AdminStudentSessionSummary } from "@/lib/api/v2/students";
import { queryKeys } from "@/lib/query/keys";

import { MoveEnrollmentDialog, OverridePriceDialog, ProrationResult } from "./BillingEnrollmentsPanel";
import { billingFactsByEnrollmentId } from "./session-rows";
import { SessionsPanel } from "./SessionsPanel";

type BillingDialog = "move" | "override" | null;

/**
 * Owns the session-type billing fetch and its move/override-price dialogs,
 * and feeds the joined facts into SessionsPanel's table (spec §3.1: one
 * table, not two). Queries always run — the section is always mounted now
 * that tabs are gone (spec §6).
 */
export function EnrollmentsSection({
  student,
  studentId,
  queryClient,
}: {
  student: AdminStudentDetail;
  studentId: string;
  queryClient: ReturnType<typeof useQueryClient>;
}) {
  const [dialog, setDialog] = useState<BillingDialog>(null);
  const [selectedSession, setSelectedSession] = useState<AdminStudentSessionSummary | null>(null);
  const [moveResult, setMoveResult] = useState<MoveBillingEnrollmentResponse | null>(null);

  const billingEnrollmentsQuery = useQuery({
    queryKey: queryKeys.admin.billingEnrollments(studentId),
    queryFn: () => listAdminBillingEnrollments({ studentId }),
  });
  const sessionTypesQuery = useQuery({
    queryKey: queryKeys.admin.sessionTypes(),
    queryFn: () => listAdminSessionTypes(),
  });

  // Memoised for the same reason BillingEnrollmentsPanel memoised it: a bare
  // `?? []` mints a new array identity every render, which defeats the two
  // useMemos below and re-renders SessionsPanel's whole table on every keystroke
  // in any dialog above it.
  const sessionTypes = useMemo(
    () => sessionTypesQuery.data?.session_types ?? [],
    [sessionTypesQuery.data],
  );
  const sessionTypeById = useMemo(
    () => new Map(sessionTypes.map((type) => [type.session_type_id, type])),
    [sessionTypes],
  );
  const billingEnrollments = useMemo(
    () => billingEnrollmentsQuery.data?.enrollments ?? [],
    [billingEnrollmentsQuery.data],
  );
  const factsByEnrollmentId = useMemo(
    () => billingFactsByEnrollmentId(billingEnrollments, sessionTypeById),
    [billingEnrollments, sessionTypeById],
  );
  const selectedBillingEnrollment = selectedSession
    ? (billingEnrollments.find((e) => e.enrollment_id === selectedSession.enrollment_id) ?? null)
    : null;

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.admin.billingEnrollments(studentId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.admin.studentDetail(studentId) });
  };
  const closeDialog = () => {
    setDialog(null);
    setSelectedSession(null);
  };

  return (
    <>
      <SessionsPanel
        sessions={student.enrolled_sessions ?? []}
        pastEnrollments={student.past_enrollments ?? []}
        parentId={student.parent_id}
        studentId={studentId}
        // Plan 1 (departure actions) made these SessionsPanel props; page.tsx used to
        // pass them and Task 10 replaces page.tsx wholesale, so they move here.
        studentName={student.full_name}
        familyLabel={student.parent_name ?? null}
        queryClient={queryClient}
        billingFactsByEnrollmentId={factsByEnrollmentId}
        onMoveBilling={(session) => {
          setSelectedSession(session);
          setMoveResult(null);
          setDialog("move");
        }}
        onOverrideBilling={(session) => {
          setSelectedSession(session);
          setDialog("override");
        }}
      />
      {moveResult && <ProrationResult result={moveResult} onDismiss={() => setMoveResult(null)} />}
      {dialog === "move" && selectedBillingEnrollment && (
        <MoveEnrollmentDialog
          enrollment={selectedBillingEnrollment}
          sessionTypes={sessionTypes}
          onCancel={closeDialog}
          onDone={(result) => {
            closeDialog();
            setMoveResult(result);
            invalidate();
          }}
        />
      )}
      {dialog === "override" && selectedBillingEnrollment && (
        <OverridePriceDialog
          enrollment={selectedBillingEnrollment}
          catalogPriceCents={
            sessionTypeById.get(selectedBillingEnrollment.session_type_id)?.price_cents ?? null
          }
          onCancel={closeDialog}
          onDone={() => {
            closeDialog();
            invalidate();
          }}
        />
      )}
    </>
  );
}
```

- [ ] Typecheck:

```
cd frontend && pnpm typecheck
```

- [ ] Commit:

```
git add frontend/app/\(admin\)/admin/students/\[studentId\]/EnrollmentsSection.tsx
git commit -m "feat(admin-students): add EnrollmentsSection orchestrator

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: `BillingSummaryLine` component

**Files:**
- Create: `frontend/app/(admin)/admin/students/[studentId]/BillingSummaryLine.tsx`

**Interfaces:**
- Consumes: `billingSummaryFacts`, `billingSummaryLine` (`./session-rows`); `AdminStudentDetail` (`@/lib/api/v2/students`).
- Produces: `BillingSummaryLine({ student }): JSX.Element` — the text rendered as `CollapsibleSection`'s `headExtra` for the Billing section.

- [ ] Implement:

```tsx
"use client";

import type { AdminStudentDetail } from "@/lib/api/v2/students";

import { billingSummaryFacts, billingSummaryLine } from "./session-rows";

/**
 * The Billing section's always-visible one-line summary (spec §3.3), shown
 * next to the section's collapse toggle whether the detail is open or not.
 */
export function BillingSummaryLine({ student }: { student: AdminStudentDetail }) {
  const line = billingSummaryLine(billingSummaryFacts(student));
  return (
    // Spec §2: "Billing summary line always visible" — it must NOT be
    // `hidden sm:inline`; the phone layout is exactly where the single view has
    // to answer "what do they owe" without opening anything.
    <span
      className="min-w-0 truncate text-left text-xs text-rally-muted"
      data-testid="admin-student-billing-summary-line"
    >
      {line}
    </span>
  );
}
```

- [ ] Typecheck:

```
cd frontend && pnpm typecheck
```

- [ ] Commit:

```
git add frontend/app/\(admin\)/admin/students/\[studentId\]/BillingSummaryLine.tsx
git commit -m "feat(admin-students): add the Billing section's always-visible summary line

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Consolidate `StudentEditForm` — drop `mode`

**Files:**
- Modify: `frontend/app/(admin)/admin/students/[studentId]/StudentEditForm.tsx`

**Interfaces:**
- Produces: `StudentEditForm({ student, onSaved }): JSX.Element` (drops the `mode: StudentEditMode` prop entirely). `ChangeParentPanel` and `Field` exports are unchanged.

- [ ] Replace the `StudentEditForm` function (lines 24-347) with a single-mode version:

```tsx
function StudentEditForm({
  student,
  onSaved,
}: {
  student: AdminStudentDetail;
  onSaved: () => void;
}) {
  const [fullName, setFullName] = useState(student.full_name);
  const [dateOfBirth, setDateOfBirth] = useState(student.date_of_birth ?? "");
  const [status, setStatus] = useState<EditableStatus>(
    (student.status as EditableStatus) ?? "active",
  );
  const [notes, setNotes] = useState(student.notes ?? "");
  const [previousExperience, setPreviousExperience] = useState(
    student.previous_experience ?? "",
  );
  const [medicalNotes, setMedicalNotes] = useState(
    student.medical_notes ?? "",
  );
  const [emergencyContactName, setEmergencyContactName] = useState(
    student.emergency_contact_name ?? "",
  );
  const [emergencyContactPhone, setEmergencyContactPhone] = useState(
    student.emergency_contact_phone ?? "",
  );
  const [tShirtSize, setTShirtSize] = useState(student.t_shirt_size ?? "");
  const [reason, setReason] = useState("Admin profile update");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitOk, setSubmitOk] = useState(false);

  // Keep local state in sync if the server-side data refreshes.
  useEffect(() => {
    setFullName(student.full_name);
    setDateOfBirth(student.date_of_birth ?? "");
    setStatus((student.status as EditableStatus) ?? "active");
    setNotes(student.notes ?? "");
    setPreviousExperience(student.previous_experience ?? "");
    setMedicalNotes(student.medical_notes ?? "");
    setEmergencyContactName(student.emergency_contact_name ?? "");
    setEmergencyContactPhone(student.emergency_contact_phone ?? "");
    setTShirtSize(student.t_shirt_size ?? "");
  }, [
    student.full_name,
    student.date_of_birth,
    student.status,
    student.notes,
    student.previous_experience,
    student.medical_notes,
    student.emergency_contact_name,
    student.emergency_contact_phone,
    student.t_shirt_size,
  ]);

  const mutation = useMutation({
    mutationFn: (payload: UpdateAdminStudentRequest) =>
      updateAdminStudent(student.student_id, payload),
    onSuccess: () => {
      setSubmitError(null);
      setSubmitOk(true);
      onSaved();
    },
    onError: (err: unknown) => {
      setSubmitOk(false);
      const message =
        err instanceof Error ? err.message : "Could not save changes.";
      setSubmitError(message);
    },
  });

  const dirtyFields = {
    fullName: fullName !== student.full_name,
    dateOfBirth: dateOfBirth !== (student.date_of_birth ?? ""),
    status: status !== student.status,
    notes: (notes ?? "") !== (student.notes ?? ""),
    previousExperience:
      previousExperience !== (student.previous_experience ?? ""),
    medicalNotes: medicalNotes !== (student.medical_notes ?? ""),
    emergencyContactName:
      emergencyContactName !== (student.emergency_contact_name ?? ""),
    emergencyContactPhone:
      emergencyContactPhone !== (student.emergency_contact_phone ?? ""),
    tShirtSize: tShirtSize !== (student.t_shirt_size ?? ""),
  };

  const dirty = Object.values(dirtyFields).some(Boolean);

  const reset = () => {
    setFullName(student.full_name);
    setDateOfBirth(student.date_of_birth ?? "");
    setStatus((student.status as EditableStatus) ?? "active");
    setNotes(student.notes ?? "");
    setPreviousExperience(student.previous_experience ?? "");
    setMedicalNotes(student.medical_notes ?? "");
    setEmergencyContactName(student.emergency_contact_name ?? "");
    setEmergencyContactPhone(student.emergency_contact_phone ?? "");
    setTShirtSize(student.t_shirt_size ?? "");
    setSubmitError(null);
    setSubmitOk(false);
  };

  return (
    <form
      className="mt-3 space-y-4"
      data-testid="admin-student-edit-form"
      onSubmit={(e) => {
        e.preventDefault();
        setSubmitOk(false);
        setSubmitError(null);
        const payload: UpdateAdminStudentRequest = {};
        if (dirtyFields.fullName) payload.full_name = fullName;
        if (dirtyFields.dateOfBirth) payload.date_of_birth = dateOfBirth || null;
        if (dirtyFields.status) payload.status = status;
        if (dirtyFields.notes) payload.notes = notes || null;
        if (dirtyFields.previousExperience) payload.previous_experience = previousExperience;
        if (dirtyFields.medicalNotes) payload.medical_notes = medicalNotes;
        if (dirtyFields.emergencyContactName)
          payload.emergency_contact_name = emergencyContactName;
        if (dirtyFields.emergencyContactPhone)
          payload.emergency_contact_phone = emergencyContactPhone;
        if (dirtyFields.tShirtSize) payload.t_shirt_size = tShirtSize;
        payload.reason = reason;
        mutation.mutate(payload);
      }}
    >
      <Field label="Full name" htmlFor="student-full-name">
        <input
          id="student-full-name"
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          required
          minLength={1}
          maxLength={120}
        />
      </Field>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Date of birth" htmlFor="student-dob">
          <input
            id="student-dob"
            type="date"
            value={dateOfBirth}
            onChange={(e) => setDateOfBirth(e.target.value)}
            className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          />
        </Field>

        <Field label="Status" htmlFor="student-status">
          <select
            id="student-status"
            value={status}
            onChange={(e) => setStatus(e.target.value as EditableStatus)}
            className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          >
            <option value="active">Active</option>
            <option value="paused">Paused</option>
            <option value="inactive">Inactive</option>
            <option value="cancelled">Cancelled</option>
          </select>
        </Field>
      </div>

      <Field label="Internal notes" htmlFor="student-notes">
        <textarea
          id="student-notes"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={4}
          maxLength={2000}
          className="w-full rounded-md border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          placeholder="Allergies, behavioural notes, comms preferences..."
        />
      </Field>

      <Field label="Previous experience" htmlFor="student-previous-experience">
        <textarea
          id="student-previous-experience"
          value={previousExperience}
          onChange={(e) => setPreviousExperience(e.target.value)}
          rows={3}
          maxLength={1000}
          className="w-full rounded-md border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          placeholder="Prior coaching, club play, school teams"
        />
      </Field>

      <Field label="Medical notes" htmlFor="student-medical-notes">
        <textarea
          id="student-medical-notes"
          value={medicalNotes}
          onChange={(e) => setMedicalNotes(e.target.value)}
          rows={3}
          maxLength={1000}
          className="w-full rounded-md border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          placeholder="Allergies, injuries, health notes"
        />
      </Field>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Emergency contact name" htmlFor="student-emergency-contact-name">
          <input
            id="student-emergency-contact-name"
            value={emergencyContactName}
            onChange={(e) => setEmergencyContactName(e.target.value)}
            className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
            maxLength={120}
          />
        </Field>

        <Field label="Emergency contact phone" htmlFor="student-emergency-contact-phone">
          <input
            id="student-emergency-contact-phone"
            value={emergencyContactPhone}
            onChange={(e) => setEmergencyContactPhone(e.target.value)}
            className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
            maxLength={40}
          />
        </Field>
      </div>

      <Field label="T-shirt size" htmlFor="student-t-shirt-size">
        <input
          id="student-t-shirt-size"
          value={tShirtSize}
          onChange={(e) => setTShirtSize(e.target.value)}
          className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          maxLength={20}
        />
      </Field>

      <Field label="Reason" htmlFor="student-edit-reason">
        <input
          id="student-edit-reason"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          required
          maxLength={500}
        />
      </Field>

      {submitError && (
        <p
          role="alert"
          data-testid="admin-student-edit-error"
          className="rounded-md border border-red-200 bg-red-50 p-2 text-sm text-red-700"
        >
          {submitError}
        </p>
      )}
      {submitOk && (
        <p
          role="status"
          data-testid="admin-student-edit-ok"
          className="rounded-md border border-emerald-200 bg-emerald-50 p-2 text-sm text-emerald-800"
        >
          Saved.
        </p>
      )}

      <div className="flex items-center gap-2">
        <Button
          type="submit"
          variant="primary"
          size="sm"
          disabled={!dirty || mutation.isPending}
          icon={mutation.isPending ? <RefreshCw className="size-3.5 animate-spin" /> : undefined}
        >
          {mutation.isPending ? "Saving…" : "Save changes"}
        </Button>
        {dirty && (
          <Button type="button" variant="secondary" size="sm" onClick={reset}>
            Reset
          </Button>
        )}
      </div>
    </form>
  );
}
```

- [ ] Delete the now-unused `type StudentEditMode = "overview" | "training" | "family";` line (was at line 22).

- [ ] `ChangeParentPanel` (lines 349-569) and `Field` (lines 571-591) are unchanged — leave them exactly as they are; `ChangeParentPanel` stays exported for spec 2's family page to relocate, and Task 11 stops importing it from this page.

- [ ] Typecheck (expect a temporary error: `page.tsx` still passes a `mode` prop — that's fixed in Task 10, which lands in the same PR before this is merged; if executing tasks strictly in order, this typecheck step may show that one error and that is expected — proceed to Task 10 next rather than treating it as a blocker):

```
cd frontend && pnpm typecheck
```

- [ ] Commit:

```
git add frontend/app/\(admin\)/admin/students/\[studentId\]/StudentEditForm.tsx
git commit -m "refactor(admin-students): drop StudentEditForm's mode prop, one form for all fields

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: `StudentRail` + rewrite `page.tsx` to the single-view layout

**Files:**
- Create: `frontend/app/(admin)/admin/students/[studentId]/StudentRail.tsx`
- Modify: `frontend/app/(admin)/admin/students/[studentId]/page.tsx`

**Interfaces:**
- `StudentRail` consumes: `Avatar` (`@/components/ds/avatar`), `Button` (`@/components/ds/button`), `Card` (`@/components/ds/card`), `Chip` (`@/components/ds/chip`), `getAdminUser` (`@/lib/api/admin`), `queryKeys.admin.userDetail` (`@/lib/query/keys`), `formatAgeFromDob` (`./format`), `StatusChip` (`./StatusChip`), `SECTION_IDS` (`./section-state`).
- `StudentRail` produces: `StudentRail({ student, onStopAllClasses, onJumpTo }): JSX.Element`.
- `page.tsx` produces the rewritten `AdminStudentDetailPage`; removes `STUDENT_TABS`, `StudentTab`, `StudentTabs`, `TabPanel`, `Header`.

- [ ] Implement `StudentRail.tsx`:

```tsx
"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { getAdminUser } from "@/lib/api/admin";
import type { AdminStudentDetail } from "@/lib/api/v2/students";
import { queryKeys } from "@/lib/query/keys";
import { Avatar } from "@/components/ds/avatar";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";

import { formatAgeFromDob } from "./format";
import { SECTION_IDS, type SectionId } from "./section-state";
import { StatusChip } from "./StatusChip";

const SECTION_LABELS: Record<SectionId, string> = {
  enrollments: "Enrollments",
  training: "Training & attendance",
  billing: "Billing",
  profile: "Profile",
  compliance: "Compliance",
};

export function StudentRail({
  student,
  onStopAllClasses,
  onJumpTo,
}: {
  student: AdminStudentDetail;
  onStopAllClasses: () => void;
  onJumpTo: (id: SectionId) => void;
}) {
  const age = formatAgeFromDob(student.date_of_birth);

  return (
    <Card p={20} className="lg:sticky lg:top-4 lg:self-start" data-testid="admin-student-rail">
      <div className="flex items-center gap-3">
        <Avatar name={student.full_name} size={56} />
        <div className="min-w-0">
          <h2 className="font-display text-lg font-semibold tracking-[-0.01em] text-rally-ink truncate">
            {student.full_name}
          </h2>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <StatusChip status={student.status} />
            {student.level && (
              <span className="text-xs text-rally-muted">{student.level}</span>
            )}
          </div>
        </div>
      </div>

      <div className="mt-2 text-xs text-rally-muted">
        {student.date_of_birth
          ? `DOB ${new Date(`${student.date_of_birth}T00:00:00.000Z`).toLocaleDateString(undefined, { timeZone: "UTC" })}${age ? ` · ${age}` : ""}`
          : "No date of birth on file"}
      </div>

      <Button size="sm" variant="ghost" className="mt-3" onClick={onStopAllClasses}>
        Stop all classes
      </Button>

      <FamilyCard student={student} />

      <nav className="mt-5 space-y-1 border-t border-neutral-200 pt-4" aria-label="Jump to section">
        {SECTION_IDS.map((id) => (
          <button
            key={id}
            type="button"
            className="block w-full rounded px-1 py-1 text-left text-sm text-rally-muted hover:text-rally-ink focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600"
            onClick={() => onJumpTo(id)}
            data-testid={`admin-student-jump-${id}`}
          >
            {SECTION_LABELS[id]}
          </button>
        ))}
      </nav>
    </Card>
  );
}

/**
 * `AdminUserView.status` is the *membership* status — the backend's
 * `MembershipStatus = Literal["invited", "active", "suspended", "removed"]`
 * (`backend/v2/contexts/identity/domain/models.py:60`) — so it is a real login
 * signal, but a three-state one. A binary "active ? REGISTERED : INVITED" would
 * label a suspended or removed parent "INVITED". Match the vocabulary spec 2 §3
 * chose for the families list (never invited / invited / active) and the chip
 * convention `app/(admin)/admin/users/[userId]/page.tsx:428-431` already uses
 * for this exact field: render the status itself, `enrolled` when active.
 */
function loginBadge(
  status: string,
  loginInviteSentAt: string | null | undefined,
): { variant: "enrolled" | "pending" | "nocharge"; label: string } {
  if (status === "active") return { variant: "enrolled", label: "ACTIVE" };
  if (status === "invited" || loginInviteSentAt) {
    return { variant: "pending", label: "INVITED" };
  }
  return { variant: "nocharge", label: status.toUpperCase() };
}

function FamilyCard({ student }: { student: AdminStudentDetail }) {
  const parentDetailQuery = useQuery({
    queryKey: queryKeys.admin.userDetail(student.parent_id ?? ""),
    queryFn: () => getAdminUser(student.parent_id as string),
    enabled: Boolean(student.parent_id),
  });
  const parent = parentDetailQuery.data;
  const badge = parent ? loginBadge(parent.status, parent.login_invite_sent_at) : null;

  return (
    <div className="mt-4 rounded-lg border border-neutral-200 p-3 text-sm" data-testid="admin-student-family-card">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium text-rally-ink truncate">
          {student.parent_name ?? student.parent_email ?? "Parent on file"}
        </span>
        {badge && <Chip variant={badge.variant} label={badge.label} />}
      </div>
      {student.parent_email && (
        <a
          href={`mailto:${student.parent_email}`}
          className="mt-1 block truncate text-rally-muted hover:underline focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600 rounded"
        >
          {student.parent_email}
        </a>
      )}
      {student.parent_phone && (
        <a
          href={`tel:${student.parent_phone}`}
          className="block text-rally-muted hover:underline focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600 rounded"
        >
          {student.parent_phone}
        </a>
      )}
      {student.parent_id ? (
        <Link
          href={`/admin/families/${encodeURIComponent(student.parent_id)}`}
          className="mt-2 inline-block text-xs font-medium text-rally-blue hover:underline"
        >
          Open family
        </Link>
      ) : (
        <p className="mt-2 text-xs text-rally-muted">No parent on file.</p>
      )}
    </div>
  );
}
```

- [ ] Replace `page.tsx` in full:

```tsx
"use client";

/**
 * Admin student detail page.
 *
 * Pulls a single student from the v2 BFF and exposes safe admin-editable
 * fields. No raw internal ids are rendered in normal UI.
 *
 * Single-view layout (spec 2026-09-10-student-page-single-view-design):
 * a sticky rail plus five collapsible sections replace the old five tabs.
 * Every section mounts unconditionally and fetches its own data, same as
 * the tabs did lazily before.
 */

import { type ReactNode, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowLeft,
  CalendarCheck,
  FileCheck,
  ShieldCheck,
  UserRound,
  Wallet,
} from "lucide-react";

import { listAdminUsers } from "@/lib/api/admin";
import { getAdminStudent, type AdminStudentDetail } from "@/lib/api/v2/students";
import { getActiveAcademyId } from "@/lib/api/client";
import { getStudentProgress, listPrograms } from "@/lib/api/curriculum";
import { getDeparturePolicy } from "@/lib/api/v2/departure-policy";
import { buildStudentProgressHref } from "@/lib/navigation/admin-student-progress-return";
import { queryKeys } from "@/lib/query/keys";
import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";
import { StopAllClassesDialog } from "@/components/admin/enrollment/stop-all-classes-dialog";

import { BillingSummaryLine } from "./BillingSummaryLine";
import { CollapsibleSection } from "./CollapsibleSection";
import { DetailList } from "./DetailList";
import { EnrollmentsSection } from "./EnrollmentsSection";
import { FamilyBillingLink } from "./FamilyBillingLink";
import { formatCurrencyCents, formatDate, formatDateUtc, formatDateTime } from "./format";
// NB: `SECTION_IDS` is deliberately NOT imported here — page.tsx spells the
// five sections out as JSX; only StudentRail iterates the list.
import {
  SECTION_STORAGE_KEY,
  defaultSectionOpen,
  parseStoredSections,
  sectionIdFromHash,
  serializeSections,
  type SectionId,
} from "./section-state";
import { OPEN_BILLING_STATUSES, StatusChip } from "./StatusChip";
import { ChangeParentPanel, StudentEditForm } from "./StudentEditForm";
import { StudentRail } from "./StudentRail";

export default function AdminStudentDetailPage() {
  const params = useParams<{ studentId: string }>();
  const studentId = params?.studentId ?? "";
  const queryClient = useQueryClient();
  const [stopAllClassesOpen, setStopAllClassesOpen] = useState(false);

  const departurePolicyQuery = useQuery({
    queryKey: queryKeys.admin.departurePolicy(),
    queryFn: getDeparturePolicy,
  });

  const studentQuery = useQuery({
    queryKey: queryKeys.admin.studentDetail(studentId),
    queryFn: () => getAdminStudent(studentId),
    enabled: Boolean(studentId),
    retry: false,
  });
  // Still fetched here for ChangeParentPanel, which this page stops rendering
  // in the task that follows this one (gated on the family page's own parent
  // picker shipping — see the plan's Task 11).
  const parentsQuery = useQuery({
    queryKey: queryKeys.admin.users("parent"),
    queryFn: () => listAdminUsers("parent"),
    enabled: Boolean(studentId),
  });

  const complianceOutstanding = studentQuery.data?.waiver_status !== "signed";
  const sections = useSectionState(complianceOutstanding);

  if (!studentId) {
    return (
      <section className="space-y-4">
        <BackLink />
        <Card p={20}>
          <p className="text-sm text-rally-muted">Missing student id.</p>
        </Card>
      </section>
    );
  }

  if (studentQuery.isPending) {
    return (
      <section className="space-y-4">
        <BackLink />
        <Card p={20}>
          <div
            className="h-24 animate-pulse rounded-lg bg-neutral-100 dark:bg-neutral-800"
            aria-label="Loading student"
          />
        </Card>
      </section>
    );
  }

  if (studentQuery.isError) {
    return (
      <section className="space-y-4">
        <BackLink />
        <Card p={20}>
          <p role="alert" className="text-sm text-red-700">
            Could not load student.
          </p>
        </Card>
      </section>
    );
  }

  const student = studentQuery.data;
  if (!student) {
    return (
      <section className="space-y-4">
        <BackLink />
        <Card p={20}>
          <p className="text-sm text-rally-muted">Student not found.</p>
        </Card>
      </section>
    );
  }

  const invalidateStudent = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.admin.studentDetail(studentId) });
    void queryClient.invalidateQueries({ queryKey: ["admin", "students"] });
  };

  return (
    <section
      className="space-y-6"
      data-testid="admin-student-detail"
      data-student-id={student.student_id}
    >
      <BackLink />
      {stopAllClassesOpen && (
        <StopAllClassesDialog
          studentId={student.student_id}
          studentName={student.full_name}
          policyDefaultOutcome={departurePolicyQuery.data?.drop_default_outcome}
          onClose={() => setStopAllClassesOpen(false)}
          onDone={() => {
            void queryClient.invalidateQueries({
              queryKey: queryKeys.admin.studentDetail(studentId),
            });
          }}
        />
      )}
      <StudentSummaryStrip student={student} />

      <div className="grid gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
        <StudentRail
          student={student}
          onStopAllClasses={() => setStopAllClassesOpen(true)}
          onJumpTo={sections.jumpTo}
        />

        <div className="min-w-0 space-y-6">
          <CollapsibleSection
            id="enrollments"
            title="Enrollments"
            icon={<CalendarCheck className="size-4 text-rally-muted" aria-hidden="true" />}
            open={sections.isOpen("enrollments")}
            onToggle={() => sections.toggle("enrollments")}
          >
            <EnrollmentsSection student={student} studentId={studentId} queryClient={queryClient} />
          </CollapsibleSection>

          <CollapsibleSection
            id="training"
            title="Training & attendance"
            icon={<Activity className="size-4 text-rally-muted" aria-hidden="true" />}
            open={sections.isOpen("training")}
            onToggle={() => sections.toggle("training")}
          >
            <div className="grid gap-6 lg:grid-cols-2">
              <div className="space-y-6">
                <TrainingSnapshot student={student} />
                <SkillPathwayPanel student={student} />
              </div>
              <div className="space-y-6">
                <RecentAttendancePanel student={student} />
                <EngagementPanel student={student} />
              </div>
            </div>
          </CollapsibleSection>

          <CollapsibleSection
            id="billing"
            title="Billing"
            icon={<Wallet className="size-4 text-rally-muted" aria-hidden="true" />}
            open={sections.isOpen("billing")}
            onToggle={() => sections.toggle("billing")}
            headExtra={<BillingSummaryLine student={student} />}
          >
            <FamilyBillingLink parentId={student.parent_id} parentName={student.parent_name} />
          </CollapsibleSection>

          <CollapsibleSection
            id="profile"
            title="Profile"
            icon={<UserRound className="size-4 text-rally-muted" aria-hidden="true" />}
            open={sections.isOpen("profile")}
            onToggle={() => sections.toggle("profile")}
          >
            <StudentEditForm student={student} onSaved={invalidateStudent} />
          </CollapsibleSection>

          <CollapsibleSection
            id="compliance"
            title="Compliance"
            icon={<ShieldCheck className="size-4 text-rally-muted" aria-hidden="true" />}
            open={sections.isOpen("compliance")}
            onToggle={() => sections.toggle("compliance")}
          >
            <ComplianceSummary student={student} />
            <div className="mt-6 border-t border-neutral-200 pt-4">
              <Overline>Parent account</Overline>
              <ChangeParentPanel
                student={student}
                parents={parentsQuery.data?.users ?? []}
                parentsLoading={parentsQuery.isLoading}
                parentsError={parentsQuery.isError}
                onSaved={() => {
                  invalidateStudent();
                  void queryClient.invalidateQueries({ queryKey: queryKeys.admin.users("parent") });
                }}
              />
            </div>
          </CollapsibleSection>
        </div>
      </div>
    </section>
  );
}

/**
 * Wraps the pure helpers in `./section-state` with the actual
 * localStorage/hash access, which only exists in the browser. A `#section`
 * hash force-opens that section (without overwriting the stored preference
 * for the others) and scrolls it into view once, on mount.
 */
function useSectionState(complianceOutstanding: boolean) {
  const [stored, setStored] = useState<Partial<Record<SectionId, boolean>>>({});
  const [hashOpen, setHashOpen] = useState<SectionId | null>(null);

  useEffect(() => {
    try {
      setStored(parseStoredSections(window.localStorage.getItem(SECTION_STORAGE_KEY)));
    } catch {
      // Private browsing / disabled storage: fall back to defaults.
    }
    const fromHash = sectionIdFromHash(window.location.hash);
    if (fromHash) {
      setHashOpen(fromHash);
      // Let the section render open before scrolling to it.
      requestAnimationFrame(() => {
        document.getElementById(`section-${fromHash}`)?.scrollIntoView({ block: "start" });
      });
    }
    // Only ever read on mount — a later manual hash edit does not re-trigger this.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const isOpen = (id: SectionId) => {
    if (id === hashOpen) return true;
    return stored[id] ?? defaultSectionOpen(id, complianceOutstanding);
  };

  const toggle = (id: SectionId) => {
    // The write stays OUTSIDE the setState updater: React invokes updaters
    // twice under StrictMode in dev, and a state updater must stay pure.
    const next = { ...stored, [id]: !isOpen(id) };
    try {
      window.localStorage.setItem(SECTION_STORAGE_KEY, serializeSections(next));
    } catch {
      // Ignore write failures (private browsing, quota) — state still updates in memory.
    }
    setStored(next);
    if (hashOpen === id) setHashOpen(null);
  };

  const jumpTo = (id: SectionId) => {
    if (!isOpen(id)) toggle(id);
    document.getElementById(`section-${id}`)?.scrollIntoView({ block: "start" });
  };

  return { isOpen, toggle, jumpTo };
}

function StudentSummaryStrip({ student }: { student: AdminStudentDetail }) {
  const outstandingBalance =
    student.outstanding_balance_cents ??
    student.payment_history.reduce(
      (sum, payment) =>
        OPEN_BILLING_STATUSES.has(payment.status) ? sum + Math.max(payment.balance_due_cents, 0) : sum,
      0,
    );
  const unpaidInvoiceCount = student.payment_history.filter(
    (payment) => OPEN_BILLING_STATUSES.has(payment.status) && payment.balance_due_cents > 0,
  ).length;
  const attendance =
    student.attendance_rate == null
      ? "—"
      : `${Math.round(Math.max(0, Math.min(student.attendance_rate, 1)) * 100)}%`;

  return (
    <div
      className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"
      data-testid="admin-student-summary-strip"
    >
      <SummaryMetric
        icon={<CalendarCheck className="size-4" aria-hidden="true" />}
        label="Active sessions"
        value={String(student.active_session_count)}
        detail={
          student.last_seen_at
            ? `Last attended ${formatDate(student.last_seen_at)}`
            : "No attendance yet"
        }
      />
      <SummaryMetric
        icon={<Activity className="size-4" aria-hidden="true" />}
        label="Attendance"
        value={attendance}
        detail="Last 30 days"
      />
      <SummaryMetric
        icon={<Wallet className="size-4" aria-hidden="true" />}
        label="Outstanding balance"
        value={formatCurrencyCents(outstandingBalance)}
        detail={
          unpaidInvoiceCount === 0
            ? "No unpaid invoices"
            : `${unpaidInvoiceCount} unpaid ${unpaidInvoiceCount === 1 ? "invoice" : "invoices"}`
        }
      />
      <SummaryMetric
        icon={<FileCheck className="size-4" aria-hidden="true" />}
        label="Waiver"
        value={(student.waiver_status ?? "unknown").toUpperCase()}
        detail={student.waiver_version ?? "No version on file"}
      />
    </div>
  );
}

function SummaryMetric({
  icon,
  label,
  value,
  detail,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-4">
      <div className="flex items-center gap-2 text-rally-muted">
        {icon}
        <span className="font-mono text-[10px] font-bold uppercase tracking-overline">
          {label}
        </span>
      </div>
      <div className="mt-3 font-mono text-2xl font-semibold tabular-nums text-rally-ink">
        {value}
      </div>
      <div className="mt-1 truncate text-xs text-rally-muted">{detail}</div>
    </div>
  );
}

function EngagementPanel({ student }: { student: AdminStudentDetail }) {
  return (
    <Card p={20}>
      <div className="flex items-center gap-2">
        <Activity className="size-4 text-rally-muted" aria-hidden="true" />
        <Overline>Engagement</Overline>
      </div>
      <DetailList
        rows={[
          { label: "Active sessions", value: String(student.active_session_count) },
          {
            label: "Attendance (30d)",
            value:
              student.attendance_rate == null
                ? "—"
                : `${Math.round(Math.max(0, Math.min(student.attendance_rate, 1)) * 100)}%`,
          },
          { label: "Last attended", value: student.last_seen_at ? formatDate(student.last_seen_at) : "—" },
          { label: "Dues", value: student.dues_status.toUpperCase() },
        ]}
      />
    </Card>
  );
}

function TrainingSnapshot({ student }: { student: AdminStudentDetail }) {
  const academyId = getActiveAcademyId() ?? "";
  const { data: programs } = useQuery({
    queryKey: ["admin", "programs", academyId],
    queryFn: () => listPrograms(academyId),
    enabled: Boolean(academyId),
  });
  // TODO: derive programId from student.enrolled_sessions once AdminStudentSessionSummary
  // exposes pathway_program_id — for now fall back to programs[0]
  const programId = programs?.[0]?.program_id ?? "";
  const { data: progress } = useQuery({
    queryKey: ["admin", "student-progress", student.student_id, programId],
    queryFn: () => getStudentProgress(student.student_id, programId),
    enabled: Boolean(programId),
  });

  return (
    <Card p={20}>
      <div className="flex items-center gap-2">
        <Activity className="size-4 text-rally-muted" aria-hidden="true" />
        <Overline>Skill pathway placement</Overline>
      </div>
      {progress?.current_level_name ? (
        <>
          <p className="mt-3 text-sm text-rally-muted">
            Level {progress.current_level_sequence}: {progress.current_level_name}
          </p>
          <p className="mt-0.5 text-xs text-rally-muted">
            {progress.passed_skills} / {progress.total_skills} skills passed
          </p>
        </>
      ) : (
        <p className="mt-3 text-sm text-rally-muted">Not placed in a level yet.</p>
      )}
    </Card>
  );
}

function SkillPathwayPanel({ student }: { student: AdminStudentDetail }) {
  return (
    <Card p={20}>
      <div className="flex items-center gap-2">
        <Activity className="size-4 text-rally-muted" aria-hidden="true" />
        <Overline>Skill pathway</Overline>
      </div>
      <p className="mt-3 text-sm text-rally-muted">
        Place this student in a curriculum level and review skill completion.
      </p>
      <div className="mt-4">
        <Link
          href={buildStudentProgressHref({
            studentId: student.student_id,
            returnTo: `/admin/students/${encodeURIComponent(student.student_id)}`,
            returnLabel: "Back to student profile",
          }) as Parameters<typeof Link>[0]["href"]}
          className="inline-flex items-center justify-center rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white transition-colors hover:bg-blue-700"
        >
          Manage skill progress
        </Link>
      </div>
    </Card>
  );
}

function RecentAttendancePanel({ student }: { student: AdminStudentDetail }) {
  const recent = student.recent_attendance ?? [];

  return (
    <Card p={20}>
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <CalendarCheck className="size-4 text-rally-muted" aria-hidden="true" />
          <Overline>Recent attendance</Overline>
        </div>
        <span className="font-mono text-xs text-rally-muted tabular-nums">{recent.length} records</span>
      </div>
      {recent.length === 0 ? (
        <p className="mt-3 text-sm text-rally-muted">No attendance records yet.</p>
      ) : (
        <div className="mt-3 overflow-x-auto" data-testid="admin-student-recent-attendance">
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-neutral-200 text-xs uppercase tracking-overline text-rally-muted">
              <tr>
                <th className="py-2 pr-4 font-medium">Date</th>
                <th className="py-2 pr-4 font-medium">Status</th>
                <th className="py-2 font-medium">Marked</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-100">
              {recent.map((entry) => (
                <tr key={`${entry.session_id}-${entry.date}-${entry.status}`}>
                  <td className="py-3 pr-4 align-top text-rally-ink">{formatDateUtc(entry.date)}</td>
                  <td className="py-3 pr-4 align-top">
                    <StatusChip status={entry.status} />
                  </td>
                  <td className="py-3 align-top text-rally-muted">{formatDateTime(entry.marked_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function ComplianceSummary({ student }: { student: AdminStudentDetail }) {
  return (
    <DetailList
      rows={[
        { label: "Waiver status", value: (student.waiver_status ?? "unknown").toUpperCase() },
        { label: "Waiver version", value: student.waiver_version ?? "—" },
        { label: "Signed at", value: formatDateTime(student.waiver_signed_at) },
        { label: "Parent", value: student.parent_name ?? student.parent_email ?? "—" },
      ]}
    />
  );
}

function BackLink() {
  return (
    <Link
      href="/admin/students"
      className="inline-flex items-center gap-1.5 text-sm text-rally-muted hover:text-rally-ink focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600 rounded"
    >
      <ArrowLeft className="size-4" aria-hidden="true" />
      <span>All students</span>
    </Link>
  );
}
```

Note: `data-testid="admin-student-edit-form"` (singular, no `-overview-`/`-training-`/`-family-` suffix, per Task 9) is the new testid the e2e spec targets in Task 12.

- [ ] Typecheck:

```
cd frontend && pnpm typecheck
```

- [ ] Lint:

```
cd frontend && pnpm lint
```

- [ ] Commit:

```
git add frontend/app/\(admin\)/admin/students/\[studentId\]/StudentRail.tsx frontend/app/\(admin\)/admin/students/\[studentId\]/page.tsx
git commit -m "feat(admin-students): replace the five-tab student page with a single scrolling view

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: Remove `ChangeParentPanel` from the student page (gated)

**Files:**
- Modify: `frontend/app/(admin)/admin/students/[studentId]/page.tsx`

**Interfaces:** none new — deletes `parentsQuery`, the `ChangeParentPanel` import and its render block, and the `listAdminUsers` import.

- [ ] **Gate check — do this before editing anything.** Confirm the family page already has a "Move child to another family" control (spec 2 §6). Run:

```
grep -rn "Move child to another family" frontend/app/\(admin\)/admin/families
```

If this returns no match, **stop this task**: leave `page.tsx` exactly as Task 10 left it (with `ChangeParentPanel` still in the Compliance section), skip straight to Task 12, and do not remove the panel until the family-page parent-picker has shipped. Re-run the grep before resuming.

**Expected outcome in the agreed build order:** the grep returns nothing. Plan 2 (`docs/superpowers/plans/2026-09-10-families-directory-consolidation.md`) has no "Move child to another family" task — its Self-review §6 row explicitly defers that control (and relocating `ChangeParentPanel`) to a follow-on plan. So this task is skipped on the first pass and becomes a one-commit follow-up after that control lands. The literal string `Move child to another family` is the gate contract; whichever plan eventually builds the control must use that exact label.

- [ ] Once the grep confirms the control exists, remove `parentsQuery` (the block right after `studentQuery`):

```tsx
  const parentsQuery = useQuery({
    queryKey: queryKeys.admin.users("parent"),
    queryFn: () => listAdminUsers("parent"),
    enabled: Boolean(studentId),
  });
```

- [ ] Remove the `listAdminUsers` import: delete `import { listAdminUsers } from "@/lib/api/admin";`.

- [ ] Remove `ChangeParentPanel` from the Compliance section's body — replace:

```tsx
            <ComplianceSummary student={student} />
            <div className="mt-6 border-t border-neutral-200 pt-4">
              <Overline>Parent account</Overline>
              <ChangeParentPanel
                student={student}
                parents={parentsQuery.data?.users ?? []}
                parentsLoading={parentsQuery.isLoading}
                parentsError={parentsQuery.isError}
                onSaved={() => {
                  invalidateStudent();
                  void queryClient.invalidateQueries({ queryKey: queryKeys.admin.users("parent") });
                }}
              />
            </div>
```

with:

```tsx
            <ComplianceSummary student={student} />
```

- [ ] Update the `StudentEditForm` import line to drop `ChangeParentPanel`:

```tsx
import { StudentEditForm } from "./StudentEditForm";
```

(`ChangeParentPanel` stays defined and exported from `StudentEditForm.tsx` — spec 2 owns relocating it to the family page; this page just stops calling it.)

- [ ] Typecheck:

```
cd frontend && pnpm typecheck
```

- [ ] Commit:

```
git add frontend/app/\(admin\)/admin/students/\[studentId\]/page.tsx
git commit -m "refactor(admin-students): remove the parent picker from the student page

Parent reassignment now lives on the family page (spec 2 §6, 'Move child to
another family'), which this change confirms is already shipped.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 12: Rewrite the e2e coverage

**Files:**
- Modify: `frontend/e2e/specs/admin-students.spec.ts` (the `"renders the student profile with enrolled sessions and payment history"` test, lines 232-486; the fixture data at lines ~236-352 is unchanged)
- Modify: `frontend/e2e/specs/tuition-discounts.spec.ts` — **this spec also drives the student page and also clicks tabs** (`getByRole("tab", { name: "Sessions" })` at line 458, `getByRole("tab", { name: "Billing" })` at line 497, against `/admin/students/student-discounts`). It was missed in the first draft of this plan; it will fail without the edits below.
- Modify: `frontend/e2e/specs/admin-enrollment-withdraw.spec.ts` — plan 1 (Task 9) added a `stubStudentDetail` helper, an `openSessionsTab` helper that clicks `getByRole("tab", { name: "Sessions" })`, and a `test.describe("departure actions from the student page …")` block that drives `/admin/students/${STUDENT_ID}`. After this plan there is no Sessions tab, and the rail's `FamilyCard` fetches `GET /api/v2/admin/users/parent-1`, which `stubStudentDetail`'s catch-all `if (request.method() === "GET") return fulfillJson(route, {})` answers with `{}` — `loginBadge(undefined, …)` then throws on `status.toUpperCase()` and blanks the page. Both need the edits below.
- Verify (no expected changes): `frontend/e2e/specs/admin-family-billing.spec.ts` — it does not navigate to `/admin/students/[studentId]` and does not use `getByRole("tab")`.

**Interfaces:** none — this is test-only. Exercises: `admin-student-section-<id>-toggle`, `admin-student-section-<id>`, `admin-student-jump-<id>`, `admin-student-edit-form`, `admin-student-billing-summary-line`.

- [ ] Re-run the sweep that finds every spec touching the student page's tabs, so nothing else is missed:

```
cd frontend && grep -rn 'getByRole("tab"' e2e/specs/ && grep -rn 'admin/students/' e2e/specs/
```

Expected hits: `admin-students.spec.ts` (edited below), `tuition-discounts.spec.ts` (edited below), `admin-enrollment-withdraw.spec.ts` (plan 1's student-page block — edited below), `parent-self-service.spec.ts` (a *parent* page's tabs — unrelated, leave alone) and `local-auth-inventory.spec.ts` (route-matrix table only, no tab clicks — leave alone). Anything else, extend this task.

- [ ] **New route stub required in both student-page specs.** The rail's `FamilyCard`
now calls `getAdminUser(student.parent_id)` → `GET /api/v2/admin/users/{parentId}` on every
page load. The existing `**/api/v2/admin/users?role=parent` stub does **not** match that
path, so without a new stub the request 401/404s and trips each spec's
`expect(errors).toEqual([])` clean-console assertion. Add to `admin-students.spec.ts`
alongside the other student-page routes:

```ts
    // The rail's family card reads the parent's membership status for the login badge.
    await page.route("**/api/v2/admin/users/parent-1", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, {
        user_id: "parent-1",
        email: "rohan@example.com",
        display_name: "Rohan Rao",
        role: "parent",
        status: "active",
        phone: "555-0101",
        roles: ["parent"],
        linked_student_count: 1,
        session_count: 0,
        login_invite_sent_at: "2026-05-01T10:00:00Z",
      });
    });
```

and the same shape (ids swapped for `parent-discounts`) in `tuition-discounts.spec.ts`.
Register it **before** the broader `**/api/v2/admin/users?role=parent` route so Playwright's
last-registered-wins ordering does not shadow it — or simply confirm the two globs cannot
both match (`users?role=parent` has no path segment after `users`, so they are disjoint).

- [ ] Replace lines 411-485 of `admin-students.spec.ts` (from `await expect(page.getByTestId("admin-student-detail"))...` through the final `expect(errors, ...)`). **Leave lines 486-487 (`  });` and `});`) in place** — the block below ends with them for readability, so if you paste it verbatim you must replace 411-487, not 411-485. Pick one and check the file's brace balance afterwards.

```ts
    await expect(page.getByTestId("admin-student-detail")).toContainText("Amit Rao");
    await expect(page.getByTestId("admin-student-summary-strip")).toContainText("$110");
    await expect(page.getByTestId("admin-student-summary-strip")).toContainText("91%");

    // Enrollments is open by default — no click needed.
    await expect(page.getByTestId("admin-student-enrolled-sessions")).toContainText("Advanced Footwork");
    await expect(page.getByTestId("admin-student-enrolled-sessions")).toContainText("$150");
    const autopayChip = page.getByTestId("admin-student-autopay-enr-1");
    await expect(autopayChip).toHaveText("Autopay");
    await expect(autopayChip).toHaveAttribute("href", "/admin/families/parent-1");
    await expect(page.getByTestId("admin-student-autopay-enr-2")).toHaveText("Manual");
    const pastRow = page.getByTestId("admin-student-past-enrollment-enr-0");
    await expect(pastRow).toContainText("Beginner Basics");
    await expect(pastRow).toContainText("Cancelled");
    await expect(pastRow).toContainText("2026");
    await expect(pastRow).toContainText("Parent");
    await expect(pastRow).toContainText("Schedule conflict");
    const adminCancelRow = page.getByTestId("admin-student-past-enrollment-enr-9");
    await expect(adminCancelRow).toContainText("9/1/2026");
    await expect(adminCancelRow).not.toContainText("8/31");
    await expect(adminCancelRow).toContainText("Admin");
    await expect(adminCancelRow).toContainText("Moved away");

    // Training & attendance is open by default too.
    await expect(page.getByTestId("admin-student-recent-attendance")).toContainText("PRESENT");

    // Billing: the summary line is always visible even though the detail is collapsed.
    await expect(page.getByTestId("admin-student-billing-summary-line")).toContainText("/mo across");
    await page.getByTestId("admin-student-section-billing-toggle").click();
    await expect(page.getByTestId("admin-student-family-billing-link")).toContainText("Open family billing");
    await expect(
      page.getByTestId("admin-student-family-billing-link").getByRole("link"),
    ).toHaveAttribute("href", /\/admin\/families\//);

    // Profile is collapsed by default; open it to edit the consolidated form.
    await page.getByTestId("admin-student-section-profile-toggle").click();
    const editForm = page.getByTestId("admin-student-edit-form");
    await expect(page.getByLabel("Previous experience")).toHaveValue("Two years of club play");
    await expect(page.getByLabel("Previous experience")).toHaveAttribute("maxlength", "1000");
    await expect(page.getByLabel("Medical notes")).toHaveValue("Peanut allergy");
    await expect(page.getByLabel("Medical notes")).toHaveAttribute("maxlength", "1000");
    await expect(page.getByLabel("Emergency contact name")).toHaveValue("Anita Chen");
    await expect(page.getByLabel("Emergency contact phone")).toHaveValue("555-0199");
    await expect(page.getByLabel("Emergency contact phone")).toHaveAttribute("maxlength", "40");
    await expect(page.getByLabel("T-shirt size")).toHaveValue("M");
    await expect(page.getByLabel("T-shirt size")).toHaveAttribute("maxlength", "20");
    const medicalNotes = editForm.getByLabel("Medical notes");
    await medicalNotes.focus();
    await page.keyboard.press(process.platform === "darwin" ? "Meta+A" : "Control+A");
    await page.keyboard.press("Backspace");
    await expect(medicalNotes).toHaveValue("");
    await editForm.getByRole("button", { name: /^save changes$/i }).click();
    expect(patchBody).toMatchObject({ medical_notes: "", reason: "Admin profile update" });

    // Compliance is collapsed by default here — the fixture's waiver is signed.
    await page.getByTestId("admin-student-section-compliance-toggle").click();
    await expect(page.getByTestId("admin-student-section-compliance")).toContainText("2026-v1");

    expect(errors, `App console errors: ${errors.join("\n")}`).toEqual([]);
  });
});
```

- [ ] Update `tuition-discounts.spec.ts` (test `"admin sets scholarship waiver and coach-child partial discounts"`):
  - delete line 458 `await page.getByRole("tab", { name: "Sessions" }).click();` — Enrollments is open by default, so the table is on screen straight after `page.goto`.
  - replace line 497 `await page.getByRole("tab", { name: "Billing" }).click();` with `await page.getByTestId("admin-student-section-billing-toggle").click();` (the comment above it about the invoice ledger having moved to the family page stays accurate).
  - add the `**/api/v2/admin/users/parent-discounts` stub described above.
  - that spec's own trailing `expect(errors).toEqual([])` and `guard.assertNoLegacyApiCalls()` are what catch anything else the newly always-mounted panels fetch — run it and read the failing URL rather than guessing.

- [ ] Update `admin-enrollment-withdraw.spec.ts` (plan 1's student-page additions):
  - In `openSessionsTab`, delete `await page.getByRole("tab", { name: "Sessions" }).click();` and its explanatory doc comment about `useState<StudentTab>` — Enrollments is open by default, so `page.goto` followed by the `Tuesday Beginner` visibility check is enough. Rename the helper `openStudentPage` (both call sites are inside the `"departure actions from the student page"` describe block).
  - In `stubStudentDetail`, add a branch **above** the trailing `if (request.method() === "GET") return fulfillJson(route, {});` catch-all so the rail's family card gets a real user document:
    ```ts
    if (request.method() === "GET" && path === "/api/v2/admin/users/parent-1") {
      return fulfillJson(route, {
        user_id: "parent-1", email: "parent@example.com", display_name: "Parent Example",
        role: "parent", status: "active", phone: null, roles: ["parent"],
        linked_student_count: 1, session_count: 0, login_invite_sent_at: null,
      });
    }
    ```
  - Leave every other assertion in that block alone — the Hold → Return and Drop flows, the `notify_family: true` body assertion and the `admin-student-past-enrollment-…` row check are plan 1's contract and still hold on the single-view page.

- [ ] Run the spec:

```
cd frontend && pnpm exec playwright test admin-students --project=chromium-desktop
```

Expected: PASS. Note `--project=chromium` does **not** exist: `playwright.config.ts` defines `chromium-mobile`, `webkit-mobile` and `chromium-desktop`. Run it once on `--project=chromium-mobile` too — that is the phone breakpoint spec §6 asks to eyeball, and the always-visible Billing summary line has to survive it. If the "Profile" section's toggle click doesn't reveal the form (e.g. a selector mismatch), re-check `CollapsibleSection`'s `data-testid` pattern from Task 2 (`admin-student-section-${id}-toggle`) against what's used here.

- [ ] Run the other student-page spec and the two adjacent specs. Note the project split: only `admin-(shell|students|registrations|level-ups-lifecycle)` match `chromium-desktop`'s `testMatch`, so `tuition-discounts`, `admin-family-billing` and `admin-enrollment-withdraw` run under `chromium-mobile` (plan 1 verified this; `--project=chromium-desktop` would select zero tests for them):

```
cd frontend && pnpm exec playwright test tuition-discounts admin-family-billing admin-enrollment-withdraw --project=chromium-mobile
```

Expected: PASS.

- [ ] Commit:

```
git add frontend/e2e/specs/admin-students.spec.ts frontend/e2e/specs/tuition-discounts.spec.ts frontend/e2e/specs/admin-enrollment-withdraw.spec.ts
git commit -m "test(admin-students): rewrite e2e coverage for the single-view student page

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 13: Release note

**Files:**
- Create: `docs/release-notes/2026-09-10-student-page-single-view.md`

- [ ] Write the release note. The `PR:` line is filled in after the PR is opened — replace `#<number>` with the real PR number before merging (CI's "Release Notes Gate" requires the real number):

```md
# student-page-single-view

PR: #<number>

## What changed

Replaces the admin student detail page's five tabs (Overview, Training, Sessions, Billing,
Family) with one scrolling page: a sticky left rail (avatar, status, level, DOB/age, Stop all
classes, a compact family card with a login badge, and section jump links) plus five
collapsible sections — Enrollments, Training & attendance, Billing, Profile, Compliance.
Enrollments now shows session-type billing (price, override badge, Move/Override-price
actions) merged into the same table as the per-session enrollment rows instead of a separate
tab, alongside the Hold / Return / Drop / Delete actions the departure-actions change
(`2026-09-10-departure-actions-from-student-page.md`) already put there. Profile consolidates
the old Overview/Training/Family split into one form. Parent reassignment
(`ChangeParentPanel`) now sits inside the collapsed Compliance section; it leaves this page
in a follow-up once the family page ships its "Move child to another family" control
(spec 2 §6 — not part of the families-directory-consolidation PR). *(If Task 11's gate passed
and the panel was removed in this PR, replace the previous sentence with: Parent reassignment
is off this page; the family page's "Move child to another family" control is the only place
to do it now.)* Section open/closed state is remembered per browser, and
`#enrollments`-style links from other pages still work.

## Deploy notes

Frontend-only; no backend or migration changes. No new routes — the QA inventory manifest is
untouched.

## Risk / rollback

Every section now mounts unconditionally instead of lazily behind a tab, so all of the panels'
queries (session-type billing, session types, programs, student progress) fire on every page
load rather than only when their tab was opened — this is the intended tradeoff (spec §2) and
is covered by the rewritten `admin-students.spec.ts` clean-console assertion, which fails on
any unstubbed request. Revert the merge commit if the extra concurrent requests cause load
problems in practice.
```

- [ ] Commit:

```
git add docs/release-notes/2026-09-10-student-page-single-view.md
git commit -m "docs(release-notes): add release note for student page single view

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review

| Spec section | Covered by |
|---|---|
| §2 Tabs removed → one scrolling page with collapsible sections + sticky rail | Task 2 (`CollapsibleSection`), Task 10 (layout) |
| §2 Parent data off this page; compact family card links to family page | Task 10 (`StudentRail`'s `FamilyCard`), Task 11 (`ChangeParentPanel` removal, gated — **expected to be skipped** on the first pass because plan 2 defers "Move child to another family"; see Global Constraints) |
| §2 Sections open by default: Header/Enrollments/Training; Billing summary always visible, detail collapsed; Compliance auto-opens when outstanding | Task 1 (`defaultSectionOpen`), Task 8 (`BillingSummaryLine`), Task 10 |
| §2 No aggregate endpoint; panels keep their own queries, skeletons while loading | Task 7 (`EnrollmentsSection` fetches its own data); every existing panel's own `useQuery` is untouched |
| §3 Rail: avatar, name, status, level, DOB/age, Stop all classes, family card with login badge, jump links | Task 10 (`StudentRail.tsx`) |
| §3.1 Enrollments: SessionsPanel table + BillingEnrollmentsPanel facts merged into the same rows, one table not two; past enrollments collapse after 5 | Task 4 (`billingFactsByEnrollmentId`), Task 5 (`SessionsPanel` row/cell merge + collapse), Task 6-7 (dialogs relocated to `EnrollmentsSection`) |
| §3.1 "**the spec-1 action set**" | **NOT this plan.** Delivered first by `docs/superpowers/plans/2026-09-10-departure-actions-from-student-page.md` (plan 1): `departureActionsFor(session.status)` → Hold / Return / Drop / Delete in `DepartureActions`' overflow menu, dialogs under `frontend/components/admin/enrollment/`. This plan consumes it as-is — Task 5 leaves the `actions={departureActionsFor(session.status)}` block untouched and only adds the session-type billing cell; Task 7's `EnrollmentsSection` forwards plan 1's `studentName` / `familyLabel` props. See Global Constraints and Task 5's sequencing note. |
| §3.2 Training & attendance: SkillPathwayPanel, training snapshot, RecentAttendancePanel, EngagementPanel | Task 10 |
| §3.3 Billing: always-visible summary line + link, detail collapsed | Task 4 (`billingSummaryFacts`/`billingSummaryLine`), Task 8, Task 10 |
| §3.4 Profile: one StudentEditForm, mode prop gone | Task 9 |
| §3.5 Compliance: ComplianceSummary, collapsed when clean / open when outstanding | Task 1, Task 10 |
| §3 Section state remembered per browser (localStorage); `#section` deep links open + scroll | Task 1 (pure helpers), Task 10 (`useSectionState` hook) |
| §4 What leaves this page: ChangeParentPanel, family-mode parent fields, FamilyBillingLink panel body | Task 9 (mode removed — `StudentEditForm` never had parent contact fields, only t-shirt under `mode="family"`, now folded into Profile), Task 11 (`ChangeParentPanel`); `FamilyBillingLink`'s existing "point at the family page" body is kept as-is inside the Billing section's collapsed detail, matching §3.3's own description of that detail |
| §4 Sequencing: family page's parent-picker ships before ChangeParentPanel leaves this page | Task 11's gate check (`grep` for "Move child to another family" before editing) |
| §5 Out of scope: no backend/endpoint change | No task touches `backend/` or adds a route |
| §5 Out of scope: no coach/parent view changes | Not touched |
| §5 Out of scope: no redesign of individual panels' internals (skill pathway, attendance) | `SkillPathwayPanel` and `RecentAttendancePanel` are carried over verbatim in Task 10. **`TrainingSnapshot` is not verbatim**: it was an inline bordered `div` nested inside the Training tab's "Training details" card (`page.tsx:479-495`) and Task 10 promotes it to its own `Card` with an `Overline` heading, because the card that used to contain it is gone. That is a wrapper change, not an internals change, but it does mean Training now shows two adjacent cards headed "Skill pathway placement" and "Skill pathway" — spec §3.2 asks for both, so this is intentional; give the pair a look during the manual QA pass and merge them only if the owner asks. |
| §6 Testing: e2e spec rewritten off tab roles/testids; other specs re-checked | Task 12 — `admin-students.spec.ts` **and** `tuition-discounts.spec.ts` (which the spec's "other two specs" wording missed; it also drives this page and clicks its tabs). `admin-family-billing.spec.ts` and `admin-enrollment-withdraw.spec.ts` verified clean. |
| §6 Testing: clean-console spec, no unstubbed 4xx/5xx | Task 12 (existing `errors` assertion, kept) |
| §6 Testing: visual check phone/desktop | Not automatable in this repo's suite — flag for manual QA before merge (see below) |

**Open questions for the owner (answer before or during execution; both are listed in full at their task):**

1. **Where the two session-type actions go in the enrollment row** (Task 5). Adding them inline contradicts sibling spec 1 §3's "nothing new is inline". Options (a) overflow menu / (b) inline as drafted / (c) second line under the billing cell.
2. **Whether `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json` gets its `/admin/students/[studentId]` entry updated** (Global Constraints). Its "Billing tab" / "Family tab" workflows, the "Selected invoice stale after tab switch" risk edge and the "Parent selector" / "Parent change" controls all describe a page this change deletes. Leaving it alone keeps CI green; updating it means touching the matching `acceptance` strings in the same edit.

**Deliberately deferred / documented deviations:**

- **"Login badge" on the family card** (§3): there is no "last logged in" field anywhere in the API, and adding one is a backend change this spec rules out. Task 10 instead reads the already-existing `GET /admin/users/{id}` (`getAdminUser`) response, which carries both `status` — the membership status, `Literal["invited", "active", "suspended", "removed"]` per `backend/v2/contexts/identity/domain/models.py:60` — and `login_invite_sent_at`. The badge renders three states (ACTIVE / INVITED / the raw status), matching the vocabulary spec 2 §3 picked for the families list ("never invited / invited on date / active") and the chip convention at `app/(admin)/admin/users/[userId]/page.tsx:428-431`, which renders `status.toUpperCase()` with variant `enrolled` when active and `expired` otherwise. (An earlier draft of this plan collapsed it to a binary REGISTERED/INVITED off `status` alone; that mislabels a suspended or removed parent as "INVITED", and "REGISTERED" is already taken on the families page for a *card-on-file* billing state — don't reintroduce it.) This adds one request per student-page load; both e2e specs that open the page now stub it (Task 12).
- **Compliance auto-open's "medical answer outstanding" clause** (§3.5): only `waiver_status` is available as a compliance signal on `AdminStudentDetail` — there is no "medical answer outstanding" field in the current schema. `defaultSectionOpen` (Task 1) keys only on `waiver_status !== "signed"`. If a medical-compliance flag is added later, extend `defaultSectionOpen`'s single call site in `page.tsx`.
- **Visual check on phone and desktop** (§6): left as manual QA — this repo's Playwright suite doesn't do screenshot diffing for this page, and adding it is a larger effort than this plan's scope.
- **`ChangeParentPanel` and `Field`'s continued export from `StudentEditForm.tsx`** (§4): Task 11 stops this page from rendering `ChangeParentPanel`, but does not delete or relocate the component itself — moving it onto the family page is spec 2's deliverable, and duplicating it here would violate DRY ahead of that work landing.
