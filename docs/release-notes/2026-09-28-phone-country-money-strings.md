# Phone calling code from the academy country; backend money strings via format_money

PR: #997

## What changed

- Batch C of the hardcoded-values cleanup (HARDCODED.md rows 11 and 12).
- WhatsApp links and CRM duplicate matching take the calling code from the academy's country at read time. US, CA, missing and unknown countries all give "1".
- The admin frontend now prefixes bare national numbers with that code. A 10-digit US number links to `wa.me/1…` instead of a dead link.
- The admin academy view exposes a read-only `phone_country_code`.
- The four backend `$` money strings go through the shared `format_money`, which has two new flags (`group_thousands`, `drop_zero_cents`). Its default output is unchanged. Currency is locked to USD.

## Deploy notes

- No migration, no new env vars and no new routes.

## Risk / rollback

- Money strings are byte-identical, pinned by tests.
- The only BLNO-visible change is the admin people-page WhatsApp links, which now work.
- Rollback: revert this PR's merge commit. No stored data changes.
