# Onboard academy two

End-to-end steps for bringing a second academy live on CourtMastr, from the
platform operator creating the tenant to the owner's go-live. Every step links
to the runbook or screen that owns the detail; this file is the order of
operations and the gates between them.

Examples below use a synthetic academy: display name `Example Shuttle Club`,
slug `example-shuttle`, host `example-shuttle.courtmastr.com`, owner
`owner@example.com`. Never paste a real family's data into tickets or this
file.

Who does what:

| Role | Does |
| --- | --- |
| Platform operator (platform admin) | Stages 0-3 and 7: prerequisites, tenant, host, owner access, go-live flip |
| Academy owner | Stages 4-6: setup checklist, Stripe, staff, data, trial run |
| Engineer on call | Any code or migration a gate turns up; nothing here edits prod data by hand |

---

## Stage 0 - Prerequisites (once, before the first second academy)

Production has so far run one academy in single-academy mode
(`APP_TENANCY_MODE = "single_academy"` in `backend/fly.toml`). A second
academy needs the multi-academy regime (`V2_SAAS_MODE=true`,
`V2_TENANCY_MODE=multi_academy`; see PROJECT.md section 3.3 and
`DEPLOYMENT.md` "SaaS v2 Production Readiness"). Do not flip it until every box
below is ticked; the flip is an owner decision and a deploy, never a console
edit made mid-onboarding.

- [ ] `docs/requirements/2026-05-22-saas-production-readiness.md` has no open
      launch gate.
- [ ] `scripts/smoke/saas_readiness_smoke.sh --static-only` passes on the
      release commit, and the full smoke passes against a prod-like SaaS
      staging stack (`docs/runbooks/saas-local-staging.md`).
- [ ] The two-tenant isolation contract test
      (`backend/v2/tests/contract/test_two_tenant_isolation.py`) is green on
      the release commit. It enumerates every route; a new route with a path
      parameter must be seeded there.
- [ ] Unique indexes that are still global rather than per-academy (the
      backlog item for tenant-scoping them, #849) are fixed, or confirmed
      harmless for how academy two's data will arrive. A global unique index
      makes a second academy's legitimate row collide with the first
      academy's.
- [ ] `docs/runbooks/index-drift-audit.md` reports `ok: true` on production.
- [ ] Pending migrations are applied through the deploy pipeline
      (`docs/runbooks/migrations-rollout.md`), never by hand.
- [ ] Backups verified restorable (`docs/runbooks/backup-restore.md`).

## Stage 1 - Create the tenant (platform operator)

Platform console: `/platform/tenants`.

1. **Bootstrap academy** (`POST /api/v2/platform/academies/bootstrap`). Enter
   display name, slug, primary domain, owner email, owner name and the
   academy's real timezone (required: sessions, invoices and reminders all
   read it).
2. Bootstrap is idempotent by slug. The result says `created: true` the first
   time and lists the default records it wrote: academy, owner user and owner
   membership, academy settings, billing policy, a placeholder waiver, roles
   and feature flags.
3. Set the platform plan and limits on the tenant row if they differ from the
   default (`PATCH /api/v2/platform/tenants/{academy_id}/plan`).
4. Leave the platform application fee at its default of 0 unless the owner
   agreed otherwise (`/api/v2/platform/academies/{academy_id}/application-fee`).
5. Check `GET /api/v2/platform/tenants/{academy_id}/health` reports the tenant
   servable before moving on.

## Stage 2 - Register the host (platform operator)

Follow `docs/runbooks/tenant-host-onboarding.md` in full: Gate 0 (host
resolves), Gate 1 (Google OAuth origins and redirect URI), Gate 2 (Firebase
authorized domains), Gate 3 (redirect/CORS origins).

```bash
source backend/.venv/bin/activate
python -m backend.scripts.tenant_host_preflight --host example-shuttle.courtmastr.com
```

Do not continue until the preflight exits 0 and Google sign-in works on the
host in a private window. A custom domain comes later, after ownership is
verified, and goes through the same four gates.

## Stage 3 - Owner access (platform operator)

1. Bootstrap already created the owner's user and an `owner` membership for
   the owner email. No password is stored: the owner signs in with Firebase
   (Google, or email/password with a verified email) on the academy host.
