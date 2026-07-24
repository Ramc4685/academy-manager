# MT5 — Split frontend monolith pages

Status: DONE (PR #331, 2026-07-23)
Size: L · Depends on: DS3 (dialog primitives — optional; use `Modal` primitive instead of the extracted `RallyDialog` if DS3 lands first) · Tracker: ../TRACKER.md

## Problem

Three admin pages are monoliths: `frontend/app/(admin)/admin/students/[studentId]/page.tsx` (3,038 lines — grown from 3,026 at audit), `admin/sessions/[id]/page.tsx` (2,226), `admin/payments/page.tsx` (1,822). Every internal component is already a named function inside the file, and the dialog chrome (`RallyDialog`, `DialogActions`, `Field`, `Th`, `TableSkeleton`) is copy-pasted across all three. Any touch means a 2-3k-line diff surface and merge-conflict magnet.

## Current behavior (verified boundaries, 2026-07-20 — slightly shifted from audit doc)

- **students/[studentId]/page.tsx (3,038L):** `BillingWorkflowPanel` :628, `SessionsPanel` :1295, billing dialogs `CreateInvoiceDialog` :1940 / `AddInvoiceLineDialog` :2016 / `RecordPaymentDialog` :2137 / `VoidInvoiceDialog` :2226, `StudentEditForm` :2471, local `Field` :3018. (Audit's `:628-1282 / :1283+ / :1928-2314 / :2459+` boundaries confirmed, +~12 drift.)
- **sessions/[id]/page.tsx (2,226L):** tables `ReplacementCoachTable` :602, `RosterTable` :1047, `WaitlistTable` :1254, `EnrollmentHistory` :1232; **7 dialogs**: `OccurrenceReplacementDialog` :667, `SessionEditDialog` :797, `AddToRosterDialog` :1318, `PauseEnrollmentDialog` :1443, `TransferEnrollmentDialog` :1588, `WithdrawalCreditDialog` :1843, `RemoveEnrollmentDialog` :1986; selectors `StudentSelect` :2065 / `CoachSelect` :2094 / `DaySelect` :2124; chrome `RallyDialog` :1795, `DialogActions` :1839, `DialogError` :1831, `Field` :2188, `Th` :2208, `TableSkeleton` :2218. (Audit's ":667-2065" confirmed exactly.)
- **payments/page.tsx (1,822L):** `ReconciliationReportPanel` :676 (+ `ReconciliationReportSummary` :744), `PaymentActions` :814, **6 dialogs**: `GenerateDialog` :884, `DiscountDialog` :991, `MarkPaidDialog` :1060, `InvoiceDialog` :1165, `SyncStripeDialog` :1472, `RefundDialog` :1612; chrome `RallyDialog` :1711, `DialogActions` :1747, `Alert` :1756, `SummaryRow` :1764, `Th` :1773, `Field` :1791, `TableSkeleton` :1814. (Audit's ":676-813 / :884-1710" confirmed.)
- Shared chrome duplication confirmed: `RallyDialog`/`DialogActions`/`Field`/`Th`/`TableSkeleton` appear in payments + sessions; students has its own `Field` (its dialogs share the file's chrome). Signatures **differ slightly** between copies (payments `DialogActions` takes `{onCancel, submitLabel}`; sessions takes `{children}`) — unification needs a superset API.
- `frontend/components/ds/` today: avatar, button, card, charts, chip, icons, lane, shuttle, typography — **no dialog/modal, form field, table, or skeleton primitive** (that's DS3's scope).

## Proposed change

Mechanical extraction, no behavior change, one PR per page, preceded by one PR that lifts the shared dialog chrome into `components/ds`. Components move verbatim into sibling files; the page keeps state/hooks and composes imports.

## Implementation steps (each phase = one PR)

**Phase 0 — shared chrome → `components/ds` (S, do first).**
1. Check DS3 status in ../TRACKER.md. If DS3 is DONE, use its `Modal`/`FormField`/`Skeleton` primitives directly and skip creating `RallyDialog` — map each page's `RallyDialog` usage onto `Modal` during Phases 1-3. If DS3 is TODO, proceed:
2. Create `frontend/components/ds/dialog.tsx` (`RallyDialog` with the superset of the three copies' props, `DialogActions` supporting both the `{onCancel, submitLabel}` and `{children}` forms, `DialogError`), `components/ds/form-field.tsx` (`Field`), `components/ds/table.tsx` (`Th`, `TableSkeleton`). Export from `components/ds/index.ts`.
3. Diff the three copies first (`git diff --no-index` on extracted snippets) — reconcile deliberately; note that none of the current copies implement focus trap / Escape / focus-return (audit DS3 finding). Do NOT add that behavior in this PR (mechanical = no behavior change); leave a `// TODO(DS3)` marker.
4. Point all three pages at the shared imports; delete local copies.

**Phase 1 — payments/page.tsx (S-M).** Create `frontend/app/(admin)/admin/payments/` siblings: `ReconciliationReportPanel.tsx` (:676-813 incl. Summary + `Metric` :665), `dialogs.tsx` or one file per dialog (:884-1710, six dialogs + `PaymentActions`), moving each function + its local types verbatim. Page shrinks to ~600L of state + table. Props = exactly the identifiers each function already closes over (the compiler enumerates them).

**Phase 2 — sessions/[id]/page.tsx (M).** Extract to `frontend/app/(admin)/admin/sessions/[id]/`: `RosterPanel.tsx` (RosterMetrics/RosterMetric/RosterTable/LevelSelect/DuesChip/EnrollmentHistory), `WaitlistTable.tsx`, `dialogs/` (7 dialogs + `ReplacementCoachTable` + `RallySessionPicker` :1721 + the Student/Coach/Day selectors), `format.ts` (the pure helpers :100-202 and :2145-2173). Keep `DETAIL_TABS`/chip maps in the page or a `constants.ts`.

**Phase 3 — students/[studentId]/page.tsx (M).** Extract `BillingWorkflowPanel.tsx` (:628-1294), `SessionsPanel.tsx` (:1295-1939), `billing-dialogs.tsx` (:1940-2313, four dialogs), `StudentEditForm.tsx` (:2471+). Page keeps the tab shell (`overview`/`billing` tabs at ~:83-100) and data fetching.

Rules for all phases: no logic edits, no prop renames, no hook reshuffling; `"use client"` at top of every extracted file; types imported from their existing `lib/api` sources, local interfaces move with their component. Re-verify line boundaries with `grep -n "^function " <page>` immediately before each phase — they drift.

## Files to change

- New: `frontend/components/ds/{dialog,form-field,table}.tsx` + `index.ts` export (Phase 0, unless DS3 supplies them)
- `frontend/app/(admin)/admin/payments/page.tsx` + new sibling component files
- `frontend/app/(admin)/admin/sessions/[id]/page.tsx` + new sibling files
- `frontend/app/(admin)/admin/students/[studentId]/page.tsx` + new sibling files

## Tests & verification

- Per phase: `pnpm typecheck` (note QW6: local typecheck may fail on stale `.next/types` — `rm -rf .next` first if QW6 hasn't landed), `pnpm lint`, `pnpm exec playwright test --project=chromium-mobile` (existing specs `admin-students.spec.ts`, `billing-health.spec.ts`, `qa-defects.spec.ts` etc. cover these pages).
- Manual smoke per phase in the local stack (`scripts/local_test_stack.sh fresh`): open each dialog, submit one mutation, confirm error banner still renders (`role="alert"` pattern).
- `git diff --stat` sanity: page line count drops by ≈ extracted lines; extracted files should be near-verbatim moves (review with `--color-moved=dimmed-zebra`).

## Risks / rollback

- These are the highest-traffic admin billing surfaces; the only real risk is accidental logic drift during the move — mitigated by verbatim moves + moved-code diff review + existing e2e specs.
- Merge conflicts with in-flight work on the same pages: check open PRs touching these paths before starting a phase; land quickly.
- Chrome unification (Phase 0) is the one place behavior could shift (superset props) — keep render output pixel-identical; screenshot-compare one dialog per page.
- Rollback: per-phase PR revert; no data or API changes.

## PR checklist

- [ ] Release note (per AGENTS.md `docs/release-notes/`)
- [ ] TRACKER.md updated
- [ ] Plan Status flipped to DONE
