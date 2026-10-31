# CourtMastr product name, tenant chrome, self-hosted login art

PR: #992

## What changed

- `frontend/lib/brand.ts`: `productName`/`productFullName` -> "CourtMastr"; `productDescriptor` is sport-neutral ("Academy operations platform"); `copyrightYears`/`copyrightNotice()` now compute from the current year instead of a static "2024-2026" string. Company/legal-owner name (`Marvy Labs`) and support/security email domains are unchanged - the owner has not confirmed a new legal entity or CourtMastr mailboxes.
- Admin shell sub-label reads `brand.productName` instead of the literal "Academy Manager"; the PWA manifest `name`/`short_name` -> "CourtMastr"; the FastAPI app title -> "CourtMastr API".
- Marketing landing page headline/eyebrow copy no longer names "badminton" (sport-neutral).
- Login/register hero background is now a local CSS gradient instead of a hotlinked third-party build-host image (`static.prod-images.emergentagent.com`) - removes an external dependency that would break under a tighter CSP and an unlicensed-image risk.
- Public tenant page: `academies.contact_email` is now surfaced read-only as `support_email` on the public DTO and rendered as a `mailto:` link in the footer. No phone number is exposed (owner decision: public page shows support email only).
- `backend/scripts/parent_account_audit.py` no longer silently defaults `--academy-id` to `acad_blno_badminton`; it now requires the flag or `PRIMARY_ACADEMY_ID`/`V2_PRIMARY_ACADEMY_ID` to be set.
- Coach profile phone placeholder changed from a real Illinois number to a fictional one.
- Deferred to follow-up work: row 14 (AcademyMark component across admin/parent/coach shells) and the remainder of row 15 (per-host page titles/login header via per-academy branding) - larger, cross-cutting scope; row 20 (CSP `img-src` broadening) - needs explicit owner review as a security-relevant change; row 35 (footer/OG shuttle icon) - deferred by PLAN.md until the sport field (batch F) lands.

## Deploy notes

- No new migration. No new env vars or secrets.
- Purely additive/display changes; safe to deploy independently of other batches.
- `parent_account_audit.py` now requires an explicit `--academy-id` (or `PRIMARY_ACADEMY_ID`/`V2_PRIMARY_ACADEMY_ID`) - any scheduled invocation that relied on the implicit BLNO default must be updated to pass it explicitly.

## Risk / rollback

- Low risk: copy/branding text changes, a local CSS gradient replacing a hotlinked image, a stricter CLI argument requirement, and one new read-only public DTO field (`support_email`).
- BLNO's billing, invoicing, emails, session times, and links are unchanged; the public page gains a support-email mailto link, gated by the owner's decision.
- Rollback: revert PR #992. No migration to unwind.
