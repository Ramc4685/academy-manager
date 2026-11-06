# AI Phase 3 E1: per-child AI/video consent, stored and unused

## What changed

- Parents can opt each child in to AI analysis of coaching video from the waivers page, and revoke it there at any time; each grant and revocation is recorded with the text version, time and parent.
- Admins see each child's consent status, read-only, on the waivers page.
- New `consent_ai_video(academy_id, student_id)` read path that every later video slice must call. Nothing calls it yet: no model, no upload, no clip handling.

## Deploy notes

- Migration `0227_ai_video_consents` adds a unique index on a new, empty collection; nothing to watch in the dry-run beyond it applying.
- The consent text is a PLACEHOLDER (`ai_video_consent_v0_placeholder`) awaiting counsel review, with the vendor and the 30/60/90-day retention still open owner decisions. It authorizes nothing: the read path returns False for every child while the text is the placeholder.

## Risk / rollback

- Low: an optional, separate opt-in that no feature reads. Rollback is a revert; the `ai_video_consents` rows and index can stay.

PR: #1151
