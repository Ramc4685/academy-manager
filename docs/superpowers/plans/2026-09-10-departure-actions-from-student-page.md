# Departure Actions From The Student Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an admin Hold, Return, Drop or Delete a single enrollment from the student page's Sessions tab (today it only offers Transfer), reusing the existing `DepartureActions` vocabulary and the `/hold` `/return` `/withdraw` backend routes, and add an opt-in family-notification email to all three.

**Architecture:** `resolveDepartureActions` (pure gating logic) gains a sibling `departureActionsFor(status)` helper that both the class roster and the student page call, so the two surfaces render the same action set from the same status; the five enrollment dialogs (Transfer, Hold, Return, Drop, Delete) move out of the session-detail page into `components/admin/enrollment/` so both surfaces mount the identical components. On the backend, `HoldEnrollmentRequest`/`ReturnFromHoldRequest`/`WithdrawEnrollmentRequest` each gain `notify_family: bool = False`; a `notify_family=True` call reaches a best-effort notifier (`HoldNotifier.hold_started`/`hold_returned`, new `WithdrawalNotifier.dropped`) through the same claim-then-send idempotency pattern `HoldNotificationAdapter`/`AbsenceNoticeNotificationAdapter` already use, so a retried or re-run request never double-emails a family.

**Tech Stack:** Next.js 16 (webpack) + TanStack Query + Tailwind on the frontend; FastAPI + Pydantic + Motor(Mongo) on the backend; vitest for frontend units, pytest for backend, Playwright for e2e.

## Global Constraints

