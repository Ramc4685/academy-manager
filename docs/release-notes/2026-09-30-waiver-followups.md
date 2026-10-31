# Waiver follow-ups after several live waivers

PR: #1023

## What changed

- Admin waiver report (`GET /admin/waivers`): now per waiver. `lineages` carries one entry per live waiver with its own counts (signed current, pending, outdated) and its own student rows, counting only the students the waiver applies to (all families, or families with a live class in its programs). The Waivers screen shows one block per waiver when more than one is live. The top-level `summary`, `current_waiver` and `waivers` fields are the primary waiver's (the first all-family waiver), so a one-waiver academy such as BLNO reads the same numbers as before.
- A live waiver nobody is asked to sign (not assigned) is listed with zero students instead of counting every student as pending.
- Dashboard setup checklist: the waiver step is done when at least one live waiver of any lineage exists that is not still the bootstrap placeholder. Drafts and superseded versions no longer count.
- Registrations queue (Inbox): an application with an unsigned required waiver now shows an UNSIGNED chip naming the waiver(s). It is a warning; approval is never blocked.
- Archiving a program (`POST /admin/programs/{id}/archive`) still succeeds, and the response now lists `assigned_waivers` and a `warning` naming the live waivers still assigned to it. Public page > Programs shows the warning with a link to Family policies. In the waiver Assign panel an assigned-but-archived program reads "Archived: name" so the admin can untick it; it is never offered as a new choice, and keeping it on save is refused.
- Waiver detail page: the old "Require for registration" button is replaced by a link to the Assign control in Settings > Family policies. `POST /admin/waivers/templates/{id}/assign-registration` still works for clients loaded before the deploy and is marked deprecated.
- New Playwright spec `parent-onboarding-class-first.spec.ts`: program-scoped waiver gives parent, child, class, waiver, review; only an all-family waiver keeps parent, child, waiver, class, review.

## Deploy notes

- No migration. Backend and frontend can ship in either order: the new response fields are additive and the old frontend keeps reading the primary waiver's fields.
- BLNO (one all-family waiver): same report numbers, same checklist result, same onboarding order.

## Risk / rollback

- Low. Read-side changes plus one additive field on the archive response. The report reads `lineage` and assignment with the same read-time defaults the parent page uses, so the admin and parent views agree.
- Behaviour change to know: an academy whose only live waiver is not assigned to anyone now shows 0 students against it (before, every student read as pending). Rollback is a revert of the PR; nothing new is stored.
