# Invoice prefix per academy (no more BLNO- for everyone)

PR: #987

## What changed

- Invoice numbers used a hardcoded `BLNO` prefix. Every settings save also wrote that default into the academy's `billing_settings`, so a second academy would have issued `BLNO-2026-10-0001`. Each academy now has its own prefix. Only the platform sets it, and there is no `BLNO` fallback anywhere in code.
- BLNO keeps `BLNO`. Its invoice numbers stay byte-identical (`BLNO-2026-09-0042`). Migration 0206 sets BLNO's prefix explicitly (`acad_blno_badminton` in production, `blno` in the local seed).
- A new academy gets a prefix from its slug when it is created (`ace-badminton` becomes `ACE`). If another academy already holds that prefix, it gets the next free one (`ACE2`). Both creation paths do this: bootstrap and create-tenant. Format: 2-6 uppercase letters or digits, starting with a letter. Prefixes are unique across academies, enforced by a unique index.
- New super-admin endpoints `GET/PUT /api/v2/platform/academies/{id}/billing-identity` show and change the prefix. A change is refused (409) once the academy has a numbered invoice, and also when another academy holds the prefix. Every change writes an `invoice_prefix_changed` billing audit entry. Academy admins get 404.
- Admin Settings › Academy shows the prefix read-only, with an example number.
- Missing prefix: no number is minted and no counter value is used. An ERROR is logged (`invoice_prefix_not_configured`), so it reaches Sentry. The invoice is still created, unnumbered, and the existing display back-fill numbers it once the prefix is set. This is why a missing prefix does not raise. Three of the five minting paths run inside payment webhooks and money flows, and numbering must not block money. It is also why the code does not derive a default at mint time: a guessed prefix would skip the uniqueness check and then be locked in by the first number issued.

## Deploy notes

- Migration `0206_invoice_prefix_per_academy` must run before the new code serves traffic. The Fly `release_command` does this on deploy, after the production approval gate. Deploying this image without running 0206 would leave BLNO's new invoices unnumbered until it runs: they are created and payable, but show no number.
- 0206 writes `invoice_number_prefix` for every academy. BLNO gets `BLNO`. Other academies keep a valid unique prefix they already have, or get one from their slug. Any non-BLNO academy that held the old persisted `BLNO` default is re-derived. It then creates the unique partial index `billing_settings_invoice_number_prefix_unique`. It is idempotent.
- Suggested read-only check after deploy: `db.billing_settings.find({}, {academy_id: 1, invoice_number_prefix: 1})` should show `acad_blno_badminton` with `BLNO` and no other academy with `BLNO`.
- No new env vars or secrets.

## Risk / rollback

- Main risk: a production academy other than BLNO held the persisted `BLNO` default and has issued `BLNO-` numbers. 0206 moves it to its own prefix, so its future numbers change (for example `ACE-...`). Its past numbers stay as they are. Production runs single-academy mode, so none is expected. The read-only check above confirms it.
- Rollback: revert this PR. The stored prefixes can stay: the old code reads the same field, and BLNO's value is still `BLNO`. Also drop `billing_settings_invoice_number_prefix_unique`. Otherwise the old code's settings save, which writes its `BLNO` default for any academy without a document, fails on the index for every academy other than BLNO.
