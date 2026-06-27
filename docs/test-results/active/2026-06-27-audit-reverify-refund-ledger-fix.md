# 2026-06-27 — Audit re-verification + refund ledger-gap fix

## Problem / scope
Re-verify the prior code/config audit against current `main` (it was produced on
the now-deleted `feat/coach-payroll-datetime-hotfix` branch), then fix confirmed
defects with regression tests.

Branch: `main` @ `5235a9f3`. Backend v2 (FastAPI DDD).

## Re-verification results (5 prior findings)

| # | Finding | Prior | Now | Evidence |
|---|---------|-------|-----|----------|
| 1 | `charge.refunded` dropped for ledger-only charges | High | **STILL HELD → FIXED (this ledger)** | `_on_charge_refunded` looked up only legacy `payments`; autopay / invoice pay-link / balance-checkout write only `ledger_payments` |
| 2 | import-linter contract broken (interfaces→domain) | High | **FIXED before this session** | `lint-imports`: 4 kept, 0 broken |
| 3 | Coach roster `default_academy_id` baked at startup | High latent | **HOLDS, DORMANT** | `saas_mode=False` + roster mutation routes hard-disabled (403, no caller). Same pattern on `MarkAttendance`/`BulkMarkAttendance` writes (`composition/coach.py:324,332`) is likely reachable — needs separate check |
| 4 | In-process scheduler, no leader lock | Medium | **HOLDS** | `max_instances=1` added to 3 interval jobs, but resume job (`main.py:380-387`) + migration runner (`migrations/runner.py:39-54`) still have no atomic claim/leader election |
| 5 | import-linter nested-context glob hole | Medium | **HOLDS** | `contexts.*.domain` (single `*`) misses `contexts.platform.{audit,billing,governance}.domain`; `interfaces/platform/governance_routes.py:20` imports nested domain directly, escaping the gate. No structural backstop in `tests/structural/test_layering.py` |

Shared root cause for #1 and #3: v2 migration to new patterns (ledger repo,
per-request tenancy) not propagated to every call site.

## Fix implemented — Finding #1 (refund ledger gap)

Refunds of charges recorded only as a `LedgerPayment` (autopay direct charge,
invoice pay-link checkout, balance checkout) were silently dropped: the webhook
handler looked up the original payment only in the legacy `payments` collection,
returned early on `None`, recorded no refund, emitted no event, and left the
invoice reading as paid.

Change (TDD, RED→GREEN):
- `contexts/billing/domain/ledger.py` — `LedgerPayment.refunded_cents: int = 0`;
  `LedgerPaymentStatus` gains `"partially_refunded"`.
- `contexts/billing/application/ports.py` — `LedgerRepository.mark_payment_refunded(...)`.
- `contexts/billing/infrastructure/mongo_billing_ledger_repo.py` —
  implement `mark_payment_refunded` (atomic `find_one_and_update`); read
  `refunded_cents` in `_payment_from_doc` (defaults 0 for old docs).
- `contexts/billing/application/use_cases/handle_webhook_event.py` —
  `_on_charge_refunded` falls back to `_on_charge_refunded_ledger` when the legacy
  payment is absent. Mirrors legacy semantics: cumulative-amount idempotency,
  partial-vs-full status, `PaymentRefunded` event. **Does not** reverse invoice
  allocations (matches legacy path).
- Regression tests: `tests/application/test_webhook_handler.py`
  `test_charge_refunded_records_full_refund_for_ledger_only_payment`,
  `test_charge_refunded_ledger_partial_then_idempotent`.

### Open product question (flagged, not implemented)
Should a refund of an autopay charge **reopen** the allocated invoice
(balance/`partially_paid`)? Current + legacy behavior records the refund on the
payment but leaves the invoice paid. Out of scope for this bug; needs a product call.

## Verification
- `pytest -k "ledger_only_payment or ledger_partial_then_idempotent"` → 2 passed
- `pytest -k "billing or webhook or ledger or refund or stripe"` → 347 passed
- `ruff check` (changed files) → clean
- `lint-imports` → 4 kept, 0 broken
- mypy: zero errors on any added line (verified via single-root run)

