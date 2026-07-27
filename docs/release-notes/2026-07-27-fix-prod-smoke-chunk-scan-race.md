# fix-prod-smoke-chunk-scan-race

PR: #367

## What changed
Hardened the Firebase-config check in `scripts/smoke/production_smoke.sh`
against frontend deploy races. Production Smoke on run 30303994791 fetched
`https://academy.courtmastr.com/login` while the Fly frontend rollout was still
in flight, got HTML that referenced a `_next/static` chunk from the outgoing
build, spent ~35s inside `curl --retry-all-errors` re-requesting that single
404 URL, and then reported `built Next.js chunks do not contain Firebase
project academy-courtmastr` — even though the deployed build was fine (the live
`/login` page serves 15 chunks and `7333-e5d862deb342d9d2.js` contains the
project id).

The login-HTML fetch and the chunk scan are now retried together as a unit
(`CHUNK_SCAN_ATTEMPTS`, default 6, `CHUNK_SCAN_DELAY_SECONDS`, default 10), so
a stale HTML snapshot is simply re-fetched on the next pass instead of poisoning
the whole check. Individual chunk fetches use a new `curl_chunk` helper with a
minimal retry budget so one dead URL can no longer consume the job's time. Real
failures now print the list of chunks that were actually scanned. The
`Production Smoke` job timeout in `.github/workflows/production.yml` goes from
5 to 10 minutes to cover the new retry budget.

## Deploy notes
None — CI-only change. No migrations, no new env vars, no application code
touched. `CHUNK_SCAN_ATTEMPTS` and `CHUNK_SCAN_DELAY_SECONDS` are optional
overrides with working defaults.

## Risk / rollback
Low risk: the check's pass/fail semantics are unchanged — it still requires the
expected Firebase project id to appear in a served login chunk, and still exits
1 when it does not. The only behavioral change is how long it waits before
concluding that, so the failure mode moves from "flaky red on a healthy deploy"
to "slower red on a genuinely broken one". Rollback: revert this PR.

Verified against live production: the updated script passes end to end
(`Production smoke checks passed`), and the failure path was exercised with a
deliberately wrong `EXPECTED_FIREBASE_PROJECT_ID` — it retried, then exited 1
with the full scanned-chunk list. `bash -n` clean.
