# academy-sender-identity

PR: #TBD

## What changed

- **Per-academy sender display name and reply-to (L9a).** Two optional academy settings, `email_sender_name` (max 80 characters, no line breaks or angle brackets) and `email_reply_to` (a valid email), are editable under Settings → Branding → Outbound email and through `PATCH /api/v2/admin/academy` (admin persona). Unsafe values are a 422.
- **The From address does not change.** It is still the platform's verified `SENDER_EMAIL`. Only the display name changes: `"<sender name, else academy display name>" <SENDER_EMAIL>`. Non-ASCII names are RFC 2047 encoded. The send port now takes `sender_name` (a name only) and the Resend adapter builds the header around its own address, so an academy value can never change the address. `backend/v2/shared/comms/sender_identity.py` holds `resolve_sender(academy_doc)` and re-validates stored values when it reads them.
- **Wired paths (non-billing):** parent and coach digests, admin-triggered coach test digest, campaigns, roster alerts, absence notices, session announcements, hold notices, win-back, registration decisions, enrollment welcome, public trial-request owner alert (reply-to stays the family's address), and admin/staff login invites. Each resolves the academy from the current tenant at send time.
- **Reply-to:** `email_reply_to` wins when it is set. Otherwise each path keeps what it did before: digests use contact/owner email, and the other paths set no reply-to.
- **Not wired (follow-up, billing work #928-#932 in flight or file in open PR #941):** `InvoiceEmailAdapter.send_invoice_email`, `.send_dunning_notice`, `.send_autopay_notice`, `.send_autopay_receipt`, `DuesReminderEmailAdapter.send_past_due_reminder`, `.send_reminder`, `AddCardReminderEmailAdapter.send_invite_email` (all `backend/v2/composition/email_adapters.py`); the parent registration verification email (`backend/v2/main.py` `build_user_facing_invite_sender(...)`, which needs `academies=MongoAcademyRepository(db)`); and the platform ops digest/alerts in `main.py`, which stay platform-branded on purpose.

## Deploy notes

- No migration, no backfill, no new env var. When the fields are absent, the display name falls back to the academy display name. Before this change the From header was the bare `SENDER_EMAIL`, so every academy's non-billing email now shows its academy name.

## Risk / rollback

- Low. A bad stored value is ignored when read (bare address, no reply-to) and never blocks a send. A failed academy lookup also falls back to the old headers.
- Rollback: revert the PR. The two stored fields are then ignored.
