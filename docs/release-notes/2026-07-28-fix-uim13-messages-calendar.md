# fix-uim13-messages-calendar

PR: #PLACEHOLDER

## What changed
Coaches and parents can now read the messages admins already send them, and
see their schedule on a calendar. Backend: new `GET /coach/messages` +
`GET /parent/messages` read routes (`backend/v2/interfaces/{coach,parent}/messages_routes.py`)
over the existing tenant-scoped `messages` collection, plus
`POST /{persona}/messages/{message_id}/read` backed by a new idempotent
`MongoMessageRepository.mark_read()` (`$addToSet` onto `read_by`). No new
read model was needed — `MongoMessageRepository.for_recipient` already
returned each user's DMs plus academy announcements. Persona view models
deliberately expose only `message_id, kind, sender_persona, body,
created_at, read` — never `sender_id`/`recipient_id`. Frontend: real inbox
pages at `/coach/messages` and `/parent/messages` (grouped by day,
announcement vs DM styling, unread dot, mark-read on open with an
optimistic update, 30s polling), calendar pages at `/coach/calendar` and
`/parent/calendar` composing the existing `GET /coach/sessions` and
`GET /parent/children` + `/parent/children/{id}/schedule` endpoints via a
shared `PersonaCalendarView` FullCalendar wrapper (parent view is
colour-coded per child), and Messages/Calendar entries with an unread badge
in both persona headers. The `(shared)/messages` and `(shared)/calendar`
redirect stubs from UIC8 (#327) now point coaches and parents at these real
pages instead of falling back to `/post-login` and `/coach/sessions`.

## Deploy notes
None — no migrations, no new env vars. Purely additive read routes plus one
idempotent write to an existing collection and new frontend routes.

## Risk / rollback
Low. Reads are recipient-scoped (`for_recipient(claims.user_id)` returns
only the caller's DMs plus academy-wide announcements) and tenant-scoped by
inheritance from `TenantScopedRepository`, which threads `academy_id` into
every query; wrong-persona callers get 404, matching the repo convention of
not leaking route existence. `mark_read` only `$addToSet`s the caller's own
user id, so a replay or a wrong id is inert. Polling is 30s, per the plan's
guidance to avoid hammering. Rollback: revert this PR — all surfaces are
additive, and the `(shared)` stubs fall back to their previous redirect
targets.
