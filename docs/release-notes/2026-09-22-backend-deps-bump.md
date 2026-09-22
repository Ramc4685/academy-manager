# backend-deps-bump

PR: #832

## What changed

- Dependabot's weekly backend group bump (25 packages: pymongo 4.18.1, stripe 15.6.1, uvicorn 0.53.0, sentry-sdk 2.69.1, resend 2.45.0, ruff 0.16.7, import-linter 2.15, and patch bumps of the rest).
- One correction on top of the bot's diff: `pydantic_core` stays at 2.46.5, the version `pydantic==2.13.5` pins. Dependabot had bumped it to 2.49.0 on its own, which no released pydantic accepts, so `pip install` failed with `ResolutionImpossible` on every CI job.
- The branch was also brought up to date with `main`.

## Deploy notes

None. Normal backend deploy; no migrations, no settings.

## Risk / rollback

Low. Every bump is a minor or patch release and the full backend suite runs against the new pins in CI. Rollback is reverting this squash commit and redeploying the previous image.
