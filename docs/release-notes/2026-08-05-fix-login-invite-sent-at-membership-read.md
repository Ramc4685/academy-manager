# Login invite timestamp read from the membership row

PR: #402

## What changed
- `record_login_invite` writes `login_invite_sent_at` to the tenant's `academy_memberships` row, but `_to_admin_detail` read it back off the `users` doc, which nothing ever writes. `AdminUserDetail.login_invite_sent_at` was therefore always `None`, and the admin user-detail page permanently rendered "No invite sent yet" even after a successful send.
- This was not cosmetic. Because the page never reflected a sent invite, admins clicked "Send login invite" again; each call mints a new Firebase `oobCode`, which invalidates the link already emailed, so the parent clicks a dead link. This happened in production in `acad_blno_badminton`, where a parent's `users` doc carried no timestamp while the membership row did, and two invite POSTs returned 200 OK 13 seconds apart.
- `_admin_detail_for_doc` now sources the timestamp from the active membership, reusing the `_active_membership_for_doc` helper added in #400. `get_login_invite_user` passes the membership it has already fetched, so the fix adds no extra query on that path; `get_admin_user` gains one `academy_memberships` lookup per user-detail request.
- No frontend change was needed: the admin user page already renders "Invite sent &lt;date&gt;" and relabels the button "Re-send invite" once the field is populated.
- Adds two contract tests: one asserting the timestamp survives the write/read round trip through `get_admin_user` and `get_login_invite_user`, one asserting an invite sent in one academy does not read as sent in another.

## Deploy notes
No migration, environment variable, or manual deployment step is required. The timestamps were being written correctly all along, so already-invited parents show their real invite date as soon as the backend is deployed. No backfill is needed.

## Risk / rollback
Low. The change is read-side only — no write path, schema, or API contract changes, and the field stays scoped to `academy_id` + `status: "active"`, so one tenant's invite never surfaces in another. The one behavioural consequence is intended: admins will now see "Re-send invite" instead of "Send login invite" for already-invited parents, which is the whole point — re-sending invalidates the outstanding link. Revert PR #402 to restore the previous read; the page would again always show "No invite sent yet" and re-invites would resume breaking emailed links.
