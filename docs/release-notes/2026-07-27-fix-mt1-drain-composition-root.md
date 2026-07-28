# fix-mt1-drain-composition-root

PR: #368

## What changed
MT1 Phase A: moved the admin billing money math out of the composition root
into the billing application layer. The 34 pure helper functions that lived in
`backend/v2/composition/admin.py` (cents/dollar conversion, payment and invoice
amount semantics, report date coercion, and the Mongo effective-date window
query builders) now live in
`backend/v2/contexts/billing/application/admin_money.py` as public functions,
and `compose_admin` imports them instead of defining them. Bodies moved
verbatim — only the leading-underscore names became public, so no report,
payment row, or payout figure changes. `composition/admin.py` shrinks from
7,219 to 6,870 lines. Added `backend/v2/tests/contexts/billing/test_admin_money.py`
(19 tests) pinning the money-path semantics the production-readiness audit
flagged: `payment_final_amount_cents` field-precedence and discount clamping,
`payment_collected_cents` refund netting, `invoice_outstanding_cents` terminal-
status handling, and `invoice_to_admin_payment_row` status mapping plus
Stripe-linked detection.

Phases B–E of the MT1 plan (reports read models, payout logic, email adapters,
import-linter contract) remain TODO and are tracked as follow-on PRs.

## Deploy notes
None — pure code move inside the backend. No migrations, no new env vars, no
API surface change.

## Risk / rollback
Low risk: behaviour-preserving refactor with no signature or logic changes;
the existing composition contract tests exercise the same closures unchanged.
Rollback: revert this PR — no data migrations involved.
Verified: full backend `v2/tests` suite (2609 tests) green, `ruff check v2` and
`ruff format --check v2` clean, `lint-imports --config pyproject.toml` 5/5
contracts kept, and `mypy -p backend.v2` filtered against the frozen baseline
reports no new errors.