2. Send the owner the host URL (`https://example-shuttle.courtmastr.com/login`)
   and ask them to sign in with exactly the email used at bootstrap.
3. Confirm the owner lands on `/admin` and sees **Set up your academy**. If
   they land on a parent or error screen, the email or the host is wrong: fix
   that before anything else, never by granting roles in the database.

## Stage 4 - Setup checklist (academy owner)

The **Set up your academy** card on the admin dashboard (`/admin`) lists
every step, reads its status from the academy's own settings, links to the
screen where the step is done, and disappears once everything is done. There
is nothing to tick by hand; a step turns done when the thing it names exists.

| Step | Done when | Where |
| --- | --- | --- |
| Academy details | Timezone and contact email set | Settings > Academy |
| Branding | Logo or brand colour set | Settings > Branding |
| Billing rules (owner) | Late fee and grace period chosen (0 is a valid choice) | Settings > Billing rules |
| Card payments (owner) | Stripe Connect account connected | Settings > Gateway |
| Session types | At least one active session type | Settings > Session types |
| First classes | A class scheduled in the next 30 days | Sessions |
| Invite your team | At least one staff account besides the owner | Users |
| Waiver | An active waiver that is not the bootstrap placeholder | Waivers |
| Public class page | Public page published | Settings > Public page |

A step showing **Couldn't check** means its source did not answer; reload, and
if it persists raise it with the engineer on call rather than treating the
step as done.

Notes for the owner:

- Billing rules and Stripe are owner-only. Admins see their status but the
  owner finishes them. Money-moving actions stay owner-only throughout.
- Stripe Connect: finish Stripe's onboarding until the account can take
  charges; the Gateway panel shows connected only once it is linked. A
  connected account that Stripe has not activated yet cannot take charges, so
  the Stage 6 test payment is the real proof.
- Staff tiers: give billing staff the **billing** role and the front desk
  the **front desk** role on the Staff page. Front desk sees an "owes money"
  flag only, never amounts.
- Sender identity: set the email sender name and reply-to on Settings >
  Academy so family emails come from the academy, not the platform.

## Stage 5 - Bring families in (academy owner)

There is no tenant-safe historical importer. `backend/scripts/import_blno.py`
is single-tenant, drops collections and refuses to run against a database
with more than one academy: never use it for academy two.

1. Classes: create them on **Sessions** (step "First classes").
2. Families: invite parents from **Users > Bulk invite parents** by pasting or
   uploading a CSV of names and emails. Each row gets a real login-invite
   email, so preview the batch before sending and send it only when the
   academy is ready for parents to sign in.
3. Parents then register their children and sign the waiver themselves; the
   owner approves registrations from the dashboard.
4. Balances carried over from a previous system are entered by the owner as
   invoices or credits in the app, one family at a time, never written into
   the database directly.

A bulk historical import (families, children, enrolments, balances) needs a
new tenant-scoped importer with `academy_id` on every document and selector.
Plan it as its own piece of work before promising it to an academy.

## Stage 6 - Trial run (academy owner, platform operator watching)

- [ ] The setup checklist card is gone from `/admin` (every step done).
- [ ] A test family (owner's own second email) registers a child for a class,
      signs the waiver and reaches checkout on the academy host.
- [ ] A real card payment of the smallest class price completes, lands on the
      academy's connected Stripe account, and the invoice shows paid after
      the webhook job runs (up to about a minute). Refund it from Stripe
      afterwards if the owner wants.
- [ ] A coach signs in on the academy host and sees only this academy's
      sessions.
- [ ] Nothing from the first academy appears anywhere in academy two, and
      the first academy's owner sees nothing of academy two.

## Stage 7 - Go live (platform operator)

1. Confirm Stages 2 and 6 again on the day: rerun the host preflight.
2. Activate the tenant if it is not already active
   (`POST /api/v2/platform/tenants/{academy_id}/activate`).
3. The owner sends the family invites (Stage 5 step 2).
4. Watch Sentry and the admin Billing Health page for the first week, and
   rerun `tenant_host_preflight` after any console change.

Rollback: suspend the tenant (`POST /api/v2/platform/tenants/{academy_id}/suspend`)
to stop it being served without touching its data. Deleting a tenant goes
through the governance flow (`/api/v2/platform/tenant-deletions`), never a
manual database drop.