- Vocabulary: Transfer, Hold, Return, Drop, Delete — never "Cancel" (`departure-actions.logic.ts` already enforces this in a test).
- `departureActionsFor(status)`: `active` → `[transfer, hold, drop, delete]`; `held` / `reclaim_pending` → `[return, transfer, drop, delete]`; `paused` → `[return, transfer, drop, delete]` (legacy rows, per the design contract §3 — `Return` still posts to `/return` even though the backend CAS only accepts `held`; #703 is tracked separately to reconcile this, not fixed here); anything else → `[delete]`.
  - OPEN QUESTION (owner): the design spec §3's table lists only `active`, `held`, `paused` and `other: [delete]`. `reclaim_pending` is not in it, so under a literal reading it falls to `other` → `[delete]` only. This plan groups it with `held` because `RosterPanel`'s `ENROLL_CHIP` already renders it as "ON HOLD" and an admin looking at an on-hold row would reasonably expect Return. But `reclaim_pending` means the seat is mid-hand-over to another family, and `ReturnFromHold`'s `mark_active_if_held` CAS does not accept it — so Return would 409, and Transfer/Drop could race the reclaim. Decide before implementing Task 1: (a) group with `held` as written here, or (b) follow the spec literally and let `reclaim_pending` fall through to `[delete]`. If (b), delete the `reclaim_pending` case and its unit test from Task 1.
- Only `transfer` ever renders as an inline button; `hold`, `return`, `drop` and `delete` always render inside the overflow menu, in both `layout="inline"` and `layout="menu"` (this changes `ALWAYS_OVERFLOW_ACTIONS`, which today only forces `delete`).
- `pause` and `resume` are removed from the `DepartureAction` union and `DEPARTURE_ACTION_LABEL`, `PauseEnrollmentDialog` is deleted, and `RosterPanel`/`page.tsx` stop wiring them — **all in Task 8, in one commit**, because those four edits are mutually dependent (see the typecheck constraint above). The `/pause` and `/resume` HTTP routes and their backend use cases are untouched (they still serve the parent pause-request approval flow, #616).
- **Every dialog's notify toggle names who will be emailed** (design spec §2: "The dialog always names who will be emailed"). The three dialogs take an optional `familyLabel?: string | null`; when present the checkbox reads `Email {familyLabel}` (e.g. "Email Parent Example"), otherwise it falls back to "Email the family". The student page has `student.parent_name` and passes it; see the OPEN QUESTION on the roster surface in Task 8.
- Hold dialog: return date required, default `today + 30`, max `today + max_hold_days` (from `GET /admin/enrollment/departure-policy`'s `max_hold_days`), reason optional, **Email the family** toggle default **off**.
- Return dialog: reason optional, **Email the family** toggle default **off**.
- Drop dialog (`WithdrawalCreditDialog`): unchanged fields, gains **Email the family** toggle default **on**.
- `notify_family` defaults to `false` on every backend request DTO so existing (untoggled) callers and tests are unchanged.
- `composition/admin.py` is at 4318/4500 lines (`test_composition_is_wiring.py::ADMIN_COMPOSITION_LINE_BUDGET`) — no edits to it. New wiring follows the existing `set_seat_broker`-style setter pattern, attached in `main.py` outside `compose_admin`, exactly like `compose_enrollment_holds`/`compose_departures` already do.
- **Playwright project names**: `frontend/playwright.config.ts` defines only `chromium-mobile`, `webkit-mobile` and `chromium-desktop`. There is no project called `chromium`; `--project=chromium` errors out. `admin-enrollment-withdraw.spec.ts` does not match the `chromium-desktop` `testMatch` regex (`admin-(shell|students|registrations|level-ups-lifecycle)`), so it runs under `chromium-mobile` / `webkit-mobile` — every e2e command below uses `--project=chromium-mobile`.
- **Every task must leave `pnpm typecheck` green.** That is why the `pause`/`resume` union removal is NOT in Task 1: deleting those members while `RosterPanel.rosterActionsFor` still pushes them is a compile error that would persist across Tasks 2-7. Task 1 only *adds* `departureActionsFor` and changes `ALWAYS_OVERFLOW_ACTIONS` (both safe standalone — the roster renders `layout="menu"` and the student page passes `["transfer"]` today, so neither surface changes appearance). The union removal, `PauseEnrollmentDialog` deletion and roster rewrite all land together in Task 8.
- No new HTTP route and no new `app/` route is added by this plan, so neither the 404-not-403 persona rule nor the "New Frontend Route Checklist" (`docs/qa/2026-06-28-production-scale-local-inventory-manifest.json` + the two hardcoded route counts) needs a change — Task 9 verifies that rather than assuming it. No migration either: the family-email claim reuses the existing `enrollment_hold_notice_sends` collection and its index, so there is nothing for prod's by-hand `run_pending_migrations` to apply.

## File structure

| File | Responsibility |
|---|---|
| `frontend/components/admin/enrollment/departure-actions.logic.ts` | Vocabulary, gating (`resolveDepartureActions`), new `departureActionsFor(status)` |
| `frontend/components/admin/enrollment/departure-actions.test.tsx` | Unit coverage for both, updated for the removed pause/resume and the new overflow rule |
| `frontend/components/admin/enrollment/dialog-shared.ts` | New: `inputClass`, `formatLocalDateInput`, `todayDateInput`, `dateInputValueFromOffset`, `formatCents`, `formatShortDateTime`, plus the pure `defaultReturnOn`/`maxReturnOn` — extracted so the moved dialogs don't reach into a route-group-local file |
| `frontend/components/admin/enrollment/dialog-shared.test.ts` | New: return-date bounds (a `.ts` test, since vitest runs `environment: "node"`) |
| `frontend/components/admin/enrollment/transfer-enrollment-dialog.tsx` | Moved `TransferEnrollmentDialog` + `RallySessionPicker`, unchanged behavior |
| `frontend/components/admin/enrollment/withdrawal-credit-dialog.tsx` | Moved `WithdrawalCreditDialog` ("Drop"), gains the notify-family toggle |
| `frontend/components/admin/enrollment/remove-enrollment-dialog.tsx` | Moved `RemoveEnrollmentDialog` ("Delete"), unchanged |
| `frontend/components/admin/enrollment/hold-enrollment-dialog.tsx` | New `HoldEnrollmentDialog` |
| `frontend/components/admin/enrollment/return-from-hold-dialog.tsx` | New `ReturnFromHoldDialog` |
| `frontend/app/(admin)/admin/sessions/[id]/dialogs.tsx` | Loses the five moved/deleted dialogs; keeps `AddToRosterDialog`, `StudentSelect`, `CoachSelect`, `DaySelect` |
| `frontend/app/(admin)/admin/sessions/[id]/format.ts` | Imports **and** re-exports the six helpers from `dialog-shared.ts` instead of defining them (the plain import is required — `toDateInputValue` calls `formatLocalDateInput` locally); `formatLifecycleType` gains `held`/`returned`/`dropped` |
| `frontend/app/(admin)/admin/sessions/[id]/RosterPanel.tsx` | `rosterActionsFor`/`dispatchRosterAction` replaced by the shared `departureActionsFor`; `onPause`/`onResume` renamed `onHold`/`onReturn` |
| `frontend/app/(admin)/admin/sessions/[id]/page.tsx` | Swaps `PauseEnrollmentDialog` for `HoldEnrollmentDialog` + `ReturnFromHoldDialog`; imports the moved dialogs from `components/admin/enrollment/` |
| `frontend/app/(admin)/admin/students/[studentId]/SessionsPanel.tsx` | Renders the full action set per row and mounts all five dialogs |
| `frontend/app/(admin)/admin/students/[studentId]/page.tsx` | Passes `studentName={student.full_name}` and `familyLabel={student.parent_name}` into `SessionsPanel` |
| `frontend/lib/api/admin.ts` | `WithdrawEnrollmentRequest` gains `notify_family?: boolean` |
| `frontend/lib/admin/withdrawal.ts` | `buildWithdrawRequest` takes and forwards `notifyFamily` |
| `frontend/lib/admin/withdrawal.test.ts` | Its two `buildWithdrawRequest` cases gain the new field (otherwise typecheck fails) |
| `frontend/lib/api/v2/departure-policy.ts` | `HoldEnrollmentRequest`/`ReturnFromHoldRequest` gain `notify_family?: boolean` |
| `backend/v2/interfaces/admin/hold_routes.py` | `HoldEnrollmentRequest`/`ReturnFromHoldRequest` gain `notify_family: bool = False`; routes pass it through |
| `backend/v2/interfaces/admin/views.py` | `WithdrawEnrollmentRequest` gains `notify_family: bool = False` |
| `backend/v2/interfaces/admin/sessions_routes.py` | `withdraw_enrollment` route passes `body.notify_family` into `WithdrawEnrollmentCommand` |
| `backend/v2/contexts/enrollment/application/ports.py` | `HoldNotifier` gains `hold_started`/`hold_returned`; new `WithdrawalNotifier` protocol |
| `backend/v2/contexts/enrollment/application/use_cases/holds.py` | `HoldEnrollment`/`ReturnFromHold` take a `notifier: HoldNotifier | None`, call it when `notify_family=True` |
| `backend/v2/contexts/enrollment/application/use_cases/admin_writes.py` | `WithdrawEnrollmentCommand` gains `notify_family`; `WithdrawEnrollment` takes an optional `WithdrawalNotifier`, with a `set_withdrawal_notifier` setter, calls it when the flag is set |
| `backend/v2/composition/hold_notifications.py` | `HoldNotificationAdapter` implements `hold_started`/`hold_returned` |
| `backend/v2/composition/enrollment_holds.py` | Wires `notifier=hold_notifier` into `HoldEnrollment`/`ReturnFromHold` |
| `backend/v2/composition/withdrawal_notifications.py` | New: `WithdrawalNotificationAdapter` implementing `WithdrawalNotifier.dropped`, reusing `MongoHoldNoticeSendRepository` |
| `backend/v2/main.py` | Calls `app.state.admin.withdraw_enrollment.set_withdrawal_notifier(...)` after `compose_departures` |
| `backend/v2/tests/fixtures/enrollment_fakes.py` | `FakeHoldNotifier` gains `hold_started_calls`/`hold_returned_calls`; new `FakeWithdrawalNotifier` |
| `backend/v2/tests/application/test_enrollment_holds.py` | Notifier-call tests for Hold/Return |
| `backend/v2/tests/application/test_withdraw_single_path.py` | Notifier-call tests for Drop |
| `frontend/e2e/specs/admin-enrollment-withdraw.spec.ts` | Gains Hold → Return and Drop from the student page; Drop's request-body assertions gain `notify_family`; a roster-label assertion for Hold |
| `docs/release-notes/2026-09-10-departure-actions-from-student-page.md` | Release note |

## Task 1: Gating — add `departureActionsFor`, make hold/return/drop always overflow

> Scope note: this task does NOT remove `pause`/`resume` from the union. Doing
> so here would break `RosterPanel.rosterActionsFor` and stay broken through
> Tasks 2-7. The removal is Task 8, together with its consumers.

**Files:**
- Modify: `frontend/components/admin/enrollment/departure-actions.logic.ts`
- Modify: `frontend/components/admin/enrollment/departure-actions.test.tsx`

**Interfaces:**
- Consumes: nothing new.
- Produces: `departureActionsFor(status: string): DepartureAction[]`, exported from `departure-actions.logic.ts` and re-exported from `departure-actions.tsx` (mirroring how `resolveDepartureActions` is already re-exported at `departure-actions.tsx:35-40`).

- [ ] Write the failing tests first — replace the one test the new overflow rule invalidates, and add coverage for `departureActionsFor`. Edit `frontend/components/admin/enrollment/departure-actions.test.tsx`:
  - Leave `"never owner-gates a non-delete action"` (lines 42-48) and `"does not flag transfer, hold, return, pause or resume as danger"` (lines 83-89) ALONE — they still reference `pause`/`resume`, which are still in the union until Task 8.
  - Replace `"keeps non-delete actions inline in inline layout"` (lines 57-63 — it asserts `["transfer", "drop"]` are both inline, which the new rule makes false) with:
    ```ts
    it("keeps only transfer inline in inline layout; hold/return/drop/delete overflow", () => {
      const resolved = resolveDepartureActions(["transfer", "hold", "return", "drop", "delete"], {
        isOwner: true,
        layout: "inline",
      });
      expect(resolved.find((e) => e.action === "transfer")!.inOverflow).toBe(false);
      for (const action of ["hold", "return", "drop", "delete"] as const) {
        expect(resolved.find((e) => e.action === action)!.inOverflow).toBe(true);
      }
    });
    ```
  - Append a new top-level `describe` block for the new helper:
    ```ts
    describe("departureActionsFor", () => {
      it("offers transfer/hold/drop/delete for an active enrollment", () => {
        expect(departureActionsFor("active")).toEqual(["transfer", "hold", "drop", "delete"]);
      });

      it("offers return/transfer/drop/delete for a held enrollment", () => {
        expect(departureActionsFor("held")).toEqual(["return", "transfer", "drop", "delete"]);
      });

      it("offers return/transfer/drop/delete for a reclaim_pending enrollment", () => {
        expect(departureActionsFor("reclaim_pending")).toEqual([
          "return",
          "transfer",
          "drop",
          "delete",
        ]);
      });

      it("offers return/transfer/drop/delete for a legacy paused enrollment", () => {
        expect(departureActionsFor("paused")).toEqual(["return", "transfer", "drop", "delete"]);
      });

      it("offers only delete for any other status", () => {
        expect(departureActionsFor("dropped")).toEqual(["delete"]);
        expect(departureActionsFor("deleted")).toEqual(["delete"]);
      });
    });
    ```
  - Add `departureActionsFor` to the top-of-file import: `import { DEPARTURE_ACTION_LABEL, departureActionsFor, resolveDepartureActions, type DepartureAction } from "./departure-actions.logic";`.

- [ ] Run it (expect failure — `departureActionsFor` doesn't exist yet, and the new overflow assertion fails against today's `ALWAYS_OVERFLOW_ACTIONS`): `cd frontend && pnpm vitest run components/admin/enrollment/departure-actions.test.tsx`

- [ ] Implement. Edit `frontend/components/admin/enrollment/departure-actions.logic.ts`. The union and `DEPARTURE_ACTION_LABEL` (lines 8-27) are UNCHANGED in this task; only line 36's set changes:
  ```ts
  /**
   * Actions that always render inside the overflow menu, never as an inline
   * button. Only Transfer is ever an inline button (design contract §3) — Hold,
   * Return, Drop and Delete overflow in EVERY layout, not just "menu".
   */
  const ALWAYS_OVERFLOW_ACTIONS = new Set<DepartureAction>(["hold", "return", "drop", "delete"]);
  ```
  (`resolveDepartureActions` itself is unchanged — it already reads from `ALWAYS_OVERFLOW_ACTIONS`. `pause`/`resume` stay in the union and the label map until Task 8; they are not listed in `ALWAYS_OVERFLOW_ACTIONS` because they are about to be deleted and no surface renders them inline anyway.)
  Append below `resolveDepartureActions`:
  ```ts
  /**
   * Which departure actions apply to one enrollment row, by status — the ONE
   * table both the class roster and the student page read from (design
   * contract §3). `paused` is the legacy pre-#697 status; it still offers
   * Return even though `ReturnFromHold`'s CAS only accepts `held` today —
   * tracked separately under #703, not resolved here.
   */
  export function departureActionsFor(status: string): DepartureAction[] {
    switch (status) {
      case "active":
        return ["transfer", "hold", "drop", "delete"];
      case "held":
      case "reclaim_pending":
      case "paused":
        return ["return", "transfer", "drop", "delete"];
      default:
        return ["delete"];
    }
  }
  ```

- [ ] Update the re-export barrel. Edit `frontend/components/admin/enrollment/departure-actions.tsx` lines 35-40:
  ```ts
  export {
    DEPARTURE_ACTION_LABEL,
    departureActionsFor,
    resolveDepartureActions,
    type DepartureAction,
    type ResolvedDepartureAction,
  } from "./departure-actions.logic";
  ```

- [ ] Run it (expect PASS): `cd frontend && pnpm vitest run components/admin/enrollment/departure-actions.test.tsx`

- [ ] Typecheck and lint (expect PASS — nothing was removed from the union, so no consumer breaks): `cd frontend && pnpm typecheck && pnpm lint`

- [ ] Commit:
  ```
  git add frontend/components/admin/enrollment/departure-actions.logic.ts frontend/components/admin/enrollment/departure-actions.tsx frontend/components/admin/enrollment/departure-actions.test.tsx
  git commit -m "feat(enrollment): add departureActionsFor, keep only Transfer inline

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
  ```

## Task 2: Extract shared dialog utilities

**Files:**
- Create: `frontend/components/admin/enrollment/dialog-shared.ts`
- Modify: `frontend/app/(admin)/admin/sessions/[id]/format.ts`

**Interfaces:**
- Produces: `inputClass: string`, `formatLocalDateInput(value: Date): string`, `todayDateInput(): string`, `dateInputValueFromOffset(days: number): string`, `formatCents(cents: number): string`, `formatShortDateTime(value: string): string`, `defaultReturnOn(): string`, `maxReturnOn(maxHoldDays: number): string`.

- [ ] No test — this is a pure move with no behavior change; the safety net is `pnpm typecheck` after the move (a broken import path fails typecheck immediately). Note there is NO `format.test.ts` under `app/(admin)/admin/sessions/[id]/` (the only `format.test.ts` in the tree is `app/(admin)/admin/students/[studentId]/format.test.ts`, a different module) — do not try to run one.

- [ ] Create `frontend/components/admin/enrollment/dialog-shared.ts`:
  ```ts
  /**
   * Small formatting/style helpers shared by every enrollment departure
   * dialog (Transfer/Hold/Return/Drop/Delete). Extracted from
   * `app/(admin)/admin/sessions/[id]/format.ts` (issue #700 follow-up) so the
   * dialogs can live in `components/admin/enrollment/` and be mounted from
   * both the class roster and the student page without reaching into a
   * route-group-local file.
   */

  export const inputClass =
    "w-full rounded-md border border-rally-line bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30";

  export function formatLocalDateInput(value: Date): string {
    const year = value.getFullYear();
    const month = String(value.getMonth() + 1).padStart(2, "0");
    const day = String(value.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

  export function todayDateInput(): string {
    return formatLocalDateInput(new Date());
  }

  export function dateInputValueFromOffset(days: number): string {
    const value = new Date();
    value.setDate(value.getDate() + days);
    return formatLocalDateInput(value);
  }

  export function formatCents(cents: number): string {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
    }).format(cents / 100);
  }

  export function formatShortDateTime(value: string): string {
    return new Date(value).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  }

  /**
   * Hold return-date bounds (design spec §4.1). Kept here, in a pure `.ts`
   * module, rather than in the dialog `.tsx`: `vitest.config.ts` runs
   * `environment: "node"`, so a unit test must not have to import a React
   * component (and through it `@/components/ds/modal`, which reaches for
   * `react-dom`'s `createPortal`). Same reason `departure-actions.logic.ts`
   * exists separately from `departure-actions.tsx`.
   */
  export function defaultReturnOn(): string {
    return dateInputValueFromOffset(30);
  }

  export function maxReturnOn(maxHoldDays: number): string {
    return dateInputValueFromOffset(maxHoldDays);
  }
  ```

- [ ] Edit `frontend/app/(admin)/admin/sessions/[id]/format.ts`: delete the now-duplicated definitions of `inputClass` (lines 33-34), `formatLocalDateInput`/`todayDateInput`/`dateInputValueFromOffset` (lines 202-217), and `formatCents`/`formatShortDateTime` (lines 223-237), replacing them with an **import plus a re-export** so every other importer of `"./format"` (`dialogs.tsx`'s `AddToRosterDialog`, `SessionEditing.tsx`) is unaffected:
  ```ts
  import {
    dateInputValueFromOffset,
    formatCents,
    formatLocalDateInput,
    formatShortDateTime,
    inputClass,
    todayDateInput,
  } from "@/components/admin/enrollment/dialog-shared";

  export {
    inputClass,
    formatLocalDateInput,
    todayDateInput,
    dateInputValueFromOffset,
    formatCents,
    formatShortDateTime,
  };
  ```
  The plain `import` is NOT optional and a bare `export { … } from "…"` will NOT do: `toDateInputValue` (lines 219-221, still used by `SessionEditing.tsx:44,354` — verified by grep, so it stays) calls `formatLocalDateInput` as a **local** binding, and a re-export-from creates no local binding. Without the import line, `format.ts` fails to compile. Put the import with the other imports at the top and the `export { … }` block right after it (before `DEFAULT_TIMEZONE`), then remove the five now-orphaned local definitions further down.

- [ ] Run typecheck and lint (expect PASS — this step is a pure move, no callers change): `cd frontend && pnpm typecheck && pnpm lint`

- [ ] Commit:
  ```
  git add frontend/components/admin/enrollment/dialog-shared.ts "frontend/app/(admin)/admin/sessions/[id]/format.ts"
  git commit -m "refactor(enrollment): extract shared dialog formatting helpers

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
  ```

## Task 3: Move Transfer and Remove dialogs, unchanged

**Files:**
- Create: `frontend/components/admin/enrollment/transfer-enrollment-dialog.tsx` (moved `TransferEnrollmentDialog` + `RallySessionPicker`, `dialogs.tsx:316-522`)
- Create: `frontend/components/admin/enrollment/remove-enrollment-dialog.tsx` (moved `RemoveEnrollmentDialog`, `dialogs.tsx:686-768`)
- Modify: `frontend/app/(admin)/admin/sessions/[id]/dialogs.tsx` (delete the two moved dialogs only — `PauseEnrollmentDialog` STAYS until Task 8)
- Modify: `frontend/app/(admin)/admin/sessions/[id]/page.tsx` (import path only)

**Interfaces:**
- Consumes: `transferEnrollment` from `@/lib/api/admin`; `listAdminSessions` from `@/lib/api/admin`; `inputClass`/`todayDateInput` from `@/components/admin/enrollment/dialog-shared`.
- Produces: `TransferEnrollmentDialog`, `RallySessionPicker`, `RemoveEnrollmentDialog` — same props as today.

- [ ] No new test — behavior is unchanged; the existing `frontend/e2e/specs/admin-enrollment-withdraw.spec.ts` (re-run in Tasks 4, 8 and 9), `pnpm typecheck` and `pnpm lint` are the safety net.

- [ ] Create `frontend/components/admin/enrollment/transfer-enrollment-dialog.tsx` with this content (copied verbatim from `dialogs.tsx` lines 316-522 — `TransferEnrollmentDialog` (316-449) and its `RallySessionPicker` helper (450-453 comment, 454-522) — with only the import block changed):
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
  import { DialogActions, DialogError, Field, RallyModal as RallyDialog } from "@/components/ds/dialog-chrome";

  import { inputClass, todayDateInput } from "./dialog-shared";

  export function TransferEnrollmentDialog({
    enrollment,
    currentSessionId,
    currentSessionTitle,
    onClose,
    onMoved,
  }: {
    enrollment: AdminEnrollmentView | null;
    currentSessionId: string;
    currentSessionTitle: string;
    onClose: () => void;
    onMoved: () => void;
  }) {
    // ... body identical to dialogs.tsx lines 328-449 (unchanged) ...
  }

  // Rally-styled session picker — replaces native <select> whose OS dropdown
  // renders as a giant unstyled overlay on macOS Chrome. Click the button to
  // toggle an absolute-positioned options list constrained to the dialog.
  export function RallySessionPicker({
    sessions,
    value,
    onChange,
    loading,
  }: {
    sessions: AdminSessionView[];
    value: string;
    onChange: (value: string) => void;
    loading: boolean;
  }) {
    // ... body identical to dialogs.tsx lines 465-521 (unchanged) ...
  }
  ```
  Copy the two function bodies byte-for-byte from the current `dialogs.tsx` (lines 329-448 for `TransferEnrollmentDialog`'s body, 465-521 for `RallySessionPicker`'s body) — only the import list at the top changes to the one shown above (drop everything `TransferEnrollmentDialog` didn't itself use: `createEnrollment`, `deleteEnrollment`, `listAdminStudents`, `pauseEnrollment`, `previewWithdrawalCredit`, `quoteAdminEnrollment`, `withdrawEnrollment`, `useIsOwner`, `buildWithdrawRequest`/etc., `ApiError`, `Dialog` from radix, `formatCents`/`formatShortDateTime`, `DAYS_OF_WEEK` — none of those are referenced by `TransferEnrollmentDialog` or `RallySessionPicker`).

- [ ] Create `frontend/components/admin/enrollment/remove-enrollment-dialog.tsx`, copied verbatim from `dialogs.tsx` lines 686-768:
  ```tsx
  "use client";

  import { useState } from "react";
  import { useMutation } from "@tanstack/react-query";

  import { deleteEnrollment, type AdminEnrollmentView } from "@/lib/api/admin";

  import { Button } from "@/components/ds/button";
  import { DialogActions, DialogError, Field, RallyModal as RallyDialog } from "@/components/ds/dialog-chrome";

  import { inputClass, todayDateInput } from "./dialog-shared";

  export function RemoveEnrollmentDialog({
    enrollment,
    onClose,
    onRemoved,
  }: {
    enrollment: AdminEnrollmentView | null;
    onClose: () => void;
    onRemoved: () => void;
  }) {
    // ... body identical to dialogs.tsx lines 695-767 (unchanged) ...
  }
  ```

- [ ] Edit `frontend/app/(admin)/admin/sessions/[id]/dialogs.tsx`:
  - Delete `TransferEnrollmentDialog` and `RallySessionPicker` (lines 316-522, now moved).
  - Delete `RemoveEnrollmentDialog` (lines 686-768, now moved).
  - `PauseEnrollmentDialog` (lines 175-314) STAYS in this file — deleting it now would leave `page.tsx`'s `<PauseEnrollmentDialog>` at lines 563-572 and `RosterTable`'s REQUIRED `onPause`/`onResume` props with nothing behind them, and `pnpm typecheck` would be red for the rest of the plan. It is deleted in Task 8, together with the union change and the roster rewrite.
  - `WithdrawalCreditDialog` (lines 528-684) stays in this file for now — it moves in Task 4.
  - Trim the top import block (lines 3-38) to only what the remaining members (`AddToRosterDialog`, `PauseEnrollmentDialog`, `WithdrawalCreditDialog`, `StudentSelect`, `CoachSelect`, `DaySelect`) still use. Verified against the current file:
    - **Drop** `deleteEnrollment` (only `RemoveEnrollmentDialog` used it), `transferEnrollment`, `listAdminSessions` and `type AdminSessionView` (only `TransferEnrollmentDialog`/`RallySessionPicker` used those — `AddToRosterDialog` does NOT list sessions; its quote flow calls `quoteAdminEnrollment` with the `sessionId` prop it is already given).
    - **Keep** `createEnrollment`, `listAdminStudents`, `pauseEnrollment`, `previewWithdrawalCredit`, `quoteAdminEnrollment`, `withdrawEnrollment`, `AdminEnrollmentQuote`, `AdminEnrollmentView`, `AdminStudentView`, `AdminUserView`, `CreateEnrollmentRequest`, `queryKeys`, the withdrawal helpers, `ApiError`, `useIsOwner`, `Dialog` (radix), `DAYS_OF_WEEK`, and from `./format`: `dateInputValueFromOffset`, `formatCents`, `formatShortDateTime`, `inputClass`, `todayDateInput`.
    - `pnpm lint` is the check: eslint flags any import that is now unused, so run it before committing rather than reasoning further.

- [ ] Edit `frontend/app/(admin)/admin/sessions/[id]/page.tsx` line 43 — split the single `./dialogs` import into the moved-dialog imports plus the remaining local ones. Nothing else in this file changes in this task:
  ```ts
  import { AddToRosterDialog, PauseEnrollmentDialog, WithdrawalCreditDialog } from "./dialogs";
  import { TransferEnrollmentDialog } from "@/components/admin/enrollment/transfer-enrollment-dialog";
  import { RemoveEnrollmentDialog } from "@/components/admin/enrollment/remove-enrollment-dialog";
  ```

- [ ] Run typecheck (expect PASS): `cd frontend && pnpm typecheck`

- [ ] Run lint: `cd frontend && pnpm lint`

- [ ] Commit:
  ```
  git add frontend/components/admin/enrollment/transfer-enrollment-dialog.tsx frontend/components/admin/enrollment/remove-enrollment-dialog.tsx "frontend/app/(admin)/admin/sessions/[id]/dialogs.tsx" "frontend/app/(admin)/admin/sessions/[id]/page.tsx"
  git commit -m "refactor(enrollment): move Transfer and Remove dialogs into components/admin/enrollment

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
  ```

## Task 4: Move the Drop dialog and add the notify-family toggle

**Files:**
- Create: `frontend/components/admin/enrollment/withdrawal-credit-dialog.tsx` (moved `WithdrawalCreditDialog`, `dialogs.tsx:528-684`, plus the toggle)
- Modify: `frontend/app/(admin)/admin/sessions/[id]/dialogs.tsx` (delete the moved dialog)
- Modify: `frontend/app/(admin)/admin/sessions/[id]/page.tsx` (import path)
- Modify: `frontend/lib/api/admin.ts` (`WithdrawEnrollmentRequest` gains `notify_family?: boolean`)
- Modify: `frontend/lib/admin/withdrawal.ts` (`buildWithdrawRequest` accepts and forwards `notifyFamily`)
- Modify: `frontend/lib/admin/withdrawal.test.ts` (its two `buildWithdrawRequest` cases must pass the new field — see below)
- Modify: `frontend/e2e/specs/admin-enrollment-withdraw.spec.ts` (existing body assertions gain `notify_family: true`)

**Interfaces:**
- Consumes: `withdrawEnrollment`, `previewWithdrawalCredit` from `@/lib/api/admin`; `useIsOwner` from `@/components/admin/owner-context`; `buildWithdrawRequest`/`defaultWithdrawalOutcome`/`withdrawalOutcomeOptions`/`withdrawErrorMessage` from `@/lib/admin/withdrawal`.
- Produces: `WithdrawalCreditDialog` — same props, body now also POSTs `notify_family`.

- [ ] Write the failing test first. Edit `frontend/e2e/specs/admin-enrollment-withdraw.spec.ts`: the two request-body assertions at lines 173-175 and 196-198 currently expect exactly `{ effective_date, outcome, reason }`. Update them for the new default-on toggle:
  ```ts
  expect(stub.withdrawBodies).toEqual([
    { effective_date: "2026-09-15", outcome: "credit", reason: "Moving away", notify_family: true },
  ]);
  ```
  and
  ```ts
  expect(stub.withdrawBodies).toEqual([
    { effective_date: "2026-09-15", outcome: "refund", reason: "Withdrawal refund", notify_family: true },
  ]);
  ```
  (Leave the 409/404 tests' assertions — they only check `stub.withdrawBodies` length, not shape.)

- [ ] Run it (expect failure — the dialog doesn't send `notify_family` yet): `cd frontend && pnpm exec playwright test admin-enrollment-withdraw --project=chromium-mobile`

- [ ] Edit `frontend/lib/api/admin.ts` line 227-231:
  ```ts
  export interface WithdrawEnrollmentRequest {
    effective_date: string;
    outcome?: "credit" | "refund" | "adjustment";
    reason: string;
    notify_family?: boolean;
  }
  ```

- [ ] Edit `frontend/lib/admin/withdrawal.ts` — `buildWithdrawRequest` (lines 42-52) gains a `notifyFamily` input and forwards it:
  ```ts
  export function buildWithdrawRequest(input: {
    withdrawalDate: string;
    outcome: WithdrawalOutcome;
    adminNote: string;
    notifyFamily: boolean;
  }): WithdrawEnrollmentRequest {
    const note = input.adminNote.trim();
    return {
      effective_date: input.withdrawalDate,
      outcome: input.outcome,
      reason: note || `Withdrawal ${input.outcome}`,
      notify_family: input.notifyFamily,
    };
  }
  ```

- [ ] Edit `frontend/lib/admin/withdrawal.test.ts` — its two existing `buildWithdrawRequest` cases (lines 33-45) call the helper with three fields and `toEqual` a three-field body. Adding a REQUIRED `notifyFamily` breaks both at typecheck. Update them (and keep one covering each toggle state, since the caller now sends both):
  ```ts
  describe("buildWithdrawRequest", () => {
    it("sends every outcome through the same withdraw body", () => {
      expect(
        buildWithdrawRequest({
          withdrawalDate: "2026-09-15",
          outcome: "credit",
          adminNote: " moving ",
          notifyFamily: true,
        }),
      ).toEqual({
        effective_date: "2026-09-15",
        outcome: "credit",
        reason: "moving",
        notify_family: true,
      });
    });

    it("falls back to a reason naming the outcome when the note is blank", () => {
      expect(
        buildWithdrawRequest({
          withdrawalDate: "2026-09-15",
          outcome: "refund",
          adminNote: "",
          notifyFamily: false,
        }),
      ).toEqual({
        effective_date: "2026-09-15",
        outcome: "refund",
        reason: "Withdrawal refund",
        notify_family: false,
      });
    });
  });
  ```

- [ ] Run it (expect PASS): `cd frontend && pnpm vitest run lib/admin/withdrawal.test.ts`

- [ ] Create `frontend/components/admin/enrollment/withdrawal-credit-dialog.tsx`, copied from `dialogs.tsx:528-684` with the toggle added. Full content:
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

  import { inputClass, todayDateInput } from "./dialog-shared";

  export function WithdrawalCreditDialog({
    enrollment,
    familyLabel,
    onClose,
    onApproved,
  }: {
    enrollment: AdminEnrollmentView | null;
    /** Design spec §2: the dialog names who will be emailed. */
    familyLabel?: string | null;
    onClose: () => void;
    onApproved: () => void;
  }) {
    const isOwner = useIsOwner();
    const outcomeOptions = withdrawalOutcomeOptions(isOwner);
    const [withdrawalDate, setWithdrawalDate] = useState(todayDateInput);
    const [outcome, setOutcome] = useState<WithdrawalOutcome>(() =>
      defaultWithdrawalOutcome(isOwner),
    );
    const [adminNote, setAdminNote] = useState("");
    // Design contract §2: default ON for Drop (opposite of Hold/Return).
    const [notifyFamily, setNotifyFamily] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const previewMutation = useMutation({
      mutationFn: () =>
        previewWithdrawalCredit(enrollment!.enrollment_id, {
          withdrawal_date: `${withdrawalDate}T00:00:00.000Z`,
        }),
      onError: (err: Error) => setError(err.message ?? "Could not preview credit."),
    });
    const approveMutation = useMutation({
      mutationFn: () =>
        withdrawEnrollment(
          enrollment!.enrollment_id,
          buildWithdrawRequest({ withdrawalDate, outcome, adminNote, notifyFamily }),
        ),
      onSuccess: () => {
        setOutcome(defaultWithdrawalOutcome(isOwner));
        setAdminNote("");
        setNotifyFamily(true);
        setError(null);
        onApproved();
      },
      onError: (err: ApiError) => setError(withdrawErrorMessage(err)),
    });
    const preview = previewMutation.data;
    return (
      <Dialog.Root open={enrollment !== null} onOpenChange={(open) => !open && onClose()}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
          <Dialog.Content
            className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-xl bg-white p-6 shadow-xl focus:outline-none dark:bg-neutral-900"
            aria-describedby="withdrawal-credit-desc"
          >
            <Dialog.Title className="mb-1 text-lg font-semibold">Drop enrollment</Dialog.Title>
            <Dialog.Description id="withdrawal-credit-desc" className="mb-4 text-sm text-neutral-500">
              {enrollment
                ? `Drop ${enrollment.full_name} — releases the seat, stops autopay, and settles unused-class credit per the outcome below.`
                : ""}
            </Dialog.Description>
            {error && (
              <p role="alert" className="mb-3 rounded-md bg-red-50 p-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
                {error}
              </p>
            )}
            <div className="space-y-3">
              <Field label="Outcome" required>
                <select
                  value={outcome}
                  onChange={(event) => {
                    setOutcome(event.target.value as WithdrawalOutcome);
                    previewMutation.reset();
                  }}
                  className={inputClass}
                >
                  {outcomeOptions.map((option) => (
                    <option
                      key={option.value}
                      value={option.value}
                      disabled={option.disabledReason !== undefined}
                    >
                      {option.label}
                    </option>
                  ))}
                </select>
              </Field>
              {outcomeOptions.some((option) => option.disabledReason) && (
                <p className="text-xs text-neutral-500">
                  {outcomeOptions.find((option) => option.disabledReason)?.disabledReason}
                </p>
              )}
              <Field label="Drop date" required>
                <input
                  type="date"
                  required
                  value={withdrawalDate}
                  onChange={(event) => {
                    setWithdrawalDate(event.target.value);
                    previewMutation.reset();
                  }}
                  className={inputClass}
                />
              </Field>
              {outcome === "credit" && (
                <button
                  type="button"
                  disabled={!withdrawalDate || previewMutation.isPending}
                  onClick={() => previewMutation.mutate()}
                  className="min-h-touch rounded-md border border-blue-300 px-3 text-sm font-medium text-blue-700 hover:bg-blue-50 disabled:opacity-60 dark:border-blue-700 dark:text-blue-300"
                >
                  {previewMutation.isPending ? "Previewing..." : "Preview credit"}
                </button>
              )}
              {preview && (
                <div className="rounded-md bg-neutral-50 p-3 text-sm dark:bg-neutral-800">
                  <p className="font-medium">Credit: {preview.display_amount}</p>
                  <p className="mt-1 text-neutral-500">
                    {preview.unused_classes} of {preview.total_classes} unused classes.
                  </p>
                  <p className="mt-1 text-xs text-neutral-500">{preview.message}</p>
                </div>
              )}
              <Field label="Admin note">
                <textarea
                  value={adminNote}
                  onChange={(event) => setAdminNote(event.target.value)}
                  rows={3}
                  className={inputClass}
                />
              </Field>
              <label className="flex items-center gap-2 text-sm text-rally-ink">
                <input
                  type="checkbox"
                  checked={notifyFamily}
                  onChange={(event) => setNotifyFamily(event.target.checked)}
                />
                {familyLabel ? `Email ${familyLabel}` : "Email the family"}
              </label>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={onClose}
                  className="min-h-touch rounded-md border border-neutral-300 px-4 text-sm dark:border-neutral-700"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={
                    !withdrawalDate ||
                    approveMutation.isPending ||
                    (outcome === "credit" && !preview)
                  }
                  onClick={() => approveMutation.mutate()}
                  className="min-h-touch rounded-md bg-orange-600 px-4 text-sm font-medium text-white hover:bg-orange-700 disabled:opacity-60"
                >
                  {approveMutation.isPending ? "Saving..." : "Drop"}
                </button>
              </div>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    );
  }
  ```

- [ ] Edit `frontend/app/(admin)/admin/sessions/[id]/dialogs.tsx`: delete `WithdrawalCreditDialog` (lines 528-684) and trim its now-unused imports (`Dialog` from `@radix-ui/react-dialog`, `previewWithdrawalCredit`, `withdrawEnrollment`, `useIsOwner`, `buildWithdrawRequest`/`defaultWithdrawalOutcome`/`withdrawErrorMessage`/`withdrawalOutcomeOptions`/`WithdrawalOutcome`, `ApiError`) — check each is not still used by `AddToRosterDialog`/`StudentSelect`/`CoachSelect`/`DaySelect` before removing.

- [ ] Edit `frontend/app/(admin)/admin/sessions/[id]/page.tsx`: replace the `./dialogs` import (from Task 3) with (`PauseEnrollmentDialog` still comes from `./dialogs` — it is not deleted until Task 8):
  ```ts
  import { AddToRosterDialog, PauseEnrollmentDialog } from "./dialogs";
  import { TransferEnrollmentDialog } from "@/components/admin/enrollment/transfer-enrollment-dialog";
  import { RemoveEnrollmentDialog } from "@/components/admin/enrollment/remove-enrollment-dialog";
  import { WithdrawalCreditDialog } from "@/components/admin/enrollment/withdrawal-credit-dialog";
  ```

- [ ] Run it (expect PASS): `cd frontend && pnpm exec playwright test admin-enrollment-withdraw --project=chromium-mobile`

- [ ] Run typecheck and lint: `cd frontend && pnpm typecheck && pnpm lint`

- [ ] Commit:
  ```
  git add frontend/components/admin/enrollment/withdrawal-credit-dialog.tsx "frontend/app/(admin)/admin/sessions/[id]/dialogs.tsx" "frontend/app/(admin)/admin/sessions/[id]/page.tsx" frontend/lib/api/admin.ts frontend/lib/admin/withdrawal.ts frontend/lib/admin/withdrawal.test.ts frontend/e2e/specs/admin-enrollment-withdraw.spec.ts
  git commit -m "feat(enrollment): move the Drop dialog into components/admin/enrollment, add the email-family toggle

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
  ```

## Task 5: Backend — notify_family on Hold and Return

**Files:**
- Modify: `backend/v2/contexts/enrollment/application/ports.py` (`HoldNotifier` gains `hold_started`/`hold_returned`, after line 668)
- Modify: `backend/v2/contexts/enrollment/application/use_cases/holds.py` (`HoldEnrollment`/`ReturnFromHold` take `notifier`, call it)
- Modify: `backend/v2/composition/hold_notifications.py` (`HoldNotificationAdapter` implements the two new methods)
- Modify: `backend/v2/composition/enrollment_holds.py` (wire `notifier=hold_notifier`)
- Modify: `backend/v2/interfaces/admin/hold_routes.py` (`notify_family` on both request DTOs, passed to `.execute()`)
- Modify: `frontend/lib/api/v2/departure-policy.ts` (`HoldEnrollmentRequest`/`ReturnFromHoldRequest` gain `notify_family?: boolean`)
- Modify: `backend/v2/tests/fixtures/enrollment_fakes.py` (`FakeHoldNotifier` records the two new calls)
- Modify: `backend/v2/tests/application/test_enrollment_holds.py` (notifier-call tests)

**Interfaces:**
- Consumes: existing `HoldEnrollment.execute(enrollment_id, *, return_on, reason=None, actor_id=None)`, `ReturnFromHold.execute(enrollment_id, *, reason=None, actor_id=None, close_billing_deferral=True)`.
- Produces: both `.execute()` methods gain `notify_family: bool = False`; `HoldNotifier.hold_started(*, enrollment_id, hold_seq, session_id, student_id, return_on, reason)`, `HoldNotifier.hold_returned(*, enrollment_id, hold_seq, session_id, student_id, reason)`.

- [ ] Write the failing test first. Edit `backend/v2/tests/fixtures/enrollment_fakes.py` — extend `FakeHoldNotifier` (line 414-422):
  ```python
  @dataclass
  class FakeHoldNotifier:
      reclaimed_calls: list[dict[str, Any]] = field(default_factory=list)
      reminder_calls: list[dict[str, Any]] = field(default_factory=list)
      started_calls: list[dict[str, Any]] = field(default_factory=list)
      returned_calls: list[dict[str, Any]] = field(default_factory=list)

      async def hold_reclaimed(self, **kwargs: Any) -> None:
          self.reclaimed_calls.append(kwargs)

      async def hold_reminder(self, **kwargs: Any) -> None:
          self.reminder_calls.append(kwargs)

      async def hold_started(self, **kwargs: Any) -> None:
          self.started_calls.append(kwargs)

      async def hold_returned(self, **kwargs: Any) -> None:
          self.returned_calls.append(kwargs)
  ```

  Edit `backend/v2/tests/application/test_enrollment_holds.py`: `FakeHoldNotifier` is ALREADY in the fixtures import (line 50) — no import change is needed. Append three tests after `test_hold_keeps_status_moves_to_held_and_billing_syncs_once` (which ends at line 95). Note each case needs its own `FakeEnrollmentWriter` row: a second `execute` against the same row raises `EnrollmentNotHoldable`, because it is now `held`.
  ```python
  @pytest.mark.asyncio
  async def test_hold_notifies_the_family_only_when_asked() -> None:
      notifier = FakeHoldNotifier()

      silent = FakeEnrollmentWriter(rows={"enr-1": make_enrollment(status="active")})
      silent_uc = HoldEnrollment(
          enrollments=silent,
          departure_policy=FakeDeparturePolicyRepo(),
          notifier=notifier,
          clock=_clock,
      )
      await silent_uc.execute("enr-1", return_on=date(2026, 10, 1), notify_family=False)
      assert notifier.started_calls == []

      loud = FakeEnrollmentWriter(rows={"enr-2": make_enrollment(status="active")})
      loud_uc = HoldEnrollment(
          enrollments=loud,
          departure_policy=FakeDeparturePolicyRepo(),
          notifier=notifier,
          clock=_clock,
      )
      await loud_uc.execute(
          "enr-2", return_on=date(2026, 10, 1), reason="family trip", notify_family=True
      )
      assert len(notifier.started_calls) == 1
      call = notifier.started_calls[0]
      assert call["enrollment_id"] == "enr-2"
      assert call["hold_seq"] == 1
      assert call["return_on"] == date(2026, 10, 1)
      assert call["reason"] == "family trip"


  @pytest.mark.asyncio
  async def test_return_notifies_the_family_only_when_asked() -> None:
      notifier = FakeHoldNotifier()

      silent = FakeEnrollmentWriter(rows={"enr-1": make_enrollment(status="held")})
      silent_uc = ReturnFromHold(enrollments=silent, notifier=notifier, clock=_clock)
      await silent_uc.execute("enr-1", notify_family=False)
      assert notifier.returned_calls == []

      loud = FakeEnrollmentWriter(rows={"enr-2": make_enrollment(status="held")})
      loud_uc = ReturnFromHold(enrollments=loud, notifier=notifier, clock=_clock)
      await loud_uc.execute("enr-2", reason="back early", notify_family=True)
      assert len(notifier.returned_calls) == 1
      assert notifier.returned_calls[0]["enrollment_id"] == "enr-2"
      assert notifier.returned_calls[0]["reason"] == "back early"


  @pytest.mark.asyncio
  async def test_a_failing_family_notifier_does_not_fail_the_hold() -> None:
      """Design spec §8: a notifier failure must never fail the write."""

      class _Exploding:
          async def hold_started(self, **_: object) -> None:
              raise RuntimeError("resend is down")

      enrollments = FakeEnrollmentWriter(rows={"enr-1": make_enrollment(status="active")})
      uc = HoldEnrollment(
          enrollments=enrollments,
          departure_policy=FakeDeparturePolicyRepo(),
          notifier=_Exploding(),  # type: ignore[arg-type]
          clock=_clock,
      )

      result = await uc.execute("enr-1", return_on=date(2026, 10, 1), notify_family=True)

      assert result.status == "held"
      assert enrollments.rows["enr-1"].status == "held"
  ```
  (`make_enrollment(status="held")` takes `**extra` straight through to the `Enrollment` model, so `hold_seq` gets the model's default. These assertions never read `hold_seq` off a returned row, so no explicit `hold_seq=` is needed — but if a future assertion does, pass `hold_seq=1` in the `make_enrollment(...)` call.)

- [ ] Run it (expect failure — `HoldEnrollment`/`ReturnFromHold` accept no `notifier` kwarg yet): `cd backend && .venv/bin/pytest v2/tests/application/test_enrollment_holds.py -k "notifies_the_family or failing_family_notifier" -q`

- [ ] Implement. Edit `backend/v2/contexts/enrollment/application/ports.py`, add two methods to `HoldNotifier` right after `hold_reminder` (before the file ends at line 668):
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

- [ ] Edit `backend/v2/contexts/enrollment/application/use_cases/holds.py`:
  - `HoldEnrollment.__init__` (line 129-146): add `notifier: HoldNotifier | None = None,` next to `roster_notifier`, store as `self._notifier = notifier`. Add `HoldNotifier` to the `ports` import at the top (it's already imported at line 22 for the module-level type hints used elsewhere — confirm and reuse).
  - `HoldEnrollment.execute` (line 148-266): add `notify_family: bool = False` to the signature, and after the existing `if self._roster_notifier is not None:` staff-alert block (lines 246-256), add:
    ```python
            if notify_family and self._notifier is not None:
                try:
                    await self._notifier.hold_started(
                        enrollment_id=enrollment_id,
                        hold_seq=e.hold_seq + 1,
                        session_id=e.session_id,
                        student_id=e.student_id,
                        return_on=return_on,
                        reason=reason,
                    )
                except Exception:
                    log.exception("hold_started_notify_failed", extra={"enrollment_id": enrollment_id})
    ```
  - `ReturnFromHold.__init__` (lines 272-287): same addition — `notifier: HoldNotifier | None = None,` / `self._notifier = notifier`. (`ReturnFromHold` has no `departure_policy` collaborator; put `notifier` next to `roster_notifier` here too.)
  - `ReturnFromHold.execute` (lines 289-356): add `notify_family: bool = False` to the signature, and after the existing `if self._roster_notifier is not None:` block (lines 345-355), immediately before `return before.model_copy(update={"status": "active"})` at line 356, add:
    ```python
            if notify_family and self._notifier is not None:
                try:
                    await self._notifier.hold_returned(
                        enrollment_id=enrollment_id,
                        hold_seq=before.hold_seq,
                        session_id=e.session_id,
                        student_id=e.student_id,
                        reason=reason,
                    )
                except Exception:
                    log.exception("hold_returned_notify_failed", extra={"enrollment_id": enrollment_id})
    ```

- [ ] Run it (expect PASS): `cd backend && .venv/bin/pytest v2/tests/application/test_enrollment_holds.py -k "notifies_the_family or failing_family_notifier" -q`

- [ ] Run the full hold suite (guard against regressions in the 40+ existing tests): `cd backend && .venv/bin/pytest v2/tests/application/test_enrollment_holds.py -q`

- [ ] Implement the adapter. Edit `backend/v2/composition/hold_notifications.py`, add two methods to `HoldNotificationAdapter` (after `hold_reminder`, before `# -- shared plumbing --` at line 124):
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
                      session=session,
                      student_name=student_name,
                      return_on=return_on,
                      reason=reason,
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
  And two static rendering helpers next to `_render_reclaim_body`/`_render_reminder_body` (after line 250):
  ```python
      @staticmethod
      def _render_started_body(
          *, session: Session, student_name: str, return_on: date, reason: str | None
      ) -> str:
          safe_name = html.escape(student_name)
          safe_title = html.escape(session.title)
          parts = [
              _para(f"<strong>{safe_name}</strong>'s seat in {safe_title} is on hold."),
              _para(
                  f"Billing pauses starting with the next invoice and resumes on "
                  f"{html.escape(return_on.isoformat())}, when {safe_name} is expected back."
              ),
          ]
          if reason:
              parts.append(_para(f"Reason: {html.escape(reason)}."))
          return "".join(parts)

      @staticmethod
      def _render_returned_body(*, session: Session, student_name: str) -> str:
          safe_name = html.escape(student_name)
          safe_title = html.escape(session.title)
          return _para(
              f"<strong>{safe_name}</strong> is back in {safe_title}. Billing resumes with the "
              "next invoice."
          )
  ```

- [ ] Wire it. Edit `backend/v2/composition/enrollment_holds.py`: pass `notifier=hold_notifier` into both `HoldEnrollment(...)` (line 82-89) and `ReturnFromHold(...)` (line 90-96) constructor calls.

- [ ] Edit `backend/v2/interfaces/admin/hold_routes.py`:
  ```python
  class HoldEnrollmentRequest(BaseModel):
      return_on: date
      reason: str | None = None
      notify_family: bool = False


  class ReturnFromHoldRequest(BaseModel):
      reason: str | None = None
      notify_family: bool = False
  ```
  and pass the flag through both routes:
  ```python
      await _hold_enrollment(use_cases).execute(
          enrollment_id,
          return_on=body.return_on,
          reason=body.reason,
          actor_id=claims.user_id,
          notify_family=body.notify_family,
      )
  ```
  and
  ```python
      await _return_from_hold(use_cases).execute(
          enrollment_id,
          reason=body.reason,
          actor_id=claims.user_id,
          notify_family=body.notify_family,
      )
  ```

- [ ] Edit `frontend/lib/api/v2/departure-policy.ts` lines 42-49:
  ```ts
  export interface HoldEnrollmentRequest {
    return_on: string;
    reason?: string | null;
    notify_family?: boolean;
  }

  export interface ReturnFromHoldRequest {
    reason?: string | null;
    notify_family?: boolean;
  }
  ```

- [ ] Run the backend hold interface test (guards the route wiring): `cd backend && .venv/bin/pytest v2/tests/interface -k hold -q`

- [ ] Run `cd backend && .venv/bin/ruff check v2/contexts/enrollment/application/ports.py v2/contexts/enrollment/application/use_cases/holds.py v2/composition/hold_notifications.py v2/composition/enrollment_holds.py v2/interfaces/admin/hold_routes.py`

- [ ] Run `cd frontend && pnpm typecheck`

- [ ] Commit:
  ```
  git add backend/v2/contexts/enrollment/application/ports.py backend/v2/contexts/enrollment/application/use_cases/holds.py backend/v2/composition/hold_notifications.py backend/v2/composition/enrollment_holds.py backend/v2/interfaces/admin/hold_routes.py backend/v2/tests/fixtures/enrollment_fakes.py backend/v2/tests/application/test_enrollment_holds.py frontend/lib/api/v2/departure-policy.ts
  git commit -m "feat(enrollment): add opt-in family email to Hold and Return

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
  ```

## Task 6: Backend — notify_family on Drop (WithdrawalNotifier)

**Files:**
- Modify: `backend/v2/contexts/enrollment/application/ports.py` (new `WithdrawalNotifier` protocol, after `HoldNotifier`)
- Modify: `backend/v2/contexts/enrollment/application/use_cases/admin_writes.py` (`WithdrawEnrollmentCommand` gains `notify_family`; `WithdrawEnrollment` gains optional notifier + setter + call)
- Create: `backend/v2/composition/withdrawal_notifications.py` (`WithdrawalNotificationAdapter`, `compose_withdrawal_notifications`)
- Modify: `backend/v2/main.py` (wire the setter after `compose_departures`)
- Modify: `backend/v2/interfaces/admin/views.py` (`WithdrawEnrollmentRequest` gains `notify_family: bool = False`)
- Modify: `backend/v2/interfaces/admin/sessions_routes.py` (pass `body.notify_family` into the command)
- Modify: `backend/v2/tests/fixtures/enrollment_fakes.py` (new `FakeWithdrawalNotifier`)
- Modify: `backend/v2/tests/application/test_withdraw_single_path.py` (notifier-call tests)

**Interfaces:**
- Consumes: `MongoHoldNoticeSendRepository.try_claim(*, academy_id, enrollment_id, notice_key)` (reused as-is from `backend/v2/composition/hold_notice_send_repo.py` — generic on `enrollment_id`/`notice_key`, not hold-specific despite the class name).
- Produces: `WithdrawalNotifier.dropped(*, enrollment_id, session_id, student_id, effective_at, outcome, billing_result, reason)`; `WithdrawEnrollment.set_withdrawal_notifier(notifier: WithdrawalNotifier) -> None`.

- [ ] Write the failing test first. Edit `backend/v2/tests/fixtures/enrollment_fakes.py`, add next to `FakeHoldNotifier`:
  ```python
  @dataclass
  class FakeWithdrawalNotifier:
      dropped_calls: list[dict[str, Any]] = field(default_factory=list)

      async def dropped(self, **kwargs: Any) -> None:
          self.dropped_calls.append(kwargs)
  ```

  Edit `backend/v2/tests/application/test_withdraw_single_path.py`: this file imports its fakes from `test_enrollment_lifecycle_actions`, not from `enrollment_fakes`, so add a NEW import line (`from backend.v2.tests.fixtures.enrollment_fakes import FakeWithdrawalNotifier`). Give `Harness` a `notifier: FakeWithdrawalNotifier` field, build one in `_build` (lines 67-84) and attach it **via the setter**, not a constructor kwarg — that is how production wires it (`main.py`), and `WithdrawEnrollment.__init__` deliberately gains no new kwarg:
  ```python
  def _build(status: str = "active") -> Harness:
      enrollments = FakeEnrollments(rows={"enr-1": _enrollment(status)})
      sessions = FakeSessions()
      outbox = FakeOutbox()
      events = FakeEnrollmentEvents()
      decision = FakeWithdrawalDecision()
      sync = RecordingBillingSync()
      roster = RecordingRoster()
      notifier = FakeWithdrawalNotifier()
      use_case = WithdrawEnrollment(
          enrollments=enrollments,
          enrollment_events=events,
          billing=decision,
          roster_notifier=roster,
          billing_sync=sync,
          sessions=sessions,
          outbox=outbox,
          clock=_now,
      )
      use_case.set_withdrawal_notifier(notifier)
      return Harness(use_case, enrollments, sessions, outbox, events, decision, sync, roster, notifier)
  ```
  (add `notifier: FakeWithdrawalNotifier` as the last field of the `Harness` dataclass, lines 55-64.)

  Append two tests at the end of the file:
  ```python
  @pytest.mark.asyncio
  async def test_drop_notifies_the_family_only_when_asked() -> None:
      harness = _build()
      cmd_silent = WithdrawEnrollmentCommand(
          enrollment_id="enr-1", effective_at=EFFECTIVE, outcome="credit",
          actor_id="owner-1", reason="moving away", notify_family=False,
      )
      await harness.use_case.execute(cmd_silent)
      assert harness.notifier.dropped_calls == []


  @pytest.mark.asyncio
  async def test_drop_notifies_the_family_when_asked() -> None:
      harness = _build()
      cmd_loud = WithdrawEnrollmentCommand(
          enrollment_id="enr-1", effective_at=EFFECTIVE, outcome="refund",
          actor_id="owner-1", reason="moving away", notify_family=True,
      )
      await harness.use_case.execute(cmd_loud)
      assert len(harness.notifier.dropped_calls) == 1
      call = harness.notifier.dropped_calls[0]
      assert call["enrollment_id"] == "enr-1"
      assert call["outcome"] == "refund"
      assert call["reason"] == "moving away"


  @pytest.mark.asyncio
  async def test_a_failing_family_notifier_does_not_fail_the_drop() -> None:
      """Design spec §8: a notifier failure must never fail the write."""

      class _Exploding:
          async def dropped(self, **_: object) -> None:
              raise RuntimeError("resend is down")

      harness = _build()
      harness.use_case.set_withdrawal_notifier(_Exploding())  # type: ignore[arg-type]

      await harness.use_case.execute(
          WithdrawEnrollmentCommand(
              enrollment_id="enr-1", effective_at=EFFECTIVE, outcome="refund",
              actor_id="owner-1", reason="moving away", notify_family=True,
          )
      )

      assert harness.enrollments.rows["enr-1"].status == "dropped"
  ```

- [ ] Run it (expect failure — `WithdrawEnrollmentCommand` has no `notify_family` field, `WithdrawEnrollment` has no `set_withdrawal_notifier`): `cd backend && .venv/bin/pytest v2/tests/application/test_withdraw_single_path.py -k "notifies_the_family or failing_family_notifier" -q`

- [ ] Implement. Edit `backend/v2/contexts/enrollment/application/ports.py`, append after `HoldNotifier` (end of file, after line 668):
  ```python


  class WithdrawalNotifier(Protocol):
      """Best-effort family email for a Drop (issue #700). Same idempotency
      contract as ``HoldNotifier``: implementations claim before sending, and
      this never raises into the caller's write path."""

      async def dropped(
          self,
          *,
          enrollment_id: str,
          session_id: str,
          student_id: str,
          effective_at: datetime,
          outcome: WithdrawalOutcome,
          billing_result: str | None,
          reason: str | None,
      ) -> None: ...
  ```
  (`WithdrawalOutcome` is already defined at line 426 in this same file — no new import needed.)

- [ ] Edit `backend/v2/contexts/enrollment/application/use_cases/admin_writes.py`:
  - `WithdrawEnrollmentCommand` (lines 1831-1837, `model_config = {"frozen": True}`): add `notify_family: bool = False` as the last field.
  - Add `WithdrawalNotifier` to the `ports` import block at lines 22-38, alphabetically — between `WaitlistRepository` and `WithdrawalOutcome`.
  - `WithdrawEnrollment.__init__` (lines 1922-1945): add `self._withdrawal_notifier: WithdrawalNotifier | None = None` (not a constructor kwarg — set only via the setter below, mirroring `ResumeEnrollment.set_seat_broker`'s pattern exactly since `admin.py`'s line budget forbids adding a new constructor kwarg there).
  - Add a setter right after `__init__`:
    ```python
        def set_withdrawal_notifier(self, notifier: WithdrawalNotifier) -> None:
            self._withdrawal_notifier = notifier
    ```
  - In `execute` (starts at line 1947), after the existing `await _notify_roster_change(...)` call that ends the method, add (`billing_decision` is the local dict built earlier in the same method — it exists and is re-assigned once with the sync result appended):
    ```python
        if cmd.notify_family and self._withdrawal_notifier is not None:
            try:
                await self._withdrawal_notifier.dropped(
                    enrollment_id=e.enrollment_id,
                    session_id=e.session_id,
                    student_id=e.student_id,
                    effective_at=cmd.effective_at,
                    outcome=cmd.outcome,
                    billing_result=billing_decision.get("billing_result"),
                    reason=cmd.reason,
                )
            except Exception:
                log.exception("withdrawal_notify_failed", extra={"enrollment_id": e.enrollment_id})
    ```

- [ ] Run it (expect PASS): `cd backend && .venv/bin/pytest v2/tests/application/test_withdraw_single_path.py -k "notifies_the_family or failing_family_notifier" -q`

- [ ] Run the full withdraw suite: `cd backend && .venv/bin/pytest v2/tests/application/test_withdraw_single_path.py -q`

- [ ] Create `backend/v2/composition/withdrawal_notifications.py`, reusing `hold_notifications.py`'s send-claim repo AND its claim/resolve/send plumbing (do not create a new Mongo collection — `MongoHoldNoticeSendRepository` claims on `(academy_id, enrollment_id, notice_key)`, which is exactly what a one-time "dropped" notice needs).

  **Reuse, do not copy.** `HoldNotificationAdapter._send_claimed` and `._resolve_parent` (`hold_notifications.py:126-190`) are entirely generic over `(enrollment_id, notice_key, session_id, student_id, build)` — nothing in them is hold-specific. Copying them would fork ~65 lines of the claim/suppression/mark-failed contract that the 2026-09-02 duplicate-digest incident is the reason for, and the two copies would drift. Instead, `WithdrawalNotificationAdapter` holds a `HoldNotificationAdapter` and delegates:

  ```python
  class WithdrawalNotificationAdapter:
      def __init__(self, *, sends: HoldNotificationAdapter) -> None:
          self._sends = sends

      async def dropped(self, *, enrollment_id, session_id, student_id,
                        effective_at, outcome, billing_result, reason) -> None:
          await self._sends._send_claimed(
              enrollment_id=enrollment_id,
              notice_key=_NOTICE_KEY,
              session_id=session_id,
              student_id=student_id,
              build=lambda session, student_name: (
                  f"{student_name} has been dropped from {session.title}",
                  self._render_body(session=session, student_name=student_name,
                                    effective_at=effective_at, outcome=outcome, reason=reason),
              ),
          )
  ```

  Reaching into `_send_claimed` across module boundaries is the one wart; fix it by renaming `HoldNotificationAdapter._send_claimed` → `send_claimed` (public) and `._resolve_parent` stays private, updating its two call sites in `hold_notifications.py`, and adding `send_claimed` to a short `ClaimedSender` Protocol in that module. `compose_withdrawal_notifications(db, settings)` then returns `WithdrawalNotificationAdapter(sends=compose_hold_notifications(db, settings))`. Keep `_NOTICE_KEY = "dropped"`, `_OUTCOME_WORDS` and `_render_body` (below) in the new module — the copy is the only genuinely withdrawal-specific part.

  The fully-expanded version below is what you would write if the delegation above is rejected in review; it is kept for the exact copy, claim semantics and `TRANSACTIONAL` category, NOT as the preferred shape:
  ```python
  """WithdrawalNotifier adapter — family email for a Drop (issue #700).

  Lives outside ``composition/admin.py`` for the same reason
  ``hold_notifications.py`` does (that module's wiring line-budget test).
  Reuses ``MongoHoldNoticeSendRepository`` (issue #697) rather than a fourth
  send-claim collection — its claim key is ``(academy_id, enrollment_id,
  notice_key)``, generic on both fields despite the class's name; every other
  enrollment/communications bridge already reuses this repo the same way
  (``compose_hold_notifications`` for reclaim/reminder, this module for
  drop). ``notice_key="dropped"`` is enough: ``WithdrawEnrollment``'s CAS
  guarantees a given ``enrollment_id`` can be dropped at most once.

  Best-effort from the caller's point of view (never raises) and
  TRANSACTIONAL — a family whose child's enrollment just ended must get the
  notice regardless of marketing preferences.
  """

  from __future__ import annotations

  import html
  import logging
  from datetime import datetime
  from typing import Any, Protocol

  from backend.v2.composition.hold_notice_send_repo import MongoHoldNoticeSendRepository
  from backend.v2.contexts.communications.application.ports import (
      AudienceResolver,
      EmailSendPort,
      ResolvedRecipient,
  )
  from backend.v2.contexts.communications.domain.email_category import EmailCategory
  from backend.v2.contexts.communications.domain.models import SelectedRecipientsAudience
  from backend.v2.contexts.enrollment.application.ports import WithdrawalOutcome
  from backend.v2.contexts.enrollment.domain.models import Session, Student
  from backend.v2.shared.tenancy import current_academy_id

  logger = logging.getLogger(__name__)

  _NOTICE_KEY = "dropped"

  _OUTCOME_WORDS: dict[str, str] = {
      "credit": "an account credit",
      "refund": "a refund",
      "adjustment": "no credit — an admin adjustment",
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
          notice_sends: MongoHoldNoticeSendRepository,
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
          outcome: WithdrawalOutcome,
          billing_result: str | None,
          reason: str | None,
      ) -> None:
          academy_id = current_academy_id()
          claim = await self._notice_sends.try_claim(
              academy_id=academy_id, enrollment_id=enrollment_id, notice_key=_NOTICE_KEY
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
              reason=reason,
          )
          try:
              outcome_result = await self._sender.send(
                  recipient=recipient,
                  subject=subject,
                  body=body,
                  category=EmailCategory.TRANSACTIONAL,
              )
          except Exception:
              logger.exception("withdrawal_notice_send_failed", extra={"enrollment_id": enrollment_id})
              await self._notice_sends.mark_failed(claim["send_id"], "send_exception")
              return

          if outcome_result.ok:
              await self._notice_sends.mark_sent(claim["send_id"])
          elif outcome_result.suppressed:
              await self._notice_sends.mark_failed(claim["send_id"], "suppressed", retryable=False)
          else:
              await self._notice_sends.mark_failed(
                  claim["send_id"], outcome_result.failed_reason or "send_failed"
              )

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
          outcome: WithdrawalOutcome,
          reason: str | None,
      ) -> str:
          safe_name = html.escape(student_name)
          safe_title = html.escape(session.title)
          words = _OUTCOME_WORDS.get(outcome, outcome)
          parts = [
              _para(
                  f"<strong>{safe_name}</strong> has been dropped from {safe_title}, effective "
                  f"{html.escape(effective_at.date().isoformat())}."
              ),
              _para(f"Billing outcome: {html.escape(words)}."),
          ]
          if reason:
              parts.append(_para(f"Reason: {html.escape(reason)}."))
          return "".join(parts)


  def compose_withdrawal_notifications(db: Any, settings: Any) -> WithdrawalNotificationAdapter:
      """Convenience constructor mirroring ``compose_hold_notifications``."""
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
          notice_sends=MongoHoldNoticeSendRepository(db),
      )
  ```

- [ ] Wire it in `backend/v2/main.py`, right after the existing `_departures = compose_departures(...)` block (after line 595-597, which sets `app.state.admin.stop_all_classes`/`leaving_report`):
  ```python
      from backend.v2.composition.withdrawal_notifications import compose_withdrawal_notifications

      app.state.admin.withdraw_enrollment.set_withdrawal_notifier(
          compose_withdrawal_notifications(db, settings)
      )
  ```

- [ ] Edit `backend/v2/interfaces/admin/views.py` line 621-624:
  ```python
  class WithdrawEnrollmentRequest(BaseModel):
      effective_date: date
      outcome: Literal["credit", "refund", "adjustment"] = "credit"
      reason: str = Field(min_length=1, max_length=500)
      notify_family: bool = False
  ```

- [ ] Edit `backend/v2/interfaces/admin/sessions_routes.py` lines 664-672 — add `notify_family=body.notify_family` to the `WithdrawEnrollmentCommand(...)` call:
  ```python
      await use_cases.withdraw_enrollment.execute(
          WithdrawEnrollmentCommand(
              enrollment_id=enrollment_id,
              effective_at=_start_of_day_utc(body.effective_date),
              outcome=body.outcome,
              actor_id=claims.user_id,
              reason=body.reason,
              notify_family=body.notify_family,
          )
      )
  ```

- [ ] Run the withdraw interface tests: `cd backend && .venv/bin/pytest v2/tests/interface/test_admin_withdrawal_credit.py -q`

- [ ] Run structural/wiring tests that assert on `composition/admin.py`'s line count and on `main.py`'s wiring shape, to confirm this task didn't touch the guarded file: `cd backend && .venv/bin/pytest v2/tests/structural -q`

- [ ] Run `cd backend && .venv/bin/ruff check v2/contexts/enrollment/application/ports.py v2/contexts/enrollment/application/use_cases/admin_writes.py v2/composition/withdrawal_notifications.py v2/main.py v2/interfaces/admin/views.py v2/interfaces/admin/sessions_routes.py`

- [ ] Commit:
  ```
  git add backend/v2/contexts/enrollment/application/ports.py backend/v2/contexts/enrollment/application/use_cases/admin_writes.py backend/v2/composition/withdrawal_notifications.py backend/v2/main.py backend/v2/interfaces/admin/views.py backend/v2/interfaces/admin/sessions_routes.py backend/v2/tests/fixtures/enrollment_fakes.py backend/v2/tests/application/test_withdraw_single_path.py
  git commit -m "feat(enrollment): add opt-in family email to Drop

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
  ```

## Task 7: New Hold and Return dialogs

**Files:**
- Create: `frontend/components/admin/enrollment/hold-enrollment-dialog.tsx`
- Create: `frontend/components/admin/enrollment/return-from-hold-dialog.tsx`
- Create: `frontend/components/admin/enrollment/dialog-shared.test.ts` (return-date bounds — a plain `.ts` test against the pure helpers added to `dialog-shared.ts` in Task 2)

**Interfaces:**
- Consumes: `holdEnrollment`, `returnFromHold`, `getDeparturePolicy` from `@/lib/api/v2/departure-policy`; `queryKeys.admin.departurePolicy()` from `@/lib/query/keys`; `defaultReturnOn`/`maxReturnOn`/`dateInputValueFromOffset`/`inputClass` from `./dialog-shared`.
- Produces: `HoldEnrollmentDialog({ enrollment, familyLabel, onClose, onHeld })`, `ReturnFromHoldDialog({ enrollment, familyLabel, onClose, onReturned })` where `enrollment: HoldableEnrollment | null` and `HoldableEnrollment = { enrollment_id: string; full_name: string }` (a structural subset of `AdminEnrollmentView`, so the student page — whose rows are `AdminStudentSessionSummary`, not `AdminEnrollmentView` — can build a matching object).

- [ ] Write the failing test first. Create `frontend/components/admin/enrollment/dialog-shared.test.ts`. Note it targets `dialog-shared.ts`, NOT the dialog `.tsx`: `vitest.config.ts` sets `environment: "node"`, and importing the dialog would drag in `@/components/ds/modal` → `react-dom`'s `createPortal`. Note also that the expectation is built with `formatLocalDateInput` (local calendar parts), NOT `toISOString().slice(0,10)` (UTC) — nothing pins `TZ` for vitest, so a UTC comparison is off by one for most of the day in any negative-offset zone, including the academy's own `America/Chicago`:
  ```ts
  import { describe, expect, it } from "vitest";

  import { defaultReturnOn, formatLocalDateInput, maxReturnOn } from "./dialog-shared";

  describe("hold dialog return-date bounds", () => {
    it("defaults to 30 days out", () => {
      const expected = new Date();
      expected.setDate(expected.getDate() + 30);
      expect(defaultReturnOn()).toBe(formatLocalDateInput(expected));
    });

    it("caps at max_hold_days out", () => {
      const expected = new Date();
      expected.setDate(expected.getDate() + 60);
      expect(maxReturnOn(60)).toBe(formatLocalDateInput(expected));
    });
  });
  ```

- [ ] Run it (expect failure — `defaultReturnOn`/`maxReturnOn` are added to `dialog-shared.ts` in Task 2, so this passes as soon as Task 2 landed; if Task 2 was already done, skip straight to green and note it): `cd frontend && pnpm vitest run components/admin/enrollment/dialog-shared.test.ts`

- [ ] Implement. Create `frontend/components/admin/enrollment/hold-enrollment-dialog.tsx`:
  ```tsx
  "use client";

  import { useState } from "react";
  import { useMutation, useQuery } from "@tanstack/react-query";

  import { getDeparturePolicy, holdEnrollment } from "@/lib/api/v2/departure-policy";
  import { queryKeys } from "@/lib/query/keys";

  import { Button } from "@/components/ds/button";
  import { DialogActions, DialogError, Field, RallyModal as RallyDialog } from "@/components/ds/dialog-chrome";

  import { dateInputValueFromOffset, defaultReturnOn, inputClass, maxReturnOn } from "./dialog-shared";

  export interface HoldableEnrollment {
    enrollment_id: string;
    full_name: string;
  }

  export function HoldEnrollmentDialog({
    enrollment,
    familyLabel,
    onClose,
    onHeld,
  }: {
    enrollment: HoldableEnrollment | null;
    /** Design spec §2: the dialog names who will be emailed. */
    familyLabel?: string | null;
    onClose: () => void;
    onHeld: () => void;
  }) {
    // `queryKeys.admin.departurePolicy()` is ["admin","enrollment","departure-policy"],
    // the SAME key the student page and the settings panel already use — so the
    // dialog reuses their cached policy instead of refetching, and one
    // Playwright route stub covers all three. Do NOT invent a new key here.
    const policyQuery = useQuery({
      queryKey: queryKeys.admin.departurePolicy(),
      queryFn: getDeparturePolicy,
      enabled: enrollment !== null,
      staleTime: 60_000,
    });
    const maxHoldDays = policyQuery.data?.max_hold_days ?? 60;
    const [returnOn, setReturnOn] = useState(defaultReturnOn);
    const [reason, setReason] = useState("");
    // Design contract §2: default OFF for Hold (opposite of Drop).
    const [notifyFamily, setNotifyFamily] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const mutation = useMutation({
      mutationFn: () =>
        holdEnrollment(enrollment!.enrollment_id, {
          return_on: returnOn,
          reason: reason || null,
          notify_family: notifyFamily,
        }),
      onSuccess: () => {
        setReturnOn(defaultReturnOn());
        setReason("");
        setNotifyFamily(false);
        setError(null);
        onHeld();
      },
      onError: (err: Error) => setError(err.message ?? "Could not place this enrollment on hold."),
    });

    return (
      <RallyDialog
        open={enrollment !== null}
        onOpenChange={(open) => !open && onClose()}
        title="Hold enrollment"
        description={enrollment ? `Hold ${enrollment.full_name}'s seat until they return.` : ""}
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
            <input
              type="date"
              required
              min={dateInputValueFromOffset(1)}
              max={maxReturnOn(maxHoldDays)}
              value={returnOn}
              onChange={(event) => setReturnOn(event.target.value)}
              className={inputClass}
            />
            <p className="mt-1 text-xs text-rally-subtle">
              Up to {maxHoldDays} days from today.
            </p>
          </Field>
          <p className="text-xs text-rally-subtle">
            Seat is kept. Billing pauses from the next invoice and resumes on the return date. If
            the class fills, the longest-held family is asked to return or drop first.
          </p>
          <Field label="Reason">
            <textarea
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              rows={3}
              className={inputClass}
            />
          </Field>
          <label className="flex items-center gap-2 text-sm text-rally-ink">
            <input
              type="checkbox"
              checked={notifyFamily}
              onChange={(event) => setNotifyFamily(event.target.checked)}
            />
            {familyLabel ? `Email ${familyLabel}` : "Email the family"}
          </label>
          <DialogActions>
            <Button variant="secondary" size="sm" type="button" onClick={onClose}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" type="submit" disabled={!returnOn || mutation.isPending}>
              {mutation.isPending ? "Holding..." : "Hold"}
            </Button>
          </DialogActions>
        </form>
      </RallyDialog>
    );
  }
  ```

- [ ] Create `frontend/components/admin/enrollment/return-from-hold-dialog.tsx`:
  ```tsx
  "use client";

  import { useState } from "react";
  import { useMutation } from "@tanstack/react-query";

  import { returnFromHold } from "@/lib/api/v2/departure-policy";

  import { Button } from "@/components/ds/button";
  import { DialogActions, DialogError, Field, RallyModal as RallyDialog } from "@/components/ds/dialog-chrome";

  import { inputClass } from "./dialog-shared";
  import type { HoldableEnrollment } from "./hold-enrollment-dialog";

  export function ReturnFromHoldDialog({
    enrollment,
    familyLabel,
    onClose,
    onReturned,
  }: {
    enrollment: HoldableEnrollment | null;
    /** Design spec §2: the dialog names who will be emailed. */
    familyLabel?: string | null;
    onClose: () => void;
    onReturned: () => void;
  }) {
    const [reason, setReason] = useState("");
    const [notifyFamily, setNotifyFamily] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const mutation = useMutation({
      mutationFn: () =>
        returnFromHold(enrollment!.enrollment_id, {
          reason: reason || null,
          notify_family: notifyFamily,
        }),
      onSuccess: () => {
        setReason("");
        setNotifyFamily(false);
        setError(null);
        onReturned();
      },
      onError: (err: Error) => setError(err.message ?? "Could not return this enrollment from hold."),
    });

    return (
      <RallyDialog
        open={enrollment !== null}
        onOpenChange={(open) => !open && onClose()}
        title="Return from hold"
        description={enrollment ? `Return ${enrollment.full_name} to active billing.` : ""}
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
          <p className="text-xs text-rally-subtle">Billing resumes with the next invoice.</p>
          <Field label="Reason">
            <textarea
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              rows={3}
              className={inputClass}
            />
          </Field>
          <label className="flex items-center gap-2 text-sm text-rally-ink">
            <input
              type="checkbox"
              checked={notifyFamily}
              onChange={(event) => setNotifyFamily(event.target.checked)}
            />
            {familyLabel ? `Email ${familyLabel}` : "Email the family"}
          </label>
          <DialogActions>
            <Button variant="secondary" size="sm" type="button" onClick={onClose}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? "Returning..." : "Return"}
            </Button>
          </DialogActions>
        </form>
      </RallyDialog>
    );
  }
  ```

- [ ] Run it (expect PASS): `cd frontend && pnpm vitest run components/admin/enrollment/dialog-shared.test.ts`

- [ ] Run typecheck and lint: `cd frontend && pnpm typecheck && pnpm lint`

- [ ] Commit:
  ```
  git add frontend/components/admin/enrollment/hold-enrollment-dialog.tsx frontend/components/admin/enrollment/dialog-shared.test.ts frontend/components/admin/enrollment/return-from-hold-dialog.tsx
  git commit -m "feat(enrollment): add Hold and Return dialogs

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
  ```

## Task 8: Retire pause/resume and wire the class roster

This is the one task that removes `pause`/`resume` from the vocabulary. Every
edit below is part of the same compile unit — do them in one pass and commit
once; splitting them leaves `pnpm typecheck` red.

**Files:**
- Modify: `frontend/components/admin/enrollment/departure-actions.logic.ts` (drop `"pause"`/`"resume"` from the `DepartureAction` union at lines 8-16 and from `DEPARTURE_ACTION_LABEL` at lines 18-27)
- Modify: `frontend/components/admin/enrollment/departure-actions.test.tsx` (three tests still name the removed members — see below)
- Modify: `frontend/app/(admin)/admin/sessions/[id]/dialogs.tsx` (delete `PauseEnrollmentDialog`, lines 175-314, and the now-unused `pauseEnrollment` import)
- Modify: `frontend/app/(admin)/admin/sessions/[id]/RosterPanel.tsx` (`rosterActionsFor`/`dispatchRosterAction` → shared helper; `onPause`/`onResume` props → `onHold`/`onReturn`)
- Modify: `frontend/app/(admin)/admin/sessions/[id]/page.tsx` (remove `pauseTarget`/`resumeMutation`/`PauseEnrollmentDialog`; add `holdTarget`/`returnTarget`/`HoldEnrollmentDialog`/`ReturnFromHoldDialog`)
- Modify: `frontend/app/(admin)/admin/sessions/[id]/format.ts` (`formatLifecycleType` gains `held`/`returned`/`dropped`)
- Modify: `frontend/e2e/specs/admin-enrollment-withdraw.spec.ts` (roster Hold-label assertion, since no dedicated roster-pause e2e spec exists today — grepped and confirmed none does)

**Interfaces:**
- Consumes: `departureActionsFor` from `@/components/admin/enrollment/departure-actions`.
- Produces: `RosterTable` props `onHold: (enrollment: AdminEnrollmentView) => void`, `onReturn: (enrollment: AdminEnrollmentView) => void` (replacing `onPause: (enrollment) => void` / `onResume: (id: string) => void` — note `onResume` took an id, `onReturn` takes the whole row, because the Return dialog needs `full_name` for its copy).

- [ ] OPEN QUESTION (owner): `familyLabel` on the roster surface. Design spec §2 says the dialog "always names who will be emailed". The student page has `student.parent_name` (Task 9 passes it). `AdminEnrollmentView` — the roster's row shape — carries `parent_id` but no parent name, and `GET /admin/sessions/{id}/enrollments` does not return one. Options: (a) ship the roster with the generic "Email the family" fallback and only the student page naming the parent; (b) add `parent_name` to `AdminEnrollmentView` and the roster read model (a backend change this plan does not otherwise need). Decide before writing the roster wiring below; (a) is assumed by the code as written.

- [ ] Write the failing test first. Add to `frontend/e2e/specs/admin-enrollment-withdraw.spec.ts`, inside the existing `test.describe` block, a new test asserting the roster overflow menu now says "Hold" for an active row (the roster spec's closest existing coverage — there is no dedicated pause/resume roster e2e spec to update, confirmed via `grep -rln "PauseEnrollmentDialog\|pauseEnrollment" frontend/e2e/specs/`):
  ```ts
  test("roster overflow menu offers Hold, not Pause, for an active enrollment", async ({ page }) => {
    await stubAdminShell(page, ["admin", "owner"]);
    await stubSessionDetail(page, "active");
    await page.goto(`/admin/sessions/${SESSION_ID}`);
    await expect(page.getByText("Alice Example")).toBeVisible();
    await page.getByRole("button", { name: "More actions for Alice Example" }).click();
    await expect(page.getByRole("menuitem", { name: "Hold" })).toBeVisible();
    await expect(page.getByRole("menuitem", { name: "Pause" })).toHaveCount(0);
  });
  ```

- [ ] Run it (expect failure — the roster still offers Pause): `cd frontend && pnpm exec playwright test admin-enrollment-withdraw --project=chromium-mobile -g "Hold, not Pause"`

- [ ] Edit `frontend/components/admin/enrollment/departure-actions.logic.ts`: delete `| "pause"` and `| "resume"` from the `DepartureAction` union (lines 14-15) and the `pause: "Pause"` / `resume: "Resume"` entries from `DEPARTURE_ACTION_LABEL` (lines 24-25). Nothing else in this file mentions them.

- [ ] Edit `frontend/components/admin/enrollment/departure-actions.test.tsx` — three tests name the removed members and stop compiling:
  - `"never owner-gates a non-delete action"` (lines 42-48): change the array to `["transfer", "hold", "return", "drop", "stop_all_classes"]`.
  - `"pushes every action into the overflow menu in menu layout"` (lines 65-71): change `["transfer", "drop", "pause"]` to `["transfer", "drop", "hold"]`.
  - `"does not flag transfer, hold, return, pause or resume as danger"` (lines 83-89): rename to `"does not flag transfer, hold or return as danger"` and change the array to `["transfer", "hold", "return"]`.

- [ ] Edit `frontend/app/(admin)/admin/sessions/[id]/dialogs.tsx`: delete `PauseEnrollmentDialog` (lines 175-314) and drop `pauseEnrollment` (and anything else it alone used — `pnpm lint` names them) from the import block.

- [ ] Edit `frontend/app/(admin)/admin/sessions/[id]/RosterPanel.tsx`:
  - Line 18-21 import: change `DepartureActions, type DepartureAction` to also pull `departureActionsFor`:
    ```ts
    import {
      DepartureActions,
      departureActionsFor,
      type DepartureAction,
    } from "@/components/admin/enrollment/departure-actions";
    ```
  - `RosterTable`'s destructured parameter list (lines 128-129, `onPause,` / `onResume,`) and its prop TYPES (lines 144-145, `onPause: (enrollment: AdminEnrollmentView) => void;` / `onResume: (id: string) => void;`) — rename both to:
    ```ts
    onHold: (enrollment: AdminEnrollmentView) => void;
    onReturn: (enrollment: AdminEnrollmentView) => void;
    ```
  - The `<DepartureActions>` call (lines 252-268): replace `actions={rosterActionsFor(e.status)}` with `actions={departureActionsFor(e.status)}`, and update `onAction`'s handler map:
    ```tsx
    <DepartureActions
      enrollmentId={e.enrollment_id}
      studentName={e.full_name}
      status={e.status}
      layout="menu"
      isOwner={isOwner}
      actions={departureActionsFor(e.status)}
      onAction={(action, enrollmentId) =>
        dispatchRosterAction(action, enrollmentId, e, {
          onDelete,
          onHold,
          onReturn,
          onTransfer,
          onWithdraw,
        })
      }
    />
    ```
  - Delete `rosterActionsFor` (lines 280-294, docstring included) entirely, and drop the now-unused `type EnrollmentStatus` from the `@/lib/api/admin` import at lines 6-10 ONLY if `ENROLL_CHIP` at line 33 no longer needs it — it does need it, so keep it.
  - Rewrite `dispatchRosterAction` (lines 296-329):
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

- [ ] Edit `frontend/app/(admin)/admin/sessions/[id]/format.ts`'s `formatLifecycleType` (near the end of the file) to add the three labels that would otherwise fall back to "Updated" once Hold/Return/Drop start appearing in `EnrollmentHistory`:
  ```ts
  export function formatLifecycleType(value: string): string {
    const labels: Record<string, string> = {
      created: "Added",
      moved: "Moved",
      paused: "Paused",
      resumed: "Resumed",
      held: "Held",
      returned: "Returned",
      withdrawn: "Withdrawn",
      dropped: "Dropped",
      removed: "Removed",
      cancelled: "Cancelled",
      waitlisted: "Waitlisted",
      promoted: "Promoted",
    };
    return labels[value] ?? "Updated";
  }
  ```

- [ ] Edit `frontend/app/(admin)/admin/sessions/[id]/page.tsx`:
  - Replace the `[pauseTarget, setPauseTarget]` state (line 80) with:
    ```ts
    const [holdTarget, setHoldTarget] = useState<AdminEnrollmentView | null>(null);
    const [returnTarget, setReturnTarget] = useState<AdminEnrollmentView | null>(null);
    ```
  - Delete `resumeMutation` (lines 147-154) — Return is now a dialog (with an optional reason + notify toggle), not a one-click mutation.
  - Replace the `onPause`/`onResume` props passed into `<RosterTable>` (lines 419-420) with:
    ```tsx
    onHold={(enrollment) => setHoldTarget(enrollment)}
    onReturn={(enrollment) => setReturnTarget(enrollment)}
    ```
  - Replace the `<PauseEnrollmentDialog ... />` block (lines 563-572) with:
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
  - Add the two new imports next to the other moved-dialog imports (Task 4), and drop `PauseEnrollmentDialog` from the `./dialogs` import:
    ```ts
    import { AddToRosterDialog } from "./dialogs";
    import { HoldEnrollmentDialog } from "@/components/admin/enrollment/hold-enrollment-dialog";
    import { ReturnFromHoldDialog } from "@/components/admin/enrollment/return-from-hold-dialog";
    ```
  - Remove the now-unused `resumeEnrollment` import (line 24).

- [ ] Run it (expect PASS): `cd frontend && pnpm exec playwright test admin-enrollment-withdraw --project=chromium-mobile -g "Hold, not Pause"`

- [ ] Run the full withdraw e2e file (regression guard on everything Tasks 1-8 touched): `cd frontend && pnpm exec playwright test admin-enrollment-withdraw --project=chromium-mobile`

- [ ] Run typecheck and lint: `cd frontend && pnpm typecheck && pnpm lint`

- [ ] Commit:
  ```
  git add frontend/components/admin/enrollment/departure-actions.logic.ts frontend/components/admin/enrollment/departure-actions.test.tsx "frontend/app/(admin)/admin/sessions/[id]/dialogs.tsx" "frontend/app/(admin)/admin/sessions/[id]/RosterPanel.tsx" "frontend/app/(admin)/admin/sessions/[id]/page.tsx" "frontend/app/(admin)/admin/sessions/[id]/format.ts" frontend/e2e/specs/admin-enrollment-withdraw.spec.ts
  git commit -m "feat(enrollment): wire Hold/Return dialogs onto the class roster, retire Pause/Resume

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
  ```

## Task 9: Wire the student page (SessionsPanel)

**Files:**
- Modify: `frontend/app/(admin)/admin/students/[studentId]/SessionsPanel.tsx`
- Modify: `frontend/app/(admin)/admin/students/[studentId]/page.tsx` (pass `studentName`)
- Modify: `frontend/e2e/specs/admin-enrollment-withdraw.spec.ts` (student-page Hold → Return and Drop tests)

**Interfaces:**
- Consumes: `departureActionsFor` from `@/components/admin/enrollment/departure-actions`; the five dialog components from `@/components/admin/enrollment/*`.
- Produces: `SessionsPanel` gains a `studentName: string` prop.

- [ ] Write the failing test first. Append to `frontend/e2e/specs/admin-enrollment-withdraw.spec.ts` — this needs the student-detail route's own stubs, which the existing helpers in this file don't cover (they stub `/admin/sessions/{id}`, not `/admin/students/{id}`). Add a second stub helper and two tests at the end of the `test.describe` block:
  ```ts
  const STUDENT_ID = "stu-withdraw-1";

  async function stubStudentDetail(page: Page): Promise<WithdrawStub> {
    const stub: WithdrawStub = {
      withdrawBodies: [],
      approveCalls: 0,
      respond: (route) => route.fulfill({ status: 204, body: "" }),
    };
    let enrollmentStatus = "active";
    let dropped = false;
    const row = () => ({
      enrollment_id: ENROLLMENT_ID,
      session_id: SESSION_ID,
      session_title: "Tuesday Beginner",
      status: enrollmentStatus,
      start_at: "2026-09-08T23:00:00Z",
      end_at: "2026-09-08T23:45:00Z",
      amount_cents: 10000,
    });
    await page.route("**/api/v2/admin/**", (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const path = url.pathname;
      if (request.method() === "GET" && path === `/api/v2/admin/students/${STUDENT_ID}`) {
        // The Drop test asserts the row lands in Past enrollments, so the stub
        // has to actually move it — design spec §8 ("with the past-enrollments
        // row asserted").
        return fulfillJson(route, {
          student_id: STUDENT_ID,
          full_name: "Alice Example",
          parent_id: "parent-1",
          parent_name: "Parent Example",
          enrolled_sessions: dropped ? [] : [row()],
          past_enrollments: dropped
            ? [
                {
                  ...row(),
                  status: "dropped",
                  ended_at: "2026-09-15T00:00:00Z",
                  withdrawal_date: "2026-09-15",
                  cancelled_by: "user-admin-withdraw-e2e",
                  reason: "Withdrawal credit",
                },
              ]
            : [],
        });
      }
      if (request.method() === "GET" && path === "/api/v2/admin/users") {
        return fulfillJson(route, { users: [] });
      }
      if (request.method() === "GET" && path === `/api/v2/admin/enrollment/departure-policy`) {
        return fulfillJson(route, {
          max_hold_days: 60,
          hold_reclaim_policy: "longest_held",
          drop_default_outcome: "credit_mid_month",
          delete_enrollment_requires_owner: true,
        });
      }
      if (request.method() === "POST" && path === `/api/v2/admin/enrollments/${ENROLLMENT_ID}/hold`) {
        enrollmentStatus = "held";
        return route.fulfill({ status: 204, body: "" });
      }
      if (request.method() === "POST" && path === `/api/v2/admin/enrollments/${ENROLLMENT_ID}/return`) {
        enrollmentStatus = "active";
        return route.fulfill({ status: 204, body: "" });
      }
      if (
        request.method() === "POST" &&
        path === `/api/v2/admin/enrollments/${ENROLLMENT_ID}/withdrawal-credit/preview`
      ) {
        return fulfillJson(route, {
          credit_amount_cents: 3750,
          display_amount: "$37.50",
          total_classes: 8,
          unused_classes: 3,
          formula: "max(10000 - 0, 0) * 3 / 8",
          message: "Credit is calculated for 3 unused classes.",
          no_credit_reason: null,
        });
      }
      if (request.method() === "POST" && path === `/api/v2/admin/enrollments/${ENROLLMENT_ID}/withdraw`) {
        stub.withdrawBodies.push(request.postDataJSON());
        dropped = true;
        return stub.respond(route);
      }
      if (request.method() === "GET") return fulfillJson(route, {});
      return route.fallback();
    });
    return stub;
  }

  /**
   * `/admin/students/[studentId]` does NOT read a `?tab=` param — `page.tsx`
   * holds the active tab in `useState<StudentTab>("overview")` and only
   * `StudentTabs`' `role="tab"` buttons change it. Navigating to
   * `?tab=sessions` lands on Overview and every locator below times out.
   * `admin-students.spec.ts` uses the same click.
   *
   * Forward note: the sibling plan
   * `2026-09-10-student-page-single-view.md` (plan 4, built after this one)
   * removes the tabs; its Task 12 drops this click, renames the helper
   * `openStudentPage`, and adds a `GET /api/v2/admin/users/parent-1` branch
   * to `stubStudentDetail` for the new rail. Nothing to do here.
   */
  async function openSessionsTab(page: Page) {
    await page.goto(`/admin/students/${STUDENT_ID}`);
    await page.getByRole("tab", { name: "Sessions" }).click();
    await expect(page.getByText("Tuesday Beginner")).toBeVisible();
  }

  test.describe("departure actions from the student page (design 2026-09-10)", () => {
    test("Hold, then Return, from the student page", async ({ page }) => {
      await stubAdminShell(page, ["admin", "owner"]);
      await stubStudentDetail(page);
      await openSessionsTab(page);

      await page.getByRole("button", { name: /More actions for/ }).click();
      await page.getByRole("menuitem", { name: "Hold" }).click();
      const holdDialog = page.getByRole("dialog", { name: "Hold enrollment" });
      await expect(holdDialog).toBeVisible();
      await holdDialog.getByRole("button", { name: "Hold", exact: true }).click();
      await expect(holdDialog).toBeHidden();

      await page.getByRole("button", { name: /More actions for/ }).click();
      await page.getByRole("menuitem", { name: "Return" }).click();
      const returnDialog = page.getByRole("dialog", { name: "Return from hold" });
      await expect(returnDialog).toBeVisible();
      await returnDialog.getByRole("button", { name: "Return", exact: true }).click();
      await expect(returnDialog).toBeHidden();
    });

    test("Drop from the student page shows in past enrollments", async ({ page }) => {
      await stubAdminShell(page, ["admin", "owner"]);
      const stub = await stubStudentDetail(page);
      await openSessionsTab(page);

      await page.getByRole("button", { name: /More actions for/ }).click();
      await page.getByRole("menuitem", { name: "Drop" }).click();
      const dialog = page.getByRole("dialog", { name: "Drop enrollment" });
      await expect(dialog).toBeVisible();
      await dialog.getByLabel("Drop date").fill("2026-09-15");
      await dialog.getByRole("button", { name: "Preview credit" }).click();
      await expect(dialog.getByText("Credit: $37.50")).toBeVisible();
      await dialog.getByRole("button", { name: "Drop", exact: true }).click();
      await expect(dialog).toBeHidden();

      expect(stub.withdrawBodies).toEqual([
        { effective_date: "2026-09-15", outcome: "credit", reason: "Withdrawal credit", notify_family: true },
      ]);

      // Design spec §8: assert the past-enrollments row, not just the POST.
      await expect(
        page.getByTestId(`admin-student-past-enrollment-${ENROLLMENT_ID}`),
      ).toBeVisible();
      await expect(page.getByTestId("admin-student-past-enrollments")).toContainText("1 ended");
    });
  });
  ```
  (This adds a new `test.describe` after the existing one closes at line 260, rather than nesting inside it — confirm the file's final `});` at line 260 and insert after it. `Page` and `Route` are already imported at line 1; `WithdrawStub`, `fulfillJson`, `stubAdminShell`, `SESSION_ID` and `ENROLLMENT_ID` are all module-level in this file and reusable as-is.)

- [ ] Run it (expect failure — the student page still only offers Transfer): `cd frontend && pnpm exec playwright test admin-enrollment-withdraw --project=chromium-mobile -g "student page"`

- [ ] Edit `frontend/app/(admin)/admin/students/[studentId]/page.tsx` (the `<SessionsPanel …/>` inside `{activeTab === "sessions" && …}`, lines 216-222) — add `studentName` and `familyLabel`:
  ```tsx
  <SessionsPanel
    sessions={student.enrolled_sessions ?? []}
    pastEnrollments={student.past_enrollments ?? []}
    parentId={student.parent_id}
    studentId={studentId}
    studentName={student.full_name}
    familyLabel={student.parent_name ?? null}
    queryClient={queryClient}
  />
  ```

- [ ] Edit `frontend/app/(admin)/admin/students/[studentId]/SessionsPanel.tsx`:
  - Add imports at the top (after the existing `DepartureActions` import, line 27):
    ```ts
    import {
      DepartureActions,
      departureActionsFor,
      type DepartureAction,
    } from "@/components/admin/enrollment/departure-actions";
    import { HoldEnrollmentDialog } from "@/components/admin/enrollment/hold-enrollment-dialog";
    import { ReturnFromHoldDialog } from "@/components/admin/enrollment/return-from-hold-dialog";
    import { WithdrawalCreditDialog } from "@/components/admin/enrollment/withdrawal-credit-dialog";
    import { RemoveEnrollmentDialog } from "@/components/admin/enrollment/remove-enrollment-dialog";
    ```
    (drop the plain `DepartureActions` import at line 27 and replace with the block above.)
  - Add `studentName: string;` and `familyLabel?: string | null;` to the component's destructured params (lines 54-60) and its prop type (lines 61-68), right after `studentId`.
  - Add four new pieces of dialog state next to `moving` (line 70):
    ```ts
    const [holding, setHolding] = useState<AdminStudentSessionSummary | null>(null);
    const [returning, setReturning] = useState<AdminStudentSessionSummary | null>(null);
    const [dropping, setDropping] = useState<AdminStudentSessionSummary | null>(null);
    const [removing, setRemoving] = useState<AdminStudentSessionSummary | null>(null);
    ```
  - Replace the `<DepartureActions>` block (lines 332-348, currently `actions={["transfer"]}` with a bare `onAction`) with the full action set:
    ```tsx
    <DepartureActions
      enrollmentId={session.enrollment_id}
      studentName={session.session_title}
      status={session.status}
      layout="inline"
      isOwner={isOwner}
      actions={departureActionsFor(session.status)}
      onAction={(action: DepartureAction) => {
        switch (action) {
          case "transfer":
            setMoving(session);
            setTargetSessionId("");
            setReason("");
            setEffectiveDate(new Date().toISOString().slice(0, 10));
            break;
          case "hold":
            setHolding(session);
            break;
          case "return":
            setReturning(session);
            break;
          case "drop":
            setDropping(session);
            break;
          case "delete":
            setRemoving(session);
            break;
          default:
            // stop_all_classes has its own launcher (#698), not this row.
            break;
        }
      }}
    />
    ```
  - Mount the four new dialogs alongside the existing `{moving && (...)}` inline dialog, right before the closing `</>` of the component's returned JSX (after the `{billingOverride && (...)}` block, before line 718's `</>`):
    ```tsx
    <HoldEnrollmentDialog
      enrollment={holding ? { enrollment_id: holding.enrollment_id, full_name: studentName } : null}
      familyLabel={familyLabel}
      onClose={() => setHolding(null)}
      onHeld={() => {
        setHolding(null);
        void queryClient.invalidateQueries({ queryKey: queryKeys.admin.studentDetail(studentId) });
      }}
    />
    <ReturnFromHoldDialog
      enrollment={returning ? { enrollment_id: returning.enrollment_id, full_name: studentName } : null}
      familyLabel={familyLabel}
      onClose={() => setReturning(null)}
      onReturned={() => {
        setReturning(null);
        void queryClient.invalidateQueries({ queryKey: queryKeys.admin.studentDetail(studentId) });
      }}
    />
    <WithdrawalCreditDialog
      enrollment={
        dropping
          ? ({ enrollment_id: dropping.enrollment_id, full_name: studentName } as AdminEnrollmentView)
          : null
      }
      familyLabel={familyLabel}
      onClose={() => setDropping(null)}
      onApproved={() => {
        setDropping(null);
        void queryClient.invalidateQueries({ queryKey: queryKeys.admin.studentDetail(studentId) });
      }}
    />
    <RemoveEnrollmentDialog
      enrollment={
        removing
          ? ({ enrollment_id: removing.enrollment_id, full_name: studentName } as AdminEnrollmentView)
          : null
      }
      onClose={() => setRemoving(null)}
      onRemoved={() => {
        setRemoving(null);
        void queryClient.invalidateQueries({ queryKey: queryKeys.admin.studentDetail(studentId) });
      }}
    />
    ```
    `WithdrawalCreditDialog`/`RemoveEnrollmentDialog` expect a full `AdminEnrollmentView` — the cast above mirrors how these dialogs already only read `.enrollment_id`/`.full_name` off the object (verified in Tasks 3-4's copied bodies); nothing else on `AdminEnrollmentView` is dereferenced by either dialog.
  - Add the `AdminEnrollmentView` type import needed for the cast above: add `type AdminEnrollmentView` to the existing `@/lib/api/admin` import, or (cleaner) import it from `@/lib/api/admin` directly since `listAdminSessions` already comes from there (line 8-11) — extend that import block's type list.

- [ ] Run it (expect PASS): `cd frontend && pnpm exec playwright test admin-enrollment-withdraw --project=chromium-mobile -g "student page"`

- [ ] Run the full spec file (final regression guard for this feature): `cd frontend && pnpm exec playwright test admin-enrollment-withdraw --project=chromium-mobile`

- [ ] Run typecheck and lint: `cd frontend && pnpm typecheck && pnpm lint`

- [ ] Confirm the "New Frontend Route Checklist" does not apply. No `app/` route is added anywhere in this plan (`/admin/students/[studentId]` and its Sessions tab are pre-existing; the tab is component state, not a route), so `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json` and the two hardcoded route counts stay untouched. Verify rather than assume: `cd backend && .venv/bin/pytest v2/tests -k "route_manifest or route_inventory or qa_inventory" -q` must be green, and `git status --short docs/qa/` must be empty.

- [ ] Commit:
  ```
  git add "frontend/app/(admin)/admin/students/[studentId]/SessionsPanel.tsx" "frontend/app/(admin)/admin/students/[studentId]/page.tsx" frontend/e2e/specs/admin-enrollment-withdraw.spec.ts
  git commit -m "feat(enrollment): offer Hold/Return/Drop/Delete from the student page, not just Transfer

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
  ```

## Task 10: Full regression pass

**Files:** none (verification only).

- [ ] Backend: `cd backend && .venv/bin/pytest v2/tests -q` — full suite, catches any fixture/import fallout from Tasks 5-6.
- [ ] Backend structural/layering: `cd backend && .venv/bin/pytest v2/tests/structural -q` (already run in Task 6; re-run here as the final gate since Task 9 touched no backend files but this confirms nothing regressed).
- [ ] Frontend unit: `cd frontend && pnpm vitest run`
- [ ] Frontend typecheck: `cd frontend && pnpm typecheck`
- [ ] Frontend lint: `cd frontend && pnpm lint`
- [ ] Frontend e2e, the touched spec plus its neighbors that reference roster/withdraw/student-sessions shell state: `cd frontend && pnpm exec playwright test admin-enrollment-withdraw admin-shell --project=chromium-mobile`
- [ ] Fix anything red before Task 11. Do not proceed with a known-red suite.

## Task 11: Release note

**Files:**
- Create: `docs/release-notes/2026-09-10-departure-actions-from-student-page.md`

- [ ] Write the release note. CI's "Release Notes Gate" requires exactly these three `##` sections plus a `PR: #<number>` line — the PR number is filled in after the PR opens (see the last step below), so leave a placeholder now and update it once the PR exists, before merge:
  ```markdown
  # Departure actions from the student page

  ## What changed

  The student page's Sessions tab now offers the full departure action set —
  Transfer, Hold, Return, Drop and Delete — instead of Transfer alone. Hold and
  Return are new dialogs backed by the existing `/hold` and `/return` routes
  (issue #697); Drop reuses the existing withdraw dialog. The class roster's
  Pause/Resume buttons are replaced by Hold/Return, calling the seat-keeping
  hold endpoints instead of the old seat-releasing pause endpoint — the
  `/pause` and `/resume` routes themselves are untouched, since the parent
  self-service pause-request flow (#616) still uses them.

  All three actions (Hold, Return, Drop) gained an **Email the family** toggle
  in their dialog — off by default for Hold and Return, on by default for
  Drop. When checked, a best-effort transactional email goes to the family,
  claimed once per enrollment/event so a retried request never double-sends.

  ## Deploy notes

  No migrations, no new environment variables, no new collections — the
  family-email claim reuses the existing `enrollment_hold_notice_sends`
  collection from issue #697. Purely additive backend fields
  (`notify_family: bool = False` on the hold, return and withdraw request
  bodies) — safe to deploy in any order relative to the frontend.

  ## Risk / rollback

  Low risk: the underlying `/hold`, `/return` and `/withdraw` routes and their
  use cases are unchanged except for the new optional notifier call, which is
  wrapped in try/except and cannot fail the write. Rollback is a plain revert;
  no data migration to undo. The roster's Pause/Resume buttons are removed in
  the same change, so a rollback also restores them — verify the deployed
  frontend and backend revert together rather than independently, since a
  frontend-only rollback would point old Hold/Return dialogs at routes that
  still work identically either way.

  PR: #<fill in after PR is opened>
  ```

- [ ] Commit:
  ```
  git add docs/release-notes/2026-09-10-departure-actions-from-student-page.md
  git commit -m "docs(release-notes): add release note for departure actions from the student page

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
  ```

- [ ] After the PR is opened, edit the `PR: #<fill in after PR is opened>` line to the real PR number and push a follow-up commit (the CI gate parses this exact line — see `project_ci_gates_release_notes_and_no_force_push` for the three-section-plus-PR-number contract).

## Self-review

| Spec section | Covered by |
|---|---|
| §2 owner decisions — Hold vs Drop as two distinct actions, notify toggle defaults, Hold/Return replace Pause/Resume everywhere, **and the dialog naming who will be emailed** (`familyLabel`) | Tasks 1, 4, 5-9 (naming: Tasks 4, 7, 9; roster surface is an OPEN QUESTION in Task 8) |
| §3 actions per row (`departureActionsFor` table, Transfer-only-inline layout rule) | Task 1; the pause/resume removal moved to Task 8 so every intermediate task typechecks. `reclaim_pending` is an OPEN QUESTION (Global Constraints). |
| §4.1 Hold dialog (return date bounds/default, reason, toggle default off, consequence text) | Task 7 |
| §4.2 Return dialog (reason, toggle default off, consequence text) | Task 7 |
| §4.3 Drop dialog toggle (default on) + existing fields unchanged | Task 4 |
| §4 dialogs move into `components/admin/enrollment/` so both surfaces share them | Tasks 3, 4, 7 |
| §5 backend notify flag on all three requests, notifier pattern (claim, TRANSACTIONAL, never fails the write), copy states effective/return date and billing outcome in plain words | Tasks 5, 6 |
| §6 past enrollments — no code change, reason still flows to the lifecycle event | Verified only (Tasks 5-6 pass `reason` straight through to `_record_event`/`_persist_lifecycle_dates`, already exercised by `PastEnrollmentsPanel`); no new task needed |
| §7 out of scope (whole-session cancel, family page action row, pause-request approval flow, hold reclaim/reminder/billing math) | Deliberately untouched by every task — `/pause`, `/resume`, `stop_all_classes`, `ExpireDueHolds`, `SendHoldReminders`, `ProcessStalledReclaims` are not modified anywhere in this plan |
| §8 testing — unit (`departureActionsFor`, overflow placement), backend (DTO defaults, notifier called once/never, failure doesn't fail the write), e2e (Hold→Return + Drop from student page with the past-enrollments row asserted, roster Pause→Hold label) | Task 1 + Task 7 (unit), Tasks 5-6 (backend: `test_hold_notifies_the_family_only_when_asked`, `test_return_notifies_the_family_only_when_asked`, `test_drop_notifies_the_family_only_when_asked`/`_when_asked`, plus an explicit `test_a_failing_family_notifier_does_not_fail_the_{hold,drop}` in each file — the spec asks for it by name, so it is written per-action rather than assumed from the roster-notify pattern), Tasks 8-9 (e2e) |

**Open questions for the owner (must be answered before the task that needs them):**
- `reclaim_pending` in `departureActionsFor` — see Global Constraints. Blocks Task 1.
- `familyLabel` on the class roster (no parent name in `AdminEnrollmentView`) — see Task 8. Blocks Task 8's roster wiring; the code as written assumes option (a), the generic fallback.

**Deferred, with reason:**
- The `paused` status offering `return` even though `ReturnFromHold`'s CAS only accepts `held` (design contract §3's own footnote, "legacy rows until #703's vocab settles") — implemented literally as specified in Task 1; reconciling `mark_active_if_held` to also accept `paused`, or migrating remaining `paused` rows to `held`, is issue #703's scope, not this one's.
- `formatLifecycleType`'s missing `held`/`returned`/`dropped` labels were a pre-existing gap the spec doesn't mention, but Task 8 fixes it in passing since Hold/Return actions now make those event types visible in `RosterTable`'s `EnrollmentHistory` for the first time — leaving them as "Updated" would be a visible regression introduced by this feature, not a pre-existing one.
