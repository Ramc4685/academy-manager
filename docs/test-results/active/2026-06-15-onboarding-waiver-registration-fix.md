# onboarding-waiver-registration-fix

## Current State

Status: active

## Problem

Registration waiver step errors 'no active waiver to accept' because it reads from empty 'waivers' collection instead of admin-managed 'waiver_templates'

## Changed Files

- None recorded yet.

## Log

- 2026-06-15T09:38:35 main/NA: Task ledger created.
- 2026-06-15T09:51:12 main/done: All phases implemented: MongoRegistrationWaiverRepository, composition rewired, WaiverAcceptance.waiver_template_id, GET /onboarding/waiver BFF, WaiverStep fetches real content, seed updated, legacy repo deleted. 1167 tests pass.
## Verification

- No verification recorded yet.
- 2026-06-15T09:51:24: pytest v2/tests -q: 1167 passed 0 failed. ruff format --check v2: 631 files formatted. pnpm typecheck: no errors. 5/5 contract tests pass (resolve, unassigned, non-active, tenant-isolation, empty).
## Reusable Lessons

- None recorded yet.
