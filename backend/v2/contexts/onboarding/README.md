# onboarding

Applications (registration), waiver templates, waiver signatures, and the
per-child AI/video consent.

## Per-child AI/video consent (AI strategy Phase 3, slice E1)

Stored and unused: no model, no upload, no clip handling.

- **Record.** `ai_video_consents`, one row per (academy, student): `status`
  (`granted` / `revoked`), `text_version`, `accepted_at`, `accepted_by` (the
  parent's user id), `accepted_by_email`, `revoked_at`, `revoked_by`, plus an
  append-only `history` of every grant and revocation. Absent means no consent.
  Migration `0227_ai_video_consents` adds the unique `(academy_id, student_id)`
  index.
- **Text.** `domain/ai_video_consent.py`: `AI_VIDEO_CONSENT_TEXT` at version
  `ai_video_consent_v0_placeholder`. It is a PLACEHOLDER that has not been
  reviewed by counsel; the vendor ("[vendor to be confirmed]") and the
  retention number ("[30, 60 or 90] days") are open owner decisions. The owner
  replaces the text after counsel and bumps the version to one without
  "placeholder". A grant must name the current version, so a stale page is
  refused (409).
- **Routes.** Parent: `GET /parent/waivers/ai-video-consent`,
  `POST /parent/waivers/ai-video-consent/{student_id}/grant` (`text_version`,
  `consent: true`) and `.../revoke`. Another family's child is 404; other
  personas get 404. Admin, read-only: `GET /admin/waivers/ai-video-consents`.
- **Read path, the only video gate.** `ConsentAiVideo`
  (`composition/ai_video_consent.compose_consent_ai_video`):
  `await consent_ai_video(academy_id, student_id) -> bool`. Every later video
  slice (E2 on real clips, E3 capture and the clip-deletion job) must call it
  before touching a child's clip. It returns False unless the child has an
  active, non-revoked consent to the current text version, and it is always
  False while the current text is a placeholder: placeholder consent can never
  authorize real use. A consent given to an older text does not carry over to
  a new version; the parent consents again.