## NOT committed
Working tree also contains an **unrelated concurrent session's** coach-payroll
datetime hotfix (`compute_payout.py`, `test_coach_payout.py`) — leave untouched;
stage only the 5 billing files if committing this fix.

## Fix implemented — Finding #5 (import-linter nested-context glob hole)

`interfaces/platform/governance_routes.py:20` imported
`contexts.platform.governance.domain.models.GovernanceActor` directly — a
direct interfaces→domain import that escaped the import-linter contract because
its globs used a single `*` (`contexts.*.domain`), which does not match the
two-segment nested path `contexts.platform.governance.domain`.

Change (TDD, RED→GREEN):
- `tests/structural/test_layering.py` — new
  `test_interfaces_do_not_import_context_domain_directly` (AST backstop; failed
  RED on the governance import, now green). This is the authoritative enforcer
  (catches nested contexts regardless of import-linter glob depth).
- `interfaces/platform/governance_routes.py` — import `GovernanceActor` from the
  application layer (`...governance.application.use_cases`, which already
  re-exports it). Interfaces→application is legal; the domain reach is now
  indirect (allowed). No behavior change.
- `backend/pyproject.toml` — deepened all 4 importlinter contracts with `*.*`
  variants so nested subcontexts are covered at the gate too (belt-and-suspenders).

Verified: structural tests 4 passed; `lint-imports` 4 kept / 0 broken WITH
deepened globs; governance/platform/layering tests 94 passed; ruff clean.

## Fix implemented — Finding #4 (scheduler), partial

The daily `process_scheduled_resume_actions` cron was the only scheduled job
missing `max_instances=1` (the other 3 have it). Added it
(`main.py:380-391`) — prevents a slow run from overlapping the next tick within
the process. Config parity change; py_compile + 25 resume/scheduler tests pass.

**Deferred (documented, not implemented):** cross-machine leader election /
atomic claim for the resume job and an advisory lock for the boot migration
runner. Safe today (single Fly machine, `auto_stop_machines=false`, no
autoscaling). This is an infra-architecture decision, not a code one — the
resume use case is *not* atomically claimed (`list_due` is read-then-act), so if
>1 machine ever runs concurrently, double-resume is possible. Track as a
SaaS/scale prerequisite.

## Finding #3 (coach tenancy) — DECISION: document, do not fix now

Re-scoped and **narrower than the audit implied**:
- `MarkAttendance` and `BulkMarkAttendance` ALREADY resolve `academy_id`
  per-request via `_current_academy_id()` (prefers `current_academy_id()`,
  falls back to the baked default only outside request context). **Not
  vulnerable.** The audit's "higher-priority attendance instance" was incorrect.
- Only `CoachAddStudentToRoster` lacks the per-request fallback, and it
  delegates to the **shared** `EditRosterAdd` (also used by the live admin
  path). Its routes are **hard-disabled** (`roster_routes.py:80,95` raise 403,
  no caller — dead code), and it is **dormant** (`saas_mode=False` makes the
  default academy the correct tenant).
- Fixing it invasively would risk the live admin roster flow for zero current
  benefit. Proper fix (thread per-request tenancy through `EditRosterAdd`, or
  give the coach use case the `_current_academy_id()` fallback) belongs to the
  SaaS-enablement workstream. **SaaS-rollout prerequisite, not a live defect.**

## Not done (needs direction / environment)
- Full "real-user" QA across every feature/role/route requires the app stack
  (Mongo + Firebase emulator + Stripe test keys) + sanitized production-scale
  seed data. Deferred: the worktree is contended by a concurrent coach-payroll
  session, so standing up servers/seeders here is unsafe.

## Final verification (whole backend)
- `pytest v2/tests` → **1605 passed**, 0 failed
- `lint-imports` → 4 kept, 0 broken
- ruff (all changed files) → clean
- mypy: my added lines type-clean (full-repo mypy blocked locally by a
  pre-existing dual-root `mypy_path` quirk; CI will validate)
