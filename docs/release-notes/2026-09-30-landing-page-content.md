# Landing page content: hero photo, about text, gallery, coach profiles and FAQs

PR: #TBD

## What changed

- Settings > Public page gets a "Photos & details" card (owner and admins): hero photo (upload, replace, remove, preview), About us text (1,200 characters), Highlights (up to 6 chips of 60 characters), Gallery (up to 12 photos with captions), Coaches shown (photo, 280-character bio and a shown switch per academy coach) and a FAQ editor (up to 12 questions, reorder, remove; empty means the standard questions).
- `POST /admin/academy/media` takes an optional multipart `purpose`: `logo` (default, unchanged: 2 MB, 512 px PNG), `hero`, `gallery` or `coach`. Photos are up to 5 MB, PNG or JPEG only, re-encoded as metadata-free JPEG (EXIF and GPS dropped), long edge capped at 2400 px (hero, gallery) or 800 px (coach), source canvas capped at 8000 px a side and about 30 megapixels. Each purpose stores under its own per-academy path (`academies/<id>/<purpose>/...`). A `gallery` upload without `consent=true` is a 422 ("Confirm that parents or guardians of anyone shown agreed..."). The hourly upload cap (shared across purposes) goes from 20 to 40. The response gains `url` and `purpose`; `logo_url` is still set for a logo.
- The early body limit on that endpoint is now the photo size (5 MB) because the `purpose` field cannot be read before the body is parsed; a logo over 2 MB still gets the same 413 and message, from the use case.
- `academies.public_page` gains `hero_photo_url`, `about_text`, `highlights`, `gallery`, `coach_profiles` and `faqs`, saved through `PATCH /admin/academy/public-page`. Each gallery item must carry `consent_confirmed: true`; the server stamps who confirmed and when from the caller (an existing photo keeps its original stamp). Coach profiles are accepted only for active coaches or assistant coaches of the caller's academy (422 otherwise).
- `GET /public/academy` gains `hero_photo_url`, `about_text`, `highlights`, `gallery` (`url` and `caption` only), `coaches` (`name`, `photo_url`, `bio` for shown profiles; the name comes from the membership-gated lookup) and `faqs`. Consent and uploader fields never leave the server; the no-leak test now bans them by name and checks a seeded gallery.
- Review fixes: public coach profiles are re-checked at read time against an active coach or assistant coach membership (a coach who left, was deactivated or lost the role is no longer published); a shown profile lists the full name and overrides the per-class `coach_display` (which only governs class cards); saved photo links must be objects this academy uploaded for that use (`academies/<id>/hero|gallery|coach/`), so no third-party images and no hero or coach upload reused as a gallery photo; a gallery write requires an actor (consent is never attributed to nobody); PNG sources are capped at about 16 megapixels (JPEG stays 30) to bound decode memory; the public TS type gains the new optional fields.
- Security fix: a saved photo link must now be a URL the media store produced (https, the store's own host and bucket, and exactly `academies/<id>/<purpose>/<one file>` once decoded). A look-alike link on another host, the marker behind extra path segments, and `..` traversal are refused; if uploads are not configured, new photo links are refused. Links already saved are untouched.
- The public page itself is not changed here: the render lane draws these fields.

## Deploy notes

- No migration (0213 not used). Every field defaults to today's page and is filled at read time; BLNO has none of them set, so its public page and settings screen read exactly as before.
- Backend first or together with the frontend. The old frontend ignores the new response fields. The new admin card needs the new backend.
- No new environment variables; uploads use the existing `media_storage_bucket`.

## Risk / rollback

- Low. Additive fields and one additive form field on an existing endpoint. Logo behaviour and limits are unchanged apart from the shared hourly cap (20 to 40).
- Retention: removing a photo from settings drops the link only; the stored object stays in the bucket (its `academy_media` row is kept, no delete path yet). Follow-up: delete the object on removal so a withdrawn-consent photo is gone, not just unlinked.
- Gallery photos can show children: the upload consent box and the server-side consent refusal are the guard. Rollback: revert the PR; stored `public_page` content keys are ignored by the old code.
