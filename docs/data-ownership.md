# Data Ownership Map

**Status:** Authoritative. Referenced by [ADR-0005](adr/0005-clean-architecture-lite-monolith.md).
**Ticket:** P0-08
**Last reviewed:** 2026-05-16

This document is the contract for **who writes what**. Every Mongo collection in v2 has exactly one owning context. **Writes to a collection happen only through the owning context's application layer.** Reads are cross-context but always go through repositories — never raw Mongo from outside.

Cross-context state changes happen via **domain events** ([docs/event-rules.md](event-rules.md)), never direct DB writes.

## Why this matters

A bounded context is a *write-side ownership boundary*. The aggregate inside the context enforces invariants (capacity, idempotency, valid state transitions). If two contexts write to the same collection, neither can enforce invariants — the contract collapses. Reads are different: any context's read model can query any collection through a repository, because reads don't change state.

This map prevents that collapse.

## Ownership Table

| Collection | Owning context | Read by | Notes |
|---|---|---|---|
| `users` | Identity | All contexts (auth resolution) | Only Identity creates / mutates user records. Other contexts reference `user_id` but never edit `users`. |
| `sessions` | Enrollment | Coaching, Admin BFF | Coaching reads roster + session metadata; never writes. |
| `enrollments` | Enrollment | Coaching, Billing, Admin BFF, Parent BFF | Billing reacts to `Billing.PaymentSucceeded` by emitting a command to Enrollment, which confirms; Billing never writes `enrollments`. |
| `students` | Enrollment | Coaching (roster), Parent BFF (own child), Admin BFF | |
| `waitlist` | Enrollment | Admin BFF, Parent BFF | FIFO promotion is an Enrollment use case triggered by cancellation events. |
| `attendance` | Coaching | Admin BFF, Parent BFF (own child) | Idempotency keyed on `(academy_id, session_id, student_id)` unique. |
| `lesson_plans` | Coaching | Admin BFF | Coach-created, optionally admin-reviewed. |
| `progress_notes` | Coaching | Parent BFF (own child), Admin BFF | |
| `invoices` | Billing | Admin BFF, Parent BFF (own) | Source of truth for what is owed. Totals are derived from `invoice_lines`. |
| `invoice_lines` | Billing | Admin BFF, Parent BFF (own) | Itemized billing lines for tuition, fees, adjustments, and add-ons. |
| `ledger_payments` | Billing | Admin BFF, Parent BFF (own) | Source of truth for received money. Stripe/manual payments are allocated to invoices through `payment_allocations`. |
| `payment_allocations` | Billing | Admin BFF, Parent BFF (own) | Connects payments to invoices; must be idempotent. |
| `account_credit_ledger` | Billing | Admin BFF, Parent BFF (own) | Source of truth for credits and overpayments. |
| `payments` | Billing | Admin BFF, Parent BFF (own) | Legacy transition/archive only. New billing writes must not use this collection; retire via `docs/runbooks/legacy-payments-retirement.md`. |
| `subscriptions` | Billing | Admin BFF, Parent BFF (own) | |
| `payouts` | Billing (Finance subset) | Admin BFF, Coach BFF (self only) | Marked `# FINANCE` in code per ADR-0006 promotion trigger. |
| `expenses` | Billing (Finance subset) | Admin BFF | Marked `# FINANCE`. |
| `messages` | Shared `comms/` module | Admin BFF, Coach BFF, Parent BFF | Thin module per plan; no aggregate. |
| `announcements` | Shared `comms/` module | All BFFs | |
| `waivers` | Onboarding (lives inside Enrollment for now) | Admin BFF, Parent BFF | Promoted when waiver versioning gains independent rules. |
| `idempotency_keys` | `shared/idempotency` | shared | Crosscutting infrastructure. |
| `outbox_events` | `shared/events` | event dispatcher | Producer context writes; dispatcher reads + marks processed. |
| `event_handler_runs` | `shared/events` | event dispatcher | Idempotency record for handlers. |
| `dead_letter_events` | `shared/events` | event dispatcher + replay CLI | |
| `event_audit` | `shared/events` | observability | 90-day TTL. |
| `v2_migrations` | `shared/config` | migration runner | |
| `audit_logs` | shared (writer per context) | Admin BFF | Each context emits to a shared collection; no aggregate. |

## Rules

1. **One writer per collection.** If you find yourself wanting to write to another context's collection, you actually want to emit a domain event.
2. **Cross-context reads go through repositories.** Coaching's `SessionQuery` calls Enrollment's `MongoSessionRepository` (imported via the application port, not the infra class). Composition root wires the binding.
3. **No cross-context imports between `contexts/`.** Enforced by `import-linter` (ADR-0005). The interface layer composes both, OR they communicate via events.
4. **Events are the only cross-context state mutation channel.** A `PaymentSucceeded` event triggers an Enrollment command, which writes through Enrollment's repository. Billing never writes `enrollments`.
5. **Reads in the BFF compose; they don't bypass.** A coach BFF route that needs session + roster + lesson plan calls three application queries (one per relevant context) and stitches the response in `views.py`. It does not do its own Mongo joins.
6. **Shared collections (idempotency, outbox, audit) are infrastructure.** They are not domain data and are not subject to the one-writer rule.

## When a collection's ownership changes

If a collection needs to move ownership (e.g., `waivers` graduates from Enrollment to Onboarding):

1. New ADR documenting the move.
2. Migration to update any indexes if the leading filter changes.
3. Refactor the writing use cases to the new context.
4. Old context retains read access via the application port.

## When a new collection is added

1. Update this file with the new row before the migration is merged.
2. Identify the owning context. If you can't, the collection is probably a domain event payload masquerading as a collection — reconsider.
3. Add a tenant-isolation test for the new repository (ADR-0006).
4. Add `academy_id` as the leading field of every index.
