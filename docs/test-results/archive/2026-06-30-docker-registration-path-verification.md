# docker registration path verification

## Current State

Status: active

## Problem

Verify parent registration path works in Docker staging/local environment

## Changed Files

- None recorded yet.

## Log

- 2026-06-30T23:00:38 main/NA: Task ledger created.
- 2026-06-30T23:00:54 main/working: Preparing Docker SaaS staging registration-path verification; read testing guidance and prior registration/waiver ledgers.
- 2026-06-30T23:16:36 main/working: Implemented registration membership activation: public SaaS parent registration now creates/activates active parent membership for onboarding; suspended/removed memberships remain untouched. Focused identity tests and ruff passed.
## Verification

- No verification recorded yet.
- 2026-06-30T23:02:35: Docker browser registration attempt 1 reached email account creation and verification notice, then aborted before onboarding because the local Firebase verification helper path was wrong (spawnSync ../backend/.venv/bin/python ENOENT). No app failure observed in this attempt.
- 2026-06-30T23:08:25: Docker SaaS staging smoke passed. Browser registration against http://blno-academy.localhost:3000/register: email account creation and verification notice passed; local Firebase emulator user verified; POST /api/v2/register/parent returned 200 and created parent user plus academy_memberships status=invited. Immediate redirect to /parent/onboarding failed because parent layout /api/v2/me returned 401 with backend auth_failed: Identity.MembershipNotFound. After manually activating only the disposable local Docker membership, /me returned 200 and parent onboarding mounted; parent profile PATCH returned 200. Flow then blocked at session selection because GET /api/v2/parent/sessions/available returned {sessions:[]} while BLNO seed sessions lack start_at/end_at/days_of_week fields required by available_for_parent_catalog. No production data touched; local Docker test data only.
- 2026-06-30T23:09:10: Additional continuation attempt after local membership activation did not add new proof; browser did not reach the child-step assertion within 10s in that rerun. Prior debug run already proved parent onboarding mounted and parent-profile PATCH succeeded; session catalog evidence remains direct API/browser response sessions=[].
- 2026-06-30T23:26:52: Docker SaaS staging browser registration path passed: email signup and verification via Firebase emulator, POST /api/v2/register/parent 200, parent onboarding PATCH steps 200, available BLNO session selected, POST /api/v2/parent/checkout/start 200, browser reached Stripe custom checkout host pay.courtmastr.com. Test user codex.reg.1782879998969.5a9caa@gmail.com / uid onYYSiixAwsMDshLXLijbZ95U6Ms created only in local Docker staging.
- 2026-06-30T23:27:03: Post-change scripts/dev/saas_staging.sh smoke passed after backend restart with blno-academy.localhost in Docker SaaS CORS/redirect allowlist.
## Reusable Lessons

- None recorded yet.
