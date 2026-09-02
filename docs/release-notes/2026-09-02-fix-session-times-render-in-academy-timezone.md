# fix-session-times-render-in-academy-timezone

PR: #624

## What changed
Parent-facing session times now render in the **academy's** timezone instead of
the viewer's browser timezone, and the parent catalog API now carries the zone
needed to do that.

Production symptom: on the parent "Review & pay" screen a real 6:00 PM class
displayed as `Sep 3, 1:00 PM - 1:45 PM` — off by exactly five hours
(America/Chicago CDT, UTC-5), on the screen where the parent commits to paying.
The weekday was right, so the error read as plausible rather than obviously
broken.

Ground truth established before fixing: **`start_at` is written as a genuine
tz-aware UTC instant everywhere in the backend.** `admin_writes.py`
(`_representative_series_datetimes`), `mongo_session_repo.py`
(`synthesize_recurring_session_docs`) and `mongo_monthly_billing.py`
(`_session_occurrences`) all combine the local wall clock with `ZoneInfo(...)`
and `.astimezone(UTC)`. There is no path that stores a naive local wall clock
and calls it UTC. The write arithmetic is correct — but only as correct as the
session document's own `timezone` field.

Three distinct defects were found in the chain; all three are fixed:

**1. The admin form defaulted the session timezone to the literal `"UTC"`
(data defect — the likely owner of the five hours).**
`app/(admin)/admin/sessions/page.tsx` used `DEFAULT_TIMEZONE = "UTC"` whenever
`getAdminAcademy().timezone` was null (which `composition/parent.py:2032` shows
is possible). A 6:00 PM class then stores as `18:00Z`, which *is* 1:00 PM in
Chicago — matching the report exactly. The same fallback in
`app/(admin)/admin/sessions/[id]/format.ts` meant **editing** any session with a
null timezone silently rewrote it to UTC. This corrupts billing and payroll, not
just display, because monthly invoicing and payroll re-derive occurrences from
the same field.
- The create dialog now seeds from the academy zone, falling back to the admin's
  browser zone (never a guessed "UTC"), and exposes it as a **visible, labelled,
  editable** field with a warning when the academy has no zone configured.
- `buildEditSessionForm`'s fallback is now `null` — the browser no longer
  asserts a zone nobody chose; the backend applies its own default instead.
- `CreateSession` now persists the **effective** zone rather than `None`, so a
  document is never left interpretable only by a reader that happens to share
  this module's private default.

**2. The parent onboarding page rendered in the browser zone (rendering
defect).** `formatSessionTime` called `toLocaleTimeString(undefined, …)` with no
`timeZone`, and the page had no timezone data available to it at all — it never
called `/parent/academy`. It now fetches the academy and renders via a new
`lib/format/session-display.ts` built on the existing `lib/format/academy-time`
helpers, which append an explicit zone label ("CDT") so a fallback to the
browser zone is *visible* rather than silent.

**3. The catalog endpoint emitted two incompatible timestamp shapes
(serialization defect).** `GET /parent/sessions/available` returned `…Z` for
recurring rows synthesized in Python and **offset-less naive** strings for dated
rows read from Mongo, because the Motor client is built without `tz_aware=True`.
JS `new Date()` parses an offset-less string as browser-**local** wall clock, so
two rows in the same array meant opposite things. A new `ensure_utc()` re-stamps
UTC on read in the catalog, so every timestamp in the payload now ends in `Z`.
(Done locally rather than by flipping `tz_aware=True` in `main.py`, which would
change every read in the app at once.)

API contract addition (additive, nullable): `ParentAvailableSession` /
`ParentAvailableSessionView` now carry `timezone: str | None`. Null means
"unknown — fall back to the academy zone", never "UTC". Synthesized recurring
rows also report the zone their instants were actually computed in.

Also swept, same defect class, since the zone was already at hand:
admin session list and detail time/date rendering, and the occurrence times in
`ReplacementCoachTable`.

## Deploy notes
No schema migration ships with this PR, and **nothing in it moves an existing
class**: re-stamping `Z` and rendering in the academy zone change no stored
instant. New sessions stop being created with a wrong zone.

**The data repair already ran.** PR #615 (commit `04688f0b5`) rewrote the four
affected prod session rows and their 13 occurrences to `America/Chicago`,
applied and verified against production on 2026-09-01. That PR changed no
application code, so until this one deploys the bad data is one admin edit away
from coming back — `buildEditSessionForm`'s `"UTC"` fallback rewrote the zone as
a side effect of editing anything else on the session. Deploying this PR is what
makes #615 stick.

No further data work is required for `blno-badminton`. If another academy is
onboarded, note that bootstrap now **requires** a validated IANA zone rather
than defaulting to `"UTC"`, and `academies.timezone` reads back as `null` (not
`"UTC"`) when unset, so an operator is prompted instead of silently inheriting a
zone nobody chose.

Sessions whose academy has no timezone set now fail closed on create/edit with a
422 and an actionable message ("Set your academy's timezone in Settings →
Academy") rather than being written with a guessed zone. Read paths never raise:
a legacy row with neither its own zone nor a resolvable tenant zone falls back to
`LEGACY_FALLBACK_TIMEZONE` and **logs a warning** so the case is visible.

## Risk / rollback
Low risk. The API change is additive and nullable, so an un-deployed client
ignores it. The rendering change is display-only. The admin-form change alters
what *new* sessions record, in the safe direction (academy zone instead of a
hardcoded "UTC").

Known remaining sites, deliberately out of scope (same defect class, each needs
its own API contract change to carry a zone — the occurrence payloads have no
`timezone` field): `app/(student)/student/schedule/page.tsx`,
`app/(student)/student/dashboard/page.tsx`,
`components/teaching/admin-teaching-plan.tsx`,
`app/(parent)/parent/progress/page.tsx`, `app/(parent)/parent/payments/page.tsx`
(date-only parsed as local), and `lib/time/session-time.ts`, whose
`sessionTimezone()` still defaults to `"UTC"` when passed a null zone. The admin
reporting stack (`admin/students/[studentId]/format.ts`,
`BillingEnrollmentsPanel.tsx`) pins `timeZone: "UTC"` deliberately and was left
alone — localizing it would recreate the #541 mismatch.

This PR also drains the session-series dedupe cluster
(`dedupe_session_series_rows` and its signature helpers) out of
`composition/admin.py` into `contexts/enrollment/infrastructure/`. That was
required by the wiring-budget ratchet, which sits at exactly 4800 lines on
`main` and whose docstring says to extract rather than raise the number; it also
removed two further hardcoded `"America/Chicago"` defaults, and folded
`admin.py`'s private `_as_utc_datetime` into the new shared `ensure_utc`. Pure
code movement — the dedupe behaviour is unchanged for a tenant in that zone and
now correct for tenants outside it. Covered by the existing admin session
interface tests.

Roll back by reverting this PR; parents then see browser-zone times again, and
new sessions can again be written with a guessed `"UTC"`.
