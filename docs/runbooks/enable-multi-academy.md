# Enable multi-academy mode in production

**Who:** the owner decides; a platform operator runs the steps.
**When:** once, before academy #2 goes live (Stage 0 of
[`onboard-academy-two.md`](onboard-academy-two.md)).
**What it is:** a config change shipped as a reviewed PR and an approved deploy.
It is never a console edit or a `fly secrets set` of the tenancy flags.

Production today runs `APP_TENANCY_MODE=single_academy` with
`PRIMARY_ACADEMY_ID=acad_blno_badminton` and `ENABLE_PLATFORM_ROUTES=false`
(`backend/fly.toml`). Every request is BLNO's, and requests for any other
academy are refused.

## What changes when you switch

| | single_academy (today) | multi_academy + SaaS |
| --- | --- | --- |
| Which academy a request belongs to | Always `PRIMARY_ACADEMY_ID` | The request host: `<slug>.courtmastr.com` or a verified custom domain |
| Where a user's access comes from | The `users` row (`academy_id` + `roles`) | `academy_memberships` only |
| Platform routes (`/api/v2/platform/*`) | Off | May be turned on; every route requires a platform admin |
| Boot guards | — | Refuses to start unless `V2_SAAS_MODE`, `V2_PLATFORM_BASE_DOMAIN` and `V2_PROXY_SHARED_SECRET` are set, and `V2_ALLOW_STATIC_TENANT_PARENT_WIRING=true` records your decision |

## Pre-flight (all must pass)

1. **Stage 0 of `onboard-academy-two.md` is fully ticked.** That covers the
   readiness doc, the SaaS smoke, the two-tenant isolation test, global unique
   indexes (#849), index drift, migrations and backups.
2. **The data is ready.** From a machine that can reach production Mongo (for
   example `fly ssh console -a courtmastr-academy-api`, which already has
   `MONGO_URL` and `DB_NAME`), run:

   ```bash
   python -m backend.scripts.multi_academy_preflight
   ```

   It is read-only. It must print `READY`. It checks that every academy has a
   slug, every academy has an active owner membership, and every active user
   has a membership in their academy.

   If users are missing memberships (anyone who registered while production
   ran single-academy), do a dry run of the backfill first and read what it
   would write:

   ```bash
   python -m backend.scripts.multi_academy_preflight --backfill-memberships
   ```

   Read the dry-run list before applying:
   - Rows marked `[REVIEW]` would grant owner, admin or billing. Confirm each one
     belongs to that academy today.
   - Users under "blocked by a non-active membership" were suspended or removed
     on purpose. The backfill never overrides that; decide each by hand in the
     Staff page.

   Then apply it. This is the only step that writes to the database, so the
   owner must approve it. It only inserts missing rows. It never touches an
   existing membership under any of the user's ids, and it skips disabled or
   deleted accounts. Owner, admin and billing rows are only written when you
   add `--include-privileged` after reviewing them.

   ```bash
   python -m backend.scripts.multi_academy_preflight --backfill-memberships --apply
   ```

   Re-run the plain check until it prints `READY`. Users listed under "no
   academy_id" are legacy rows; decide per row whether they belong to BLNO
   (set `academy_id`) or should be deactivated.
3. **BLNO's hosts resolve to BLNO.** In SaaS mode the host picks the academy.
   BLNO is served on `blno-academy.courtmastr.com` and on
   `academy.courtmastr.com` (`FRONTEND_URL`). Confirm that BLNO's slug is
   `blno-academy`, and that `academy.courtmastr.com` is a **verified** custom
   domain row for `acad_blno_badminton` (or that the owner accepts that host
   stops serving BLNO). Then run the host preflight for both hosts:

   ```bash
   python -m backend.scripts.tenant_host_preflight --host blno-academy.courtmastr.com
   python -m backend.scripts.tenant_host_preflight --host academy.courtmastr.com
   ```

4. **The proxy secret is shared.** Generate one random secret. Set it as the
   Fly secret `V2_PROXY_SHARED_SECRET` and as the Cloudflare Worker secret
   `BFF_PROXY_SHARED_SECRET` (the frontend proxy sends it in
   `x-cm-proxy-auth`). Both must hold the same value. Without it, SaaS mode
   refuses to boot. With the wrong value, the API ignores the forwarded host
   and tenant resolution fails, so every request is refused rather than
   served to the wrong academy.
5. **CORS covers the tenant hosts.** `CORS_ORIGINS` in `backend/fly.toml`
   lists every host that serves an academy.

## Switch it on

Open a PR that changes only `backend/fly.toml` `[env]`:

```toml
APP_TENANCY_MODE = "multi_academy"
V2_SAAS_MODE = "true"
V2_PLATFORM_BASE_DOMAIN = "courtmastr.com"
# Your recorded decision; the app refuses SaaS mode without it.
V2_ALLOW_STATIC_TENANT_PARENT_WIRING = "true"
# Optional: only if a platform admin needs the platform routes now.
ENABLE_PLATFORM_ROUTES = "true"
```

Leave `PRIMARY_ACADEMY_ID` and `HOUSE_ACADEMY_ID` as they are. The primary id
is unused in multi-academy mode. The house academy id still decides which
academy charges on the platform Stripe account.

Merge the PR when CI is green, then approve the production deploy.

## Verify (within 15 minutes of the deploy)

- The API health check (`/api/v2/healthz`) returns 200 and the machine is
  not crash-looping (`fly status -a courtmastr-academy-api`). A boot refusal names the missing setting in
  the logs: `fly logs -a courtmastr-academy-api`.
- On `blno-academy.courtmastr.com`, the owner, a coach and a parent can each
  sign in and see BLNO's data.
- The next scheduler tick logs per-academy work for BLNO. The 07:30 owner brief
  arrives for BLNO as before.
- A request with a forged `X-Forwarded-Host` sent straight to the API resolves
  by its real host, not the forged one.

## Roll back

Revert the `fly.toml` PR and deploy. Production is back in single-academy mode
on the next boot. Memberships written by the backfill are harmless in
single-academy mode, which ignores them, so leave them in place.
