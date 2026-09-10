# Departure Actions From Student Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an admin Hold, Return, Drop or Delete a child's enrollment from the student page's Sessions tab — the same `DepartureActions` vocabulary and dialogs the class roster uses — instead of forcing every departure through the roster, and notify the family by email when the admin opts in.

**Architecture:** One shared pure helper (`departureActionsFor`) decides which departure actions a row offers per status; one shared set of dialog components (moved out of the roster's `dialogs.tsx` into `components/admin/enrollment/`) is mounted by both the roster page and the student Sessions panel. On the backend, `HoldEnrollment`/`ReturnFromHold`/`WithdrawEnrollment` each gain an optional `notify_family` flag on their request DTO and an optional best-effort notifier collaborator, wired through a claim-based send (the `digest_claim` pattern already proven by `hold_notifications.py` and `absence_notifications.py`) so a mail failure never fails the write and a retried request never double-sends.

**Tech Stack:** Next.js 16 (webpack build) + TanStack Query + Tailwind on the frontend; FastAPI + Motor(Mongo) DDD contexts on the backend; vitest (frontend unit), pytest (backend), Playwright (e2e).

## Global Constraints

- Vocabulary: Transfer, Hold, Return, Drop, Delete — never "Cancel", never "Pause"/"Resume" (those are removed from `DepartureAction`).
- `departureActionsFor(status)`: `active → [transfer, hold, drop, delete]`; `held → [return, transfer, drop, delete]`; `paused → [return, transfer, drop, delete]` (Return calls `/return` even for legacy paused rows — an accepted, spec-directed rough edge, see Self-review); `reclaim_pending → [transfer, drop, delete]`; every other status → `[delete]`.
- **Owner decision 2026-09-10 — reclaim in flight:** a `reclaim_pending` row offers Transfer and Drop but never Return. `ReturnFromHold`'s CAS is `mark_active_if_held`, which rejects `reclaim_pending`, so a Return button there would always error. Do not "fix" this by widening the CAS.
- **Owner decision 2026-09-10 — name who gets emailed:** every notify toggle's helper line names the recipient. The student page uses `student.parent_name`; the class roster uses `enrollment.parent_name`, which Task 8b adds to the roster read model. When it is `null`, fall back to the words "the family".
- **Task 8b is a prerequisite for Tasks 9-10 and fixes a live production defect** (held enrollments are missing from the class roster). Do not reorder it after the frontend wiring.
- Student page layout: Transfer is the only inline button; Hold/Return, Drop and Delete render in the row's overflow menu, Delete last behind a separator.
- Hold dialog defaults: return date defaults to today + 30, capped at today + `EnrollmentDeparturePolicyView.max_hold_days` (NOT `hold_max_days` — that is the spec prose's shorthand, the real field on `EnrollmentDeparturePolicyView` and the backend policy object is `max_hold_days`). Reason optional. "Email the family" toggle defaults **off**.
- Return dialog: reason optional, "Email the family" toggle defaults **off**.
- Drop dialog (`WithdrawalCreditDialog`): "Email the family" toggle defaults **on**. Everything else about the dialog is unchanged.
- `notify_family: bool = False` is added to `HoldEnrollmentRequest`, `ReturnFromHoldRequest` and `WithdrawEnrollmentRequest` on both sides (frontend request type + backend Pydantic model) — the default keeps every existing caller and test unchanged.
- Notification send is best-effort, TRANSACTIONAL category, claimed once per `(academy_id, enrollment_id, notice_key)` via `claim_digest_send` — never allowed to fail the write it rides on.
- `/pause` and `/resume` backend routes and their Pydantic models are untouched (issue #616's parent-approval flow still uses them); only the admin session-detail and student-page UI stop calling them.
- `backend/v2/composition/admin.py` is at 4318/4500 lines (verified: `ADMIN_COMPOSITION_LINE_BUDGET = 4_500` in `backend/v2/tests/structural/test_composition_is_wiring.py`) — do not add lines to it. New collaborators attach onto the already-built `AdminUseCases` object in `main.py`, exactly like `compose_enrollment_holds` already does for Hold/Return.
- **Cross-plan contracts this plan owns** (build order for the four 2026-09-10 admin-UX plans is 1 → 2 → 4 → 3; this is plan 1, first):
  - Migration number **`0173` is claimed by this plan** (`0173_withdrawal_notice_sends`). Plan 3 (`2026-09-10-birthdays-and-profile-nudges.md`) uses 0174/0175/0176 accordingly. Verify `0172` is still the highest on `main` before creating the file.
  - `departureActionsFor`, the `notify_family` flag and the five dialog modules under `frontend/components/admin/enrollment/` (`hold-dialog.tsx`, `return-dialog.tsx`, `transfer-dialog.tsx`, `withdrawal-credit-dialog.tsx`, `remove-dialog.tsx`) are defined here and consumed as-is by later plans. Do not rename them after this lands.
  - Task 9 makes `studentName` a **required** prop on `SessionsPanel` and passes `student.full_name` from `students/[studentId]/page.tsx`. Plan 4 (`2026-09-10-student-page-single-view.md`, Task 6) rewrites that page's layout on top of this and must keep the prop — its plan already carries that note.
- No NEW backend route and no new frontend `app/` route is created by this plan. `POST /admin/enrollments/{id}/hold`, `/return` and `/withdraw` all already exist and already guard with `require_persona("admin")` (wrong persona → 404, per the repo's persona rule) — that guard is unchanged, so no persona test is added.
- Because no `app/` route is added, `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json` and the two hardcoded route counts are NOT touched. Every new file is under `components/` or `lib/` (frontend) or `composition/`/`contexts/` (backend). Re-verify this before committing Task 9 if the implementation ends up adding a route file.
- Frontend unit tests run under vitest with `environment: "node"`, `globals: false`, and the repo has **no** `@testing-library/react`, `jsdom` or `happy-dom` dependency (see `frontend/vitest.config.ts` and `frontend/package.json`). Every new frontend unit test in this plan must therefore test a **pure module** — never render a component. Adding a DOM testing dependency is out of scope (`Frontend Static` goes red repo-wide on new advisories; see `components/ds/menu.tsx`'s own header comment).

## File structure

| File | Responsibility |
|---|---|
| `frontend/components/admin/enrollment/departure-actions.logic.ts` | Modify: drop `pause`/`resume` from `DepartureAction`; add `departureActionsFor(status)`; fix inline-layout gating so only `transfer` is inline-eligible; add `separatorBefore` to `ResolvedDepartureAction`. |
| `frontend/components/admin/enrollment/departure-actions.test.tsx` | Modify: remove pause/resume assertions, fix the two existing assertions the inline-gating change invalidates, add `departureActionsFor` + inline-overflow + separator coverage. |
| `frontend/components/admin/enrollment/departure-actions.tsx` | Modify: re-export `departureActionsFor` from the barrel; drop the stale "Pause/Resume are a *transitional* group" paragraph from the module doc comment; pass `separatorBefore` into the overflow `MenuItem`s. |
| `frontend/components/ds/menu.tsx` | Modify: `MenuItem.separatorBefore` + divider rendering, so Delete can render behind a separator. No test file (component render is untestable in this repo's node-env vitest — see Global Constraints); the placement decision is unit-tested as pure logic in `departure-actions.logic.ts` instead. |
| `frontend/components/admin/enrollment/hold-dialog.tsx` | Create: `HoldEnrollmentDialog`. |
| `frontend/components/admin/enrollment/return-dialog.tsx` | Create: `ReturnFromHoldDialog`. |
| `frontend/components/admin/enrollment/transfer-dialog.tsx` | Create (moved from `sessions/[id]/dialogs.tsx`): `TransferEnrollmentDialog`. |
| `frontend/components/admin/enrollment/withdrawal-credit-dialog.tsx` | Create (moved): `WithdrawalCreditDialog` + notify toggle (default on). |
| `frontend/components/admin/enrollment/remove-dialog.tsx` | Create (moved): `RemoveEnrollmentDialog`. |
| `frontend/app/(admin)/admin/sessions/[id]/dialogs.tsx` | Modify: delete `PauseEnrollmentDialog` (retired), and move out `TransferEnrollmentDialog` + its `RallySessionPicker` helper, `WithdrawalCreditDialog`, `RemoveEnrollmentDialog`. Keep `AddToRosterDialog`, `StudentSelect`, `CoachSelect`, `DaySelect`, `DAYS_OF_WEEK`. (`RallySessionPicker` is exported but its ONLY caller is `TransferEnrollmentDialog` — verified by grep across `app/`, `components/`, `lib/`, `e2e/` — so it moves with it.) |
| `frontend/app/(admin)/admin/sessions/[id]/RosterPanel.tsx` | Modify: `rosterActionsFor` → shared `departureActionsFor`; `dispatchRosterAction` gains hold/return, drops pause/resume. |
| `frontend/app/(admin)/admin/sessions/[id]/page.tsx` | Modify: remove Pause dialog + `pauseTarget`/`resumeMutation`; add `holdTarget`/`returnTarget` state and the two new dialogs; update dialog imports to the new `components/admin/enrollment/` paths. |
| `frontend/app/(admin)/admin/students/[studentId]/SessionsPanel.tsx` | Modify: `actions={departureActionsFor(session.status)}`; mount Hold/Return/Drop/Delete dialogs; keep Transfer's existing inline "Move student session" flow untouched; take a new `studentName` prop (today the panel passes `studentName={session.session_title}` into `DepartureActions` — the session title, not the child — so the dialogs have no name to show). |
| `frontend/app/(admin)/admin/students/[studentId]/page.tsx` | Modify: pass `studentName={student.full_name}` into `<SessionsPanel …>` (the sibling `<ProfileHeader … studentName={student.full_name}>` at line 143 already proves the field exists on `AdminStudentDetail`). |
| `frontend/lib/api/v2/departure-policy.ts` | Modify: `notify_family?: boolean` on `HoldEnrollmentRequest`/`ReturnFromHoldRequest`. |
| `frontend/lib/api/admin.ts` | Modify: `notify_family?: boolean` on `WithdrawEnrollmentRequest`. |
| `frontend/lib/admin/withdrawal.ts` | Modify: `buildWithdrawRequest` accepts and forwards `notifyFamily`. |
| `backend/v2/interfaces/admin/hold_routes.py` | Modify: `notify_family: bool = False` on both request models, forwarded to the use cases. |
| `backend/v2/interfaces/admin/views.py` | Modify: `notify_family: bool = False` on `WithdrawEnrollmentRequest`. |
| `backend/v2/interfaces/admin/sessions_routes.py` | Modify: forward `body.notify_family` into `WithdrawEnrollmentCommand`. |
| `backend/v2/contexts/enrollment/application/use_cases/holds.py` | Modify: `HoldEnrollment`/`ReturnFromHold` take an optional `notifier: HoldNotifier`, `execute(..., notify_family: bool = False)`, best-effort call at the end. |
| `backend/v2/contexts/enrollment/application/use_cases/admin_writes.py` | Modify: `WithdrawEnrollmentCommand.notify_family`; `WithdrawEnrollment` gains `set_notifier` + best-effort call. |
| `backend/v2/contexts/enrollment/application/ports.py` | Modify: `HoldNotifier` gains `hold_started`/`hold_returned`; new `WithdrawalNotifier` protocol with `dropped`. |
| `backend/v2/composition/hold_notifications.py` | Modify: `HoldNotificationAdapter` implements `hold_started`/`hold_returned`. |
| `backend/v2/composition/enrollment_holds.py` | Modify: pass `notifier=hold_notifier` into `HoldEnrollment`/`ReturnFromHold`. |
| `backend/v2/composition/withdrawal_notice_send_repo.py` | Create: `MongoWithdrawalNoticeSendRepository` (claim, mirrors `hold_notice_send_repo.py`). |
| `backend/v2/composition/withdrawal_notifications.py` | Create: `WithdrawalNotificationAdapter` + `compose_withdrawal_notifications`. |
| `backend/v2/migrations/0173_withdrawal_notice_sends.py` | Create: unique index on the new claim collection. |
| `backend/v2/main.py` | Modify: build the withdrawal notifier and call `app.state.admin.withdraw_enrollment.set_notifier(...)`. |
| `backend/v2/tests/fixtures/enrollment_fakes.py` | Modify: `FakeHoldNotifier` gains `hold_started`/`hold_returned` recording + a new `FakeWithdrawalNotifier`. |
| `backend/v2/tests/application/test_enrollment_holds.py` | Modify: notify-flag coverage for Hold/Return. |
| `backend/v2/tests/application/test_withdraw_single_path.py` | Modify: notify-flag coverage for Withdraw. |
| `frontend/e2e/specs/admin-enrollment-withdraw.spec.ts` | Modify: Hold → Return from the student page; Drop from the student page asserting the past-enrollments row. |
| ~~roster Pause e2e spec~~ | **No such file exists.** Verified: every `pause` reference under `frontend/e2e/specs/` is the parent pause-**request** flow (#616) — `/admin/pause-requests`, `/api/v2/parent/pause-requests`, `/admin/families/{id}/autopay/pause` — none of which this plan touches. The roster's Pause/Resume departure buttons have no e2e coverage today, so spec §8's "Roster spec updates Pause → Hold labels" is a no-op. Task 10 re-runs the grep to confirm before skipping. |
| `docs/release-notes/2026-09-10-departure-actions-from-student-page.md` | Create: release note. |

## Task 1: Frontend — `departureActionsFor` and vocabulary cleanup

**Files:**
- Modify: `frontend/components/admin/enrollment/departure-actions.logic.ts`
- Modify: `frontend/components/admin/enrollment/departure-actions.tsx` (barrel re-export + doc comment)
- Test: `frontend/components/admin/enrollment/departure-actions.test.tsx`

**Interfaces:**
- Consumes: nothing new.
- Produces: `export function departureActionsFor(status: string): DepartureAction[]`; `DepartureAction` narrowed to `"transfer" | "hold" | "return" | "drop" | "delete" | "stop_all_classes"`; `ResolvedDepartureAction.separatorBefore: boolean`.

- [ ] Write the failing tests. Replace the pause/resume-touching assertions and add the new ones. Edit `frontend/components/admin/enrollment/departure-actions.test.tsx`:
  - In `"never owner-gates a non-delete action"` (line 42), change the actions array from `["transfer", "hold", "return", "drop", "pause", "resume", "stop_all_classes"]` to `["transfer", "hold", "return", "drop", "stop_all_classes"]`.
  - In `"does not flag transfer, hold, return, pause or resume as danger"` (line 83), rename it to `"does not flag transfer, hold or return as danger"` and change the actions array from `["transfer", "hold", "return", "pause", "resume"]` to `["transfer", "hold", "return"]`.
  - **`"pushes every action into the overflow menu in menu layout"` (line 65) passes `["transfer", "drop", "pause"]`** — `"pause"` stops being a valid `DepartureAction` in this task, so this file will not compile until it is changed to `["transfer", "drop", "hold"]`. Change it.
  - **`"keeps non-delete actions inline in inline layout"` (line 57) passes `["transfer", "drop"]` and asserts `resolved.every((entry) => !entry.inOverflow)`** — the `INLINE_LAYOUT_ALLOWED` change below deliberately breaks that assumption (`drop` moves to overflow). Rewrite it to state the new rule:
    ```ts
    it("keeps transfer inline in inline layout", () => {
      const resolved = resolveDepartureActions(["transfer"], {
        isOwner: true,
        layout: "inline",
      });
      expect(resolved.every((entry) => !entry.inOverflow)).toBe(true);
    });
    ```
  - Append at the end of the file, before the final closing `});`:
    ```ts
    describe("inline layout only allows transfer inline", () => {
      it("keeps transfer inline but pushes hold/return/drop to overflow", () => {
        const resolved = resolveDepartureActions(["transfer", "hold", "drop"], {
          isOwner: true,
          layout: "inline",
        });
        const byAction = Object.fromEntries(resolved.map((r) => [r.action, r.inOverflow]));
        expect(byAction.transfer).toBe(false);
        expect(byAction.hold).toBe(true);
        expect(byAction.drop).toBe(true);
      });
    });

    describe("overflow separator", () => {
      it("puts a separator before delete when something precedes it in the menu", () => {
        const resolved = resolveDepartureActions(["transfer", "hold", "drop", "delete"], {
          isOwner: true,
          layout: "menu",
        });
        const byAction = Object.fromEntries(resolved.map((r) => [r.action, r.separatorBefore]));
        expect(byAction.delete).toBe(true);
        expect(byAction.transfer).toBe(false);
        expect(byAction.hold).toBe(false);
        expect(byAction.drop).toBe(false);
      });

      it("does not separate delete when it is the only overflow entry", () => {
        const resolved = resolveDepartureActions(["delete"], { isOwner: true, layout: "inline" });
        expect(resolved[0].separatorBefore).toBe(false);
      });
    });

    describe("departureActionsFor", () => {
      it("offers hold/drop/delete (and transfer) for an active enrollment", () => {
        expect(departureActionsFor("active")).toEqual(["transfer", "hold", "drop", "delete"]);
      });

      it("offers return in front for a held enrollment", () => {
        expect(departureActionsFor("held")).toEqual(["return", "transfer", "drop", "delete"]);
      });

      it("offers return for a legacy paused enrollment too", () => {
        expect(departureActionsFor("paused")).toEqual(["return", "transfer", "drop", "delete"]);
      });

      it("offers transfer and drop but never return while a reclaim is in flight", () => {
        expect(departureActionsFor("reclaim_pending")).toEqual(["transfer", "drop", "delete"]);
      });

      it("offers only delete for every other status", () => {
        for (const status of ["cancelled", "deleted", "withdrawn", "dropped"]) {
          expect(departureActionsFor(status)).toEqual(["delete"]);
        }
      });
    });
    ```
  - Add `departureActionsFor` to the top `import` from `./departure-actions.logic`.
- [ ] Run it and confirm the expected failure: `cd frontend && pnpm vitest run components/admin/enrollment/departure-actions.test.tsx`. Expected failure, precisely: `departureActionsFor is not a function` (the new `departureActionsFor` describe block), plus `expected undefined to be true` in the new `overflow separator` block (`separatorBefore` is not on `ResolvedDepartureAction` yet), plus the new `inline layout only allows transfer inline` block failing on `byAction.hold` / `byAction.drop` being `false`. The four edited existing tests still PASS at this point (vitest does not typecheck, so the `"pause"` literal still runs) — they are edited now so the type change below does not leave the file uncompilable for `pnpm typecheck`.
- [ ] Implement. Edit `frontend/components/admin/enrollment/departure-actions.logic.ts`:
  - Change the `DepartureAction` union (remove `"pause"` and `"resume"`):
    ```ts
    export type DepartureAction =
      | "transfer"
      | "hold"
      | "return"
      | "drop"
      | "delete"
      | "stop_all_classes";
    ```
  - Remove the `pause`/`resume` entries from `DEPARTURE_ACTION_LABEL`.
  - **The "Pause/Resume are a *transitional* group…" paragraph is NOT in this file** — it is the module doc comment of `frontend/components/admin/enrollment/departure-actions.tsx`, lines 12-18. Edit **that** file and replace that paragraph's second half with:
    ```ts
     * Vocabulary (owner-settled, see the departures design contract):
     *   Transfer, Hold, Return, Drop, Delete — never "Cancel", which is reserved
     *   for classes and dates, not a child. Pause/Resume are retired (2026-09-10
     *   departures spec): Hold/Return cover the same ground with a seat-keeping
     *   guarantee Pause never had.
    ```
  - In the same file (`departure-actions.tsx`), add `departureActionsFor` to the existing barrel re-export block (lines 35-40) — Task 9 imports it from `@/components/admin/enrollment/departure-actions`, not from the `.logic` module:
    ```ts
    export {
      DEPARTURE_ACTION_LABEL,
      departureActionsFor,
      resolveDepartureActions,
      type DepartureAction,
      type ResolvedDepartureAction,
    } from "./departure-actions.logic";
    ```
  - Add, after `ALWAYS_OVERFLOW_ACTIONS`:
    ```ts
    /**
     * In "inline" layout, only these actions render as inline buttons; every
     * other action (besides the always-overflow ones above) still goes to the
     * overflow menu. "menu" layout is unaffected — everything there already
     * goes to overflow. Today only the student Sessions panel uses "inline"
     * layout, and only Transfer is meant to sit next to the row.
     */
    const INLINE_LAYOUT_ALLOWED = new Set<DepartureAction>(["transfer"]);
    ```
  - Add `separatorBefore: boolean;` to the `ResolvedDepartureAction` interface, documented as: "True when a `role=\"separator\"` divider should render above this entry in the overflow menu. Today only `delete` asks for one, and only when it is not the menu's first entry."
  - Rewrite the body of `resolveDepartureActions` so `inOverflow` honours the inline allow-list and `separatorBefore` can see the entries before it (the current one-pass `.map` cannot, so compute `inOverflow` first):
    ```ts
    export function resolveDepartureActions(
      actions: readonly DepartureAction[],
      { isOwner, layout }: { isOwner: boolean; layout: "menu" | "inline" },
    ): ResolvedDepartureAction[] {
      const placed = actions.map((action) => ({
        action,
        inOverflow:
          layout === "menu" ||
          ALWAYS_OVERFLOW_ACTIONS.has(action) ||
          (layout === "inline" && !INLINE_LAYOUT_ALLOWED.has(action)),
      }));
      let overflowSeen = 0;
      return placed.map(({ action, inOverflow }) => {
        const ownerGated = OWNER_ONLY_ACTIONS.has(action) && !isOwner;
        const separatorBefore =
          inOverflow && SEPARATED_ACTIONS.has(action) && overflowSeen > 0;
        if (inOverflow) overflowSeen += 1;
        return {
          action,
          label: DEPARTURE_ACTION_LABEL[action],
          disabled: ownerGated,
          ownerGated,
          inOverflow,
          separatorBefore,
          danger: DANGER_ACTIONS.has(action),
        };
      });
    }
    ```
    with, next to `ALWAYS_OVERFLOW_ACTIONS`:
    ```ts
    /** Actions that sit apart from the rest of the overflow menu. */
    const SEPARATED_ACTIONS = new Set<DepartureAction>(["delete"]);
    ```
  - Append at the end of the file:
    ```ts
    /**
     * Which departure actions a row offers, purely from enrollment status
     * (2026-09-10 departures-from-student-page spec §3). Shared by the class
     * roster and the student Sessions panel so both surfaces show the same
     * set — this replaces `RosterPanel.rosterActionsFor`, which only the
     * roster had.
     *
     * `paused` still renders Return (not Resume — that action is retired) even
     * though `ReturnFromHold` only transitions a `held` row today; a legacy
     * paused row surfaces the same button and may 409 until issue #703 folds
     * paused into the hold vocabulary. That gap is accepted by the spec, not
     * fixed here.
     */
    export function departureActionsFor(status: string): DepartureAction[] {
      switch (status) {
        case "active":
          return ["transfer", "hold", "drop", "delete"];
        case "held":
        case "paused":
          return ["return", "transfer", "drop", "delete"];
        // Owner decision 2026-09-10: a reclaim in flight still allows moving or
        // dropping the child, but never Return — ReturnFromHold's CAS
        // (mark_active_if_held) rejects reclaim_pending, so offering it would
        // render a button that always errors.
        case "reclaim_pending":
          return ["transfer", "drop", "delete"];
        default:
          return ["delete"];
      }
    }
    ```
- [ ] Run it and confirm PASS: `cd frontend && pnpm vitest run components/admin/enrollment/departure-actions.test.tsx`.
- [ ] Run the frontend typecheck to catch any other file still using `"pause"`/`"resume"` as a `DepartureAction` literal (expected to fail here — later tasks fix the call sites): `cd frontend && pnpm typecheck`. Expect failures only in `app/(admin)/admin/sessions/[id]/RosterPanel.tsx` (`rosterActionsFor` pushes `"pause"`/`"resume"`, `dispatchRosterAction` switches on them). Note them for Task 9; do not fix them in this task. Any OTHER failing file is an unmapped call site — add it to Task 9 before continuing.
- [ ] Commit: `git add frontend/components/admin/enrollment/departure-actions.logic.ts frontend/components/admin/enrollment/departure-actions.tsx frontend/components/admin/enrollment/departure-actions.test.tsx` then `git commit -m "feat(enrollment): add departureActionsFor and retire pause/resume vocabulary\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>"`.

## Task 2: Frontend — overflow-menu separator

**Files:**
- Modify: `frontend/components/ds/menu.tsx`
- Modify: `frontend/components/admin/enrollment/departure-actions.tsx`
- Test: none new. **This repo cannot render-test a component**: `frontend/vitest.config.ts` sets `environment: "node"` and there is no `@testing-library/react`, `jsdom` or `happy-dom` in `frontend/package.json`. The *decision* of which entry gets a separator is already unit-tested as pure logic (`separatorBefore` on `ResolvedDepartureAction`, Task 1's `overflow separator` describe block); the *rendering* of the divider is covered by `pnpm typecheck` + `pnpm lint` here and by Task 10's Playwright run, which drives the real menu.

**Interfaces:**
- Consumes: `ResolvedDepartureAction.separatorBefore` from Task 1.
- Produces: `MenuItem.separatorBefore?: boolean`, rendered as a `role="separator"` divider immediately before that item.

- [ ] Implement. Edit `frontend/components/ds/menu.tsx`:
  - Add to the `MenuItem` interface (after `danger?: boolean;`, line 32):
    ```ts
    /** Renders a `role="separator"` divider immediately above this item. */
    separatorBefore?: boolean;
    ```
  - In the `items.map((item, index) => (...))` render block (line 162), wrap each button in a keyed `<div>` that renders the divider first. **Copy the existing `<button>` verbatim from the file** — the only changes are the wrapping `<div key={item.key}>`, the divider, and removing `key={item.key}` from the inner `<button>` (it moved to the wrapper). For reference, the button's real danger classes are `text-status-red-800 hover:bg-status-red-50` (NOT `text-red-700`/`bg-red-50`) and its children are `<span>{item.label}</span>` then `{item.hint}`:
    ```tsx
    {items.map((item, index) => (
      <div key={item.key}>
        {item.separatorBefore && (
          <div role="separator" className="my-1 border-t border-rally-line" />
        )}
        <button
          ref={(el) => {
            itemRefs.current[index] = el;
          }}
          type="button"
          role="menuitem"
          /* …every remaining prop, className and child copied unchanged… */
        >
          <span>{item.label}</span>
          {item.hint}
        </button>
      </div>
    ))}
    ```
    Note the divider is a sibling *inside* the wrapper, so `itemRefs.current[index]` still points at the button and the roving-focus/`enabledIndexes` maths in this component is unaffected.
- [ ] Edit `frontend/components/admin/enrollment/departure-actions.tsx`: in the `overflowItems: MenuItem[]` mapping (line 66), forward the new flag — `separatorBefore: entry.separatorBefore,`.
- [ ] Run typecheck and lint: `cd frontend && pnpm typecheck && pnpm lint`. (`pnpm typecheck` still fails on `RosterPanel.tsx`'s retired `pause`/`resume` literals until Task 9 — confirm no NEW error names `menu.tsx` or `departure-actions.tsx`.)
- [ ] Re-run Task 1's unit suite to confirm the separator logic still passes end to end: `cd frontend && pnpm vitest run components/admin/enrollment/departure-actions.test.tsx`.
- [ ] Commit: `git add frontend/components/ds/menu.tsx frontend/components/admin/enrollment/departure-actions.tsx` then `git commit -m "feat(ds): support a separator before an overflow-menu item\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>"`.

## Task 3: Backend — `notify_family` on Hold/Return + `HoldNotifier.hold_started`/`hold_returned`

**Files:**
- Modify: `backend/v2/contexts/enrollment/application/ports.py`
- Modify: `backend/v2/contexts/enrollment/application/use_cases/holds.py`
- Modify: `backend/v2/interfaces/admin/hold_routes.py`
- Modify: `backend/v2/tests/fixtures/enrollment_fakes.py`
- Test: `backend/v2/tests/application/test_enrollment_holds.py`

**Interfaces:**
- Consumes: existing `HoldNotifier` Protocol (`hold_reclaimed`, `hold_reminder`) at `ports.py:638`. Both existing methods take `hold_seq: int` and `HoldNotificationAdapter` keys its claim off it (`hold-reclaim:{hold_seq}`, `hold-reminder:{hold_seq}:{n}`) — the two new methods MUST do the same, or a second hold-and-return cycle on the same enrollment would silently never email again.
- Produces: `HoldNotifier.hold_started(...)`, `HoldNotifier.hold_returned(...)` (both carrying `hold_seq: int`); `HoldEnrollment.execute(..., notify_family: bool = False)`; `ReturnFromHold.execute(..., notify_family: bool = False)`.

- [ ] Write the failing tests. Append to `backend/v2/tests/application/test_enrollment_holds.py` (after the existing `test_hold_keeps_status_moves_to_held_and_billing_syncs_once`, and update `_harness` to accept a notifier):
  - Change `_harness`'s signature and body to:
    ```python
    def _harness(status: str = "active", *, notifier: FakeHoldNotifier | None = None):
        enrollments = FakeEnrollmentWriter(rows={"enr-1": make_enrollment(status=status)})
        policy_repo = FakeDeparturePolicyRepo()
        billing = FakeBillingSync()
        events = FakeEnrollmentEvents()
        hold_uc = HoldEnrollment(
            enrollments=enrollments,
            departure_policy=policy_repo,
            enrollment_events=events,
            billing_sync=billing,
            notifier=notifier,
            clock=_clock,
        )
        return_uc = ReturnFromHold(
            enrollments=enrollments,
            enrollment_events=events,
            billing_sync=billing,
            notifier=notifier,
            clock=_clock,
        )
        return enrollments, policy_repo, billing, events, hold_uc, return_uc
    ```
    (Every existing call site of `_harness(...)` in this file keeps working unchanged since `notifier` defaults to `None`.)
  - Append. **Note each hold gets its OWN `_harness()`**: `FakeEnrollmentWriter.mark_held_if_active` mutates `self.rows` to `status="held"`, and `HoldEnrollment.execute` raises `EnrollmentNotHoldable` for anything but `active` — so calling `hold_uc.execute` twice against one harness fails on the second call, not on the assertion.
    ```python
    @pytest.mark.asyncio
    async def test_hold_does_not_notify_family_by_default() -> None:
        notifier = FakeHoldNotifier()
        _enrollments, _policy, _billing, _events, hold_uc, _return_uc = _harness(notifier=notifier)

        await hold_uc.execute("enr-1", return_on=date(2026, 10, 1), notify_family=False)
        assert notifier.hold_started_calls == []

    @pytest.mark.asyncio
    async def test_hold_notifies_family_once_when_flag_is_set() -> None:
        notifier = FakeHoldNotifier()
        _enrollments, _policy, _billing, _events, hold_uc, _return_uc = _harness(notifier=notifier)

        await hold_uc.execute("enr-1", return_on=date(2026, 10, 1), notify_family=True)
        assert len(notifier.hold_started_calls) == 1
        assert notifier.hold_started_calls[0]["enrollment_id"] == "enr-1"
        assert notifier.hold_started_calls[0]["return_on"] == date(2026, 10, 1)
        # The claim key is hold_seq-scoped, exactly like hold_reclaimed /
        # hold_reminder, so a second hold-and-return cycle emails again.
        # make_enrollment() starts at hold_seq=0 and the CAS stamps +1.
        assert notifier.hold_started_calls[0]["hold_seq"] == 1

    @pytest.mark.asyncio
    async def test_hold_notifier_failure_does_not_fail_the_write() -> None:
        class BoomNotifier(FakeHoldNotifier):
            async def hold_started(self, **kwargs):  # type: ignore[override]
                raise RuntimeError("mail outage")

        enrollments = FakeEnrollmentWriter(rows={"enr-1": make_enrollment(status="active")})
        policy_repo = FakeDeparturePolicyRepo()
        billing = FakeBillingSync()
        events = FakeEnrollmentEvents()
        hold_uc = HoldEnrollment(
            enrollments=enrollments,
            departure_policy=policy_repo,
            enrollment_events=events,
            billing_sync=billing,
            notifier=BoomNotifier(),
            clock=_clock,
        )

        result = await hold_uc.execute("enr-1", return_on=date(2026, 10, 1), notify_family=True)
        assert result.status == "held"

    @pytest.mark.asyncio
    async def test_return_does_not_notify_family_by_default() -> None:
        notifier = FakeHoldNotifier()
        _enrollments, _policy, _billing, _events, hold_uc, return_uc = _harness(notifier=notifier)
        await hold_uc.execute("enr-1", return_on=date(2026, 10, 1))

        await return_uc.execute("enr-1", notify_family=False)
        assert notifier.hold_returned_calls == []

    @pytest.mark.asyncio
    async def test_return_notifies_family_once_when_flag_is_set() -> None:
        notifier = FakeHoldNotifier()
        _enrollments, _policy, _billing, _events, hold_uc, return_uc = _harness(notifier=notifier)
        await hold_uc.execute("enr-1", return_on=date(2026, 10, 1))

        await return_uc.execute("enr-1", notify_family=True)
        assert len(notifier.hold_returned_calls) == 1
        assert notifier.hold_returned_calls[0]["enrollment_id"] == "enr-1"
        # `before` (the mark_active_if_held pre-image) carries the seq of the
        # hold that is closing, so the return notice pairs with its start.
        assert notifier.hold_returned_calls[0]["hold_seq"] == 1

    @pytest.mark.asyncio
    async def test_return_notifier_failure_does_not_fail_the_write() -> None:
        class BoomNotifier(FakeHoldNotifier):
            async def hold_returned(self, **kwargs):  # type: ignore[override]
                raise RuntimeError("mail outage")

        _enrollments, _policy, _billing, _events, hold_uc, return_uc = _harness(
            notifier=BoomNotifier()
        )
        await hold_uc.execute("enr-1", return_on=date(2026, 10, 1))

        result = await return_uc.execute("enr-1", notify_family=True)
        assert result.status == "active"
    ```
  - Update this test file's `FakeHoldNotifier` import site — it already imports it from `backend.v2.tests.fixtures.enrollment_fakes` (line ~51), no import change needed once the fixture (below) gains the two methods.
- [ ] Run it and confirm the expected failure: `cd backend && .venv/bin/pytest v2/tests/application/test_enrollment_holds.py -q -k "notif"`. Expect `TypeError: __init__() got an unexpected keyword argument 'notifier'`.
- [ ] Implement, part 1 — extend the fixture. Edit `backend/v2/tests/fixtures/enrollment_fakes.py`, in `FakeHoldNotifier` (line 414; **the `@dataclass` decorator on line 413 stays — it is what makes `field(default_factory=…)` work**):
  ```python
  @dataclass
  class FakeHoldNotifier:
      reclaimed_calls: list[dict[str, Any]] = field(default_factory=list)
      reminder_calls: list[dict[str, Any]] = field(default_factory=list)
      hold_started_calls: list[dict[str, Any]] = field(default_factory=list)
      hold_returned_calls: list[dict[str, Any]] = field(default_factory=list)

      async def hold_reclaimed(self, **kwargs: Any) -> None:
          self.reclaimed_calls.append(kwargs)

      async def hold_reminder(self, **kwargs: Any) -> None:
          self.reminder_calls.append(kwargs)

      async def hold_started(self, **kwargs: Any) -> None:
          self.hold_started_calls.append(kwargs)

      async def hold_returned(self, **kwargs: Any) -> None:
          self.hold_returned_calls.append(kwargs)
  ```
- [ ] Implement, part 2 — the port. Edit `backend/v2/contexts/enrollment/application/ports.py`, inside `HoldNotifier` (after `hold_reminder`, before the closing of the class at line 668). `date`, `datetime`, `Literal` and `Protocol` are already imported at the top of this module (line 6-7) — nothing to add:
  ```python
      async def hold_started(
          self,
          *,
          enrollment_id: str,
          hold_seq: int,
          session_id: str,
          student_id: str,
          return_on: date,
          reason: str | None,
      ) -> None: ...

      async def hold_returned(
          self,
          *,
          enrollment_id: str,
          hold_seq: int,
          session_id: str,
          student_id: str,
          reason: str | None,
      ) -> None: ...
  ```
  (`hold_seq` is not decoration: `HoldNotificationAdapter` keys its `digest_claim` off it, so without it the "hold-started"/"hold-returned" claim would be a single row per enrollment for life and only the FIRST hold cycle would ever email. Both existing `HoldNotifier` methods already carry it for exactly this reason.)
- [ ] Implement, part 3 — the use cases. Edit `backend/v2/contexts/enrollment/application/use_cases/holds.py`:
  - `HoldEnrollment.__init__`: add `notifier: HoldNotifier | None = None,` after `roster_notifier: RosterChangeNotifier | None = None,` and `self._notifier = notifier` after `self._roster_notifier = roster_notifier`.
  - `HoldEnrollment.execute`: add `notify_family: bool = False,` to the signature (after `reason: str | None = None,`), and right after the existing `if self._roster_notifier is not None:` block (before the `return e.model_copy(...)`), add:
    ```python
            if notify_family and self._notifier is not None:
                try:
                    await self._notifier.hold_started(
                        enrollment_id=enrollment_id,
                        # The CAS above stamped `hold_seq + 1`; the return
                        # value's model_copy uses the same expression.
                        hold_seq=e.hold_seq + 1,
                        session_id=e.session_id,
                        student_id=e.student_id,
                        return_on=return_on,
                        reason=reason,
                    )
                except Exception:
                    log.exception("hold_started_notify_failed", extra={"enrollment_id": enrollment_id})
    ```
  - `ReturnFromHold.__init__`: add `notifier: HoldNotifier | None = None,` after `roster_notifier: RosterChangeNotifier | None = None,` and `self._notifier = notifier`.
  - `ReturnFromHold.execute`: add `notify_family: bool = False,` to the signature (after `reason: str | None = None,`), and right after the existing `if self._roster_notifier is not None:` block (before `return before.model_copy(...)`), add:
    ```python
            if notify_family and self._notifier is not None:
                try:
                    await self._notifier.hold_returned(
                        enrollment_id=enrollment_id,
                        # `before` is mark_active_if_held's pre-image — the
                        # held row that is closing — so its seq pairs this
                        # notice with its matching hold_started.
                        hold_seq=before.hold_seq,
                        session_id=e.session_id,
                        student_id=e.student_id,
                        reason=reason,
                    )
                except Exception:
                    log.exception("hold_returned_notify_failed", extra={"enrollment_id": enrollment_id})
    ```
- [ ] Implement, part 4 — the route. Edit `backend/v2/interfaces/admin/hold_routes.py`:
  - `HoldEnrollmentRequest`: add `notify_family: bool = False`.
  - `ReturnFromHoldRequest`: add `notify_family: bool = False`.
  - `hold_enrollment` route: pass `notify_family=body.notify_family` into `.execute(...)`.
  - `return_from_hold` route: pass `notify_family=body.notify_family` into `.execute(...)`.
- [ ] Run it and confirm PASS: `cd backend && .venv/bin/pytest v2/tests/application/test_enrollment_holds.py -q`.
- [ ] Run the full holds test module plus ruff to catch any signature drift: `cd backend && .venv/bin/pytest v2/tests/application/test_enrollment_holds.py v2/tests/application/test_hold_reclaim_races.py -q && .venv/bin/ruff check v2/contexts/enrollment/application/use_cases/holds.py v2/contexts/enrollment/application/ports.py v2/interfaces/admin/hold_routes.py`.
- [ ] Commit: `git add backend/v2/contexts/enrollment/application/ports.py backend/v2/contexts/enrollment/application/use_cases/holds.py backend/v2/interfaces/admin/hold_routes.py backend/v2/tests/fixtures/enrollment_fakes.py backend/v2/tests/application/test_enrollment_holds.py` then `git commit -m "feat(enrollment): notify_family flag for Hold and Return\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>"`.

## Task 4: Backend — `notify_family` on Withdraw + `WithdrawalNotifier` port

**Files:**
- Modify: `backend/v2/contexts/enrollment/application/ports.py`
- Modify: `backend/v2/contexts/enrollment/application/use_cases/admin_writes.py`
- Modify: `backend/v2/interfaces/admin/views.py`
- Modify: `backend/v2/interfaces/admin/sessions_routes.py`
- Test: `backend/v2/tests/application/test_withdraw_single_path.py`
- Modify: `backend/v2/tests/fixtures/enrollment_fakes.py`

**Interfaces:**
- Consumes: `WithdrawEnrollmentCommand` at `admin_writes.py:1831`; `WithdrawEnrollment` at `admin_writes.py:1894`.
- Produces: `WithdrawalNotifier` protocol (`dropped`); `WithdrawEnrollmentCommand.notify_family`; `WithdrawEnrollment.set_notifier(notifier)`.

- [ ] Write the failing tests. Edit `backend/v2/tests/application/test_withdraw_single_path.py`:
  - Add `FakeWithdrawalNotifier` to the import from `backend.v2.tests.fixtures.enrollment_fakes` (created below) — add the import line:
    ```python
    from backend.v2.tests.fixtures.enrollment_fakes import FakeWithdrawalNotifier
    ```
  - Append at the end of the file:
    ```python
    @pytest.mark.asyncio
    async def test_withdraw_notifies_family_only_when_flag_is_set() -> None:
        h = _build()
        notifier = FakeWithdrawalNotifier()
        h.use_case.set_notifier(notifier)

        cmd = WithdrawEnrollmentCommand(
            enrollment_id="enr-1",
            effective_at=EFFECTIVE,
            outcome="credit",
            actor_id="owner-1",
            reason="moving away",
            notify_family=True,
        )
        await h.use_case.execute(cmd)

        assert len(notifier.dropped_calls) == 1
        assert notifier.dropped_calls[0]["enrollment_id"] == "enr-1"
        assert notifier.dropped_calls[0]["outcome"] == "credit"

    @pytest.mark.asyncio
    async def test_withdraw_does_not_notify_by_default() -> None:
        h = _build()
        notifier = FakeWithdrawalNotifier()
        h.use_case.set_notifier(notifier)

        await h.use_case.execute(_cmd("credit"))

        assert notifier.dropped_calls == []

    @pytest.mark.asyncio
    async def test_withdraw_notifier_failure_does_not_fail_the_write() -> None:
        h = _build()

        class BoomNotifier:
            async def dropped(self, **kwargs):
                raise RuntimeError("mail outage")

        h.use_case.set_notifier(BoomNotifier())
        cmd = WithdrawEnrollmentCommand(
            enrollment_id="enr-1",
            effective_at=EFFECTIVE,
            outcome="credit",
            actor_id="owner-1",
            reason="moving away",
            notify_family=True,
        )
        await h.use_case.execute(cmd)
        assert h.enrollments.rows["enr-1"].status == "dropped"
    ```
- [ ] Run it and confirm the expected failure: `cd backend && .venv/bin/pytest v2/tests/application/test_withdraw_single_path.py -q -k notif`. Expect a `pydantic.ValidationError` (`notify_family` is not a field on `WithdrawEnrollmentCommand`) or `ImportError` for `FakeWithdrawalNotifier`.
- [ ] Implement, part 1 — the fixture. Edit `backend/v2/tests/fixtures/enrollment_fakes.py`, add after `FakeHoldNotifier`:
  ```python
  @dataclass
  class FakeWithdrawalNotifier:
      dropped_calls: list[dict[str, Any]] = field(default_factory=list)

      async def dropped(self, **kwargs: Any) -> None:
          self.dropped_calls.append(kwargs)
  ```
- [ ] Implement, part 2 — the port. Edit `backend/v2/contexts/enrollment/application/ports.py`, add after `HoldNotifier`:
  ```python
  class WithdrawalNotifier(Protocol):
      """Best-effort family email for a Drop (issue #700's departures spec).
      Never raises into the caller's write path; the send is claimed exactly
      like ``HoldNotifier``'s sends, see
      ``communications/infrastructure/digest_claim.py``."""

      async def dropped(
          self,
          *,
          enrollment_id: str,
          session_id: str,
          student_id: str,
          effective_at: datetime,
          reason: str | None,
          outcome: WithdrawalOutcome,
          billing_result: str | None,
      ) -> None: ...
  ```
  (`datetime`, `Literal` and `Protocol` are already imported at the top of `ports.py` (lines 6-7) — nothing to add. Use the existing `WithdrawalOutcome = Literal["credit", "refund", "adjustment"]` alias already defined in this same module at `ports.py:426` rather than re-spelling the Literal, so the port cannot drift from `WithdrawEnrollmentCommand.outcome`, which is typed with that alias.)
- [ ] Implement, part 3 — the use case. Edit `backend/v2/contexts/enrollment/application/use_cases/admin_writes.py`:
  - `WithdrawEnrollmentCommand` (line 1831, `model_config = {"frozen": True}`): add `notify_family: bool = False` after `reason`.
  - Import `WithdrawalNotifier` from `..ports` alongside the other port imports already used in this file.
  - `WithdrawEnrollment.__init__` (ends with `self._now = clock`, ~line 1938): add `self._notifier: WithdrawalNotifier | None = None` right after `self._now = clock` (do NOT add it as a constructor parameter — mirrors `set_seat_broker`'s pattern at line 832 exactly, because `composition/admin.py` builds this use case and is at its wiring line-budget cap; a new required or even optional constructor kwarg there is still a line added to a file this plan must not grow).
  - Add a `set_notifier` method right after `__init__`:
    ```python
        def set_notifier(self, notifier: WithdrawalNotifier) -> None:
            self._notifier = notifier
    ```
  - At the very end of `execute` (after the existing `await _notify_roster_change(...)` call, before the method ends), add:
    ```python
        if cmd.notify_family and self._notifier is not None:
            try:
                await self._notifier.dropped(
                    enrollment_id=e.enrollment_id,
                    session_id=e.session_id,
                    student_id=e.student_id,
                    effective_at=cmd.effective_at,
                    reason=cmd.reason,
                    outcome=cmd.outcome,
                    billing_result=billing_decision.get("billing_result"),
                )
            except Exception:
                log.exception(
                    "withdrawal_notify_failed", extra={"enrollment_id": e.enrollment_id}
                )
    ```
- [ ] Implement, part 4 — the route. Edit `backend/v2/interfaces/admin/views.py`, `WithdrawEnrollmentRequest` (line 621): add `notify_family: bool = False`.
  Edit `backend/v2/interfaces/admin/sessions_routes.py`, the `withdraw_enrollment` route (line 656): add `notify_family=body.notify_family,` inside the `WithdrawEnrollmentCommand(...)` call.
- [ ] Run it and confirm PASS: `cd backend && .venv/bin/pytest v2/tests/application/test_withdraw_single_path.py -q`.
- [ ] Run the wider withdrawal suite plus ruff: `cd backend && .venv/bin/pytest v2/tests/application/test_withdraw_single_path.py v2/tests/interface/test_admin_withdrawal_credit.py -q && .venv/bin/ruff check v2/contexts/enrollment/application/use_cases/admin_writes.py v2/contexts/enrollment/application/ports.py v2/interfaces/admin/views.py v2/interfaces/admin/sessions_routes.py`.
- [ ] Commit: `git add backend/v2/contexts/enrollment/application/ports.py backend/v2/contexts/enrollment/application/use_cases/admin_writes.py backend/v2/interfaces/admin/views.py backend/v2/interfaces/admin/sessions_routes.py backend/v2/tests/fixtures/enrollment_fakes.py backend/v2/tests/application/test_withdraw_single_path.py` then `git commit -m "feat(enrollment): notify_family flag and WithdrawalNotifier port for Drop\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>"`.

## Task 5: Backend — wire the notifier adapters (composition + migration + main.py)

**Files:**
- Modify: `backend/v2/composition/hold_notifications.py`
- Modify: `backend/v2/composition/enrollment_holds.py`
- Create: `backend/v2/composition/withdrawal_notice_send_repo.py`
- Create: `backend/v2/composition/withdrawal_notifications.py`
- Create: `backend/v2/migrations/0173_withdrawal_notice_sends.py`
- Modify: `backend/v2/main.py`
- Test: `backend/v2/tests/contract/test_hold_notice_send_claim_mongo.py` (extend) and a new `backend/v2/tests/contract/test_withdrawal_notice_send_claim_mongo.py`

**Interfaces:**
- Consumes: `MongoHoldNoticeSendRepository` pattern at `backend/v2/composition/hold_notice_send_repo.py`; `claim_digest_send` at `backend/v2/contexts/communications/infrastructure/digest_claim.py`.
- Produces: `HoldNotificationAdapter.hold_started`/`hold_returned`; `MongoWithdrawalNoticeSendRepository`; `WithdrawalNotificationAdapter`; `compose_withdrawal_notifications(db, settings)`.

- [ ] Write the failing test. Create `backend/v2/tests/contract/test_withdrawal_notice_send_claim_mongo.py` by copying the structure of `backend/v2/tests/contract/test_hold_notice_send_claim_mongo.py` verbatim first (`cp backend/v2/tests/contract/test_hold_notice_send_claim_mongo.py backend/v2/tests/contract/test_withdrawal_notice_send_claim_mongo.py`), then edit the copy:
  - Replace the import of `MongoHoldNoticeSendRepository` with `MongoWithdrawalNoticeSendRepository` from `backend.v2.composition.withdrawal_notice_send_repo`.
  - Replace every `try_claim(academy_id=..., enrollment_id=..., notice_key=...)` call's repository instantiation (`MongoHoldNoticeSendRepository(db)` → `MongoWithdrawalNoticeSendRepository(db)`); the `try_claim` call signature is identical (`academy_id`, `enrollment_id`, `notice_key`), so no other line in the copied file needs to change beyond the import and class name.
  - Rename the test functions from `test_hold_notice_...` to `test_withdrawal_notice_...` (mechanical rename, same assertions).
- [ ] Run it and confirm the expected failure: `cd backend && .venv/bin/pytest v2/tests/contract/test_withdrawal_notice_send_claim_mongo.py -q`. Expect `ModuleNotFoundError: No module named 'backend.v2.composition.withdrawal_notice_send_repo'`. (This test needs a running Mongo — same prerequisite as `test_hold_notice_send_claim_mongo.py`; run it however that file's suite is normally run in this repo, e.g. via the Mongo-backed contract test target.)
- [ ] Implement, part 1 — the claim repo. Create `backend/v2/composition/withdrawal_notice_send_repo.py` by copying `backend/v2/composition/hold_notice_send_repo.py` and adjusting only:
  - Module docstring: replace "Mongo-backed hold-notice-send claim (issue #697)" with "Mongo-backed withdrawal-notice-send claim (2026-09-10 departures-from-student-page spec)"; keep the rest of the docstring's reasoning about `digest_claim`/cross-context imports verbatim — it applies unchanged.
  - Class rename `MongoHoldNoticeSendRepository` → `MongoWithdrawalNoticeSendRepository`.
  - `collection_name = "enrollment_withdrawal_notice_sends"`.
  - `try_claim`'s parameter names, body, `mark_sent`, `mark_failed` stay byte-for-byte identical (same shape: `academy_id`, `enrollment_id`, `notice_key`).
- [ ] Implement, part 2 — the adapter. Create `backend/v2/composition/withdrawal_notifications.py`:
  ```python
  """WithdrawalNotifier adapter — family email for a Drop.

  2026-09-10 departures-from-student-page spec §5. Structurally
  `HoldNotificationAdapter` (`composition/hold_notifications.py`) with one
  send instead of two and a plain-words billing outcome instead of a hold
  reason. Reuses the same claim primitive
  (`communications/infrastructure/digest_claim.py`) for the same reason that
  module documents: a freshly written claim would be unsafe (2026-09-02
  production incident).

  Best-effort and TRANSACTIONAL: `WithdrawEnrollment.execute` never lets this
  adapter's failure undo a completed withdrawal.
  """

  from __future__ import annotations

  import html
  import logging
  from datetime import datetime
  from typing import Any, Literal, Protocol

  from backend.v2.composition.withdrawal_notice_send_repo import (
      MongoWithdrawalNoticeSendRepository,
  )
  from backend.v2.contexts.communications.application.ports import (
      AudienceResolver,
      EmailSendPort,
      ResolvedRecipient,
  )
  from backend.v2.contexts.communications.domain.email_category import EmailCategory
  from backend.v2.contexts.communications.domain.models import SelectedRecipientsAudience
  from backend.v2.contexts.enrollment.domain.models import Session, Student
  from backend.v2.shared.tenancy import current_academy_id

  logger = logging.getLogger(__name__)

  _OUTCOME_WORDS: dict[str, str] = {
      "credit": "an account credit",
      "refund": "a refund",
      "adjustment": "an admin adjustment — no credit or refund",
  }


  def _para(text: str) -> str:
      return f"<p style='margin:0 0 12px'>{text}</p>"


  class SessionLookup(Protocol):
      async def get(self, session_id: str) -> Session | None: ...


  class StudentLookup(Protocol):
      async def by_ids(self, student_ids: list[str]) -> list[Student]: ...


  class WithdrawalNotificationAdapter:
      def __init__(
          self,
          *,
          sessions: SessionLookup,
          students: StudentLookup,
          audiences: AudienceResolver,
          sender: EmailSendPort,
          notice_sends: MongoWithdrawalNoticeSendRepository,
      ) -> None:
          self._sessions = sessions
          self._students = students
          self._audiences = audiences
          self._sender = sender
          self._notice_sends = notice_sends

      async def dropped(
          self,
          *,
          enrollment_id: str,
          session_id: str,
          student_id: str,
          effective_at: datetime,
          reason: str | None,
          outcome: Literal["credit", "refund", "adjustment"],
          billing_result: str | None,
      ) -> None:
          academy_id = current_academy_id()
          claim = await self._notice_sends.try_claim(
              academy_id=academy_id, enrollment_id=enrollment_id, notice_key="dropped"
          )
          if claim is None:
              return

          session = await self._sessions.get(session_id)
          students = await self._students.by_ids([student_id])
          student_name = students[0].full_name if students else "The student"
          parent_id = students[0].parent_id if students else None

          if session is None or not parent_id:
              await self._notice_sends.mark_failed(
                  claim["send_id"], "session_or_parent_missing", retryable=False
              )
              return

          recipient = await self._resolve_parent(parent_id)
          if recipient is None or not recipient.email:
              await self._notice_sends.mark_failed(claim["send_id"], "no_recipient", retryable=False)
              return

          subject = f"{student_name} has been dropped from {session.title}"
          body = self._render_body(
              session=session,
              student_name=student_name,
              effective_at=effective_at,
              outcome=outcome,
          )
          try:
              result = await self._sender.send(
                  recipient=recipient,
                  subject=subject,
                  body=body,
                  category=EmailCategory.TRANSACTIONAL,
              )
          except Exception:
              logger.exception("withdrawal_notice_send_failed", extra={"enrollment_id": enrollment_id})
              await self._notice_sends.mark_failed(claim["send_id"], "send_exception")
              return

          if result.ok:
              await self._notice_sends.mark_sent(claim["send_id"])
          elif result.suppressed:
              await self._notice_sends.mark_failed(claim["send_id"], "suppressed", retryable=False)
          else:
              await self._notice_sends.mark_failed(claim["send_id"], result.failed_reason or "send_failed")

      async def _resolve_parent(self, parent_id: str) -> ResolvedRecipient | None:
          try:
              resolved = await self._audiences.resolve_selected_audience(
                  SelectedRecipientsAudience(user_ids=(parent_id,))
              )
          except Exception:
              logger.exception("withdrawal_notice_audience_failed", extra={"parent_id": parent_id})
              return None
          return resolved[0] if resolved else None

      @staticmethod
      def _render_body(
          *,
          session: Session,
          student_name: str,
          effective_at: datetime,
          outcome: Literal["credit", "refund", "adjustment"],
      ) -> str:
          safe_name = html.escape(student_name)
          safe_title = html.escape(session.title)
          outcome_words = _OUTCOME_WORDS[outcome]
          return "".join(
              [
                  _para(
                      f"<strong>{safe_name}</strong> has been dropped from {safe_title}, "
                      f"effective {html.escape(effective_at.date().isoformat())}."
                  ),
                  _para(f"Billing: {outcome_words}."),
                  _para(
                      "If this was not expected, or you would like to re-enroll, please "
                      "contact the academy."
                  ),
              ]
          )


  def compose_withdrawal_notifications(db: Any, settings: Any) -> WithdrawalNotificationAdapter:
      """Mirrors `compose_hold_notifications`: builds every Mongo-backed
      collaborator itself so a caller need only pass `db`/`settings`."""
      from backend.v2.composition.digests import _build_email_sender
      from backend.v2.contexts.communications.infrastructure.mongo_audience_resolver import (
          MongoAudienceResolver,
      )
      from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import (
          MongoSessionRepository,
      )
      from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
          MongoStudentRepository,
      )

      return WithdrawalNotificationAdapter(
          sessions=MongoSessionRepository(db),
          students=MongoStudentRepository(db),
          audiences=MongoAudienceResolver(db=db),
          sender=_build_email_sender(settings, db),
          notice_sends=MongoWithdrawalNoticeSendRepository(db),
      )
  ```
- [ ] Implement, part 3 — `HoldNotificationAdapter` gets the two new methods (satisfying the extended `HoldNotifier` Protocol from Task 3). Edit `backend/v2/composition/hold_notifications.py`, add after `hold_reminder` (before `# -- shared plumbing --`):
  ```python
      async def hold_started(
          self,
          *,
          enrollment_id: str,
          hold_seq: int,
          session_id: str,
          student_id: str,
          return_on: date,
          reason: str | None,
      ) -> None:
          notice_key = f"hold-started:{hold_seq}"
          await self._send_claimed(
              enrollment_id=enrollment_id,
              notice_key=notice_key,
              session_id=session_id,
              student_id=student_id,
              build=lambda session, student_name: (
                  f"{student_name} is on hold for {session.title}",
                  self._render_started_body(
                      session=session, student_name=student_name, return_on=return_on
                  ),
              ),
          )

      async def hold_returned(
          self,
          *,
          enrollment_id: str,
          hold_seq: int,
          session_id: str,
          student_id: str,
          reason: str | None,
      ) -> None:
          notice_key = f"hold-returned:{hold_seq}"
          await self._send_claimed(
              enrollment_id=enrollment_id,
              notice_key=notice_key,
              session_id=session_id,
              student_id=student_id,
              build=lambda session, student_name: (
                  f"{student_name} is back for {session.title}",
                  self._render_returned_body(session=session, student_name=student_name),
              ),
          )
  ```
  Add the two matching `@staticmethod` renderers next to `_render_reclaim_body`/`_render_reminder_body`:
  ```python
      @staticmethod
      def _render_started_body(*, session: Session, student_name: str, return_on: date) -> str:
          safe_name = html.escape(student_name)
          safe_title = html.escape(session.title)
          return "".join(
              [
                  _para(f"<strong>{safe_name}</strong>'s seat in {safe_title} is on hold."),
                  _para(
                      f"Billing pauses starting with the next invoice and resumes on "
                      f"{html.escape(return_on.isoformat())}, when {safe_name} is expected back."
                  ),
              ]
          )

      @staticmethod
      def _render_returned_body(*, session: Session, student_name: str) -> str:
          safe_name = html.escape(student_name)
          safe_title = html.escape(session.title)
          return "".join(
              [
                  _para(f"<strong>{safe_name}</strong> is back in {safe_title}."),
                  _para("Billing resumes with the next invoice."),
              ]
          )
  ```
  Both notice keys are `hold_seq`-scoped, matching `hold_reclaimed`'s `f"hold-reclaim:{hold_seq}"` and `hold_reminder`'s `f"hold-reminder:{hold_seq}:{notice_index}"`. This is required, not stylistic: `MongoHoldNoticeSendRepository.try_claim` dedups on `(academy_id, enrollment_id, digest_date=notice_key)`, so an unscoped `"hold-started"` key would claim once per enrollment for life and every hold cycle after the first would silently send nothing. `hold_seq` is threaded in from Task 3's port signature — no repo lookup is needed or available here.
- [ ] Implement, part 4 — wire `notifier=hold_notifier` into the use cases. Edit `backend/v2/composition/enrollment_holds.py`: in `compose_enrollment_holds`, add `notifier=hold_notifier,` to both the `HoldEnrollment(...)` and `ReturnFromHold(...)` constructor calls.
- [ ] Implement, part 5 — the migration. Create `backend/v2/migrations/0173_withdrawal_notice_sends.py` (model: `backend/v2/migrations/0172_absence_notice_sends.py`):
  ```python
  """Withdrawal (Drop) notice send claims (2026-09-10 departures spec).

  Adds the claim collection behind `composition/withdrawal_notifications.py`:
  one row per (academy_id, enrollment_id, notice_key) for the family's Drop
  email. The claim itself (`digest_claim.claim_digest_send`) is already safe
  without this index — see 0170/0172 for the same reasoning — the index only
  keeps the collection from growing near-duplicate rows under a stuck or
  retried request.

  No data change and no validator change.

  Production does NOT run migrations on boot (`V2_RUN_MIGRATIONS_ON_BOOT` is
  false there, #629): apply with `run_pending_migrations` by hand after
  deploy.
  """

  from __future__ import annotations

  from motor.motor_asyncio import AsyncIOMotorDatabase

  version = "0173_withdrawal_notice_sends"


  async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
      await db["enrollment_withdrawal_notice_sends"].create_index(
          [("academy_id", 1), ("enrollment_id", 1), ("notice_key", 1)],
          unique=True,
          name="enrollment_withdrawal_notice_sends_key_unique",
      )
  ```
- [ ] Implement, part 6 — `main.py`. Edit `backend/v2/main.py`, right after the existing hold/departures block (after `app.state.admin.return_from_hold = _holds.return_from_hold` and before `app.state.enrollment_holds = _holds`, or immediately after that line — either is fine since order among these three lines doesn't matter), add:
  ```python
      from backend.v2.composition.withdrawal_notifications import compose_withdrawal_notifications

      app.state.admin.withdraw_enrollment.set_notifier(
          compose_withdrawal_notifications(db, settings)
      )
  ```
- [ ] Run it and confirm PASS: `cd backend && .venv/bin/pytest v2/tests/contract/test_withdrawal_notice_send_claim_mongo.py v2/tests/application/test_enrollment_holds.py v2/tests/application/test_withdraw_single_path.py -q`.
- [ ] Run the composition-wiring structural test to confirm `admin.py`'s line budget and cross-context import rules are still satisfied: `cd backend && .venv/bin/pytest v2/tests/structural/ -q`.
- [ ] Run ruff over every touched file: `cd backend && .venv/bin/ruff check v2/composition/hold_notifications.py v2/composition/enrollment_holds.py v2/composition/withdrawal_notice_send_repo.py v2/composition/withdrawal_notifications.py v2/migrations/0173_withdrawal_notice_sends.py v2/main.py`.
- [ ] Commit: `git add backend/v2/composition/hold_notifications.py backend/v2/composition/enrollment_holds.py backend/v2/composition/withdrawal_notice_send_repo.py backend/v2/composition/withdrawal_notifications.py backend/v2/migrations/0173_withdrawal_notice_sends.py backend/v2/main.py backend/v2/tests/contract/test_withdrawal_notice_send_claim_mongo.py backend/v2/contexts/enrollment/application/use_cases/holds.py backend/v2/contexts/enrollment/application/ports.py backend/v2/tests/application/test_enrollment_holds.py backend/v2/tests/fixtures/enrollment_fakes.py` then `git commit -m "feat(enrollment): wire hold_started/hold_returned/dropped notifier adapters\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>"`.

## Task 6: Frontend — API client types for `notify_family`

**Files:**
- Modify: `frontend/lib/api/v2/departure-policy.ts`
- Modify: `frontend/lib/api/admin.ts`
- Modify: `frontend/lib/admin/withdrawal.ts`
- Test: `frontend/lib/admin/withdrawal.test.ts` (new)

**Interfaces:**
- Consumes: `WithdrawEnrollmentRequest` at `frontend/lib/api/admin.ts:227`; `buildWithdrawRequest` at `frontend/lib/admin/withdrawal.ts:42`.
- Produces: `HoldEnrollmentRequest.notify_family`, `ReturnFromHoldRequest.notify_family`, `WithdrawEnrollmentRequest.notify_family`; `buildWithdrawRequest({ ..., notifyFamily })`.

- [ ] Write the failing test. Create `frontend/lib/admin/withdrawal.test.ts`:
  ```ts
  import { describe, expect, it } from "vitest";
  import { buildWithdrawRequest } from "./withdrawal";

  describe("buildWithdrawRequest", () => {
    it("forwards notifyFamily as notify_family", () => {
      const req = buildWithdrawRequest({
        withdrawalDate: "2026-09-10",
        outcome: "refund",
        adminNote: "",
        notifyFamily: true,
      });
      expect(req.notify_family).toBe(true);
    });

    it("defaults notify_family to false when omitted", () => {
      const req = buildWithdrawRequest({
        withdrawalDate: "2026-09-10",
        outcome: "refund",
        adminNote: "",
      });
      expect(req.notify_family).toBe(false);
    });
  });
  ```
- [ ] Run it and confirm the expected failure: `cd frontend && pnpm vitest run lib/admin/withdrawal.test.ts`. Expect `expect(received).toBe(expected)` — `received` is `undefined`.
- [ ] Implement. Edit `frontend/lib/api/v2/departure-policy.ts`:
  - `HoldEnrollmentRequest`: add `notify_family?: boolean;`.
  - `ReturnFromHoldRequest`: add `notify_family?: boolean;`.
  Edit `frontend/lib/api/admin.ts`, `WithdrawEnrollmentRequest` (line 227): add `notify_family?: boolean;`.
  Edit `frontend/lib/admin/withdrawal.ts`, `buildWithdrawRequest`:
  ```ts
  export function buildWithdrawRequest(input: {
    withdrawalDate: string;
    outcome: WithdrawalOutcome;
    adminNote: string;
    notifyFamily?: boolean;
  }): WithdrawEnrollmentRequest {
    const note = input.adminNote.trim();
    return {
      effective_date: input.withdrawalDate,
      outcome: input.outcome,
      reason: note || `Withdrawal ${input.outcome}`,
      notify_family: input.notifyFamily ?? false,
    };
  }
  ```
- [ ] Run it and confirm PASS: `cd frontend && pnpm vitest run lib/admin/withdrawal.test.ts`.
- [ ] Commit: `git add frontend/lib/api/v2/departure-policy.ts frontend/lib/api/admin.ts frontend/lib/admin/withdrawal.ts frontend/lib/admin/withdrawal.test.ts` then `git commit -m "feat(enrollment): notify_family on Hold/Return/Withdraw request types\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>"`.

## Task 7: Frontend — move Transfer/Withdrawal/Remove dialogs, delete Pause dialog, add notify toggle

**Files:**
- Create: `frontend/components/admin/enrollment/transfer-dialog.tsx`
- Create: `frontend/components/admin/enrollment/withdrawal-credit-dialog.tsx`
- Create: `frontend/components/admin/enrollment/remove-dialog.tsx`
- Modify: `frontend/app/(admin)/admin/sessions/[id]/dialogs.tsx`

**Interfaces:**
- Consumes: `RallyModal`, `Field`, `DialogActions`, `DialogError` from `@/components/ds/dialog-chrome`; `dateInputValueFromOffset`, `formatCents`, `formatShortDateTime`, `inputClass`, `todayDateInput` from `@/app/(admin)/admin/sessions/[id]/format`; `useIsOwner` from `@/components/admin/owner-context`; `withdrawalOutcomeOptions`/`defaultWithdrawalOutcome`/`buildWithdrawRequest`/`withdrawErrorMessage` from `@/lib/admin/withdrawal`.
- Produces: `TransferEnrollmentDialog`, `WithdrawalCreditDialog` (now with a notify toggle, default checked), `RemoveEnrollmentDialog` — same prop shapes as today, importable from their new paths.

- [ ] Create `frontend/components/admin/enrollment/transfer-dialog.tsx` — move `TransferEnrollmentDialog` and its helper `RallySessionPicker` verbatim out of `frontend/app/(admin)/admin/sessions/[id]/dialogs.tsx` (lines 316-522 as read in this plan's research), changing only the imports at the top of the new file to:
  ```tsx
  "use client";

  import { useState } from "react";
  import { useMutation, useQuery } from "@tanstack/react-query";

  import {
    listAdminSessions,
    transferEnrollment,
    type AdminEnrollmentView,
    type AdminSessionView,
  } from "@/lib/api/admin";
  import { Button } from "@/components/ds/button";
  import { DialogActions, Field, RallyModal as RallyDialog, DialogError } from "@/components/ds/dialog-chrome";
  import {
    dateInputValueFromOffset,
    inputClass,
    todayDateInput,
  } from "@/app/(admin)/admin/sessions/[id]/format";
  ```
  (Drop `dateInputValueFromOffset` from that import list if the moved code does not use it — `TransferEnrollmentDialog` itself only uses `todayDateInput` and `inputClass`; verify against the body being moved and keep only what is referenced, to avoid an unused-import lint failure.)
  The component bodies (`TransferEnrollmentDialog`, `RallySessionPicker`) are copied unchanged.
- [ ] Create `frontend/components/admin/enrollment/remove-dialog.tsx` — move `RemoveEnrollmentDialog` verbatim (lines 686-768), with imports trimmed to:
  ```tsx
  "use client";

  import { useState } from "react";
  import { useMutation } from "@tanstack/react-query";

  import { deleteEnrollment, type AdminEnrollmentView } from "@/lib/api/admin";
  import { Button } from "@/components/ds/button";
  import { DialogActions, DialogError, Field, RallyModal as RallyDialog } from "@/components/ds/dialog-chrome";
  import { inputClass, todayDateInput } from "@/app/(admin)/admin/sessions/[id]/format";
  ```
- [ ] Create `frontend/components/admin/enrollment/withdrawal-credit-dialog.tsx` — move `WithdrawalCreditDialog` (lines 528-684) with imports trimmed to:
  ```tsx
  "use client";

  import { useState } from "react";
  import { useMutation } from "@tanstack/react-query";
  import * as Dialog from "@radix-ui/react-dialog";

  import {
    previewWithdrawalCredit,
    withdrawEnrollment,
    type AdminEnrollmentView,
  } from "@/lib/api/admin";
  import {
    buildWithdrawRequest,
    defaultWithdrawalOutcome,
    withdrawErrorMessage,
    withdrawalOutcomeOptions,
    type WithdrawalOutcome,
  } from "@/lib/admin/withdrawal";
  import type { ApiError } from "@/lib/api/client";
  import { useIsOwner } from "@/components/admin/owner-context";
  import { Field } from "@/components/ds/dialog-chrome";
  import { inputClass, todayDateInput } from "@/app/(admin)/admin/sessions/[id]/format";
  ```
  Then add the notify toggle: introduce `const [notifyFamily, setNotifyFamily] = useState(true);` (default ON per spec §4.3) alongside the existing `adminNote` state, forward it into `buildWithdrawRequest({ withdrawalDate, outcome, adminNote, notifyFamily })` inside `approveMutation`'s `mutationFn`, reset it to `true` in `onSuccess` alongside the other resets, and render the toggle in the form body right before the "Admin note" `Field` (matching the existing "Email the families and the coach" pattern at `frontend/app/(admin)/admin/sessions/[id]/SessionEditing.tsx:299-306`):
  ```tsx
  <label className="flex items-center gap-2 text-sm text-neutral-600 dark:text-neutral-400">
    <input
      type="checkbox"
      checked={notifyFamily}
      onChange={(event) => setNotifyFamily(event.target.checked)}
    />
    Email the family
  </label>
  ```
- [ ] Edit `frontend/app/(admin)/admin/sessions/[id]/dialogs.tsx`: delete the bodies of `PauseEnrollmentDialog`, `TransferEnrollmentDialog`, `RallySessionPicker`, `WithdrawalCreditDialog`, `RemoveEnrollmentDialog` (now living in the three new files above; `PauseEnrollmentDialog` is not moved anywhere — it is retired). Remove now-unused imports from the top of the file: `pauseEnrollment`, `previewWithdrawalCredit`, `transferEnrollment`, `withdrawEnrollment`, `deleteEnrollment`, `AdminEnrollmentQuote` (check — still used by `AddToRosterDialog`'s `quoteQuery`, keep it), `AdminSessionView` (still used? check — `AddToRosterDialog` doesn't use it; `RallySessionPicker` did, now moved — remove), `buildWithdrawRequest`/`defaultWithdrawalOutcome`/`withdrawErrorMessage`/`withdrawalOutcomeOptions`/`WithdrawalOutcome` (moved, remove), `ApiError` (moved, remove), `useIsOwner` (moved — check if `AddToRosterDialog`/`AddToRosterDialog`'s siblings still need it; they don't, remove), `Dialog` from `@radix-ui/react-dialog` (only `WithdrawalCreditDialog` used it — remove), `dateInputValueFromOffset`/`formatShortDateTime` (check what `AddToRosterDialog`, `CoachSelect`, `DaySelect` still use — keep `formatCents`, `formatShortDateTime`, `inputClass`, `todayDateInput` only if still referenced by the remaining `AddToRosterDialog`; `AddToRosterDialog` uses `formatCents`, `formatShortDateTime`, `inputClass`, `todayDateInput` is not used by it so drop it from this file's import if nothing else in the file needs it — verify by reading the trimmed file after deletion, not by guessing). What remains in this file: `AddToRosterDialog`, `RallySessionPicker` is GONE (moved) so remove any leftover reference, `StudentSelect`, `CoachSelect`, `DaySelect`, and the `DAYS_OF_WEEK` constant.
- [ ] Run the frontend typecheck to catch every remaining call site that still imports from the old paths (expected to fail — fixed in Tasks 8-9): `cd frontend && pnpm typecheck 2>&1 | tee /tmp/typecheck-after-move.txt`. Confirm the failures are exactly in `RosterPanel.tsx`, `page.tsx`, and `SessionsPanel.tsx` (the files Tasks 8-9 touch) and nowhere else — if any other file breaks, its import needs updating here too.
- [ ] Run the moved dialogs' existing coverage, if any (there is no dedicated dialog test file today — this step is a smoke check via lint, not a test run): `cd frontend && pnpm lint --filter dialogs 2>/dev/null || pnpm eslint frontend/components/admin/enrollment/transfer-dialog.tsx frontend/components/admin/enrollment/remove-dialog.tsx frontend/components/admin/enrollment/withdrawal-credit-dialog.tsx frontend/app/\(admin\)/admin/sessions/\[id\]/dialogs.tsx`.
- [ ] Commit: `git add frontend/components/admin/enrollment/transfer-dialog.tsx frontend/components/admin/enrollment/remove-dialog.tsx frontend/components/admin/enrollment/withdrawal-credit-dialog.tsx "frontend/app/(admin)/admin/sessions/[id]/dialogs.tsx"` then `git commit -m "refactor(enrollment): move Transfer/Withdrawal/Remove dialogs into components/admin/enrollment, add notify toggle to Drop\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>"`.

## Task 8: Frontend — Hold and Return dialogs

**Files:**
- Create: `frontend/components/admin/enrollment/hold-dialog.tsx`
- Create: `frontend/components/admin/enrollment/return-dialog.tsx`

**Interfaces:**
- Consumes: `holdEnrollment`, `returnFromHold`, `getDeparturePolicy` from `@/lib/api/v2/departure-policy`; `AdminEnrollmentView` from `@/lib/api/admin`.
- Produces: `HoldEnrollmentDialog({ enrollment, onClose, onHeld })`, `ReturnFromHoldDialog({ enrollment, onClose, onReturned })`.

- [ ] Create `frontend/components/admin/enrollment/hold-dialog.tsx`:
  ```tsx
  "use client";

  import { useEffect, useState } from "react";
  import { useMutation, useQuery } from "@tanstack/react-query";

  import {
    getDeparturePolicy,
    holdEnrollment,
  } from "@/lib/api/v2/departure-policy";
  import type { AdminEnrollmentView } from "@/lib/api/admin";
  import { queryKeys } from "@/lib/query/keys";
  import { Button } from "@/components/ds/button";
  import { DialogActions, DialogError, Field, RallyModal as RallyDialog } from "@/components/ds/dialog-chrome";
  import { dateInputValueFromOffset } from "@/app/(admin)/admin/sessions/[id]/format";

  /**
   * Hold dialog (2026-09-10 departures-from-student-page spec §4.1). Keeps
   * the seat, pauses billing, and requires a return date bounded by the
   * academy's `EnrollmentDeparturePolicyView.max_hold_days`.
   */
  export function HoldEnrollmentDialog({
    enrollment,
    onClose,
    onHeld,
  }: {
    enrollment: AdminEnrollmentView | null;
    onClose: () => void;
    onHeld: () => void;
  }) {
    // `queryKeys.admin.departurePolicy()` — NOT a hand-rolled key. The
    // student page already fetches this policy under that exact key
    // (`app/(admin)/admin/students/[studentId]/page.tsx:62`), so reusing it
    // hits cache instead of firing a second request per dialog open.
    const policyQuery = useQuery({
      queryKey: queryKeys.admin.departurePolicy(),
      queryFn: getDeparturePolicy,
      enabled: enrollment !== null,
      staleTime: 60_000,
    });
    const maxHoldDays = policyQuery.data?.max_hold_days ?? 60;
    const [returnOn, setReturnOn] = useState(dateInputValueFromOffset(30));
    const [reason, setReason] = useState("");
    const [notifyFamily, setNotifyFamily] = useState(false);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
      if (enrollment) {
        setReturnOn(dateInputValueFromOffset(30));
        setReason("");
        setNotifyFamily(false);
        setError(null);
      }
    }, [enrollment]);

    const mutation = useMutation({
      mutationFn: () =>
        holdEnrollment(enrollment!.enrollment_id, {
          return_on: returnOn,
          reason: reason || undefined,
          notify_family: notifyFamily,
        }),
      onSuccess: () => {
        onHeld();
      },
      onError: (err: Error) => setError(err.message ?? "Could not place this enrollment on hold."),
    });

    return (
      <RallyDialog
        open={enrollment !== null}
        onOpenChange={(open) => !open && onClose()}
        title="Hold enrollment"
        description={enrollment ? `Hold ${enrollment.full_name}'s seat without releasing it.` : ""}
        overline="Lifecycle"
      >
        {error && <DialogError message={error} />}
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            mutation.mutate();
          }}
        >
          <Field label="Return date" required>
            {/* min/max mirror HoldEnrollment.execute's own window check
                (`return_on <= today || return_on > today + max_hold_days`
                raises HoldWindowExceeded) so the cap in spec §4.1 is
                enforced, not merely described in the helper text. */}
            <input
              type="date"
              required
              min={dateInputValueFromOffset(1)}
              max={dateInputValueFromOffset(maxHoldDays)}
              value={returnOn}
              onChange={(event) => setReturnOn(event.target.value)}
              className="min-h-touch w-full rounded-md border border-rally-line bg-white px-3 py-2 text-sm text-rally-ink focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30"
            />
            <p className="mt-1 text-xs text-rally-subtle">
              Up to {maxHoldDays} days from today.
            </p>
          </Field>
          <Field label="Reason">
            <textarea
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              rows={3}
              className="w-full rounded-md border border-rally-line bg-white px-3 py-2 text-sm text-rally-ink focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30"
            />
          </Field>
          <p className="text-xs text-rally-subtle">
            Seat is kept. Billing pauses from the next invoice and resumes on the return date.
            If the class fills, the longest-held family is asked to return or drop first.
          </p>
          <label className="flex items-center gap-2 text-sm text-rally-subtle">
            <input
              type="checkbox"
              checked={notifyFamily}
              onChange={(event) => setNotifyFamily(event.target.checked)}
            />
            Email the family
          </label>
          <DialogActions>
            <Button variant="secondary" size="sm" type="button" onClick={onClose}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" type="submit" disabled={!returnOn || mutation.isPending}>
              {mutation.isPending ? "Placing on hold…" : "Hold"}
            </Button>
          </DialogActions>
        </form>
      </RallyDialog>
    );
  }
  ```
- [ ] Create `frontend/components/admin/enrollment/return-dialog.tsx`:
  ```tsx
  "use client";

  import { useEffect, useState } from "react";
  import { useMutation } from "@tanstack/react-query";

  import { returnFromHold } from "@/lib/api/v2/departure-policy";
  import type { AdminEnrollmentView } from "@/lib/api/admin";
  import { Button } from "@/components/ds/button";
  import { DialogActions, DialogError, Field, RallyModal as RallyDialog } from "@/components/ds/dialog-chrome";

  /**
   * Return dialog (2026-09-10 departures-from-student-page spec §4.2).
   * Billing resumes with the next invoice; the seat was never released so
   * there is nothing to reserve.
   */
  export function ReturnFromHoldDialog({
    enrollment,
    onClose,
    onReturned,
  }: {
    enrollment: AdminEnrollmentView | null;
    onClose: () => void;
    onReturned: () => void;
  }) {
    const [reason, setReason] = useState("");
    const [notifyFamily, setNotifyFamily] = useState(false);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
      if (enrollment) {
        setReason("");
        setNotifyFamily(false);
        setError(null);
      }
    }, [enrollment]);

    const mutation = useMutation({
      mutationFn: () =>
        returnFromHold(enrollment!.enrollment_id, {
          reason: reason || undefined,
          notify_family: notifyFamily,
        }),
      onSuccess: () => {
        onReturned();
      },
      onError: (err: Error) => setError(err.message ?? "Could not return this enrollment from hold."),
    });

    return (
      <RallyDialog
        open={enrollment !== null}
        onOpenChange={(open) => !open && onClose()}
        title="Return from hold"
        description={enrollment ? `Return ${enrollment.full_name} from hold to active.` : ""}
        overline="Lifecycle"
      >
        {error && <DialogError message={error} />}
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            mutation.mutate();
          }}
        >
          <Field label="Reason">
            <textarea
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              rows={3}
              className="w-full rounded-md border border-rally-line bg-white px-3 py-2 text-sm text-rally-ink focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30"
            />
          </Field>
          <p className="text-xs text-rally-subtle">Billing resumes with the next invoice.</p>
          <label className="flex items-center gap-2 text-sm text-rally-subtle">
            <input
              type="checkbox"
              checked={notifyFamily}
              onChange={(event) => setNotifyFamily(event.target.checked)}
            />
            Email the family
          </label>
          <DialogActions>
            <Button variant="secondary" size="sm" type="button" onClick={onClose}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? "Returning…" : "Return"}
            </Button>
          </DialogActions>
        </form>
      </RallyDialog>
    );
  }
  ```
- [ ] Run typecheck for these two new files in isolation (full-project typecheck still fails until Task 9 finishes wiring — that is expected): `cd frontend && pnpm tsc --noEmit -p . 2>&1 | grep -E "hold-dialog|return-dialog"` — expect no output (no errors attributable to these two files).
- [ ] Commit: `git add frontend/components/admin/enrollment/hold-dialog.tsx frontend/components/admin/enrollment/return-dialog.tsx` then `git commit -m "feat(enrollment): add Hold and Return dialogs\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>"`.

## Task 8b: Backend — held rows return to the roster, and the roster learns the parent's name

> **Tracked as issue #714.** Can also ship on its own, ahead of this plan.
>
> **This task fixes a live production defect found while planning (2026-09-10).**
> `mark_held_if_active` CAS-transitions `active` → `held`
> (`backend/v2/contexts/enrollment/infrastructure/mongo_enrollment_writer.py:99-102`),
> but the roster read filters `status: {"$in": ["active", "paused"]}`
> (`backend/v2/composition/admin.py:2568`). **A held student therefore vanishes
> from the class roster entirely** — the same dead end #641 fixed for `paused`,
> reintroduced by #697 for `held`. `RosterPanel`'s `ENROLL_CHIP` already has
> `held` and `reclaim_pending` → "ON HOLD" entries (`RosterPanel.tsx:36-37`)
> that can never render today. Tasks 9-10 cannot offer Return from the roster
> until this is fixed, so this task comes first.
>
> It also carries the **owner decision of 2026-09-10**: the departure dialogs
> must name who gets the email, and `AdminEnrollmentView` has `parent_id` but no
> parent name (`backend/v2/interfaces/admin/views.py:561-583`). Both changes land
> in the same read, so they are one task.

**Files:**
- Modify: `backend/v2/composition/admin.py:2564-2568` (status filter) and the row-building loop that follows it (parent name)
- Modify: `backend/v2/tests/structural/test_admin_roster_policy.py:26` (it pins the old filter as a literal string and goes red otherwise)
- Modify: `backend/v2/interfaces/admin/views.py:561-583` (`AdminEnrollmentView.parent_name`)
- Modify: `frontend/lib/api/admin.ts` (`AdminEnrollmentView` TS type — add `parent_name: string | null`)
- Test: `backend/v2/tests/integration/test_admin_roster_read.py` (create if absent — check `ls backend/v2/tests/integration/ | grep -i roster` first and extend the existing file if one is there)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `AdminEnrollmentView.parent_name: str | None` on `GET /admin/sessions/{id}/enrollments`, and held/reclaim_pending rows in that response. Task 9 reads `enrollment.parent_name` for the dialogs' "who gets emailed" line and relies on held rows being present for Return.

- [ ] **Step 1: Write the failing test.** Add to the roster read test file:

```python
@pytest.mark.asyncio
async def test_roster_includes_held_and_reclaim_pending_rows(admin_use_cases, seeded_session):
    """#697 introduced held/reclaim_pending; the roster filter never learned them,
    so holding a student made them disappear from the class (regression of #641)."""
    rows = await admin_use_cases.list_admin_enrollments_for_session(seeded_session.session_id)
    statuses = {r["status"] for r in rows}
    assert "held" in statuses
    assert "reclaim_pending" in statuses


@pytest.mark.asyncio
async def test_roster_rows_carry_the_parent_name(admin_use_cases, seeded_session):
    rows = await admin_use_cases.list_admin_enrollments_for_session(seeded_session.session_id)
    assert all("parent_name" in r for r in rows)
    assert any(r["parent_name"] for r in rows)
```

  Seed the fixture with four enrollments in one session — `active`, `paused`, `held`, `reclaim_pending` — each on a student whose `parent_id` points at a seeded parent user with a `display_name`. Follow the seeding style of the existing integration tests in that directory; do not invent a fixture helper name.

- [ ] **Step 2: Run it and confirm it fails.**

Run: `cd backend && pytest v2/tests/integration/test_admin_roster_read.py -v`
Expected: both tests FAIL — the first with `assert 'held' in {'active', 'paused'}`, the second with `KeyError: 'parent_name'` or an all-missing assertion.

- [ ] **Step 3: Widen the status filter.** In `backend/v2/composition/admin.py`, replace the query at line 2568:

```python
        cursor = enrollments_r._find_many(
            # Paused rows stay on the roster (PAUSED chip + Return). Hiding them
            # left a student who blocked "Add to roster" invisible everywhere
            # (#641). held / reclaim_pending are the #697 successors of paused
            # and must stay visible for the same reason — a held child still
            # holds a seat, and Return is only reachable from a visible row.
            {
                "session_id": session_id,
                "status": {"$in": ["active", "paused", "held", "reclaim_pending"]},
            },
            sort=[("created_at", 1), ("enrollment_id", 1)],
        )
```

- [ ] **Step 3b: Update the structural test that pins the old filter.** `backend/v2/tests/structural/test_admin_roster_policy.py:26` asserts the buggy query as a literal string, so Step 3 turns it red. It was written by #641 to lock in the paused fix and was never updated when #697 added `held`. Replace that one assertion:

```python
    assert (
        '"status": {"$in": ["active", "paused", "held", "reclaim_pending"]}' in source
    )
```

  and extend the docstring above it to say why held and reclaim_pending belong: they hold seats (`SEAT_HOLDING`), so hiding them repeats the #641 dead end with an invisible student blocking add-to-roster.

  **Do NOT touch `test_admin_session_seat_counts_stay_active_only` in the same file.** It asserts `enrolled_count` counts `active` only and that `"paused" not in window` — still correct: this task changes visibility, never seat arithmetic.

- [ ] **Step 4: Add the parent name.** The loop already builds `student_detail_by_id` from the `students` collection, and each student doc carries `parent_id`. After that dict is built and before the `for e in active:` loop, batch-load the parents (one query, never per row):

```python
        parent_ids = {
            str(doc.get("parent_id"))
            for doc in student_detail_by_id.values()
            if doc.get("parent_id")
        }
        parent_name_by_id: dict[str, str] = {}
        if parent_ids:
            async for parent_doc in db["users"].find(
                {"academy_id": academy_id, "user_id": {"$in": list(parent_ids)}},
                {"user_id": 1, "display_name": 1},
            ):
                name = str(parent_doc.get("display_name") or "").strip()
                if name:
                    parent_name_by_id[str(parent_doc.get("user_id"))] = name
```

  Then inside `for e in active:`, alongside the existing `full_name` line, add:

```python
            parent_name = parent_name_by_id.get(str(student_doc.get("parent_id") or ""))
```

  and include `"parent_name": parent_name,` in the dict appended to `out`.

- [ ] **Step 5: Add the field to the response model.** In `backend/v2/interfaces/admin/views.py`, add to `AdminEnrollmentView` immediately after `parent_id: str`:

```python
    #: Display name of the parent on file, for the departure dialogs' "who gets
    #: emailed" line. None when the parent has no display_name set.
    parent_name: str | None = None
```

  It defaults to `None`, so `add_to_roster`'s hand-built `AdminEnrollmentView(...)` at `sessions_routes.py:525+` keeps compiling untouched.

- [ ] **Step 6: Mirror the type on the frontend.** In `frontend/lib/api/admin.ts`, add `parent_name: string | null;` to the `AdminEnrollmentView` interface, directly after `parent_id`.

- [ ] **Step 7: Run the tests and the roster's existing coverage.**

Run: `cd backend && pytest v2/tests/integration/test_admin_roster_read.py -v && pytest v2/tests/structural/test_admin_roster_policy.py -v && pytest v2/tests -k "roster" -q`
Expected: the two new tests PASS; `test_admin_session_roster_query_lists_paused_enrollments` PASSES with its updated literal; `test_admin_session_seat_counts_stay_active_only` PASSES untouched; no other roster test regresses. Then `cd frontend && pnpm typecheck` — expected PASS.

- [ ] **Step 8: Check the line cap.**

Run: `wc -l backend/v2/composition/admin.py`
Expected: under 4500 (it was 4318 before this task; this adds roughly 15 lines). If it is over, stop and extract rather than continuing.

- [ ] **Step 9: Commit.**

```bash
git add backend/v2/composition/admin.py backend/v2/interfaces/admin/views.py frontend/lib/api/admin.ts backend/v2/tests/integration/test_admin_roster_read.py backend/v2/tests/structural/test_admin_roster_policy.py
git commit -m "fix(admin): held students disappeared from the class roster, and name the parent on roster rows

mark_held_if_active moves an enrollment to 'held', but the roster read still
filtered on active/paused only — so holding a child removed them from the
class, the #641 dead end reintroduced by #697. Adds held and reclaim_pending
back, and carries the parent's display name on each row so the departure
dialogs can say who will be emailed.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 9: Frontend — wire the roster and student-page surfaces

**Files:**
- Modify: `frontend/app/(admin)/admin/sessions/[id]/RosterPanel.tsx`
- Modify: `frontend/app/(admin)/admin/sessions/[id]/page.tsx`
- Modify: `frontend/app/(admin)/admin/students/[studentId]/SessionsPanel.tsx`

**Interfaces:**
- Consumes: `departureActionsFor` from `@/components/admin/enrollment/departure-actions`; `HoldEnrollmentDialog`, `ReturnFromHoldDialog` from Task 8; `TransferEnrollmentDialog`, `WithdrawalCreditDialog`, `RemoveEnrollmentDialog` from Task 7's new paths.
- Produces: both the roster and the student Sessions panel offering Hold/Return/Drop/Delete alongside Transfer, sharing the same dialogs.

- [ ] Edit `frontend/app/(admin)/admin/sessions/[id]/RosterPanel.tsx`:
  - Replace the import `import { DepartureActions, type DepartureAction } from "@/components/admin/enrollment/departure-actions";` with:
    ```ts
    import {
      DepartureActions,
      departureActionsFor,
      type DepartureAction,
    } from "@/components/admin/enrollment/departure-actions";
    ```
  - Delete the `rosterActionsFor` function **and its doc comment (lines 279-295)** entirely — the comment is the "#697 replaces this with a list the backend returns" block directly above it. `departureActionsFor` takes `status: string`; `rosterActionsFor` took `status: EnrollmentStatus`, which is a string union, so the call site needs no cast.
  - In `RosterTable`'s props, replace `onPause`/`onResume` with `onHold`/`onReturn`:
    ```ts
      onHold: (enrollment: AdminEnrollmentView) => void;
      onReturn: (enrollment: AdminEnrollmentView) => void;
    ```
    (Note: `onReturn` takes the full `AdminEnrollmentView`, not just an id — `returnFromHold` needs `enrollment.enrollment_id` and the dialog needs the full enrollment for its title, matching the `onWithdraw`/`onDelete` shape already used here, unlike the old `onResume: (id: string) => void`.)
  - Update the destructured props list (`onPathwayLevelChange, onDelete, onPause, onResume, onTransfer, onWithdraw` → `onPathwayLevelChange, onDelete, onHold, onReturn, onTransfer, onWithdraw`).
  - In the `<DepartureActions .../>` call: replace `actions={rosterActionsFor(e.status)}` with `actions={departureActionsFor(e.status)}`, and in the `onAction` handler's `dispatchRosterAction(...)` call, replace the `handlers` object's `onPause, onResume,` with `onHold, onReturn,`.
  - Rewrite `dispatchRosterAction`:
    ```ts
    function dispatchRosterAction(
      action: DepartureAction,
      _enrollmentId: string,
      enrollment: AdminEnrollmentView,
      handlers: {
        onDelete: (enrollment: AdminEnrollmentView) => void;
        onHold: (enrollment: AdminEnrollmentView) => void;
        onReturn: (enrollment: AdminEnrollmentView) => void;
        onTransfer: (enrollment: AdminEnrollmentView) => void;
        onWithdraw: (enrollment: AdminEnrollmentView) => void;
      },
    ): void {
      switch (action) {
        case "hold":
          handlers.onHold(enrollment);
          break;
        case "return":
          handlers.onReturn(enrollment);
          break;
        case "transfer":
          handlers.onTransfer(enrollment);
          break;
        case "drop":
          handlers.onWithdraw(enrollment);
          break;
        case "delete":
          handlers.onDelete(enrollment);
          break;
        default:
          // stop_all_classes is not offered on this roster row (#698).
          break;
      }
    }
    ```
- [ ] Edit `frontend/app/(admin)/admin/sessions/[id]/page.tsx`:
  - Import change: replace
    `import { AddToRosterDialog, PauseEnrollmentDialog, RemoveEnrollmentDialog, TransferEnrollmentDialog, WithdrawalCreditDialog } from "./dialogs";`
    with:
    ```ts
    import { AddToRosterDialog } from "./dialogs";
    import { HoldEnrollmentDialog } from "@/components/admin/enrollment/hold-dialog";
    import { ReturnFromHoldDialog } from "@/components/admin/enrollment/return-dialog";
    import { RemoveEnrollmentDialog } from "@/components/admin/enrollment/remove-dialog";
    import { TransferEnrollmentDialog } from "@/components/admin/enrollment/transfer-dialog";
    import { WithdrawalCreditDialog } from "@/components/admin/enrollment/withdrawal-credit-dialog";
    ```
  - Remove `resumeEnrollment` from the `@/lib/api/admin` import (line 24) — it is no longer called from this file (Return now calls `returnFromHold`, not `resumeEnrollment`).
  - Replace the `pauseTarget` state declaration (line 80) with `holdTarget`/`returnTarget`:
    ```ts
    const [holdTarget, setHoldTarget] = useState<AdminEnrollmentView | null>(null);
    const [returnTarget, setReturnTarget] = useState<AdminEnrollmentView | null>(null);
    ```
  - Delete the `resumeMutation` block (lines 148-154) entirely.
  - In the `<RosterTable .../>` call, replace:
    ```ts
    onPause={(enrollment) => setPauseTarget(enrollment)}
    onResume={(id) => resumeMutation.mutate(id)}
    ```
    with:
    ```ts
    onHold={(enrollment) => setHoldTarget(enrollment)}
    onReturn={(enrollment) => setReturnTarget(enrollment)}
    ```
  - Replace the `<PauseEnrollmentDialog .../>` block (lines 563-571) with:
    ```tsx
    <HoldEnrollmentDialog
      enrollment={holdTarget}
      onClose={() => setHoldTarget(null)}
      onHeld={() => {
        setHoldTarget(null);
        void queryClient.invalidateQueries({ queryKey: queryKeys.admin.enrollments(sessionId) });
        void queryClient.invalidateQueries({ queryKey: queryKeys.admin.sessions("upcoming") });
      }}
    />
    <ReturnFromHoldDialog
      enrollment={returnTarget}
      onClose={() => setReturnTarget(null)}
      onReturned={() => {
        setReturnTarget(null);
        void queryClient.invalidateQueries({ queryKey: queryKeys.admin.enrollments(sessionId) });
        void queryClient.invalidateQueries({ queryKey: queryKeys.admin.waitlist(sessionId) });
        void queryClient.invalidateQueries({ queryKey: queryKeys.admin.sessions("upcoming") });
      }}
    />
    ```
- [ ] Edit `frontend/app/(admin)/admin/students/[studentId]/SessionsPanel.tsx`:
  - Add imports:
    ```ts
    import {
      DepartureActions,
      departureActionsFor,
    } from "@/components/admin/enrollment/departure-actions";
    import { HoldEnrollmentDialog } from "@/components/admin/enrollment/hold-dialog";
    import { ReturnFromHoldDialog } from "@/components/admin/enrollment/return-dialog";
    import { WithdrawalCreditDialog } from "@/components/admin/enrollment/withdrawal-credit-dialog";
    import { RemoveEnrollmentDialog } from "@/components/admin/enrollment/remove-dialog";
    import type { AdminEnrollmentView } from "@/lib/api/admin";
    ```
    (Replace the existing `import { DepartureActions } from "@/components/admin/enrollment/departure-actions";` line at line 27 rather than adding a duplicate.)
  - Add `studentName: string;` to `SessionsPanel`'s props type and destructure it (the component signature is at line 55; props today are `sessions`, `pastEnrollments`, `parentId`, `studentId`, `queryClient`).
  - Add state, alongside the existing `moving`/`billingOverride` state (~line 72):
    ```ts
    const [holdTarget, setHoldTarget] = useState<AdminStudentSessionSummary | null>(null);
    const [returnTarget, setReturnTarget] = useState<AdminStudentSessionSummary | null>(null);
    const [dropTarget, setDropTarget] = useState<AdminStudentSessionSummary | null>(null);
    const [removeTarget, setRemoveTarget] = useState<AdminStudentSessionSummary | null>(null);
    ```
  - `AdminEnrollmentView` and `AdminStudentSessionSummary` are different types (the dialogs expect `AdminEnrollmentView | null`, but this panel's rows are `AdminStudentSessionSummary`). Add a small adapter right above the `return (` in `SessionsPanel`. **Verified against the real bodies**: `TransferEnrollmentDialog`, `WithdrawalCreditDialog` and `RemoveEnrollmentDialog` in `dialogs.tsx` read only `enrollment!.enrollment_id` and `enrollment.full_name`; Tasks 7-8's `HoldEnrollmentDialog`/`ReturnFromHoldDialog` do the same. The `as` cast below is therefore a deliberate narrowing, not a guess — if a dialog ever reads a third field this cast becomes a runtime `undefined`, so keep the cast in ONE place and re-check it whenever a dialog's body changes:
    ```ts
    const toEnrollmentView = (
      row: AdminStudentSessionSummary,
      fullName: string,
    ): AdminEnrollmentView =>
      ({ enrollment_id: row.enrollment_id, full_name: fullName } as AdminEnrollmentView);
    ```
    Use `toEnrollmentView(row, studentName)` at each of the four new dialog call sites below.
  - Replace the `<DepartureActions .../>` block at lines 333-348 (currently `actions={["transfer"]}`, `layout="inline"`, `studentName={session.session_title}`, single `onAction` that always opens Move). Note `studentName` changes from the **session title** to the **student's name** — that is the point of threading the prop, and it is what makes the overflow trigger's `aria-label` read "More actions for &lt;child&gt;", matching the roster's existing convention that `e2e/specs/admin-enrollment-withdraw.spec.ts:152` already asserts on:
    ```tsx
    <DepartureActions
      enrollmentId={session.enrollment_id}
      studentName={studentName}
      status={session.status}
      layout="inline"
      isOwner={isOwner}
      actions={departureActionsFor(session.status)}
      onAction={(action) => {
        switch (action) {
          case "transfer":
            setMoving(session);
            setTargetSessionId("");
            setReason("");
            setEffectiveDate(new Date().toISOString().slice(0, 10));
            break;
          case "hold":
            setHoldTarget(session);
            break;
          case "return":
            setReturnTarget(session);
            break;
          case "drop":
            setDropTarget(session);
            break;
          case "delete":
            setRemoveTarget(session);
            break;
          default:
            // stop_all_classes is never in departureActionsFor's output.
            break;
        }
      }}
    />
    ```
    (`delete` is wired here, not left a no-op: spec §3's table lists `delete` for `active`/`held`/`paused` on this surface too, and `resolveDepartureActions` renders `delete` *disabled with a hint* for a non-owner rather than hiding it — so an owner clicking it must open the same `RemoveEnrollmentDialog` the roster opens, which Task 7 already moved to a shared path.)
  - Mount the four dialogs at the end of the returned JSX fragment, alongside the existing `moving`/`discounting`/`billingOverride` custom modals:
    ```tsx
    <HoldEnrollmentDialog
      enrollment={holdTarget ? toEnrollmentView(holdTarget, studentName) : null}
      onClose={() => setHoldTarget(null)}
      onHeld={() => {
        setHoldTarget(null);
        void queryClient.invalidateQueries({ queryKey: queryKeys.admin.studentDetail(studentId) });
      }}
    />
    <ReturnFromHoldDialog
      enrollment={returnTarget ? toEnrollmentView(returnTarget, studentName) : null}
      onClose={() => setReturnTarget(null)}
      onReturned={() => {
        setReturnTarget(null);
        void queryClient.invalidateQueries({ queryKey: queryKeys.admin.studentDetail(studentId) });
      }}
    />
    <WithdrawalCreditDialog
      enrollment={dropTarget ? toEnrollmentView(dropTarget, studentName) : null}
      onClose={() => setDropTarget(null)}
      onApproved={() => {
        setDropTarget(null);
        void queryClient.invalidateQueries({ queryKey: queryKeys.admin.studentDetail(studentId) });
      }}
    />
    <RemoveEnrollmentDialog
      enrollment={removeTarget ? toEnrollmentView(removeTarget, studentName) : null}
      onClose={() => setRemoveTarget(null)}
      onRemoved={() => {
        setRemoveTarget(null);
        void queryClient.invalidateQueries({ queryKey: queryKeys.admin.studentDetail(studentId) });
      }}
    />
    ```
  - Wire `studentName` through: edit `frontend/app/(admin)/admin/students/[studentId]/page.tsx` and add `studentName={student.full_name}` to the `<SessionsPanel …>` mount at line 217. (`student.full_name` is confirmed present — the sibling header at line 143 already passes `studentName={student.full_name}`.)
- [ ] Run the full frontend typecheck and confirm it is clean: `cd frontend && pnpm typecheck`.
- [ ] Run lint: `cd frontend && pnpm lint`.
- [ ] Run the existing unit suites that cover these files' pure logic (no new pure-logic files were touched directly in this task, but re-run the ones from Tasks 1/2/6 plus the student page's own `session-rows.test.ts` as a regression check): `cd frontend && pnpm vitest run components/admin/enrollment/departure-actions.test.tsx components/ds/menu.test.tsx lib/admin/withdrawal.test.ts "app/(admin)/admin/students/[studentId]/session-rows.test.ts"`.
- [ ] Commit: `git add frontend/app/"(admin)"/admin/sessions/"[id]"/RosterPanel.tsx frontend/app/"(admin)"/admin/sessions/"[id]"/page.tsx frontend/app/"(admin)"/admin/students/"[studentId]"/SessionsPanel.tsx frontend/app/"(admin)"/admin/students/"[studentId]"/page.tsx` (adjust the shell-quoting for the parenthesized route-group directories to whatever this shell needs — e.g. `git add -A -- 'frontend/app/(admin)/admin/sessions/[id]/RosterPanel.tsx' 'frontend/app/(admin)/admin/sessions/[id]/page.tsx' 'frontend/app/(admin)/admin/students/[studentId]/SessionsPanel.tsx' 'frontend/app/(admin)/admin/students/[studentId]/page.tsx'`) then `git commit -m "feat(enrollment): wire Hold/Return/Drop/Delete into the roster and student Sessions panel\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>"`.

## Task 10: e2e — Hold/Return/Drop from the student page

**Files:**
- Modify: `frontend/e2e/specs/admin-enrollment-withdraw.spec.ts`
- Test: the spec file itself (Playwright)

**Interfaces:**
- Consumes: the stubbing helpers already in the spec (`stubAdminShell`, `stubSessionDetail`) as a pattern to copy for a student-page stub; `DepartureActions`' `data-testid={`departure-actions-${enrollmentId}`}` (confirmed at `departure-actions.tsx:78`) and the overflow trigger `aria-label={`More actions for ${studentName}`}` (confirmed at `departure-actions.tsx:98`) as the selectors to drive the UI.

- [ ] Read the rest of the existing spec file beyond what this plan's research already captured (lines 100 onward) before writing new tests, so the new stub matches this file's existing conventions for the student-detail routes (`GET /api/v2/admin/students/{id}`, its sessions array, its past-enrollments array) exactly — grep `frontend/app/(admin)/admin/students/[studentId]/page.tsx` for the exact fetch calls `SessionsPanel`'s parent makes and stub every one of them the way `stubSessionDetail` stubs the roster's session/enrollments/waitlist routes.
- [ ] Write the failing test. Append to `frontend/e2e/specs/admin-enrollment-withdraw.spec.ts`:
  ```ts
  test.describe("from the student page", () => {
    test("Hold then Return updates the row without releasing the seat", async ({ page }) => {
      await stubAdminShell(page, ["admin"]);
      // Stub GET /api/v2/admin/students/{studentId} to return one active
      // session enrollment (enrollment_id: ENROLLMENT_ID, status: "active"),
      // and POST /api/v2/admin/enrollments/{ENROLLMENT_ID}/hold and
      // /return to both return 204 and flip the stubbed session's status
      // for the next GET, mirroring stubSessionDetail's mutable-state
      // pattern above.
      await page.goto(`/admin/students/stu-withdraw-1`);
      await page
        .getByTestId(`departure-actions-${ENROLLMENT_ID}`)
        .getByRole("button", { name: /more actions/i })
        .click();
      await page.getByRole("menuitem", { name: "Hold" }).click();
      await expect(page.getByRole("dialog", { name: /Hold enrollment/i })).toBeVisible();
      await page.getByLabel("Return date").fill("2026-10-15");
      await page.getByRole("button", { name: "Hold" }).click();
      await expect(page.getByText("ON HOLD")).toBeVisible();

      await page
        .getByTestId(`departure-actions-${ENROLLMENT_ID}`)
        .getByRole("button", { name: /more actions/i })
        .click();
      await page.getByRole("menuitem", { name: "Return" }).click();
      await page.getByRole("button", { name: "Return", exact: true }).click();
      await expect(page.getByText("ACTIVE")).toBeVisible();
    });

    test("Drop from the student page records a past-enrollment row", async ({ page }) => {
      await stubAdminShell(page, ["owner"]);
      // Same student stub as above, active status.
      await page.goto(`/admin/students/stu-withdraw-1`);
      await page
        .getByTestId(`departure-actions-${ENROLLMENT_ID}`)
        .getByRole("button", { name: /more actions/i })
        .click();
      await page.getByRole("menuitem", { name: "Drop" }).click();
      await page.getByLabel("Drop date").fill("2026-09-15");
      await page.getByRole("button", { name: "Drop", exact: true }).click();
      await expect(
        page.getByTestId(`admin-student-past-enrollment-${ENROLLMENT_ID}`),
      ).toBeVisible();
    });
  });
  ```
  (Selectors are written against `departure-actions.tsx` (`data-testid="departure-actions-{id}"` line 78, trigger `aria-label="More actions for {studentName}"` line 98 — after Task 9, `studentName` on the student page is the child's name), Tasks 7-8's dialogs, and `PastEnrollmentsPanel` at `SessionsPanel.tsx:763-819`. The implementer MUST run this against the real rendered page once Tasks 1-9 land and adjust to whatever Playwright's trace shows — in particular the accessible name `RallyModal` gives its dialog and the label association `Field` produces (`Field` wraps its child in a `<label>` with a `<span>` caption, so `getByLabel("Return date")` should resolve; if it does not, switch to `getByRole("dialog").getByRole("textbox")`-style scoping rather than weakening an assertion). Note `WithdrawalCreditDialog` is NOT a `RallyModal` — it is a raw Radix `Dialog.Root` whose `Dialog.Title` is "Drop enrollment" and whose date `Field` is labelled "Drop date"; `dialogs.tsx:576-581` warns that this spec file already asserts on its accessible name, so keep the two in sync.)
- [ ] Run it and confirm the expected failure (before Tasks 1-9's app code exists — since this task runs last, in practice this step is really "run it against the already-implemented app and fix the DOM-selector mismatches"): `cd frontend && pnpm exec playwright test admin-enrollment-withdraw.spec.ts --project=chromium`. Iterate on selectors/stub payloads until both new tests pass without weakening any assertion.
- [ ] Confirm the roster Pause spec really does not exist (spec §8 assumes one): `grep -rn "Pause enrollment\|PauseEnrollmentDialog\|pauseEnrollment\|admin/enrollments/.*/pause" frontend/e2e/specs/`. **Expected result: no match on the roster's departure row.** Every current `pause` hit under `frontend/e2e/specs/` is the parent pause-**request** flow (#616), which this plan does not touch: `/admin/pause-requests` (`admin-shell.spec.ts`, `local-auth-qa.spec.ts`, `saas-launch-route-matrix.spec.ts`), `/api/v2/parent/pause-requests` (`qa-defects.spec.ts`, `billing-trust-recovery.spec.ts`, `tuition-discounts.spec.ts`) and `/admin/families/{id}/autopay/pause` (`admin-family-billing.spec.ts`). Leave all of them alone. If the grep DOES surface a roster-row Pause assertion (someone added one after 2026-09-10), update its label/stub to Hold and add the file to the commit below.
- [ ] Run the withdraw spec: `cd frontend && pnpm exec playwright test admin-enrollment-withdraw.spec.ts --project=chromium`.
- [ ] Also run the two specs whose selectors could be disturbed by Task 9's `studentName` change on the student page: `cd frontend && pnpm exec playwright test admin-students.spec.ts tuition-discounts.spec.ts --project=chromium`. Any failure here is a real regression from `DepartureActions` now labelling itself with the child's name instead of the session title — fix the selector in the spec, not by reverting the prop.
- [ ] Commit: `git add frontend/e2e/specs/admin-enrollment-withdraw.spec.ts` (plus any spec the grep above actually turned up) then `git commit -m "test(e2e): Hold/Return/Drop from the student page\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>"`.

## Task 11: Release note

**Files:**
- Create: `docs/release-notes/2026-09-10-departure-actions-from-student-page.md`

- [ ] Create the release note. `scripts/dev/release_notes_check.py` requires the three headings **verbatim** — `## What changed`, `## Deploy notes`, `## Risk / rollback` — each with a non-empty body that does not start with `<` and contains none of its placeholder markers; it locates the file by searching every `docs/release-notes/*.md` for the literal string `PR: #<the PR number>`. So the `PR:` line goes directly under the title (matching `docs/release-notes/2026-09-10-absence-notice-706.md`) and **the gate stays red until `#<number>` is replaced with the real PR number** — do that immediately after opening the PR, in the same branch.
  ```markdown
  # Departure actions from the student page

  PR: #<number>

  ## What changed
  - The student page's Sessions tab now offers Hold, Return, Drop and Delete
    for an enrollment, not just Transfer — the same `DepartureActions`
    component and dialogs the class roster uses (Transfer inline, the rest in
    the row's overflow menu, Delete last behind a separator).
  - The class roster's Pause/Resume buttons are replaced by Hold/Return
    everywhere `DepartureActions` renders; the old seat-releasing
    `PauseEnrollmentDialog` is removed from the admin UI (the `/pause` and
    `/resume` backend routes are untouched — they still back the
    parent-initiated pause-request approval flow).
  - Hold, Return and Drop dialogs each gained an "Email the family" toggle
    (default off for Hold/Return, default on for Drop). When checked, the
    backend sends a best-effort, claim-deduplicated transactional email —
    `HoldNotifier.hold_started`/`hold_returned` and a new `WithdrawalNotifier`
    adapter, both riding the same `digest_claim` primitive
    `hold_notifications.py` already used for reclaim/reminder mail.

  ## Deploy notes
  - New collection `enrollment_withdrawal_notice_sends` with a unique
    `(academy_id, enrollment_id, notice_key)` index, added by migration
    `0173_withdrawal_notice_sends`. Production does not run migrations on
    boot (`V2_RUN_MIGRATIONS_ON_BOOT` is false) — apply by hand with
    `run_pending_migrations` after this deploys, same as 0170-0172.
  - No breaking API changes: `notify_family` is optional and defaults to
    `false` on every request DTO it was added to (`HoldEnrollmentRequest`,
    `ReturnFromHoldRequest`, `WithdrawEnrollmentRequest`), so every existing
    caller (including the parent-facing surfaces that do not send it) is
    unaffected.

  ## Risk / rollback
  - Low risk: the notify path is best-effort and never fails the underlying
    Hold/Return/Drop write on a mail-send exception (covered by
    `test_hold_notifier_failure_does_not_fail_the_write` and
    `test_withdraw_notifier_failure_does_not_fail_the_write`).
  - A legacy `paused` enrollment's Return button calls `POST .../return`,
    which only transitions a `held` row — this is a spec-accepted rough edge
    (see the spec's §3 comment and this plan's Self-review) that will 409 for
    a genuinely paused row until issue #703 folds `paused` into the hold
    vocabulary. Rollback is a straight revert of this PR; no data migration
    needs reversing (the new collection is additive and unused by anything
    else).
  ```
- [ ] Commit: `git add docs/release-notes/2026-09-10-departure-actions-from-student-page.md` then `git commit -m "docs(release-notes): add release note for departure actions from student page\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>"`.

## Self-review

| Spec section | Covered by |
|---|---|
| §1 Purpose (Hold/Drop reachable from the student page) | Tasks 8, 9 |
| §2 Owner decisions — Hold vs Drop as two distinct actions | Tasks 1, 3, 4, 8 |
| §2 — #697 frontend finish (Hold/Return replace Pause/Resume everywhere) | Tasks 1, 9, 10 |
| §2 — notify toggle defaults (off Hold/Return, on Drop) | Tasks 7, 8 |
| §3 Actions per row (`departureActionsFor` table, layout) | Tasks 1, 2, 9 |
| §3 — pause/resume removed from `DepartureAction`, `/pause`/`/resume` routes untouched | Task 1 (frontend type), Global Constraints (backend routes explicitly not touched) |
| §4.1 Hold dialog (fields, consequence text, `holdEnrollment` call) | Task 8 |
| §4.2 Return dialog | Task 8 |
| §4.3 Drop dialog (notify toggle default on) | Task 7 |
| §4 Dialogs move into `components/admin/enrollment/` | Task 7 |
| §5 Backend notify flag + notifier ports/adapters/claim pattern | Tasks 3, 4, 5 |
| §6 Past enrollments (no change; reason lands on the row) | Verified as already correct at `SessionsPanel.tsx:763-819` and `session-rows.ts` — no task needed, confirmed unmodified by this plan. |
| §7 Out of scope (whole-session cancel, family page row, #616 flow) | Deliberately untouched — no task references or modifies `stop_all_classes` UI, the family page, or `/pause`/`/resume`. |
| §8 Testing — unit (`departureActionsFor`, overflow placement) | Task 1 |
| §8 Testing — backend (DTO defaults, notifier-once, notifier-failure-safe) | Tasks 3, 4 |
| §8 Testing — e2e (Hold→Return and Drop from the student page) | Task 10 |
| §8 Testing — e2e ("Roster spec updates Pause → Hold labels") | **No task — nothing to update.** Verified by grep: no e2e spec exercises the roster's Pause/Resume departure buttons; every `pause` reference under `frontend/e2e/specs/` belongs to the parent pause-request flow (#616), explicitly out of scope per §7. Task 10 re-runs the grep to confirm before skipping. |

**Deferred / accepted gaps, with reasons:**
- A legacy `paused` enrollment's Return button calls `/return`, which only transitions `held → active` (`ReturnFromHold.execute`'s `mark_active_if_held`). The spec's own §3 table annotates this row with "legacy rows until #703's vocab settles" — this plan implements the button exactly as specified and does not attempt to widen `ReturnFromHold` to accept a `paused` pre-image, since that is issue #703's job, not this spec's.
- `hold_started`/`hold_returned` notice keys ARE `hold_seq`-scoped (`f"hold-started:{hold_seq}"` / `f"hold-returned:{hold_seq}"`), matching the existing `hold-reclaim:{seq}` and `hold-reminder:{seq}:{n}` keys, so a second hold-and-return cycle on the same enrollment emails again. `hold_seq` is a parameter on both new `HoldNotifier` methods from Task 3 onward — there is no follow-up correction to remember.
- Student-page Delete: the spec's §3 table lists `delete` for `active`/`held`/`paused` rows on every surface, including the student page. Task 9 wires it to the same `RemoveEnrollmentDialog` Task 7 already moved, rather than treating it as out of scope — there is no dedicated spec section calling this out explicitly, but leaving it a no-op would contradict §3's table, so this plan does not defer it.
- No new frontend `app/` route is added by this feature (only existing routes' panels change), so `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json` and the two hardcoded route counts are untouched — confirmed by inspecting the file list above: every new frontend file is a `components/` module, not an `app/` route.
- No new backend route is added either. `POST /admin/enrollments/{id}/hold`, `/return` and `/withdraw` already exist and already guard with `require_persona("admin")` (404, not 403, for the wrong persona). The plan only adds optional fields to their existing request models, so no persona-gate test is added or changed.
- **`DepartureActions.studentName` on the student page changes meaning** — today `SessionsPanel` passes `session.session_title` there, so every button's `aria-label` and the overflow trigger's read "… Beginner Badminton" instead of the child's name. Task 9 changes it to the student's name, which the dialogs need and which matches the roster. This is a behaviour change the spec does not mention; it is deliberate, and Task 10 re-runs `admin-students.spec.ts` / `tuition-discounts.spec.ts` to catch selectors that relied on the old label.
- **Frontend component rendering is not unit-tested anywhere in this plan**, because it cannot be: vitest runs `environment: "node"` with no DOM library installed. `menu.tsx`'s divider and every dialog body are covered only by `pnpm typecheck`, `pnpm lint` and Task 10's Playwright run. The pure decisions (`departureActionsFor`, inline/overflow placement, `separatorBefore`, `buildWithdrawRequest`) ARE unit-tested.
- **`ReturnFromHold` still refuses a genuinely `paused` row** (`mark_active_if_held` only moves `held`), and `HoldEnrollment` refuses one too (`EnrollmentNotHoldable`, "Resume this enrollment first"). `departureActionsFor("paused")` therefore offers Return and Transfer/Drop/Delete but NOT Hold — which matches spec §3 — and Return on such a row surfaces the backend's error in the dialog. Accepted per §3's own annotation; #703's job to fix.

## OPEN QUESTIONS

- **OPEN QUESTION (owner):** Spec §8 asks the roster e2e spec to be updated from Pause → Hold labels, but no such spec exists — the roster's Pause/Resume departure buttons have never had e2e coverage. Is a *new* roster-surface e2e test wanted (Hold/Return from `/admin/sessions/{id}`), or is the student-page coverage in Task 10 sufficient? This plan assumes sufficient and adds no roster test.
- **OPEN QUESTION (owner):** Spec §5 says the Drop email states "the billing outcome in plain words (credit / no credit / refund) using the policy vocabulary already rendered in the dialog". The dialog's three options are `credit` → "Account credit", `refund` → "Refund", `adjustment` → "Admin adjustment" (`lib/admin/withdrawal.ts:withdrawalOutcomeOptions`) — there is no "no credit" option. Task 5's `_OUTCOME_WORDS` maps `adjustment` → "an admin adjustment — no credit or refund". Confirm that wording is what the owner meant by "no credit", or supply the exact parent-facing sentence for each of the three outcomes.
