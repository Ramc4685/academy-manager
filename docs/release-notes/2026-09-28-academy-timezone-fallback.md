# Academy timezone replaces the Chicago fallback; return links on the academy host

PR: #995

## What changed

- Batch A of the hardcoded-values cleanup (HARDCODED.md rows 7, 19, 9, 24).
- One `LEGACY_FALLBACK_TIMEZONE` constant, in `shared/time/academy_timezone.py`, replaces 15 hardcoded `America/Chicago` fallbacks. A session's time zone resolves as the session zone, then the academy zone, then the legacy zone. A structural test bans the literal anywhere else in backend/v2.
- Coach Today, Sessions and the skill day hub fill a zoneless session's time zone from the academy. The frontend session-time helper uses UTC only as a last resort. The admin teaching-plan dropdown shows session-local time instead of UTC.
- The add-card reminder's Stripe return URL and the Stripe Connect link, refresh and callback-success redirects are built from the academy's slug. They fall back to `FRONTEND_URL` if the slug is missing or not a DNS label, and never use the request Host.
- Scheduler loops add the fallback academy only in `single_academy` mode.

## Deploy notes

- No migration, no new env vars, and no scheduler hour or `SCHEDULER_TZ` change.
- Before deploy, run a read-only check that prod `academies.slug` for `acad_blno_badminton` is `blno-academy`. BLNO's add-card and Connect return links move to that host.

## Risk / rollback

- Low for BLNO. Its sessions and its academy both use America/Chicago, so bills, quotes, occurrences, emails and coach times are unchanged (pinned by tests).
- The visible changes are the return-link host and the corrected teaching-plan times.
- Rollback: revert this PR's merge commit. No stored data changes.
