# House academy replaces the platform-charge fallback switch

PR: #975

## What changed

- **Only the house academy charges on the platform Stripe account.** `billing_settings.allow_platform_charge_fallback` is no longer a stored switch. The billing-settings repository now derives it on every read from the new `HOUSE_ACADEMY_ID` setting: true for the house academy (BLNO, which owns the platform account), false for every other academy, whatever the stored value is. All charge paths (checkout, invoice pay links, balance checkout, enrollment and autopay setup, off-session autopay) and the "can take payments" read models already read that field, so they follow automatically. The app never writes the field back, so an admin settings save cannot persist the derived value.
- **The academy owner can no longer turn the fallback on.** `PUT /api/v2/admin/billing/settings/platform-fallback` and its use case are removed. Until now an academy owner could route its own charges, and their refund and dispute liability, onto the platform account. The `GET` stays, read-only.
- **The house academy cannot start Stripe Connect onboarding.** Connecting a second Stripe account would silently move BLNO's charges, saved cards and autopay off the platform account. Both the admin and platform onboarding routes now return 409 `Billing.HouseAcademyUsesPlatformAccount` for the house academy.
- **Settings → Payments** shows a read-only "Where payments settle" card ("House academy" or "Connected account") in place of the fallback toggle. Billing health shows "Charges settle on" instead of "Platform charge fallback".
- The 2026-09-25 owner decisions (house academy plus direct charges for other academies) are in the design doc; the follow-up slices are tracked there.

## Deploy notes

- `backend/fly.toml` sets `HOUSE_ACADEMY_ID = "acad_blno_badminton"`, so this deploy sets it too. No migration, no new index, no secret.
- BLNO keeps charging on the platform account exactly as today. Production BLNO already charges there through the stored fallback flag, and after this deploy the house setting gives the same answer.
- When `HOUSE_ACADEMY_ID` is unset (local, staging, tests), the stored per-academy flag is read as before, so existing seeds keep working. The app logs `house_academy_not_configured` at startup in that case.
- Changing `HOUSE_ACADEMY_ID` moves money. Treat it as a reviewed PR plus an approved deploy.

## Risk / rollback

- Risk: an academy other than BLNO that relied on the stored flag would now be refused platform charges. Production runs single-academy mode with BLNO only, so no other academy is affected.
- If `HOUSE_ACADEMY_ID` were missing from the deployed environment, behaviour falls back to the stored flag, which is today's behaviour. It does not stop BLNO's payments.
- Rollback: revert this PR. The stored `allow_platform_charge_fallback` values are untouched, because this change never writes them, so the old code reads them as before.
