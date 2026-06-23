# Launch Readiness Agent Prompt

Use this prompt when continuing the launch-readiness work in this thread, a forked
thread, or bounded subagents.

## Required Skills

- `superpowers:subagent-driven-development`
- `testing-strategy`
- Repo rules from `AGENTS.md`
- `docs/agent/backend-api-rules.md`
- `docs/agent/frontend-rules.md`
- `docs/agent/testing-verification.md`
- `docs/agent/feedback-loop.md`

## Goal

Finish launch-grade SaaS/billing readiness without stopgap legacy payment
dependencies. The app ledger owns invoices, Stripe owns collection, and BFF/UI
surfaces must continue to work after the legacy `payments` collection is
archived.

## Subagents

Use read-only explorers first, then bounded workers only for disjoint write sets:

- Backend schema/index explorer: audit migrations, launch audit, validators,
  and missing natural keys.
- UI/persona explorer: audit admin, parent, coach, and support/platform flows
  affected by billing cleanup.
- Backend worker, if used: own only migrations/scripts/tests.
- Frontend worker, if used: own only frontend tests/UI files.
- Code reviewer: review final implementation after tests pass.

Workers must not revert unrelated dirty work. They must list changed files and
test results.

## Required Work

P0:

1. Expand launch billing audit:
   - invoice totals
   - payment allocations
   - credits
   - dead-letter counts
   - Stripe webhook replay/retry status
   - legacy-vs-ledger reconciliation
2. Add missing launch indexes:
   - `coach_attendance`: unique `academy_id + occurrence_id + coach_id`,
     history by `academy_id + coach_id + marked_at`, status lookup by
     `academy_id + status + marked_at`
   - `academy_settings`: unique `academy_id`, unique `settings_id`
   - required billing natural keys used by audit
3. Add billing-critical Mongo JSON schema validators:
   - `invoices`
   - `invoice_lines`
   - `ledger_payments`
   - `payment_allocations`
   - `subscriptions`
   - `enrollments`
   - `students`
   - `users`
   - `academy_memberships`
   - `stripe_webhook_events`
4. Verify no academy billing Stripe customer ownership remains on `users`.

P1:

5. Add broader validators for identity, enrollment, sessions, and curriculum.

P2:

6. Upgrade generic `outbox_events` to status/retry/lock model.

## UI/Persona Verification

Smoke and/or automate:

- Admin: `/admin`, `/admin/payments`, `/admin/dues`, `/admin/students`,
  `/admin/students/[studentId]`, `/admin/sessions/[id]`
- Parent: `/parent/payments`, `/parent/invoices`, autopay/card recovery
- Coach: attendance/payroll surfaces that depend on `coach_attendance`
- Support/platform: access grants, impersonation, audit/deletion/export queues

## Verification Commands

Run focused tests first, then full checks:

```bash
cd backend
source .venv/bin/activate
pytest v2/tests -q
ruff check v2 scripts

cd ../frontend
node --no-warnings --test lib/api/*.node-test.mjs lib/auth/*.node-test.mjs lib/*.node-test.mjs
pnpm typecheck
pnpm lint
pnpm build

cd ..
scripts/dev/pre-push-checks.sh --full
```

## Mongo Migration Verification

When a MongoDB migration adds validators, indexes, or collection options, do
not rely only on mongomock tests.

1. Identify whether the migration uses real MongoDB-only features:
   - `db.command(...)`
   - `collMod`
   - `$jsonSchema` validators
   - collection validators
   - advanced index options not fully supported by mongomock
2. Run the migration against a disposable real local MongoDB database. This
   proves the migration works on actual MongoDB.
3. Separately run the normal test suite that uses mongomock. If mongomock fails
   because it does not support a MongoDB feature, treat that as a
   test-environment compatibility issue, not automatically as a production
   migration bug.
4. Make migrations test-safe:
   - indexes should still run in mongomock when possible
   - validators/collMod should be skipped or guarded only when running under
     mongomock
   - real MongoDB behavior must remain unchanged
5. Add or update tests for both concerns:
   - mongomock test: migration runner does not crash
   - real MongoDB smoke/manual evidence: validators apply successfully
6. Do not claim launch readiness until:
   - focused migration tests pass
   - full backend tests pass
   - real MongoDB migration smoke passes
   - any skipped mongomock-only behavior is explicitly documented

If E2E dependencies are unavailable locally, record the skipped check and exact
reason in the active test ledger.

## Acceptance Criteria

- Launch audit fails on missing validators/indexes and passes when migrations
  are applied.
- Billing validators prevent bad document shapes without blocking known valid
  app writes.
- No new code writes parent Stripe customer ownership to `users`.
- Legacy `payments` can remain empty while admin/parent billing UI reads ledger
  data.
- Full backend/frontend/persona verification is run or explicitly recorded as
  blocked with a concrete reason.
