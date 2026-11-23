# push-exact-destinations

PR: #1232

## What changed
Tapping a push now opens the exact thing it is about. Message pushes (direct
messages, academy broadcasts, class announcements, urgent announcements) open
the inbox scrolled to and outlined on that message (`?message=<id>`); an admin
receiving a DM opens that thread (`?dm=<sender>`). A cancelled class date opens
the parent calendar list on that date (`?occurrence=<id>`), and an academy
closure opens the calendar instead of the home screen. A link to a message or
date that is gone or not this family's shows a short note above the normal page.

## Deploy notes
None. No migration, no env var, no native or push-certificate change; the app
shell's tap handler and `safeAppPath` check are unchanged.

## Risk / rollback
Payload URLs and two read-only page params only. If a new link misbehaves the
page still loads in full without the highlight. Roll back by reverting the PR.
