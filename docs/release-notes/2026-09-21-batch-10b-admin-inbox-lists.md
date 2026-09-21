# batch-10b: admin inbox lists

PR: #0

## What changed
- Fixes #863 — Admin settings no longer drops unsaved edits when switching tabs: every editable panel publishes its existing dirty flag through a new settings-scoped React context, and the tab strip confirms ("You have unsaved changes on this tab. Leave without saving?") before navigating. Dismiss keeps the panel and the typed value; accept navigates.
- Fixes #860 — Pauses had no phone layout at all: the sticky Decline/Approve cell sat over the session, pause dates and reason, so an admin decided blind. It now renders through the shared `PhoneListRow` below md, with every decision fact above a 44px actions menu that routes into the same confirm dialog the desktop table uses (table path unchanged).
- Fixes #864 — Admin direct messages now show unread state, a last-message preview and a time on every thread row, and opening a thread clears its unread marker (same mark-on-open the coach and parent inboxes already had).
- Fixes #865 — All four remaining People items landed, frontend-only, no new route and no new endpoint.

## Deploy notes
No migrations. Frontend-only changes; no new routes or endpoints. Standard deploy.

## Risk / rollback
Low risk: scoped to admin settings tabs, admin pause-request rows, admin messages inbox, and admin People views. No backend/data changes. If a regression appears, revert this PR's merge commit.
