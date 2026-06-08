# BLNO production login failure

## Current State

Status: active

## Problem

Diagnose why ramchand4685@gmail.com cannot log in at https://blno-academy.courtmastr.com/login after BLNO production data reload.

## Changed Files

- `backend/v2/main.py`
- `backend/v2/tests/contract/test_platform_mongo_tenant_lifecycle_repo.py`
- `test_result.md`

## Log

- 2026-06-08T17:00:41 main/NA: Task ledger created.
- 2026-06-08T17:00:46 main/working: Screenshot shows /api/v2/me returning 401 on blno-academy.courtmastr.com/login. Firebase Admin previously showed ramchand4685@gmail.com exists, enabled, verified, Google provider only. Backend LoadAuthClaims reads user by email then requires active academy membership roles.
- 2026-06-08T17:07:31 main/working: User is stuck on /post-login after Google flow. New symptom: post-login handoff does not redirect to role home; console shows COOP popup-close noise and ERR_BLOCKED_BY_CLIENT, no visible /api/v2/me success.
- 2026-06-08T17:28:26 main/working: Replaced unhealthy Fly machine 5683ed0df35448 with clone 781960b93e5d18 after proving the old instance had no outbound route even to example.com. New instance has outbound connectivity to example.com and Atlas; health check is passing.
- 2026-06-08T17:34:55 main/working: Confirmed current /api/v2/me 401 is tenant-resolution failure, not missing Mongo membership. Production data has academy_domains entries for blno-academy.courtmastr.com and active ramchand4685@gmail.com membership, but _AcademyLookupAdapter only checks academies.slug/custom_domain and ignores academy_domains.
- 2026-06-08T17:49:46 main/working: Implemented local backend fix: _AcademyLookupAdapter now falls back to verified academy_domains records after academies custom/primary domain lookup. Added regression for blno-academy.courtmastr.com-style mapping.
## Verification

- No verification recorded yet.
- 2026-06-08T17:04:59: Root cause for screenshot path: ramchand4685@gmail.com exists in Firebase Auth as enabled/email-verified but provider list is google.com only, so signInWithEmailAndPassword from the login form cannot succeed for that account. The production BLNO bundle contains correct admin user and membership roles for this email.
- 2026-06-08T17:19:02: Root cause for /post-login stuck: production backend cannot reach MongoDB Atlas from Fly. Logs show tenant_resolve_failed and dispatcher failures with No route to host / ServerSelectionTimeoutError to all Atlas shard hosts; Fly health becomes unhealthy and /api/v2/me returns/hangs as 503. Set V2_RUN_MIGRATIONS_ON_BOOT=false as a Fly secret override to stop boot migration crash-loop, but tenant/auth requests still require Atlas connectivity.
- 2026-06-08T17:34:55: Live checks: healthz on blno-academy.courtmastr.com returned 200; /api/v2/me without auth returned 401 {detail: Not authenticated}; fake Authorization/X-CourtMastr-Identity through blno-academy and api.academy still returned 401 with no auth_failed log. Read-only Fly SSH Mongo inspection showed academies slug/custom_domain are blno-badminton/blno-badminton.academy.courtmastr.com, academy_domains contains blno-academy.courtmastr.com, and ramchand4685@gmail.com has active admin/parent membership in acad_blno_badminton.
- 2026-06-08T17:49:59: Local fix verification passed: pytest backend/v2/tests/contract/test_platform_mongo_tenant_lifecycle_repo.py -q => 2 passed; pytest backend/v2/tests/interface/test_tenant_resolution.py -q => 20 passed; ruff format --check v2/main.py v2/tests/contract/test_platform_mongo_tenant_lifecycle_repo.py => passed; ruff check same files => passed. Initial regression failed before implementation with None != acad_blno_badminton.
## Reusable Lessons

- None recorded yet.
