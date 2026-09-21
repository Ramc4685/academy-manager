# fix-remaining-tenant-unique-ids

PR: #TBD

## What changed

- Migration `0189_remaining_ids_unique_per_academy` finishes the index work in #849. Thirty more ids become unique per academy instead of across all academies: registration and ops (applications, waitlist, expenses, payouts, enrollment events, session types, session feedback, academy settings, autopay consents), communications and waivers (messages, campaigns, deliveries, coach and parent digest sends, waiver templates and signatures), the skill and curriculum catalog (programs, levels, skills, criteria, lesson refs, lesson cards, video refs), and student progress and certificates (level and skill progress, test attempts, level-up recommendations, certificate id and certificate number, coach skill notes).
- Nothing changes for users with one academy. It removes a class of permanent 500s that a second academy onboarded from copied, imported or restored data would hit, because every read and write on these collections was already scoped to the academy while the database rule was not.
- Every new index uses the `$gt: ""` filter that MongoDB's planner can use for lookups by id (see #877). Ids that are absent, `null` or empty stay outside the rule.
- The coach and parent digest-send collections also keep a plain index on `digest_id`, because marking a digest sent, failed or skipped updates it by `digest_id` alone.
- `message_deliveries.provider_message_id` deliberately stays globally unique: the email provider issues it, and nothing reads it.
- The launch-readiness audit now expects `academy_settings_id_per_academy_uq` in place of `academy_settings_id_unique`.

## Deploy notes

Backend-only. Migrations do not run on boot in production (#629): after the deploy, apply `0189` by hand via `fly ssh console -a courtmastr-academy-api` and `backend.v2.migrations.run_pending_migrations`. It pre-flights all thirty collections first and aborts without touching any index on a duplicate `(academy_id, <id>)` pair (production had none on 2026-09-21). Each index is created before the one it replaces is dropped. Afterwards run the drift audit (`--dump` on Fly, `--check` locally) and expect `ok: true`, and confirm with a read-only `explain()` that lookups by id name the new indexes. Between the deploy and the apply, `backend/scripts/launch_readiness_audit.py` will report the new `academy_settings` index as missing; that clears once `0189` is applied. No env vars.

## Risk / rollback

Low. The largest affected collection holds about 3,400 documents, so builds take well under a second; no query or write path changes. Verified against a real MongoDB with all 105 earlier migrations replayed first: for all thirty, the plan names the new index and examines one document, a same-academy duplicate is rejected, the same id under another academy is allowed, and absent, `null` and empty ids coexist. The test fake evaluates neither partial filters nor query plans, so the unit tests pin the index shape. To roll back, revert this PR's merge commit; indexes already applied are safe to leave in place.
