# absence-notice-706

PR: #TBD

## What changed

Parents submitting an absence notice from the portal got a 500 (Sentry COURTMASTR-FASTAPI-1): the Motor client returns naive datetimes and the occurrence repository passed them straight into a use case that compares against an aware `now`. Every enrollment repository that reads a BSON datetime now normalises it to UTC at the repository boundary (`ensure_utc`): session occurrences, makeup requests, trial requests, absence notices and the enrollment writer (which the hold repository delegates to). This also removes the same latent TypeError from makeup submit/approve, trial approve, cancel-a-date and the hold-reminder scheduler job. Contract tests over mongomock (which returns naive datetimes like real pymongo) cover each repository and each affected use case.

## Deploy notes

No migration for the timezone fix; stored data was always correct (BSON holds UTC instants). Post-deploy: submit an absence notice for a future class from the parent portal and expect 201, then resolve COURTMASTR-FASTAPI-1. Migration 0172 (added later on this branch) does NOT run automatically in prod because `V2_RUN_MIGRATIONS_ON_BOOT` is false there (#629); run `run_pending_migrations` by hand after deploy.

## Risk / rollback

Low. The change only stamps `tzinfo=UTC` on values that were already UTC instants; API responses for these models gain a trailing `Z` where they previously serialised offset-less, which is the shape the frontend already expects from Python-synthesised rows. `tz_aware=True` on the Motor client is deliberately NOT flipped (14 direct readers still assume naive). Rollback by reverting.
