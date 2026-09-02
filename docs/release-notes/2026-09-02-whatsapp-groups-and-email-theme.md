# whatsapp-groups-and-email-theme

PR: #627

## What changed
- Parent and coach daily digests now carry a "Your class WhatsApp groups"
  block with a Join link per class, read from each session's
  `whatsapp_group_link`. Parents see the group for every active enrollment
  in the family; coaches see every session they are assigned to. Sessions
  without a link are skipped; if none have one the block is absent.
- All outbound email (digests, welcome, roster and announcement mail,
  invoices, dunning, dues reminders, login invite, registration
  verification, add-card reminder) renders through one shared shell built
  on the app's Rally palette, with the academy name or logo, date, brand
  colour, and contact footer. The academy's `brand_color`, `logo_url`,
  `contact_email` and `contact_phone` settings are now used by email.
- Resend sends a plain-text part alongside the HTML.
- Copy fixes: capitalised multi-child greeting; upcoming balances are no
  longer shown in red or as "was due"; one money format (`$60.00`); coach
  digest greeting and readable date; invoice heading names the period; the
  "please disregard" line appears only on the dues reminder.
- Admin session form shows where to copy a WhatsApp invite link and warns
  softly when an https link is not a `chat.whatsapp.com` invite.

## Deploy notes
No migrations, no new env vars. The first scheduled digests after deploy
will render on the new theme. To see the change immediately, use the admin
coach-digest test-send for one coach. Academies that have not set any
session `whatsapp_group_link` see no group block.

## Risk / rollback
Moderate surface (every email template), low logic risk: rendering is pure
and covered by renderer tests; group lookups and brand lookups are wrapped
so a failure drops the block rather than the send. A regression in a
specific template can be reverted per file; full rollback is reverting the
PR. The plain-text part is generated from the HTML and, if generation ever
throws, the email still goes out HTML-only with a warning logged.
