# ai-foundation

PR: #PRNUM

## What changed
AI plumbing with no feature behind it yet: a model port gated by `V2_AI_ENABLED` + `V2_ANTHROPIC_API_KEY` (off by default, so nothing calls a model), an `ai_calls` audit collection with a per-academy monthly cap, prompt versions in code, and `has_feature(academy, "ai")` read from `PlatformPlan.features` via the academy's platform subscription. The dead `openai` pin is removed.

## Deploy notes
Migration `0220_ai_calls` adds two non-unique indexes on the new (empty) `ai_calls` collection; it applies in the normal release_command with nothing to look for. No new env vars are required: both AI settings default to off/unset.

## Risk / rollback
Nothing reads `app.state.ai` or `has_feature` yet, so the runtime risk is boot-time wiring (`compose_ai` constructs a Mongo repo and the disabled port) and the `features` field on platform plans, which defaults to empty and only changes the platform `PUT /plans/{id}` payload and response. Roll back by reverting the PR; the `ai_calls` indexes can stay.
