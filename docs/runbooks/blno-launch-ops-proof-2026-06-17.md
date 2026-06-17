# BLNO Launch Ops Proof - 2026-06-17

Scope: BLNO release-candidate ops evidence for the current production apps:

- Backend: Fly app `courtmastr-academy-api`
- Frontend: Cloudflare Worker `academy-next`
- Database: MongoDB configured by Fly secret `MONGO_URL`

This proof intentionally avoids production data mutation, deploys, restarts, and rollback actions unless explicitly noted.

## Summary

| Area | Status | Evidence | Remaining Gap |
| --- | --- | --- | --- |
| Backend health | Pass | `fly status -a courtmastr-academy-api`; `fly checks list -a courtmastr-academy-api`; `curl https://api.academy.courtmastr.com/api/v2/healthz` returned `{"status":"ok"}` | None for basic health. |
| Frontend health | Pass | `curl -I https://academy.courtmastr.com` returned HTTP `200`; `wrangler deployments list --name academy-next` showed current 100% deployments. | None for basic reachability. |
| Secrets present | Pass | `fly secrets list -a courtmastr-academy-api` showed deployed secret names for Mongo, Stripe, Resend, Firebase, CORS, SaaS mode, and launch flags. Values were not read or printed. | None for name-level presence; value-level checks remain app-specific. |
| CORS | Pass | Production preflight from `https://academy.courtmastr.com` to `/api/v2/me` returned `access-control-allow-origin: https://academy.courtmastr.com`. | None for primary origin. |
| Logs | Pass | `fly logs -a courtmastr-academy-api --no-tail` showed health requests and `process_stripe_webhook_events` scheduler jobs executing successfully. | External log drain retention still not proven. |
| Backup/restore drill | Partial | Local Docker SaaS staging `mongodump`/`mongorestore` restored 31 collections and 1,077 documents into `academy_manager_restore_20260617033233`; count comparison had no mismatches. | Managed production backup and non-prod restore from a production backup are not proven. |
| Rollback | Partial | `fly releases -a courtmastr-academy-api` showed completed releases including current `v99`; `wrangler deployments list --name academy-next` showed Worker deployment history. | No actual rollback was executed. Production rollback rehearsal requires explicit approval. |
| Incident readiness | Partial | Incident checklist added in `docs/incidents/README.md`. | On-call owner, paging channel, and alert policy proof are still external/process items. |
| Alerting | Partial | Fly health check is active and passing. Worker observability is configured in `frontend/wrangler.jsonc`. | No proof of alert rules, paging route, OTLP sink, or external uptime monitor. |

## Commands Run

```bash
fly status -a courtmastr-academy-api
fly checks list -a courtmastr-academy-api
curl -fsS https://api.academy.courtmastr.com/api/v2/healthz
curl -I -sS https://academy.courtmastr.com
fly secrets list -a courtmastr-academy-api
fly logs -a courtmastr-academy-api --no-tail
curl -i -sS -X OPTIONS https://api.academy.courtmastr.com/api/v2/me \
  -H 'Origin: https://academy.courtmastr.com' \
  -H 'Access-Control-Request-Method: GET' \
  -H 'Access-Control-Request-Headers: authorization,content-type'
cd frontend && npx wrangler deployments list --name academy-next
```

Local restore drill:

```bash
docker compose -p saas-staging exec -T mongo sh -lc '
  archive=/tmp/academy-manager-saas-staging-20260617033233.archive.gz
  restore_db=academy_manager_restore_20260617033233
  mongodump --db academy_manager_saas_staging --archive=$archive --gzip
  mongorestore --archive=$archive --gzip \
    --nsFrom="academy_manager_saas_staging.*" \
    --nsTo="$restore_db.*"
'
```

Result:

```text
1077 document(s) restored successfully. 0 document(s) failed to restore.
source_collection_count=31
restored_collection_count=31
total_source=1077
total_restored=1077
mismatches=[]
```

## Rollback Runbook

Backend rollback requires an explicit production action approval before execution.

1. Capture current backend release:

   ```bash
   fly releases -a courtmastr-academy-api
   fly status -a courtmastr-academy-api
   ```

2. Identify the target previous healthy release from the release list.

3. Roll back only after approval:

   ```bash
   fly releases rollback <VERSION> -a courtmastr-academy-api
   ```

4. Verify:

   ```bash
   fly status -a courtmastr-academy-api
   fly checks list -a courtmastr-academy-api
   curl -fsS https://api.academy.courtmastr.com/api/v2/healthz
   ```

5. If rollback fails, capture logs:

   ```bash
   fly logs -a courtmastr-academy-api --no-tail
   ```

Frontend rollback requires an explicit production action approval before execution.

1. List Cloudflare Worker deployments:

   ```bash
   cd frontend
   npx wrangler deployments list --name academy-next
   ```

2. Roll back through Cloudflare/Wrangler to the selected previous Worker version, then verify:

   ```bash
   curl -I https://academy.courtmastr.com
   ```

## Backup/Restore Runbook

Preferred production proof is a managed MongoDB backup restore into a non-production database. That still needs provider-level access or approval for a controlled restore target.

Until that is available, the local restore drill command above proves the repository's Mongo dump/restore procedure and validates count parity after restore.

Minimum production-ready backup evidence still needed:

1. Confirm managed MongoDB backups are enabled.
2. Capture backup schedule and retention.
3. Restore latest production backup into a non-production restore database.
4. Compare collection counts and key launch indexes.
5. Delete the restore database after signoff.

## Incident Checklist

Use `docs/incidents/README.md` for the active checklist and incident note template.

