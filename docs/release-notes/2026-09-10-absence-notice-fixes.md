# absence-notice-fixes

PR: #708

## What changed

Parents submitting an absence notice from the portal got a 500 (Sentry COURTMASTR-FASTAPI-1): the Motor client returns naive datetimes and the occurrence repository passed one straight into a use case that compares against an aware `now`. Every enrollment repository that reads a BSON datetime now normalises it to UTC at the repository boundary (`ensure_utc`): session occurrences, makeup requests, trial requests, absence notices and the enrollment writer (which the hold repository delegates to). This also removes the same latent TypeError from five sibling paths: makeup request submit, makeup request approve, trial request approve, cancelling a session occurrence, and the hold-reminder scheduler job.

Admins and owners can now record an absence notice on a parent's behalf. `POST /api/v2/admin/self-service/absences` takes a student, a class and a class date (past dates allowed, for the phone call or note handed to the coach after the fact) and a "counts toward a make-up" flag. The notice carries a new `recorded_by_admin` flag (parent submissions leave it false, and documents written before the field existed read back as parent submissions), is stamped with the admin's user id, and the usual guards still apply: tenant-scoped student, active-or-paused enrollment in that class, one notice per student and date (409), wrong persona 404. The admin Requests › Absences tab gains a "Record absence" dialog and a Source column showing parent vs. admin-recorded rows.

Absence notices now notify someone. `SubmitAbsenceNotice` and the new admin record use case take an optional, best-effort notifier that runs after the notice is persisted and can never fail the write. It sends a NOTIFICATION-category staff alert to the occurrence's coach(es) (including a substitute) plus every admin and owner, and a TRANSACTIONAL parent confirmation stating whether the notice was in time for a make-up under the academy's minimum-notice hours; admin-recorded notices alert staff only, not the parent. The coach daily digest gains an "Expected absences today" block listing that coach's late-and-on-time notices for the day. Delivery uses the existing SMTP/Resend gate (`_build_email_sender`): dev/CI use the stub port; only staging/prod with `email_delivery_enabled` and a `RESEND_API_KEY` send real mail. Each notice is claimed once per audience, so a retried request cannot double-send.

Sentry blind spots (#707) found during the same investigation are also closed: authenticated requests now attach the Sentry user (`id` + persona, never email or name) and `academy_id`/`persona` tags to events; frame locals are kept but a PII scrubber redacts student and guardian names, phones and emails from them; the access log line for 5xx responses is WARNING instead of INFO; and the frontend API client now reports every 5xx and transport failure to `courtmastr-frontend`, tagged with the request id and fingerprinted per route, where before only route error boundaries captured anything. No new env vars are required — the existing `SENTRY_DSN` / `NEXT_PUBLIC_SENTRY_DSN` switches continue to gate everything.

## Deploy notes

No migration. After deploy, resolve Sentry issue COURTMASTR-FASTAPI-1 — the timezone fix removes its cause. The hold-reminder job stops crashing once any enrollment is held; nothing else to run by hand.

## Risk / rollback

The timezone change only stamps `tzinfo=UTC` on values that were already UTC instants, so stored data needed no repair; API responses for these models gain a trailing `Z` where they previously serialised offset-less, matching what the frontend already expects elsewhere. The notification pipeline is additive and best-effort: every send is wrapped, the write always wins, and each notice is claimed once per audience so a retry cannot double-send. The admin absence endpoint is additive (new route, new optional field with a safe default on read). The Sentry changes are additive and each SDK call is wrapped so a failure logs at DEBUG and never affects auth or the API client. Rollback by reverting.
