# opennext-next-16-4-worker-crash

PR: #1086

## What changed
Restores the frontend. Since the #1082 deploy, every Worker request had returned HTTP 500 (Cloudflare 1101). `@opennextjs/cloudflare` 1.20.6 predates Next 16.4 support, so every request threw `Unexpected loadManifest(/.next/server/preview-props.json)`. Bumped it to 1.20.14 (`@opennextjs/aws` 4.1.13). Next stays at 16.4.1, so the advisory fix is kept.

CI: Frontend Static now builds with `opennextjs-cloudflare build` and runs `scripts/smoke/worker_runtime_smoke.sh`. The script serves the built Worker in local workerd and fails on any 5xx. A Workers-runtime break now blocks the merge and the deploy instead of reaching prod.

## Deploy notes
Frontend only. No migrations, no backend change. After deploy, check that academy.courtmastr.com and blno-academy.courtmastr.com return 200 (Production Smoke does this).

## Risk / rollback
Low: a patch-level bump within the OpenNext 1.20 line, with the Worker verified locally on `/`, `/login`, `/admin`, `/parent` and `/coach`. If the Worker misbehaves, roll back `academy-next` in the Cloudflare dashboard to the version deployed before 2026-10-29 (Next 16.3), knowing that reopens the Next advisory.
