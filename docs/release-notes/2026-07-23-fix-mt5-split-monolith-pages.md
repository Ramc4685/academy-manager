# fix-mt5-split-monolith-pages

PR: (pending)

## What changed
Audit item MT5: the three largest admin frontend monoliths were split into
sibling files. This is a pure code-motion refactor — no behavior, prop, or
logic changes.

**Phase 0 — shared dialog chrome.** With DS3's `Modal`/`FormField`/
`TableSkeleton` primitives now landed (#323), the three pages' duplicated
`RallyDialog`/`DialogActions`/`DialogError`/`Field`/`Th` chrome was replaced:
- New `frontend/components/ds/dialog-chrome.tsx` exports `RallyModal` (wraps
  the DS `Modal`), a superset `DialogActions`, `DialogError`, `Field`, `Th` —
  used by the sessions and payments pages (their `RallyDialog` copies had
  matching call signatures).
- The students page's `BillingDialogFrame` now renders DS `Modal` internally
  instead of a hand-rolled portal/escape-listener; its own
  `BillingDialogActions`/`BillingDialogError`/local `Field` were left
  page-local since their shape differs from the shared chrome and unifying
  them would have required touching call sites.
- `RallyModal` wraps its content in a `max-h-[70vh] overflow-y-auto` div to
  preserve the scroll behavior the payments page's original `RallyDialog` had
  (`max-h-[90vh] overflow-y-auto`) but the DS `Modal` primitive does not
  provide.

**Phases 1-3 — page splits.**
- `admin/students/[studentId]/page.tsx`: 3,038 → 631 lines. New siblings:
  `BillingWorkflowPanel.tsx`, `SessionsPanel.tsx`, `billing-dialogs.tsx`,
  `StudentEditForm.tsx`, `StatusChip.tsx`, `DetailList.tsx`, `format.ts`.
- `admin/sessions/[id]/page.tsx`: 2,226 → 447 lines. New siblings:
  `RosterPanel.tsx`, `WaitlistTable.tsx`, `SessionEditing.tsx`, `dialogs.tsx`,
  `format.ts`.
- `admin/payments/page.tsx`: 1,822 → 554 lines. New siblings:
  `ReconciliationReportPanel.tsx`, `dialogs.tsx`, `format.ts`.

`StatusChip.tsx` exists because the students page split originally exported
`OPEN_BILLING_STATUSES`/`StatusChip` from `page.tsx` itself and imported them
back into the extracted panels — a Next.js App Router `page.tsx` (route entry
file) may only export `default` (plus a few reserved names like `metadata`),
so that pattern was caught and fixed by moving both into their own file.

## Tests & verification
`pnpm typecheck`, `pnpm lint`, and a full `pnpm build` (production) all pass
clean with no new errors or warnings. `pnpm e2e` was not run in this session —
the local stack's `backend/.venv` is not provisioned in this worktree, and the
shared local Mongo/Firebase processes on this machine appeared to be in use by
another concurrent session, so a `local_test_stack.sh fresh` reset was not
forced. Every moved function/component body was verified to be byte-identical
to its pre-move source (only import lines changed, and only in each new
file's own import block).

## Deploy notes
none — frontend-only, no API/schema/env changes.

## Risk / rollback
Low. Mechanical extraction with a clean production build; the one behavior
surface that could visibly shift is dialog chrome rendering (Phase 0 —
Modal-based dialogs vs. the old Radix/hand-rolled ones), which was reviewed
for pixel-equivalent output including the scroll-container fix above.
Rollback is a pure code revert; no data or route changes.
