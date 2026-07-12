# feat: non-Google parent login — admin-created accounts + set-password invite

**Date:** 2026-07-09
**Branch:** feat/parent-login-invite
**Spec:** docs/superpowers/specs/2026-07-09-admin-coach-toggle-and-parent-invite-design.md (Enhancement 2)
**Plan:** docs/superpowers/plans/2026-07-09-parent-login-invite.md

## What changed

Parents on Yahoo/Hotmail/any non-Google email can now log in: the admin creates
their account and the system emails a branded **"Set your password"** link
(Firebase password-reset link, sent through Resend). No one-time passwords are
ever emailed; completing the link also marks the Firebase email verified, which
the password-login path requires.

### Backend
- `SendLoginInvite` use case (identity): generates a Firebase password-reset
  link, sends the branded email, records `login_invite_sent_at` on the user.
  Send failure raises (502) and does NOT record; invite state powers re-send UI.
- `FirebaseAdminAdapter.generate_password_reset_link`,
  `MongoUserRepository.record_login_invite`,
  `MongoAcademyRepository.get_academy_name` (email branding).
- `POST /api/v2/admin/users/{id}/login-invite` (admin-only; 404 unknown user,
  502 send failure). `create_user` and `bulk_invite_parents` auto-send the
  invite for parent creations, best-effort (creation never fails on email
  errors; a failed invite can be re-sent).
- Identity stays decoupled from the communications context via a local
  `InviteEmailPort`; composition adapts it to the Resend/Stub `EmailSendPort`
  (same env gating as digests: real sends only when `email_delivery_enabled`
  and `resend_api_key` are set).

### Frontend
- `/admin/users/new` — Add-user page (name, email, phone, role; parents get the
  invite automatically). "Add user" link on the users list.
- `LoginInvitePanel` on the user detail page: "Invite sent {date}" indicator,
  Send / Re-send button, inline error surfacing.

## Existing families (kids already registered)

If the parent's email is already on a user account, creating a new account
fails with "email already exists" — the correct flow there is the existing
user's detail page → **Send login invite** (the account exists; only
credentials are missing). Verify `students.parent_id` linkage per family in
staging before inviting; orphaned students (no resolvable parent login) need a
data fix, not a new account.

## Verification
- Backend: full suite 2151 passed (0 failures), ruff format/check clean,
  structural layering tests green.
- Frontend: typecheck clean, lint clean (pre-existing warnings only).
- QA route manifest updated for `/admin/users/new`.
- Staging end-to-end pass (create parent → email → set password → login →
  payments) pending; requires `email_delivery_enabled` + `resend_api_key`.

## Rollback
Revert the branch; no migrations. New Mongo field `login_invite_sent_at` is
optional and ignored by older code.
