# Public tenant page B5: admin Settings → Public page panel

PR: #938

## What changed

- New admin endpoints for the academy's public page settings, both `require_persona("admin")` (not owner-only: nothing here moves money), academy from the caller's claim like the other academy settings: `GET /api/v2/admin/academy/public-page` returns the settings with domain defaults merged in; `PATCH /api/v2/admin/academy/public-page` is a partial update (only the keys sent are written). Unknown keys, coerced booleans (`"true"`, `1`, `null`), an unknown price period and non-http(s) privacy links are a 422. Both answer a read-only `public_url` (`https://<primary_domain or custom_domain>/` of the academy record, only when it is a bare host name; otherwise null) for the panel's "View page" link. Wired in `composition/public_page_admin.py` (new `GetPublicPageAddress` use case); nothing added to `composition/admin.py`.
- `GET /api/v2/admin/class-public-profiles` rows now carry the class `title` and `status` (admin labels only; the public read builds its own DTO and does not copy them).
- New **Public page** tab under Settings (`/admin/settings?panel=public-page`, no new route): Publish page, Show prices, Show seat availability, Accept free trial requests, price period default and privacy notice link, saved with one button and covered by the existing settings unsaved-changes guard; a note saying the page is live only when published and saved; a "View page" link to the academy's own domain (falls back to the current host only when it is not a CourtMastr product host; otherwise says the address is not set up yet). Below it, program create/rename/archive and a per-class list (publish switch, program, price period override, coach name display) that save on change, like Session types rows. Ended or cancelled classes are listed only while still switched on.

## Deploy notes

- No migration. No environment variable, feature flag or backfill.
- The "View page" link needs `primary_domain` (or `custom_domain`) on the academy record to point at the academy's own host; without it the panel on the product host shows "not set up yet" instead of a link.

## Risk / rollback

- Low: new admin routes and a new settings tab. Nothing becomes public until an admin switches Publish page on and saves, and switches classes on.
- Rollback: revert the PR. Any `public_page` keys or class switches already saved stay on the records and keep driving the public page (B2/B3); switch them off first if the page should go dark.
