# platform-and-ai-hardening

PR: TBD

## What changed
Cancelling a tenant's platform plan (schedule cancellation or cancel now) now cancels the subscription at Stripe first. The idempotency key covers the subscription, the mode and the row's last update. If Stripe fails, the row stays as it was and the route answers 502. A repeat cancel of a cancelled row does nothing. Starting a trial is refused (409) while a live Stripe subscription is on file, so the trial cannot orphan it. Governance requests (exports, deletions, support access grants, impersonation) now carry `enforced: false` and a note naming the manual step, because nothing acts on them yet. They are also refused (404) when the academy or student does not exist.

Owners get an "AI limits" card under Settings > Notifications, backed by `GET`/`PUT /admin/ai/controls`. It sets the monthly AI call cap, a daily cap per feature, and whether coaches review AI progress notes before parents see them. Each change is written to the audit log as `ai_controls.changed`. AI pipeline reply drafts now refuse links in the subject and key points, and progress notes refuse link-like text. The Anthropic adapter now does four new things. It turns a non-JSON reply into a clean 502. It retries once on 429 or 529. It stores the exact cost in a new `cost_microcents` field. It reports an answer cut off at `max_tokens` as "cut off" after the call is recorded.

## Deploy notes
- No migration and no settings change. `ai_calls` rows gain `cost_microcents` (no validator on that collection); older rows lack it.
- BLNO keeps today's AI behaviour until the owner saves the new card: a 200-call monthly cap, no daily caps, coach review on.
- BLNO has no platform Stripe subscription, so the platform cancel change does not touch it.

## Risk / rollback
- Risk: with Stripe unconfigured, cancelling a paid platform subscription now returns 502 instead of changing only the local row. That is intended.
- Risk: the stricter link check on progress notes may refuse an odd narrative containing something like an email address. The coach sees a 502 and can draft again.
- Rollback: revert the PR. Nothing is stored in a new shape, apart from the extra `cost_microcents` field and any limits an owner saved under `ai.*`.
