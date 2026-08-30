# parent-checkout-request-tenant

PR: #575

## What changed
`compose_parent` froze a single boot-time `academy_id` into the checkout-path
billing use cases (`StartCheckout`, `StartSubscriptionCheckout`,
`GetCheckoutStatus`) while `settings.tenancy_mode` defaults to
`multi_academy`. Had a second academy ever been served, a parent of academy B
starting checkout would have minted a payment record and Stripe metadata
stamped with academy A's id — visible in A's admin payment feed and invisible
to B's reconciliation — and B's autopay setup completion via the status poll
would have failed on the academy-mismatch guard. The three use cases now
accept a request-time academy provider and resolve it at execute time;
`compose_parent` wires the same `request_academy_id` helper the rest of the
file already uses (ContextVar tenant, fail-closed in `multi_academy` mode,
boot fallback only in `single_academy` mode so outbox/scheduler callers are
unchanged). Webhook processing stays per-academy by design: the scheduler
composes one `HandleWebhookEvent` per academy and the handler already
quarantines cross-academy events.

Three follow-up gaps from adversarial review are also closed:

- `EnrollChildInSessionType` (parent self-enroll, `POST
  /parent/billing-enrollments`) and its student-ownership lookup now resolve
  the academy at request time too, so the enrollment record and the Stripe
  autopay-setup checkout metadata carry the request tenant.
- Webhook INGEST (`POST /webhooks/stripe`, served by the boot-academy
  handler) now attributes each stored event to the academy it belongs to —
  `metadata.academy_id` from our own signature-verified checkout metadata
  first, then Connect `account` resolution, then the handler's academy — so
  another academy's events are drained by that academy's processor instead of
  being quarantined by the boot academy's.
- A fail-closed startup guard: `compose_parent` now refuses to compose when
  `saas_mode=True` and `tenancy_mode=multi_academy` (the config that actually
  serves multiple tenants) because some parent read paths still freeze the
  boot academy. The new `V2_ALLOW_STATIC_TENANT_PARENT_WIRING=true` setting is
  the documented, explicit acknowledgment for environments (like the local
  SaaS staging sandbox, where docker-compose.saas.yml now sets it) that accept
  the remaining static-tenant read paths until conversion finishes.

## Deploy notes
None beyond the normal deploy for today's launch configuration. No migration.
Production runs `APP_TENANCY_MODE=single_academy`, which the new guard does
not touch. Any deployment that sets `V2_SAAS_MODE=true` while leaving
`tenancy_mode` at its `multi_academy` default must now either flip to
`single_academy` or set `V2_ALLOW_STATIC_TENANT_PARENT_WIRING=true` — it will
refuse to boot otherwise, by design.

## Risk / rollback
Behaviour is identical in single-academy operation; the change only alters
which academy id is stamped when a request tenant differs from the boot
tenant, which cannot happen under the current launch guard. The one new
failure mode is deliberate: in `multi_academy` mode a checkout call with no
resolved request tenant now raises (fail closed) instead of silently stamping
the boot academy. The startup guard is the other deliberate failure mode: the
`saas_mode` + `multi_academy` combination refuses to boot without the explicit
acknowledgment flag. Webhook ingest attribution is best-effort and never
rejects an event: resolution failures fall back to the handler's academy, and
the existing processing-side guards remain the authority (they quarantine,
with alerting, anything genuinely misattributed). Roll back by reverting the
merge commit — the use cases still accept a plain string academy id, so older
wiring composes unchanged.
