# Merge Academy + Branding into one Academy profile tab, add Class defaults (Settings overhaul Phase 3 PR 9)

PR: #TBD

## What changed

- **Academy and Branding panels merged into one "Academy profile" tab.** The tab key stays `academy`; `?panel=branding` now redirects to it via `RETIRED_SETTINGS_PANELS` (same pattern as the existing `?panel=fees` -> Billing rules redirect). The standalone "Branding" tab is gone from `SETTINGS_TABS`.
- **Card order, per the settings plan:** Identity (display name, timezone — owner-only, currency — read-only USD, invoice prefix — read-only), Contact & location (email, phone, hours, address), Brand (logo URL, brand colour, live preview, outbound email sender name / reply-to), Class defaults (new).
- **Brand colour is now validated as hex**, client- and server-side (`#rgb` / `#rrggbb`); an invalid value blocks Save with an inline error, same pattern as the sender-name validator.
- **The brand preview card now shows the academy's real display name** instead of the hardcoded "Rally Academy" placeholder.
- **New Class defaults card** (admin-editable, not owner-gated): default class size (10), default class length in minutes (45), default venue/address, parking note, what to bring, arrive-minutes-early. Stored on the academy record; filled at **read time**, so an academy that never sets these reads 10 / 45 / empty today and forever — no migration, and BLNO's read is unchanged until an admin fills the card in.
- **Create-class form** (`/admin/sessions`) now seeds capacity and end time from the academy's Class defaults instead of the hardcoded `10` / `+45min`. The BLNO-specific weekday/time default (Wed 18:00) is gone — day and start time now start empty, and the admin picks them.
- **Class welcome email** falls back to the academy's Class defaults for venue, parking, what-to-bring and arrival time whenever the *class* leaves that field empty. A class value, when set, always wins — this is a fallback, never an override — so every class that already has its own values (every BLNO class today) renders byte-for-byte unchanged.
- Holidays & closures and Legal links cards from the mockup are **not** built here — out of scope for this lane.

## Deploy notes

- No migration (0208 not needed). Every new field is read with an in-code default (`get_academy_use_case.py`), so an academy doc that predates this change reads exactly as today.
- BLNO is unaffected until an owner/admin opens Academy profile -> Class defaults and saves a value.
- `UpdateAdminAcademyRequest` gained `default_class_size` / `default_class_length_minutes` / `default_venue_address` / `default_parking_note` / `default_what_to_bring` / `default_arrival_minutes_before` and a `brand_color` hex validator. No route path changed.

## Risk / rollback

- Main risk: a bookmarked `?panel=branding` link now lands on the merged tab rather than a dedicated "Branding" tab — same UX pattern as the existing `?panel=fees` redirect, covered by an e2e spec.
- The create-class day-of-week field no longer defaults to "Wed": an admin must now pick a day explicitly. Existing e2e specs that filled every field explicitly are unaffected; `admin-session-creation-ui.spec.ts` was checked and does not rely on the old default.
- Rollback: revert this PR. No data is dropped — any `default_*` fields an admin already saved on an academy doc are simply not read or shown again until a re-deploy of this change.

## Follow-ups (not built here, out of scope for this lane)

- Holidays & closures and Legal links cards (mockup sections not in this lane's spec).
- Playwright screenshot capture of the new Academy profile tab could not be completed in this sandbox: `next dev --turbopack` fails to resolve Google Fonts (`next/font/google` / `@vercel/turbopack-next` module-not-found, offline sandbox), so the e2e dev server never boots. Typecheck, lint and unit tests were run and pass; a follow-up session with network access to Google Fonts (or `next dev --webpack`, per this repo's existing webpack-only build note) should capture the 1280x900 and 390x844 screenshots.
