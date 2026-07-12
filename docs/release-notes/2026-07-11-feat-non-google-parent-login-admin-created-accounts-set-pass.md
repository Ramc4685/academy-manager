# feat-non-google-parent-login-admin-created-accounts-set-pass

PR: #298

## What changed
Parents on Yahoo/Hotmail/any non-Google email can now log in. The admin creates their account (or uses bulk invite); the system emails a branded **"Set your password"** link (Firebase password-reset link via Resend). No one-time passwords are ever emailed; completing the link marks the email verified, which the password-login path requires.

- **Backend:** `SendLoginInvite` use case (identity-local `InviteEmailPort`, composition adapter to the Resend/Stub `EmailSendPort` with the same env gating as digests); `generate_password_reset_link` on the Firebase adapter; `record_login_invite` + `login_invite_sent_at` on the user; `POST /admin/users/{id}/login-invite`; auto-send on parent creation (best-effort — creation never fails on email errors).
- **Frontend:** `/admin/users/new` add-user page (parents auto-invited), "Add user" link on the users list, `LoginInvitePanel` (sent-at indicator + send/re-send) on the user detail page.

Spec: `docs/superpowers/specs/2026-07-09-admin-coach-toggle-and-parent-invite-design.md` (Enhancement 2)
Plan: `docs/superpowers/plans/2026-07-09-parent-login-invite.md`
Release note: `docs/release-notes/2026-07-09-feat-parent-login-invite.md`

## Deploy notes
No migration detected in the diff. Confirm no manual env var or manual step is needed before merge.

## Risk / rollback
_Auto-generated stub — author: fill in what breaks if this is wrong and how
to roll back before merge._ Revert the merge commit if this regresses.
