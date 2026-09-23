# Session messages reach held students' parents and alias-linked parents; /admin/parents opens the Families view (People CRM Phase 1)

PR: #924

## What changed

- **Session message audience (backend).** A message sent to a session's families used to resolve only enrollments whose status was the literal `"active"`, then looked parents up by `user_id` alone. Per the People CRM engineering spec (section 3.2, "Session campaigns (fix)") it now:
  - resolves enrollments in the roster-visible set (`ROSTER_VISIBLE` in `contexts/enrollment/domain/models.py`, which is `active` + `held` today), so the parent of a **held** student now receives session messages. Held students keep their seat and show on the class roster, so they are part of the class.
  - resolves parents alias-aware through the resolver's existing `_resolve_users_for_ids` helper: a student whose `parent_id` stores the parent's Firebase `auth_uid` (not their `user_id`) no longer drops that parent silently. Lookups stay on the current academy's user doc, or a legacy global doc, and never another academy's. When both exist the academy's own doc wins, and siblings in one class give the parent one message.
- **Who does NOT get session messages (unchanged):** parents of `paused`, `reclaim_pending`, dropped/withdrawn and deleted/cancelled enrollments. "Waitlisted" is not an enrollment status (the waitlist is its own collection), so waitlisted families are not in a session audience before or after this change. This is the spec's intended audience: the spec names `ROSTER_VISIBLE`, and that set does not include paused or waitlisted.
- Communications cannot import the enrollment context (Rule 5, no cross-context imports, `tests/structural/test_layering.py`). The resolver carries its own `SESSION_AUDIENCE_ENROLLMENT_STATUSES` mirror, and a test pins it equal to `ROSTER_VISIBLE`, so if the roster set changes that test fails until the mirror is updated.
- **`/admin/parents` bookmark (frontend).** The `next.config.ts` redirect and the fallback `redirect()` in `app/(admin)/admin/parents/page.tsx` now land on `/admin/families?view=families` instead of bare `/admin/families`. The bare URL becomes the People section's Today view once the People sub-nav ships, so this makes the bookmark name the Families view now. The Families page ignores `?view=` for now, so today the page renders exactly as before. Unit and e2e redirect assertions updated.
- Routes: zero added, zero removed.
- **Not in this PR:** the `/admin/students` redirect stub. Deferred by owner decision 2026-09-22 (engineering spec section 8, decision 3): the Students label and the `/admin/students` route stay as they are.

## Deploy notes

- No migration, no index change, no env var, no manual step. Deploy as normal.
- Browsers that cached the older 308 from `/admin/parents` to `/admin/users?role=parent` keep landing on the Staff page's parent banner; nothing server-side can clear that.

## Risk / rollback

- **Behaviour change: wider session message audience.** After deploy, parents of held enrollments get session announcements and session campaigns they did not get before. Parents linked only by `auth_uid` also start getting them. Expect a small rise in session-message volume. Support should know that a held family now hears about their class. Paused and waitlisted families still do not.
- Recipients can now also come from a legacy global user doc (no `academy_id`) for a parent referenced by this academy's own student record. That is the same rule the academy-wide and payment-risk audiences already use. Another academy's user doc is never read.
- Rollback: revert the PR. There is no data or schema state to undo.
