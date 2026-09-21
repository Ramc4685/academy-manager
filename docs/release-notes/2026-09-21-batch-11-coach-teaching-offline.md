# batch-11-coach-teaching-offline

PR: #0

## What changed

- Fixes #895 — the coach teaching plan's quick-pass button now reads "Passed" instead of "Mastered", and all four one-tap skill-state labels come from the same shared seven-state vocabulary used by the skills page, the passport and the skill board, so a skill's status reads the same word everywhere in the product.
- Fixes #895 — each teaching-plan button now publishes the skill's current state through `aria-pressed` plus a visible ring and an `sr-only` "current state" suffix, so the active state is never conveyed by colour alone.
- Fixes #895 — a mark that failed sync now offers Retry in addition to Dismiss. Retry re-queues the same record (same `mutation_id` idempotency key, same payload) through the existing sync loop, so a coach no longer has to re-mark by hand from a session they may have already left.
- Fixes #895 — the announcements composer on the marking screen now opens on request instead of rendering open under the roster on every visit; `AnnouncementsPanel` itself is unchanged, so the admin session page still renders it open by default.

## Deploy notes

Frontend-only. No migrations. No new env vars. No manual steps required after deploy.

## Risk / rollback

Low. Changes are scoped to the coach teaching-plan screen's skill-state labels/ARIA attributes, the failed-mark retry action (reusing the existing sync queue and idempotency key), and the composer's default-open state on that one screen. The attendance save path, the queue contract, bulk eligibility, and the delayed-save Undo are untouched. To roll back, revert this PR's merge commit.
