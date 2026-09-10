# Student Page Single View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the five-tab admin student page (`/admin/students/[studentId]`) with one
scrolling page — a sticky left rail plus collapsible sections — so an admin can see status,
enrollments, billing, training and compliance without clicking between tabs.

**Architecture:** `page.tsx` keeps its three existing queries (`departurePolicyQuery`,
`studentQuery`, `parentsQuery`) and stops gating panel mounts on `activeTab`; every section
mounts on page load behind a new local `CollapsibleSection` primitive whose open/closed state
is read from and written to `localStorage` per section id (read in a `useEffect`, never in the
`useState` initializer — see Task 2 — so the SSR pass and the first client render agree), with
a `hashchange`-aware effect that forces a matching section open and scrolls to it. The
Enrollments section renders `SessionsPanel`'s table — which already carries the per-enrollment
fee, discount and autopay chip the spec asks for — with `BillingEnrollmentsPanel` beneath it
for the move/override actions that exist nowhere else; see the OPEN QUESTION under "Self-review"
for why a literal single table is not buildable client-side today.

**Owner decision 2026-09-10 — the Billing section keeps its card.** Spec §3.3 ("a link to
the family page") and §4 ("`FamilyBillingLink`'s panel body" leaves this page) contradict
each other; the owner resolved it in favour of §3.3. The Billing section shows an
always-visible summary line plus, inside the collapsed body, the `FamilyBillingLink` card
and its link to `/admin/families/[parentId]`. Nothing billing-related is deleted from this
page by this plan.

The five components currently
defined inline in `page.tsx` (`EngagementPanel`, `TrainingSnapshot`, `SkillPathwayPanel`,
`RecentAttendancePanel`, `ComplianceSummary`) stay inline but move under the new section layout.
`ChangeParentPanel` and `StudentEditForm`'s `mode="family"` t-shirt field are deleted from this
page only after spec 2 ships "Move child to another family" on the family page (gated final
task, not assumed done).

**Tech Stack:** Next.js 16 (webpack build) App Router, TanStack Query v5, Tailwind, Rally
design system (`frontend/components/ds`), Vitest for unit tests, Playwright (`--project=chromium`)
for e2e. No backend changes — this is a frontend-only plan.

## Global Constraints

- No new endpoint, no aggregate query — each section keeps its own existing query (spec §2, "Aggregate endpoint").
- Sections open by default: Header (always visible, not collapsible), Enrollments, Training & attendance. The billing summary line renders **outside** the Billing `CollapsibleSection`, immediately above it, so it stays visible when the section is collapsed (spec §2 "Billing summary line always visible, detail collapsed"). Compliance starts collapsed, EXCEPT it auto-opens when `waiver_status !== "signed"` (spec §2, §3.5). `AdminStudentDetail.waiver_status` is optional (`lib/api/v2/students.ts:106`), so a payload that omits it is treated as outstanding and auto-opens — deliberate, documented in the helper's JSDoc.
- Past enrollments table (inside Enrollments section) collapses after 5 rows, matching spec §3.1 exactly ("collapsed after five rows").
- Section open/closed state persists per browser in `localStorage`, keyed per section id (spec §3, final paragraph).
- Deep links `#enrollments`, `#training`, `#billing`, `#profile`, `#compliance` open and scroll to that section (spec §3, final paragraph). These five ids are the fixed vocabulary — do not rename them once e2e specs reference them. The DOM anchor id MUST be exactly the bare section id (`id="enrollments"`), not a prefixed variant, or the browser's own `#enrollments` navigation and the rail's jump links resolve to nothing. The rail's jump links are same-page hash changes, which fire `hashchange` but not a remount, so the hash effect must subscribe to `hashchange` as well as running once on mount — otherwise clicking "Billing" in the rail never opens the collapsed Billing section.
- `StudentEditForm`'s three `mode` values (`overview` | `training` | `family`) collapse into one always-rendered form with no `mode` prop; the `family` mode's only field (t-shirt size) becomes part of the merged Profile form (spec §3.4, "The `mode` prop and the split go away").
- `ChangeParentPanel` and the parent-contact fields leave this page ONLY in the final task, gated on the family page shipping "Move child to another family" (spec §4 sequencing rule — verify before deleting, do not assume).
- Desktop layout: sticky left rail (~280px) + one scrolling column; mobile: rail becomes the top card, sections stack (spec §3).
- No backend change, no coach/parent view change, no redesign of individual panel internals (spec §5, Out of scope).
- Repo rule: a **new** `app/` route requires a matching `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json` entry in the same commit. No route is added or removed here — `CollapsibleSection.tsx` and `section-storage.ts` are plain modules inside an existing route directory, and the route stays `/admin/students/[studentId]` — so the required-route assertions in `backend/v2/tests/unit/test_audit_inventory_manifest.py` are unaffected. The manifest entry for this route (lines 1665-1730) nonetheless names workflows "Billing tab" and "Family tab", which stop existing; Task 9 relabels them. No backend file is touched at all, so the `backend/v2/composition/admin.py` size cap and the import-linter cross-context contracts are not in play, and there is no migration (prod runs migrations by hand) and no persona 404-vs-403 surface in this change.

## File structure

| File | Responsibility |
|---|---|
| `frontend/app/(admin)/admin/students/[studentId]/CollapsibleSection.tsx` | **Create.** Local disclosure primitive: header button (title + chevron), `localStorage`-backed open state keyed by `id`, `id={`student-section-${id}`}` for deep-link scroll targeting, controlled-open override prop for the hash-driven and auto-open-on-outstanding-compliance cases. **Correction:** the anchor id must be the bare section id (`id={id}`), not a `student-section-` prefix, or `#enrollments` resolves to nothing; and the stored open state is applied in a `useEffect`, never in the `useState` initializer, so SSR and first client render agree. |
| `frontend/app/(admin)/admin/students/[studentId]/section-storage.ts` | **Create.** Pure helpers `readSectionOpen(id, fallback)` / `writeSectionOpen(id, open)` wrapping `localStorage` in try/catch (private per browser, never touches the server) — kept pure and free of React so they unit-test without rendering, matching the existing `session-rows.ts` convention. Vitest runs `environment: "node"` (`frontend/vitest.config.ts`) and jsdom/happy-dom is **not** a dependency, so both the helper and its test must go through `globalThis.window` instead of assuming a DOM. |
| `frontend/app/(admin)/admin/students/[studentId]/session-rows.ts` | **Unchanged.** No merge helper is added. Verified: `AdminStudentSessionSummary` carries `enrollment_id`/`session_id` (`lib/api/v2/students.ts:39-59`) and `AdminBillingEnrollmentView` carries its own `enrollment_id` plus `session_type_id` (`lib/api/admin.ts:3378-3389`) — no shared key exists, so a client-side join is not writable and a stub that always returns `null` is dead code. See the OPEN QUESTION in Self-review. |
| `frontend/app/(admin)/admin/students/[studentId]/SessionsPanel.tsx` | **Modify.** One change only: `PastEnrollmentsPanel` — module-private, rendered by `SessionsPanel`, **not** exported — caps its visible rows at 5 with a "Show all N" toggle (spec §3.1 "collapsed after five rows"). Its `Card` wrapper stays. No billing props are added: the current-enrollment table already renders the fee (`amount_cents`), the `discount` and the autopay chip the spec's §3.1 list names. **Cross-plan:** the line numbers quoted in Task 3 (`:763`, `:359`, `:228`) were read on `main` *before* plan 1 (`2026-09-10-departure-actions-from-student-page.md`, Task 9) rewrote this file's `<DepartureActions>` block and added four dialog mounts, a `studentName` prop and four `useState` targets. Plan 1 lands first, so re-locate `PastEnrollmentsPanel` by name, not by line number, and do **not** touch plan 1's `departureActionsFor(session.status)` call or its dialog mounts. |
| `frontend/app/(admin)/admin/students/[studentId]/BillingEnrollmentsPanel.tsx` | **Unchanged.** Rendered as-is beneath `SessionsPanel` inside the Enrollments section. Its Move / Override-price dialogs exist nowhere else, which is why it stays on the page; folding its rows away is blocked by the missing join key (Self-review OPEN QUESTION). |
| `frontend/app/(admin)/admin/students/[studentId]/StudentEditForm.tsx` | **Modify.** `StudentEditForm` drops the `mode` prop and its `StudentEditMode` type; renders all fields (identity, DOB, status, notes, previous experience, medical notes, emergency contact, t-shirt size) in one form, one dirty-check, one submit. `ChangeParentPanel` stays exported unchanged until Task 8 deletes its usage (and the function itself once spec 2 confirms readiness). |
| `frontend/app/(admin)/admin/students/[studentId]/page.tsx` | **Modify.** Remove `StudentTab` type, `STUDENT_TABS`, `StudentTabs`, `TabPanel`, tab state; add the rail/column layout, five `CollapsibleSection`s, hash-scroll effect, compliance auto-open logic. |
| `frontend/app/(admin)/admin/students/[studentId]/section-storage.test.ts` | **Create.** Unit tests for `readSectionOpen`/`writeSectionOpen`. |
| `frontend/e2e/specs/admin-students.spec.ts` | **Modify.** Replace `getByRole("tab", ...)` navigation with section-open assertions; the `admin-student-training-tab`/`admin-student-compliance-tab` testids are replaced by the `CollapsibleSection`-emitted `admin-student-section-training`/`admin-student-section-compliance`; the `admin-student-training-edit-form` testid becomes `admin-student-profile-edit-form` (spec §6). |
| `frontend/e2e/specs/tuition-discounts.spec.ts` | **Modify.** Lines 458 and 497 click `getByRole("tab", { name: "Sessions" })` / `{ name: "Billing" }` on `/admin/students/student-discounts`. Those tabs cease to exist, so this spec breaks with this change and must be rewritten in the same PR (Task 7b). The plan's earlier claim that no other spec touched the student-page tabs was wrong — re-verified 2026-09-10 by grep. |
| `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json` | **Modify.** The `/admin/students/[studentId]` entry (lines 1665-1730) lists workflows "Billing tab" and "Family tab" and acceptance strings naming them; relabel to "Billing section" / "Compliance section" so the manifest still describes the real surface. No route is added or removed, so `backend/v2/tests/unit/test_audit_inventory_manifest.py`'s required-route set is unaffected. |
| `docs/release-notes/2026-09-10-student-page-single-view.md` | **Create.** Release note for the Release Notes Gate (`scripts/dev/release_notes_check.py`: exactly `## What changed`, `## Deploy notes`, `## Risk / rollback`, plus a `PR: #<n>` marker line). |

## Task 1: `section-storage.ts` — persisted open/closed state

**Files:**
- Create: `frontend/app/(admin)/admin/students/[studentId]/section-storage.ts`
- Test: `frontend/app/(admin)/admin/students/[studentId]/section-storage.test.ts`

**Interfaces:**
- Produces: `readSectionOpen(sectionId: string, fallback: boolean): boolean`, `writeSectionOpen(sectionId: string, open: boolean): void`
- Consumes: `globalThis.window?.localStorage`. **Verified constraint:** `frontend/vitest.config.ts` sets `environment: "node"` and `globals: false`, and neither `jsdom` nor `happy-dom` is in `frontend/package.json` — so `window` does NOT exist under vitest. The helper must reach the store through `globalThis.window` (optional-chained, inside try/catch) and the test must install a fake `window` rather than assume one; a `// @vitest-environment jsdom` pragma would fail to resolve the missing dependency.

- [ ] Write failing test in `frontend/app/(admin)/admin/students/[studentId]/section-storage.test.ts`:
  ```ts
  import { afterEach, beforeEach, describe, expect, it } from "vitest";

  import { readSectionOpen, writeSectionOpen } from "./section-storage";

  // vitest runs with environment: "node" (frontend/vitest.config.ts) and no
  // jsdom dependency, so there is no `window`. Install the smallest possible
  // stand-in for the one API the helper uses.
  function installFakeStorage(overrides: Partial<Storage> = {}) {
    const map = new Map<string, string>();
    const storage = {
      getItem: (k: string) => map.get(k) ?? null,
      setItem: (k: string, v: string) => void map.set(k, v),
      removeItem: (k: string) => void map.delete(k),
      clear: () => map.clear(),
      key: () => null,
      get length() {
        return map.size;
      },
      ...overrides,
    } as unknown as Storage;
    (globalThis as { window?: unknown }).window = { localStorage: storage };
    return storage;
  }

  describe("section-storage", () => {
    beforeEach(() => {
      installFakeStorage();
    });

    afterEach(() => {
      delete (globalThis as { window?: unknown }).window;
    });

    it("returns the fallback when nothing is stored", () => {
      expect(readSectionOpen("enrollments", true)).toBe(true);
      expect(readSectionOpen("billing", false)).toBe(false);
    });

    it("round-trips a written value", () => {
      writeSectionOpen("compliance", true);
      expect(readSectionOpen("compliance", false)).toBe(true);
      writeSectionOpen("compliance", false);
      expect(readSectionOpen("compliance", true)).toBe(false);
    });

    it("keys are independent per section id", () => {
      writeSectionOpen("training", true);
      expect(readSectionOpen("profile", false)).toBe(false);
    });

    it("falls back cleanly when localStorage throws", () => {
      installFakeStorage({
        getItem: () => {
          throw new Error("blocked");
        },
      });
      expect(readSectionOpen("enrollments", true)).toBe(true);
    });

    it("falls back cleanly when there is no window at all (SSR pass)", () => {
      delete (globalThis as { window?: unknown }).window;
      expect(readSectionOpen("enrollments", true)).toBe(true);
      expect(() => writeSectionOpen("enrollments", false)).not.toThrow();
    });
  });
  ```
- [ ] Run: `cd frontend && pnpm vitest run app/\(admin\)/admin/students/\[studentId\]/section-storage.test.ts` — expected FAIL (module `./section-storage` does not exist).
- [ ] Implement `frontend/app/(admin)/admin/students/[studentId]/section-storage.ts`:
  ```ts
  /**
   * Per-browser, per-section collapse state for the student page (spec
   * 2026-09-10-student-page-single-view §3, final paragraph). Never sent to
   * the server; wrapped in try/catch because localStorage can throw in a
   * private window or with site data blocked.
   */
  const STORAGE_PREFIX = "admin-student-section:";

  export function readSectionOpen(sectionId: string, fallback: boolean): boolean {
    try {
      const raw = globalThis.window?.localStorage.getItem(
        `${STORAGE_PREFIX}${sectionId}`,
      );
      if (raw === null || raw === undefined) return fallback;
      return raw === "1";
    } catch {
      return fallback;
    }
  }

  export function writeSectionOpen(sectionId: string, open: boolean): void {
    try {
      globalThis.window?.localStorage.setItem(
        `${STORAGE_PREFIX}${sectionId}`,
        open ? "1" : "0",
      );
    } catch {
      // Best-effort only.
    }
  }
  ```
- [ ] Run: `cd frontend && pnpm vitest run app/\(admin\)/admin/students/\[studentId\]/section-storage.test.ts` — expected PASS (5 tests).
- [ ] Commit: `git add frontend/app/\(admin\)/admin/students/\[studentId\]/section-storage.ts frontend/app/\(admin\)/admin/students/\[studentId\]/section-storage.test.ts` then:
  ```
  feat(admin): add persisted collapse state for student page sections

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```

## Task 2: `CollapsibleSection` primitive

**Files:**
- Create: `frontend/app/(admin)/admin/students/[studentId]/CollapsibleSection.tsx`
- Test: none (thin presentational wrapper; covered by the page-level e2e spec in Task 7 and manual visual check in Task 9). Verified via `pnpm typecheck` in this task's run step instead.

**Interfaces:**
- Consumes: `readSectionOpen`/`writeSectionOpen` from `./section-storage`; `Card` from `@/components/ds` (verified: `frontend/components/ds/index.ts` re-exports `Card`, and `Card` accepts `p`, `className` and `data-testid` — `components/ds/card.tsx:5-13`); `ChevronDown` from `lucide-react` (already a project dependency, confirmed via existing `lucide-react` imports in `page.tsx`). `Overline` is NOT used — the header button styles its own label — so do not import it.
- Produces: `CollapsibleSection({ id, title, defaultOpen, forceOpen, children }): JSX.Element`. `id` is the deep-link/testid slug (e.g. `"enrollments"`) and is used verbatim as the DOM anchor id so `#enrollments` resolves. `forceOpen`, when `true`, opens the section and is NOT persisted back to storage (used for the hash and outstanding-compliance auto-open cases so a one-time force doesn't overwrite the admin's own preference).
- **Hydration:** the initial render must use `defaultOpen` only. Reading `localStorage` inside the `useState` initializer makes the server-rendered markup (storage unavailable → fallback) disagree with the client's first render whenever a preference is stored, and React logs a hydration error — which the spec §6 clean-console assertion would fail on. Read storage in an effect instead.

- [ ] Implement `frontend/app/(admin)/admin/students/[studentId]/CollapsibleSection.tsx`:
  ```tsx
  "use client";

  import { type ReactNode, useEffect, useState } from "react";
  import { ChevronDown } from "lucide-react";

  import { Card } from "@/components/ds";

  import { readSectionOpen, writeSectionOpen } from "./section-storage";

  export function CollapsibleSection({
    id,
    title,
    defaultOpen,
    forceOpen,
    children,
  }: {
    id: string;
    title: string;
    defaultOpen: boolean;
    /** One-time override (deep link, outstanding compliance) — opens but is not persisted. */
    forceOpen?: boolean;
    children: ReactNode;
  }) {
    // First render (server AND client) uses defaultOpen only; the stored
    // preference is applied after mount so hydration never mismatches.
    const [open, setOpen] = useState(defaultOpen);

    useEffect(() => {
      setOpen(readSectionOpen(id, defaultOpen));
      // defaultOpen is a constant per call site; re-reading storage on every
      // change would clobber a click.
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [id]);

    useEffect(() => {
      if (forceOpen) setOpen(true);
    }, [forceOpen]);

    return (
      <Card
        p={0}
        className="scroll-mt-4"
        data-testid={`admin-student-section-${id}`}
      >
        {/* Bare id: this is the target of the spec's `#enrollments` deep links
            and of the rail's jump links. Do not prefix it. */}
        <div id={id} className="scroll-mt-4" />
        <button
          type="button"
          className="flex w-full items-center justify-between gap-2 p-5 text-left"
          aria-expanded={open}
          aria-controls={`student-section-${id}-body`}
          onClick={() => {
            const next = !open;
            setOpen(next);
            writeSectionOpen(id, next);
          }}
        >
          <span className="font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
            {title}
          </span>
          <ChevronDown
            className={`size-4 text-rally-muted transition-transform ${open ? "rotate-180" : ""}`}
            aria-hidden="true"
          />
        </button>
        {open && (
          <div id={`student-section-${id}-body`} className="px-5 pb-5">
            {children}
          </div>
        )}
      </Card>
    );
  }
  ```
- [ ] Run: `cd frontend && pnpm typecheck` — expected PASS (new file compiles; not yet imported anywhere so no behavior change).
- [ ] Commit: `git add frontend/app/\(admin\)/admin/students/\[studentId\]/CollapsibleSection.tsx` then:
  ```
  feat(admin): add CollapsibleSection primitive for student page

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```

## Task 3: Past enrollments collapse after five rows

**Files:**
- Modify: `frontend/app/(admin)/admin/students/[studentId]/SessionsPanel.tsx`
- Test: none new — this is a display cap inside a module-private component with no pure-function seam; covered by the Task 7 e2e (`admin-student-past-enrollments-toggle` is absent with 2 past rows in the fixture, so the e2e asserts its absence).

> **Removed from this task (was a defect in the first draft).** The draft added a
> `mergeEnrollmentBilling(sessions, billingEnrollments, sessionTypeById)` helper to
> `session-rows.ts` whose own implementation returned `null` for every merge field, whose
> first unit test asserted those nulls under the title "attaches the matching billing
> enrollment's override", and which no other task ever called. That is dead code plus a
> misleading test. It is deleted from the plan. The reason it could not work is real and
> verified — see the OPEN QUESTION in Self-review — but the honest response is to record the
> gap, not to ship a stub.

- [ ] Locate `PastEnrollmentsPanel` **by name** (`grep -n "function PastEnrollmentsPanel"`), not by the line number this plan was written against — plan 1 (`2026-09-10-departure-actions-from-student-page.md`, Task 9) edits this same file first and shifts every line below its `<DepartureActions>` block.
- [ ] Update `SessionsPanel.tsx`'s `PastEnrollmentsPanel` to cap the visible rows at 5 with a "Show all N" toggle (spec §3.1 "collapsed after five rows"). Edit the function body:
  ```tsx
  function PastEnrollmentsPanel({ rows }: { rows: AdminStudentSessionSummary[] }) {
    const [expanded, setExpanded] = useState(false);
    const visible = expanded ? rows : rows.slice(0, 5);
    // ... existing header/empty-state JSX unchanged, but map over `visible` instead of `rows` ...
    // after the closing </table></div>, before the closing </Card>, add:
    {rows.length > 5 && (
      <button
        type="button"
        className="mt-3 text-xs font-medium text-rally-blue hover:underline"
        onClick={() => setExpanded((v) => !v)}
        data-testid="admin-student-past-enrollments-toggle"
      >
        {expanded ? "Show fewer" : `Show all ${rows.length}`}
      </button>
    )}
  }
  ```
  (`useState` is already imported in this file — `SessionsPanel.tsx:3`.)
- [ ] Run: `cd frontend && pnpm typecheck && pnpm lint` — expected PASS. (Note: the `lint` script is `eslint .`, so it always lints the whole project; passing a path just adds to the target set.)
- [ ] Commit: `git add frontend/app/\(admin\)/admin/students/\[studentId\]/SessionsPanel.tsx` then:
  ```
  feat(admin): cap past enrollments at five rows

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```

## Task 4: `StudentEditForm` — drop `mode`, one combined form

**Files:**
- Modify: `frontend/app/(admin)/admin/students/[studentId]/StudentEditForm.tsx` (593 lines total; `StudentEditForm` spans lines 24-345, `ChangeParentPanel` 347-569 and `Field` 571-591 with the `export { StudentEditForm, ChangeParentPanel, Field };` line at 593 — both untouched by this task)

**Interfaces:**
- Produces (changed signature): `StudentEditForm({ student, onSaved }: { student: AdminStudentDetail; onSaved: () => void }): JSX.Element` — `mode` prop and `StudentEditMode` type removed.
- Consumes: `UpdateAdminStudentRequest` (existing, `lib/api/v2/students.ts:129-142`) already carries every field this form edits — no API change needed.

- [ ] Edit `StudentEditForm.tsx`: remove `type StudentEditMode = "overview" | "training" | "family";` (line 22), the `mode,` entry in the destructure (line 25) and the `mode: StudentEditMode;` field in the props type literal (line 29). Leave `EditableStatus` (line 21) alone.
- [ ] Replace the `dirtyFields`/`dirty` block (lines 95-121) — every field is now always relevant:
  ```ts
  const dirtyFields = {
    fullName: fullName !== student.full_name,
    dateOfBirth: dateOfBirth !== (student.date_of_birth ?? ""),
    status: status !== student.status,
    notes: (notes ?? "") !== (student.notes ?? ""),
    previousExperience: previousExperience !== (student.previous_experience ?? ""),
    medicalNotes: medicalNotes !== (student.medical_notes ?? ""),
    emergencyContactName: emergencyContactName !== (student.emergency_contact_name ?? ""),
    emergencyContactPhone: emergencyContactPhone !== (student.emergency_contact_phone ?? ""),
    tShirtSize: tShirtSize !== (student.t_shirt_size ?? ""),
  };

  const dirty = Object.values(dirtyFields).some(Boolean);
  ```
- [ ] Replace the submit handler's payload assembly (lines 141-168, inside the `<form onSubmit>`) to build the payload unconditionally from every dirty field rather than switching on `mode`:
  ```ts
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
    if (dirtyFields.emergencyContactName) payload.emergency_contact_name = emergencyContactName;
    if (dirtyFields.emergencyContactPhone) payload.emergency_contact_phone = emergencyContactPhone;
    if (dirtyFields.tShirtSize) payload.t_shirt_size = tShirtSize;
    payload.reason = reason;
    mutation.mutate(payload);
  }}
  ```
- [ ] Remove the `mode === "..."` conditionals around the three field groups (lines 170-288) so all three groups (`overview`, `training`, `family`'s t-shirt field) always render, in that order, inside one `<form data-testid="admin-student-profile-edit-form">` (was ``admin-student-${mode}-edit-form``, now one fixed testid — this is the exact string the Task 7 e2e rewrite targets).
- [ ] Run: `cd frontend && pnpm typecheck` — expected FAIL initially (callers in `page.tsx` still pass `mode`); this is expected and resolved together with Task 6, so proceed to the next step in this task first and re-check typecheck after Task 6.
- [ ] Run: `cd frontend && pnpm lint` — expected PASS (eslint does not type-check cross-file caller mismatches).
- [ ] Note for the executor: `pnpm typecheck` stays RED from here until Task 6 lands. Tasks 5 and 6 both say so; do not treat the red as a new failure, and do not "fix" it by re-adding `mode`.
- [ ] Commit: `git add frontend/app/\(admin\)/admin/students/\[studentId\]/StudentEditForm.tsx` then:
  ```
  refactor(admin): collapse StudentEditForm's three modes into one form

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```

## Task 5: Compliance auto-open logic

**Files:**
- Modify: `frontend/app/(admin)/admin/students/[studentId]/page.tsx` (adds a pure helper near the top of the file, used by Task 6's layout)

**Interfaces:**
- Produces: `complianceNeedsAttention(student: AdminStudentDetail): boolean` — spec §2 "Compliance auto-opens only when something is outstanding" / §3.5 "collapsed when clean, open when a waiver or medical answer is outstanding".
- Consumes: `AdminStudentDetail.waiver_status` (`"signed" | "missing" | "unknown"`, `students.ts:106`), `medical_notes` (`string | null`, spec calls this "a medical answer" — the only medical field on the record is `medical_notes`, so "outstanding" is read as "waiver not signed"; there is no separate medical-questionnaire-answered flag on `AdminStudentDetail` today, so this helper only gates on waiver status and documents that limitation inline rather than inventing a field that doesn't exist).

- [ ] Add near the top of `page.tsx`, after the imports:
  ```ts
  /**
   * Spec 2026-09-10-student-page-single-view §3.5: Compliance auto-opens when
   * "a waiver or medical answer is outstanding". `AdminStudentDetail` has no
   * separate medical-questionnaire-completed flag today (only free-text
   * `medical_notes`), so this only gates on waiver status until such a field
   * exists — documented here rather than guessed at.
   *
   * `waiver_status` is optional on the wire (`lib/api/v2/students.ts:106`), so
   * an omitted field is treated as outstanding and opens the section. That is
   * the safe direction: a missing waiver fact should be visible, not hidden.
   */
  function complianceNeedsAttention(student: AdminStudentDetail): boolean {
    return student.waiver_status !== "signed";
  }
  ```

OPEN QUESTION (owner): spec §3.5 says Compliance opens "when a waiver **or medical answer** is
outstanding", but `AdminStudentDetail` exposes no medical-answered flag — only the free-text
`medical_notes` (`lib/api/v2/students.ts:98`), which is blank for most students and cannot
distinguish "not asked" from "nothing to report". Adding one is a backend read-model change,
which spec §5 puts out of scope. Confirm that waiver-only auto-open is acceptable for v1, or
re-scope to add the field.
- [ ] Run: `cd frontend && pnpm typecheck` — expected **FAIL, with exactly one class of error**: `page.tsx`'s three `StudentEditForm` call sites still pass `mode`, which Task 4 removed. Confirm the only errors reported are those `mode` prop errors (`grep`-check the output) and that `complianceNeedsAttention` itself compiles; both are cleared by Task 6. The earlier draft claimed PASS here, which was wrong.
- [ ] Commit: `git add frontend/app/\(admin\)/admin/students/\[studentId\]/page.tsx` then:
  ```
  feat(admin): add compliance auto-open predicate for student page

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```

## Task 6: `page.tsx` — replace tabs with the rail + section layout

**Files:**
- Modify: `frontend/app/(admin)/admin/students/[studentId]/page.tsx` (removes `StudentTab` type at line 45, `STUDENT_TABS` at 47-53, `activeTab` state at 59, tab-gated blocks at 156-283, `StudentTabs`/`TabPanel` functions at 372-427; rewrites the `Header` function at 614-664 to include the rail's family card and section jump links per spec §3)

**Interfaces:**
- Consumes: `CollapsibleSection` (Task 2), `readSectionOpen`/`writeSectionOpen` (Task 1, used indirectly via `CollapsibleSection`), `complianceNeedsAttention` (Task 5), the now-mode-less `StudentEditForm` (Task 4), all existing panel functions/components already in scope (`EngagementPanel`, `TrainingSnapshot`, `SkillPathwayPanel`, `RecentAttendancePanel`, `ComplianceSummary`, `SessionsPanel`, `BillingEnrollmentsPanel`, `FamilyBillingLink`, `ChangeParentPanel` — this task keeps `ChangeParentPanel` mounted; Task 8 removes it).
- Produces: the default-exported `AdminStudentDetailPage` with no tab state; a new `SectionJumpLinks` component for the rail.

- [ ] Remove `type StudentTab`, `STUDENT_TABS`, and `const [activeTab, setActiveTab] = useState<StudentTab>("overview")` (page.tsx lines 45-53, 59).
- [ ] Remove `<StudentTabs activeTab={activeTab} onChange={setActiveTab} />` (line 154) and every `{activeTab === "..." && (<TabPanel id="...">...</TabPanel>)}` block (lines 156-283), and the `StudentTabs`/`TabPanel` function definitions (lines 372-427).
- [ ] **Remove the `<Header ... />` call site at lines 136-139** (`<Header student={student} onStopAllClasses={() => setStopAllClassesOpen(true)} />`). The step further down deletes the `Header` *function*; leaving its invocation behind breaks `pnpm typecheck` and would render the old header above the new rail. Keep the `BackLink` at line 135 and the `stopAllClassesOpen` dialog block at lines 140-152 exactly where they are — `RailCard` only raises the flag, the dialog still lives on the page.
- [ ] Add the hash effect right after the existing query declarations. It must handle both the initial load and later same-page hash changes (the rail's jump links are `<a href="#billing">`, which fire `hashchange` without remounting the page), and it must scroll — `forceOpen` alone only expands:
  ```ts
  const [hashSection, setHashSection] = useState<string | null>(null);
  useEffect(() => {
    const apply = () => {
      const hash = window.location.hash.replace("#", "");
      if (!hash) return;
      setHashSection(hash);
      // The section may still be collapsed on this tick; scroll on the next
      // frame, once CollapsibleSection's forceOpen effect has expanded it.
      requestAnimationFrame(() => {
        document.getElementById(hash)?.scrollIntoView({ block: "start" });
      });
    };
    apply();
    window.addEventListener("hashchange", apply);
    return () => window.removeEventListener("hashchange", apply);
  }, []);
  ```
  (add `useEffect` to the existing `import { type ReactNode, useState } from "react";` line at `page.tsx:10`, making it `import { type ReactNode, useEffect, useState } from "react";`).
  Note: `hashSection` is only ever set, never cleared, so once an admin deep-links to a section it stays force-open for the rest of that page visit. That is intended — clearing it would let the section snap shut under them.
- [ ] Replace the main return's body (everything from `<StudentSummaryStrip .../>` through the removed tab blocks) with:
  ```tsx
  <div className="grid gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
    <div className="space-y-4 lg:sticky lg:top-4 lg:self-start">
      <RailCard student={student} onStopAllClasses={() => setStopAllClassesOpen(true)} />
      <SectionJumpLinks />
    </div>
    <div className="space-y-6 min-w-0">
      <StudentSummaryStrip student={student} />

      <CollapsibleSection id="enrollments" title="Enrollments" defaultOpen forceOpen={hashSection === "enrollments"}>
        {/* `studentName` is REQUIRED — plan 1
            (2026-09-10-departure-actions-from-student-page, Task 9) added it to
            SessionsPanel's props so the Hold/Return/Drop/Delete dialogs and the
            DepartureActions aria-labels name the child. Plan 1 lands before this
            one; dropping the prop here is a typecheck error, and re-adding a
            `studentName={session.session_title}` fallback re-introduces the bug
            plan 1 fixed. The per-row action set stays `departureActionsFor(status)`
            from `@/components/admin/enrollment/departure-actions` — this plan does
            not redefine it. */}
        <SessionsPanel
          sessions={student.enrolled_sessions ?? []}
          pastEnrollments={student.past_enrollments ?? []}
          parentId={student.parent_id}
          studentId={studentId}
          studentName={student.full_name}
          queryClient={queryClient}
        />
        <div className="mt-6">
          <BillingEnrollmentsPanel studentId={studentId} active />
        </div>
      </CollapsibleSection>

      <CollapsibleSection id="training" title="Training & attendance" defaultOpen forceOpen={hashSection === "training"}>
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1.3fr)_minmax(340px,0.9fr)]">
          <div>
            <TrainingSnapshot student={student} />
          </div>
          <div className="space-y-6">
            <SkillPathwayPanel student={student} />
            <RecentAttendancePanel student={student} />
            <EngagementPanel student={student} />
          </div>
        </div>
      </CollapsibleSection>

      {/* Spec §2/§3.3: the summary line is ALWAYS visible; only the detail
          collapses. It therefore sits OUTSIDE the CollapsibleSection. */}
      <div className="space-y-2">
        <p className="text-sm text-rally-ink" data-testid="admin-student-billing-summary">
          {billingSummaryLine(student)}
        </p>
        <CollapsibleSection id="billing" title="Billing" defaultOpen={false} forceOpen={hashSection === "billing"}>
          <FamilyBillingLink parentId={student.parent_id} parentName={student.parent_name} />
        </CollapsibleSection>
      </div>

      <CollapsibleSection id="profile" title="Profile" defaultOpen={false} forceOpen={hashSection === "profile"}>
        <StudentEditForm
          student={student}
          onSaved={() => {
            void queryClient.invalidateQueries({ queryKey: queryKeys.admin.studentDetail(studentId) });
            void queryClient.invalidateQueries({ queryKey: ["admin", "students"] });
          }}
        />
      </CollapsibleSection>

      <CollapsibleSection
        id="compliance"
        title="Compliance"
        defaultOpen={false}
        forceOpen={hashSection === "compliance" || complianceNeedsAttention(student)}
      >
        <ComplianceSummary student={student} />
        <div className="mt-6">
          <ChangeParentPanel
            student={student}
            parents={parentsQuery.data?.users ?? []}
            parentsLoading={parentsQuery.isLoading}
            parentsError={parentsQuery.isError}
            onSaved={() => {
              void queryClient.invalidateQueries({ queryKey: queryKeys.admin.studentDetail(studentId) });
              void queryClient.invalidateQueries({ queryKey: ["admin", "students"] });
              void queryClient.invalidateQueries({ queryKey: queryKeys.admin.users("parent") });
            }}
          />
        </div>
      </CollapsibleSection>
    </div>
  </div>
  ```
  Notes on this block:
  - The spec's §3 billing summary line ("$340/mo across 2 classes · nothing overdue · autopay
    on") is a new computed string, not produced by any existing panel. Add `billingSummaryLine`
    next to `complianceNeedsAttention` in `page.tsx`. Every field it reads is verified to exist:
    `AdminStudentSessionSummary.amount_cents` and `.autopay_status` (`lib/api/v2/students.ts:48,52`,
    both optional/nullable — hence the `?? 0` and the `=== "active"` test), `payment_history`
    and `balance_due_cents` (`students.ts:110, 68`), and `OPEN_BILLING_STATUSES` + `formatCurrencyCents`
    are already imported by `page.tsx` (lines 40, 42).
  - `CollapsibleSection` is itself a `Card`, and several children (`FamilyBillingLink`,
    `SkillPathwayPanel`, `RecentAttendancePanel`, `EngagementPanel`, `SessionsPanel`'s tables)
    are also `Card`s, so sections render a card inside a card. That is a visual nit, not a bug;
    resolve it in the Task 9 visual pass if it reads badly, by giving those inner panels a
    borderless variant rather than by restructuring the sections.
  ```ts
  function billingSummaryLine(student: AdminStudentDetail): string {
    const activeCount = (student.enrolled_sessions ?? []).filter((s) => s.status === "active").length;
    const monthlyCents = (student.enrolled_sessions ?? [])
      .filter((s) => s.status === "active")
      .reduce((sum, s) => sum + (s.amount_cents ?? 0), 0);
    const overdue = student.payment_history.some(
      (p) => OPEN_BILLING_STATUSES.has(p.status) && p.balance_due_cents > 0,
    );
    const anyAutopay = (student.enrolled_sessions ?? []).some((s) => s.autopay_status === "active");
    return `${formatCurrencyCents(monthlyCents)}/mo across ${activeCount} ${activeCount === 1 ? "class" : "classes"} · ${overdue ? "payment overdue" : "nothing overdue"} · autopay ${anyAutopay ? "on" : "off"}`;
  }
  ```
- [ ] Replace the `Header` function (lines 614-664) with `RailCard`, matching spec §3's rail contents (avatar, name, status chip, level, DOB/age, Stop all classes, family card, section jump links — jump links extracted to `SectionJumpLinks` below). Every field used is verified present: `level`, `date_of_birth`, `parent_phone` on `AdminStudentDetail` (`lib/api/v2/students.ts:91-99`) and `parent_id`/`parent_name`/`parent_email`/`full_name`/`status` on the inherited `AdminStudentView` (`lib/api/admin.ts:1283-1289`). The interpolated `Link href` needs no cast even under `typedRoutes: true` (`next.config.ts:56`) because `/admin/families/[parentId]` is a real route — `FamilyBillingLink.tsx:27` already does exactly this.

OPEN QUESTION (owner): spec §3's rail lists a **login badge** in the family card ("parent name,
email, phone, login badge"). Neither `AdminStudentDetail` nor its base `AdminStudentView`
carries any parent-login/invite-status field, and the parent list this page already fetches
(`listAdminUsers("parent")` → `AdminUserView`) is slated for removal in Task 8. Options: (a) drop
the badge for v1, (b) derive it from `AdminUserView.status` and keep `parentsQuery` alive past
Task 8, or (c) add the field to the student read model — which spec §5 puts out of scope. The
`RailCard` below implements (a); confirm before building.
  ```tsx
  function RailCard({
    student,
    onStopAllClasses,
  }: {
    student: AdminStudentDetail;
    onStopAllClasses: () => void;
  }) {
    const age = student.date_of_birth
      ? Math.floor(
          (Date.now() - new Date(student.date_of_birth).getTime()) / (365.25 * 24 * 60 * 60 * 1000),
        )
      : null;
    return (
      <Card p={20}>
        <div className="flex items-center gap-3">
          <Avatar name={student.full_name} size={56} />
          <div className="min-w-0">
            <h2 className="font-display text-lg font-semibold tracking-[-0.01em] text-rally-ink truncate">
              {student.full_name}
            </h2>
            <div className="mt-1 flex items-center gap-2">
              <StatusChip status={student.status} />
            </div>
          </div>
        </div>
        <dl className="mt-4 space-y-1.5 text-sm">
          {student.level && (
            <div className="flex justify-between">
              <dt className="text-rally-muted">Level</dt>
              <dd className="text-rally-ink">{student.level}</dd>
            </div>
          )}
          <div className="flex justify-between">
            <dt className="text-rally-muted">DOB</dt>
            <dd className="text-rally-ink">
              {student.date_of_birth ? `${formatDate(student.date_of_birth)}${age !== null ? ` (${age})` : ""}` : "—"}
            </dd>
          </div>
        </dl>
        <div className="mt-4">
          <Button size="sm" variant="ghost" onClick={onStopAllClasses} full>
            Stop all classes
          </Button>
        </div>
        <div className="mt-4 rounded-lg border border-neutral-200 p-3 text-sm" data-testid="admin-student-family-card">
          <div className="font-medium text-rally-ink">
            {student.parent_name ?? student.parent_email ?? "Parent on file"}
          </div>
          {student.parent_email && (
            <a href={`mailto:${student.parent_email}`} className="block text-rally-muted hover:underline">
              {student.parent_email}
            </a>
          )}
          {student.parent_phone && (
            <a href={`tel:${student.parent_phone}`} className="block text-rally-muted hover:underline">
              {student.parent_phone}
            </a>
          )}
          {student.parent_id && (
            <Link
              href={`/admin/families/${encodeURIComponent(student.parent_id)}`}
              className="mt-2 inline-block text-xs font-medium text-rally-blue hover:underline"
            >
              Open family
            </Link>
          )}
        </div>
      </Card>
    );
  }

  const SECTION_LINKS = [
    { id: "enrollments", label: "Enrollments" },
    { id: "training", label: "Training & attendance" },
    { id: "billing", label: "Billing" },
    { id: "profile", label: "Profile" },
    { id: "compliance", label: "Compliance" },
  ] as const;

  function SectionJumpLinks() {
    return (
      <Card p={16}>
        <nav className="space-y-1 text-sm" aria-label="Jump to section">
          {SECTION_LINKS.map((link) => (
            <a
              key={link.id}
              href={`#${link.id}`}
              className="block rounded px-2 py-1 text-rally-muted hover:bg-rally-ink/5 hover:text-rally-ink"
            >
              {link.label}
            </a>
          ))}
        </nav>
      </Card>
    );
  }
  ```
- [ ] Remove the now-unused `UserRound`/`ShieldCheck`/`FileCheck` icon imports if no longer referenced (`FileCheck` is still used by `StudentSummaryStrip`, keep it; `UserRound` and `ShieldCheck` were only used by the removed tab-panel `Overline` rows — remove them from the `lucide-react` import list if `pnpm lint` flags them unused).
- [ ] Run: `cd frontend && pnpm typecheck` — expected PASS (this resolves the Task 4 `mode`-prop mismatch since the only caller no longer passes `mode`).
- [ ] Run: `cd frontend && pnpm lint app/\(admin\)/admin/students/\[studentId\]/page.tsx` — expected PASS.
- [ ] Run: `cd frontend && pnpm vitest run app/\(admin\)/admin/students/\[studentId\]/` — expected PASS (all existing + new unit tests in this directory).
- [ ] Commit: `git add frontend/app/\(admin\)/admin/students/\[studentId\]/page.tsx` then:
  ```
  feat(admin): replace student page tabs with a single scrolling view

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```

## Task 7: e2e — rewrite `admin-students.spec.ts` for sections

**Files:**
- Modify: `frontend/e2e/specs/admin-students.spec.ts` (the "renders the student profile..." test, lines 232-486; the three list/search/empty/error tests at lines 77-230 are untouched — they never touch the detail page)

**Interfaces:**
- Consumes: the rewritten `page.tsx`/`SessionsPanel.tsx`/`StudentEditForm.tsx` from Tasks 1-6; existing `data-testid`s that survive unchanged (`admin-student-detail`, `admin-student-summary-strip`, `admin-student-enrolled-sessions`, `admin-student-autopay-*`, `admin-student-past-enrollment-*`, `admin-student-family-billing-link`); new ones from this plan (`admin-student-section-enrollments`, `admin-student-section-training`, `admin-student-section-billing`, `admin-student-section-profile`, `admin-student-section-compliance`, `admin-student-profile-edit-form`, `admin-student-family-card`).

- [ ] Edit the test body starting at `await page.goto("/admin/students/student-1");` (line 409): after the existing summary-strip assertions, replace every `getByRole("tab", ...)` click + tab-content assertion with section-based equivalents. Concretely, replace lines 414-485 with:
  ```ts
  await page.waitForLoadState("networkidle");
  await expect(page.getByTestId("admin-student-detail")).toContainText("Amit Rao");
  await expect(page.getByTestId("admin-student-summary-strip")).toContainText("$110");
  await expect(page.getByTestId("admin-student-summary-strip")).toContainText("91%");

  // Enrollments — open by default, no click required.
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

  // Training & attendance — open by default. NOTE: `previous_experience`
  // ("Two years of club play") is a StudentEditForm field, so it now lives in
  // the Profile section, NOT here — asserting it against the Training section
  // would fail. The Training section holds TrainingSnapshot, SkillPathwayPanel,
  // RecentAttendancePanel and EngagementPanel only.
  const trainingSection = page.getByTestId("admin-student-section-training");
  await expect(trainingSection).toContainText("Skill pathway");
  await expect(page.getByTestId("admin-student-recent-attendance")).toContainText("PRESENT");

  // Billing summary line is outside the collapsible, so it is visible with the
  // section still shut (spec §2 "always visible").
  await expect(page.getByTestId("admin-student-billing-summary")).toContainText("autopay");

  // Billing — collapsed by default; open it.
  await page.getByTestId("admin-student-section-billing").getByRole("button", { name: /billing/i }).click();
  await expect(page.getByTestId("admin-student-family-billing-link")).toContainText("Open family billing");
  await expect(
    page.getByTestId("admin-student-family-billing-link").getByRole("link"),
  ).toHaveAttribute("href", /\/admin\/families\//);

  // Profile — collapsed by default; open it, edit, save.
  await page.getByTestId("admin-student-section-profile").getByRole("button", { name: /profile/i }).click();
  const profileForm = page.getByTestId("admin-student-profile-edit-form");
  await expect(profileForm.getByLabel("Previous experience")).toHaveValue("Two years of club play");
  await expect(profileForm.getByLabel("Previous experience")).toHaveAttribute("maxlength", "1000");
  await expect(profileForm.getByLabel("Medical notes")).toHaveValue("Peanut allergy");
  await expect(profileForm.getByLabel("Medical notes")).toHaveAttribute("maxlength", "1000");
  await expect(profileForm.getByLabel("Emergency contact name")).toHaveValue("Anita Chen");
  await expect(profileForm.getByLabel("Emergency contact phone")).toHaveValue("555-0199");
  await expect(profileForm.getByLabel("T-shirt size")).toHaveValue("M");
  await expect(profileForm.getByLabel("T-shirt size")).toHaveAttribute("maxlength", "20");
  const medicalNotes = profileForm.getByLabel("Medical notes");
  await medicalNotes.focus();
  await page.keyboard.press(process.platform === "darwin" ? "Meta+A" : "Control+A");
  await page.keyboard.press("Backspace");
  await expect(medicalNotes).toHaveValue("");
  await profileForm.getByRole("button", { name: /^save changes$/i }).click();
  expect(patchBody).toMatchObject({
    medical_notes: "",
    reason: "Admin profile update",
  });

  // Compliance — this fixture's waiver_status is "signed", so nothing is
  // outstanding and the section stays collapsed. Open it explicitly.
  await page.getByTestId("admin-student-section-compliance").getByRole("button", { name: /compliance/i }).click();
  await expect(page.getByTestId("admin-student-section-compliance")).toContainText("2026-v1");
  expect(errors, `App console errors: ${errors.join("\n")}`).toEqual([]);
  ```
  Note: with `waiver_status: "signed"` (spec fixture line 258), `complianceNeedsAttention`
  returns `false`, so Compliance stays collapsed and must be clicked open — the mirror image of
  spec §2's "Compliance auto-opens only when something is outstanding". (The earlier draft's
  comment said it "auto-opens because ... signed, so it stays collapsed", which is
  self-contradictory.)
- [ ] Add a second detail-page test that pins the auto-open branch, since the existing fixture
  can only exercise the collapsed one: copy the setup, override `waiver_status: "missing"` in the
  student fixture, `goto`, and assert `page.getByTestId("admin-student-section-compliance")`
  contains "MISSING" **without** any click. Without this, spec §2's auto-open rule has no test.
- [ ] Add a deep-link test: `await page.goto("/admin/students/student-1#profile")`, then assert
  `page.getByTestId("admin-student-profile-edit-form")` is visible with no click — this is the
  only coverage of the anchor-id / `forceOpen` wiring that the first draft got wrong.
- [ ] Since every section now mounts on load (spec §6, "the billing route mocks that only the
  Billing tab installed become part of the page-level setup since every section now mounts"),
  no route-mock relocation is actually required — `stubMe`/`stubAdminAcademy`/the
  `billing-enrollments`/`session-types`/`departure-policy`/`programs` route stubs already sit
  before `page.goto` in this test (lines 353-407), so they already cover eager mounting. Confirm
  this by reading the diff after the edit above — no route-mock lines need to move.
- [ ] Run: `cd frontend && pnpm exec playwright test admin-students.spec.ts --project=chromium` — expected PASS (4 tests: search/filter, empty state, error state, detail page).
- [ ] Commit: `git add frontend/e2e/specs/admin-students.spec.ts` then:
  ```
  test(e2e): rewrite admin-students spec for the single-view student page

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```

## Task 7b: e2e — `tuition-discounts.spec.ts` also drives the student-page tabs

**Files:**
- Modify: `frontend/e2e/specs/tuition-discounts.spec.ts`

**Why this task exists:** the first draft of this plan asserted (in Task 9) that no other spec
referenced the student-page tabs. That was wrong. Verified against the worktree on 2026-09-10:

```
frontend/e2e/specs/tuition-discounts.spec.ts:457:    await page.goto("/admin/students/student-discounts");
frontend/e2e/specs/tuition-discounts.spec.ts:458:    await page.getByRole("tab", { name: "Sessions" }).click();
frontend/e2e/specs/tuition-discounts.spec.ts:497:    await page.getByRole("tab", { name: "Billing" }).click();
```

Both clicks target tabs this change deletes, so this spec goes red in the same PR. It must be
fixed here, not "re-checked" later.

**Interfaces:**
- Consumes: the same section testids as Task 7 (`admin-student-section-enrollments`, `admin-student-section-billing`).

- [ ] Read the two tests around lines 450-510 to see what each tab click was setting up for.
- [ ] Delete line 458's `getByRole("tab", { name: "Sessions" }).click()` outright — the Enrollments
  section (which contains the former Sessions table) is open by default, so no navigation is
  needed. Keep every assertion that followed it.
- [ ] Replace line 497's `getByRole("tab", { name: "Billing" }).click()` with the section-open click:
  ```ts
  await page.getByTestId("admin-student-section-billing").getByRole("button", { name: /billing/i }).click();
  ```
  If the assertions after that line target `BillingEnrollmentsPanel` (session-type rows, price
  override) rather than `FamilyBillingLink`, that panel now lives in the **Enrollments** section,
  which is already open — in that case drop the click entirely instead of retargeting it. Decide
  by reading the assertions, not by guessing.
- [ ] Run: `cd frontend && pnpm exec playwright test tuition-discounts.spec.ts --project=chromium` — expected PASS.
- [ ] Commit: `git add frontend/e2e/specs/tuition-discounts.spec.ts` then:
  ```
  test(e2e): retarget tuition-discounts spec at the student page sections

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```

## Task 8: Gated removal — `ChangeParentPanel`

**Files:**
- Modify: `frontend/app/(admin)/admin/students/[studentId]/page.tsx`, `frontend/app/(admin)/admin/students/[studentId]/StudentEditForm.tsx`
- Test: `frontend/e2e/specs/admin-students.spec.ts` (remove any `ChangeParentPanel` assertions — there are none in the current spec, verified: `grep -n "ChangeParentPanel\|change-parent\|Change parent" frontend/e2e/specs/admin-students.spec.ts` returns nothing)

**Interfaces:**
- Consumes: the family page's **"Move child to another family"** action from spec `2026-09-10-families-directory-consolidation-design.md` §6 — this task is a **hard gate**, not a default action.

> **Cross-plan status (checked 2026-09-10 — read this before running the grep):**
> the implementation plan for spec 2,
> `docs/superpowers/plans/2026-09-10-families-directory-consolidation.md`, has
> **no task that builds "Move child to another family"**. Its Self-review lists
> §6 "What this unblocks — Spec 4's `ChangeParentPanel` move" as *explicitly out
> of scope*, and its 13 tasks cover the list columns/filter, the header identity
> strip, password-reset, edit-contact, the redirects, the Users-directory pill
> and the manifest — nothing else. So under the agreed build order
> (1 → 2 → 4 → 3) the gate below is **expected to fail**, and the default,
> correct outcome of Task 8 is *skipped*. Do not treat that as a blocker on this
> plan, and do not "unblock" it by building the family-page picker here — that
> is a separate slice on the family page. Run the grep anyway (a later PR may
> have shipped it) and record the result.

- [ ] **STOP — verify the gate before touching any file in this task.** Run:
  ```
  grep -rn "Move child to another family\|move-child\|move_child" frontend/app/\(admin\)/admin/families/
  ```
  - If this returns a match: the family page has shipped the picker. Proceed with the steps below.
  - If this returns nothing (**the expected outcome** — see the cross-plan status note above; `2026-09-10-families-directory-consolidation.md` does not build it): the family page has not shipped the parent-picker replacement yet. **Do not delete `ChangeParentPanel` or the parent fields.** Stop this task here, leave `page.tsx` and `StudentEditForm.tsx` exactly as Task 6 left them (with `ChangeParentPanel` still mounted inside the Compliance section), and record in this plan's final commit message / PR description that Task 8 was skipped pending the family-page dependency. This is not a failure of the plan — it is the sequencing rule from spec §4.
- [ ] (Only if the gate passed) Remove the `ChangeParentPanel` import and its usage block from `page.tsx`'s Compliance section (the `<div className="mt-6"><ChangeParentPanel ... /></div>` block added in Task 6), and remove the now-unused `parentsQuery` if nothing else in `page.tsx` reads `parentsQuery.data`/`isLoading`/`isError` (re-check: `parentsQuery` was only ever consumed by `ChangeParentPanel`'s props in this file — confirm with `grep -n "parentsQuery" frontend/app/\(admin\)/admin/students/\[studentId\]/page.tsx` after the removal and delete the query declaration and its `listAdminUsers` import if the grep comes back empty).
- [ ] (Only if the gate passed) Delete the `ChangeParentPanel` function from `StudentEditForm.tsx` (lines 347-569 in the pre-Task-4 numbering) and remove it from the file's final `export { StudentEditForm, ChangeParentPanel, Field };` line (line 593). Run `grep -rn "ChangeParentPanel" frontend/` to find every remaining reference before deleting — as of 2026-09-10 the only importer is `page.tsx:43`; `BillingEnrollmentsPanel.tsx` does **not** import it.
- [ ] Note on scope: spec §4 also lists "parent contact fields in `StudentEditForm mode=\"family\"`" as leaving this page. Verified: `mode="family"` renders exactly one field, T-shirt size (`StudentEditForm.tsx:283-294`) — there are no parent contact fields in this form, and the t-shirt field is a student attribute that stays on the Profile section per spec §3.4. Nothing to delete here; do not remove the t-shirt field.
- [ ] (Only if the gate passed) Run: `cd frontend && pnpm typecheck && pnpm lint app/\(admin\)/admin/students/\[studentId\]/ && pnpm exec playwright test admin-students.spec.ts --project=chromium` — expected PASS.
- [ ] (Only if the gate passed) Commit: `git add frontend/app/\(admin\)/admin/students/\[studentId\]/page.tsx frontend/app/\(admin\)/admin/students/\[studentId\]/StudentEditForm.tsx` then:
  ```
  refactor(admin): remove ChangeParentPanel from the student page

  Parent reassignment now lives on the family page's "Move child to
  another family" (spec 2026-09-10-families-directory-consolidation).

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```

## Task 9: Cross-spec e2e re-check and clean-console verification

**Files:**
- None modified unless the greps below surface a hit (this task is verification, matching spec §6's "re-checked for tab assumptions").

**Interfaces:** none — this task runs existing tooling.

- [ ] Run: `cd frontend && grep -rn "getByRole(\"tab\"\|admin-student-training-tab\|admin-student-compliance-tab\|admin-student-training-edit-form\|admin-student-family-edit-form\|admin-student-overview-edit-form" e2e/specs/` — expected: **no output**, because Task 7 fixed `admin-students.spec.ts` and Task 7b fixed `tuition-discounts.spec.ts`. Verified on 2026-09-10 that `admin-family-billing.spec.ts` and `admin-enrollment-withdraw.spec.ts` contain none of these, but the grep is repo-wide here on purpose: the first draft of this plan scoped it to three named files and still got the answer wrong. Any hit is a spec that must be rewritten the way Task 7 did before proceeding.
- [ ] Update `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json`: in the
  `/admin/students/[studentId]` entry (lines 1665-1730), rename the workflows `"Billing tab"` →
  `"Billing section"` and `"Family tab"` → `"Compliance section"`, and update the two matching
  `Workflow evidence: "..."` acceptance strings so the manifest still names surfaces that exist.
  The route itself is unchanged, so `backend/v2/tests/unit/test_audit_inventory_manifest.py`'s
  required-route set is unaffected — but run it to confirm:
  `cd backend && python -m pytest v2/tests/unit/test_audit_inventory_manifest.py v2/tests/unit/test_inventory_acceptance_coverage.py -q` — expected PASS.
- [ ] Run the full frontend unit suite for this directory once more end-to-end: `cd frontend && pnpm vitest run app/\(admin\)/admin/students/\[studentId\]/` — expected PASS.
- [ ] Run: `cd frontend && pnpm typecheck && pnpm lint` — expected PASS (whole-project check, catching any straggler import of `StudentTab`/`STUDENT_TABS` elsewhere: `grep -rn "StudentTab\b" frontend/app frontend/components` should also return nothing by this point).
- [ ] Run: `cd frontend && pnpm exec playwright test admin-students.spec.ts admin-family-billing.spec.ts admin-enrollment-withdraw.spec.ts tuition-discounts.spec.ts --project=chromium` — expected PASS, and confirm via the test output that no test in these four specs reports an unstubbed 4xx/5xx console error or a React hydration warning (spec §6, "Clean-console spec"; hydration is the specific risk from `CollapsibleSection` reading `localStorage`, which Task 2 defuses by reading it in an effect).
- [ ] Manual visual check (spec §6, "Visual check on phone and desktop for the rail/stack breakpoint"): start the dev server and load `/admin/students/[any real or seeded studentId]` at a desktop width (rail beside column) and a mobile width (rail becomes the top card, sections stack) — record the result in the task's completion note; no code change expected from this step unless a breakpoint bug is found, in which case fix `page.tsx`'s `lg:grid-cols-[280px_minmax(0,1fr)]` / `lg:sticky` classes and re-run this task's automated checks.
- [ ] Commit the manifest edit (always) plus any breakpoint fix: `git add docs/qa/2026-06-28-production-scale-local-inventory-manifest.json frontend/app/\(admin\)/admin/students/\[studentId\]/page.tsx` then:
  ```
  docs(qa): relabel student-page tab workflows as sections

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```
  Amend the subject to `fix(admin): correct student page rail breakpoint` if a breakpoint fix was
  also needed. The manifest edit always ships, so this commit is never skipped.

## Task 10: Release note

**Files:**
- Create: `docs/release-notes/2026-09-10-student-page-single-view.md`

**Interfaces:** none — this is documentation required by the CI "Release Notes Gate"
(`.github/workflows/release-notes.yml` → `scripts/dev/release_notes_check.py`). Verified facts:
`REQUIRED_SECTIONS = ["## What changed", "## Deploy notes", "## Risk / rollback"]` (line 26) —
exact strings, exact order in every existing note; the gate finds the note by searching for the
literal marker `PR: #<number>` (line 68); and `validate_note` rejects any section whose body is
empty, starts with `<`, or contains a placeholder marker (lines 89-104). So the literal
`PR: #<number>` placeholder below **fails the gate** until it is replaced with the real number.

- [ ] Create `docs/release-notes/2026-09-10-student-page-single-view.md`:
  ```md
  # Student page single view

  ## What changed

  The admin student detail page (`/admin/students/[studentId]`) no longer uses five tabs
  (Overview, Training, Sessions, Billing, Family & Compliance). It is now one scrolling
  page with a sticky summary rail (avatar, status, level, DOB, Stop all classes, a compact
  family card linking to the family page) and five collapsible sections: Enrollments,
  Training & attendance, Billing, Profile, and Compliance. Section open/closed state is
  remembered per browser, and deep links (`#enrollments`, `#training`, `#billing`,
  `#profile`, `#compliance`) open and scroll to the right section. `StudentEditForm` no
  longer takes a `mode` prop — it is one combined form. `ChangeParentPanel` either stays on
  this page (if the family page's "Move child to another family" has not shipped yet) or
  has moved there (if it has) — see this PR's diff for which applies.

  ## Deploy notes

  Frontend-only change. No backend endpoint, schema, or migration involved. No feature
  flag; ships to every admin on merge. No special deploy sequencing beyond the normal
  frontend build/deploy.

  ## Risk / rollback

  Low risk: no data model or API change, so a revert of this PR is a clean rollback with no
  backward-compatibility concerns. The main runtime risk is a missed route-mock in e2e
  causing flaky CI on the now-eagerly-mounted panels (mitigated in Task 7/9 of the
  implementation plan) and the `localStorage` section-state key colliding with nothing else
  (namespaced under `admin-student-section:`, verified not already in use via
  `grep -rn "admin-student-section:" frontend/`).

  PR: #<number>
  ```
- [ ] Commit: `git add docs/release-notes/2026-09-10-student-page-single-view.md` then:
  ```
  docs(release-notes): add release note for student page single view

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```
  Once the PR exists, replace `PR: #<number>` with the real number and land it as a **new
  follow-up commit** (`docs(release-notes): record PR number`). Do **not** `git commit --amend`
  or rebase: this repo's pre-commit/pre-push hooks block `--amend` and `rebase` even on unpushed
  commits (cherry-pick is the documented workaround). The gate re-runs on every `synchronize`
  event, so a follow-up commit is enough to turn it green.

## Open questions roll-up

Three spec requirements are not fully answerable from the spec plus the code as it stands.
Each is marked `OPEN QUESTION (owner):` at the task where it bites. Get answers before the
task that needs them, not after.

1. **Task 5** — §3.5's "or medical answer is outstanding" has no backing field on
   `AdminStudentDetail`; the plan gates auto-open on waiver status only.
2. **Task 6** — §3's rail "login badge" has no backing field on `AdminStudentDetail` /
   `AdminStudentView`; the plan omits the badge.
3. **Self-review** — §3.1's "One table, not two" cannot be built client-side (no shared key
   between the two read models) without the backend work §5 forbids.

## Self-review

| Spec section | Covered by |
|---|---|
| §1 Purpose (fewer clicks, single page) | Task 6 (layout), Task 2 (CollapsibleSection) |
| §2 Tabs removed → one scrolling page + rail | Task 6 |
| §2 Parent data off this page / ChangeParentPanel moves | Task 8 (gated) |
| §2 Sections open by default (Header, Enrollments, Training) | Task 6 (`defaultOpen` props) |
| §2 Billing summary always visible, detail collapsed | Task 6 (`billingSummaryLine` + collapsed section) |
| §2 Compliance auto-opens when outstanding | Task 5, Task 6 (`complianceNeedsAttention`) |
| §2 No aggregate endpoint; panels keep own queries | Task 6 (each panel's existing `useQuery` untouched) |
| §3 Rail contents (avatar, name, status, level, DOB/age, Stop all classes, family card, jump links) | Task 6 (`RailCard`, `SectionJumpLinks`) — **login badge NOT covered**, see OPEN QUESTION in Task 6 |
| §3.1 Enrollments: past collapsed after 5 | Task 3 |
| §3.1 Enrollments: "one table, not two" | **NOT covered** — see OPEN QUESTION below |
| §3.2 Training & attendance panels | Task 6 (mounts `SkillPathwayPanel`, `TrainingSnapshot`, `RecentAttendancePanel`, `EngagementPanel`) |
| §3.3 Billing summary line + link, detail collapsed | Task 6 |
| §3.4 Profile: one `StudentEditForm`, `mode` gone | Task 4 |
| §3.5 Compliance: `ComplianceSummary`, collapsed/auto-open | Task 5, Task 6 |
| §3 Section state in `localStorage`, deep links `#section` | Task 1, Task 2, Task 6 |
| §4 What leaves: ChangeParentPanel + sequencing gate | Task 8 (there are no parent *fields* in `StudentEditForm` — only t-shirt size, which stays; see Task 8's scope note) |
| §5 Out of scope (backend, coach/parent views, panel-internals redesign) | Not built — no task touches these, by design |
| §6 e2e tab rewrite, testid renames | Task 7 (`admin-students.spec.ts`), Task 7b (`tuition-discounts.spec.ts`) |
| §6 Billing route mocks already page-level | Task 7 (verified, no change needed) |
| §6 Re-check other specs for tab assumptions | Task 7b (`tuition-discounts.spec.ts` IS affected) + Task 9 (repo-wide grep) |
| §6 Clean-console spec | Task 9 |
| §6 Visual check phone/desktop | Task 9 |

**Deliberately deferred / not fully resolved, with reason:**

OPEN QUESTION (owner): **spec §3.1 "One table, not two" is not buildable inside spec §5's
scope.** Verified against the code, not assumed:

- `AdminStudentSessionSummary` (`frontend/lib/api/v2/students.ts:39-59`) keys on `enrollment_id`
  and `session_id`.
- `AdminBillingEnrollmentView` (`frontend/lib/api/admin.ts:3378-3389`) keys on its own
  `enrollment_id` plus `session_type_id`, `student_id`, `parent_id`.
- There is no `session_type_id` on the session summary and no `session_id` on the billing
  enrollment, so the two lists cannot be joined on the client at all.

Also verified: the facts §3.1 names as the merge payload — "fee, discount, autopay chip" — are
**already on `SessionsPanel`'s rows today** (`amount_cents`, `discount`, `autopay_status`;
`SessionsPanel.tsx:228`, asserted by the existing e2e at `admin-students.spec.ts:451-458`). What
`BillingEnrollmentsPanel` uniquely adds is the session-type price override and the move dialog.

So the plan renders `SessionsPanel`'s table with `BillingEnrollmentsPanel` beneath it in one
Enrollments section. Owner to pick: (a) accept two tables in one section for v1, (b) drop
`BillingEnrollmentsPanel`'s table and keep only its dialogs, or (c) fund the read-model change
that exposes a shared key — (c) contradicts spec §5 ("Any backend change, aggregate endpoint or
read-model work" is out of scope). The first draft of this plan shipped a `mergeEnrollmentBilling`
stub that always returned nulls; that has been removed rather than left as dead code pretending
the requirement was met.
- **§4 sequencing gate (ChangeParentPanel removal)** — Task 8 is conditional by design, not a
  simplification. If spec `2026-09-10-families-directory-consolidation-design.md` has not
  shipped "Move child to another family" by the time this plan executes, Task 8's steps are
  skipped and `ChangeParentPanel` stays on the student page exactly where Task 6 put it
  (inside Compliance) — this is the spec's own required sequencing, not a plan gap.
