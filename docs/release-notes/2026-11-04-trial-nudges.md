# trial-nudges

PR: #PRNUM

## What changed
Three templated family emails now go out from the daily academy-local scheduler. A trial reminder goes the afternoon before an approved trial (16:00 local). It is claimed per assigned date, so a trial moved onto a new date after a cancellation is reminded again, and a cancelled date is skipped. A "we missed you" follow-up goes a few days after a trial marked "Didn't come" (10:00 local), unless the family has since booked another trial or enrolled. A "finish your registration" email goes for an expired Stripe checkout or a registration draft past its 7-day TTL (10:10 local), only for the parent's latest application and only if it was touched in the last 14 days. Each email is sent at most once per trial or application. A provider failure is retried on a later tick (bounded attempts); a parent with no address or who has opted out is skipped for good. The emails are under the academy's brand and go through the gated send path, so bounce suppression and unsubscribe preferences apply. All three follow a new Settings > Notifications switch, "Trial nudges" (`notifications.trial_nudges_enabled`), which is on by default and works like win-back.

## Deploy notes
Migration `0218_trial_nudge_sends` adds the unique `(academy_id, subject_id, digest_date)` index on the new, empty `trial_nudge_sends` claim collection. It applies through the normal `migrate-production` dry-run and `release_command` path. It is numbered after main's 0216 and slice 2's 0217. No new env vars. Because the switch defaults on, every academy starts sending on the first scheduler tick after deploy. Turn "Trial nudges" off in Settings > Notifications first for any academy that should not. Recovery never mails applications older than 14 days.

## Risk / rollback
If wrong, a family could get a reminder for the wrong date or an unwanted follow-up. The per-subject claim keeps a second run from sending twice, and the switch stops all three jobs per academy at once. Known limit: a trial approved for tomorrow after the 16:00 tick gets no reminder. Roll back by reverting the PR. The `trial_nudge_sends` collection and the settings key are harmless left in place.
