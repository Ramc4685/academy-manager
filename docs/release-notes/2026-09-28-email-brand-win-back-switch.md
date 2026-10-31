# Full academy brand in money and account emails; win-back on/off switch

PR: #996

## What changed

- Batch B of the hardcoded-values cleanup (HARDCODED.md rows 6 and 10).
- A new `shared/comms/email_brand.py` builds the full email brand from the academy record: name, https-only logo, hex-validated colour and an escaped contact footer. The lookup never raises, and it is tenant-scoped.
- The brand is now used by the invoice (and its family-contact copy), dunning, autopay notice, autopay receipt, past-due and manual dues reminders, add-card reminder, login invite, registration verification and owner dispute notice emails.
- `notifications.win_back_enabled` defaults to on. It is a new switch in Settings → Notify, and `SendWinBackNotices` checks it before claiming any 30/60/90 milestone.

## Deploy notes

- No migration and no new env vars.
- Owner check before deploy: any `logo_url` (https), `brand_color` or `contact_email`/`contact_phone` stored on the prod `acad_blno_badminton` record will now appear in BLNO's money and account emails.

## Risk / rollback

- For an academy with only a name stored, all 10 emails render byte-identical to before (golden fixtures).
- Win-back behaviour is unchanged unless an admin turns the switch off.
- Rollback: revert this PR's merge commit. A stored `win_back_enabled: false` is simply ignored again.
