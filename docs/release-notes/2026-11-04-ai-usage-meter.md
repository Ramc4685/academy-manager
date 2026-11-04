# ai-usage-meter

PR: #TBD

## What changed

Academy admins see "You have used X of Y AI drafts this month" on Settings -> Academy profile, with a soft "Upgrade to Growth for unlimited drafts" link once a free-tier academy reaches 20 drafts; platform admins see the same meter as a card on each tenant's page. Two read-only routes back it: `GET /api/v2/admin/ai/usage` and `GET /api/v2/platform/academies/{academy_id}/ai-usage`. The free cap is a prompt only; the existing hard abuse ceiling on recording calls is unchanged.

## Deploy notes

none (no migration, no new env vars; reads the existing `ai_calls` collection and plan features).

## Risk / rollback

Read-only: a wrong number shows a wrong meter line, nothing else; no AI call is refused by this change. Roll back by reverting the PR; no data to repair.
