# batch-9b-admin-inbox-shell-payroll

PR: #854

## What changed

- Fixes #841 — Queues, admin DMs and the coach Needs-review tray no longer print machine values. Makeups/trials now carry the class title and start instant behind each occurrence id (batched, tenant-scoped `get_many` joins mirroring `ListSelfCancellationsForAdmin`), plus the trial student's name. The makeup approval dialog's free-text "paste an occurrence id" input is replaced by the same real date picker trials already use.
- Fixes #842 — The admin dashboard now leads with "Needs your attention" above the KPI tile strip, the Sessions-today tile is a link to `/admin/sessions` like the other tiles, the sidebar's Inbox nav row shows a pending-count badge fed from the existing `/admin/inbox/counts` endpoint (same React Query cache key the Inbox page already uses, so no new polling), and the sidebar's account/user block was compacted so all three nav groups (including COMMS · OPS) fit within a 1280x900 viewport without internal scrolling.
- Fixes #845 — Payroll status mislabel: `PayslipsPanel` used to derive a coach's chip from `paid_at` alone, so an approved-but-unpaid payslip showed DRAFT instead of APPROVED. It now also queries this month's payroll status via `listMonthlyPayroll` and maps status + `paid_at` through a new shared, unit-tested `payslipChipFor` helper (`frontend/lib/payslip-chip.ts`), which the Payroll tab's status chip now reuses too. Added the missing error state on the Payroll tab's query (previously only `isLoading` was checked, so a failed fetch silently rendered an empty table). Also fixed money formatting on the Payroll table ("$900.00" instead of "900.00 usd") via a new shared `frontend/lib/format-money.ts`, and swapped the bespoke amber "unresolved" pills for the DS `Chip` component. Scoped narrowly to the real behavior change plus its directly-adjacent visual pass on `frontend/app/(admin)/admin/payouts/*`.

## Deploy notes

Frontend and backend interface-layer changes only. No new migrations, no new environment variables, no backend schema changes. The `#841` fix adds batched `get_many` joins reused from existing admin queue lookups — no new endpoints or indexes required.

## Risk / rollback

Low. Changes are additive UI/readability fixes (name resolution in queues, dashboard/sidebar layout, payroll status/error-state/money-formatting corrections) with no data or schema impact. Full backend gate (pytest, ruff check/format, lint-imports, mypy-baseline) and frontend gate (tsc, eslint, `next build --webpack`) pass on the branch. To roll back, revert this PR's merge commit.
