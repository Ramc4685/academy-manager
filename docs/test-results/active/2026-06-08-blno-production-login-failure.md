# BLNO production login failure

## Current State

Status: resolved

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
- 2026-06-08T19:03:08 main/working: User reported /api/v2/me still 401 after PR merge. Rechecked production: Mongo has ramchand4685@gmail.com active admin/parent membership and blno-academy.courtmastr.com verified domain row. Fly is still running old image labeled GH_SHA=7eb83f6, so the merged domain-resolution fix is not deployed yet.
- 2026-06-08T19:37:22 main/working: User reported Firebase auth/unauthorized-domain from mobile screenshot. Screenshot URL shows acamedy.courtmastr.com, a misspelled host. Live curl confirms acamedy.courtmastr.com currently serves the Next app through wildcard Cloudflare routing, so Firebase rejects auth on the unauthorized typo domain before /api/v2/me is reached. Planning canonical-host redirect fix.
- 2026-06-09T15:42:43 main/working: Live Cloudflare proxy check returned HTTP 404; auth proxy flag stayed off.
- 2026-06-09T17:04:08 main/working: After the Google OAuth client edit, set NEXT_PUBLIC_FIREBASE_AUTH_PROXY=1 and deployed production workflow run 27238406975 successfully. Remaining: real-device iPhone Safari sign-in test.
- 2026-06-09T17:20:00 main/resolved: User confirmed Google sign-in works on iPhone (real-device test passed). Issue fully resolved.
## Verification

- No verification recorded yet.
- 2026-06-08T17:04:59: Root cause for screenshot path: ramchand4685@gmail.com exists in Firebase Auth as enabled/email-verified but provider list is google.com only, so signInWithEmailAndPassword from the login form cannot succeed for that account. The production BLNO bundle contains correct admin user and membership roles for this email.
- 2026-06-08T17:19:02: Root cause for /post-login stuck: production backend cannot reach MongoDB Atlas from Fly. Logs show tenant_resolve_failed and dispatcher failures with No route to host / ServerSelectionTimeoutError to all Atlas shard hosts; Fly health becomes unhealthy and /api/v2/me returns/hangs as 503. Set V2_RUN_MIGRATIONS_ON_BOOT=false as a Fly secret override to stop boot migration crash-loop, but tenant/auth requests still require Atlas connectivity.
- 2026-06-08T17:34:55: Live checks: healthz on blno-academy.courtmastr.com returned 200; /api/v2/me without auth returned 401 {detail: Not authenticated}; fake Authorization/X-CourtMastr-Identity through blno-academy and api.academy still returned 401 with no auth_failed log. Read-only Fly SSH Mongo inspection showed academies slug/custom_domain are blno-badminton/blno-badminton.academy.courtmastr.com, academy_domains contains blno-academy.courtmastr.com, and ramchand4685@gmail.com has active admin/parent membership in acad_blno_badminton.
- 2026-06-08T17:49:59: Local fix verification passed: pytest backend/v2/tests/contract/test_platform_mongo_tenant_lifecycle_repo.py -q => 2 passed; pytest backend/v2/tests/interface/test_tenant_resolution.py -q => 20 passed; ruff format --check v2/main.py v2/tests/contract/test_platform_mongo_tenant_lifecycle_repo.py => passed; ruff check same files => passed. Initial regression failed before implementation with None != acad_blno_badminton.
- 2026-06-08T19:03:08: Read-only production Mongo check confirmed user user_ca90a2b95efbf0205fa0 has active membership membership_aee0262e507c45f899d5 in acad_blno_badminton; academy_domains contains blno-academy.courtmastr.com status=verified. flyctl image show shows production backend image still labeled GH_SHA=7eb83f6, before PR #153 merge a85dde6 and current main 64c760b.
- 2026-06-08T19:31:08: Production deployed from workflow_dispatch run 27175473230 at main SHA a18a18c; Backend, Frontend Static, Chromium/WebKit E2E, Deploy Backend, Deploy Frontend, and Production Smoke all passed. flyctl image show confirms courtmastr-academy-api now runs GH_SHA=a18a18c instead of old 7eb83f6. Authenticated production probe using Firebase Admin-created short-lived token for ramchand4685@gmail.com against 127.0.0.1:8001 with Host blno-academy.courtmastr.com returned 200 from /api/v2/me with academy_id=acad_blno_badminton, membership_id=membership_aee0262e507c45f899d5, roles admin/parent.
- 2026-06-08T19:42:43: Reproduced unauthorized-domain root cause: https://acamedy.courtmastr.com/login serves the app through wildcard Cloudflare routing and is a misspelled unauthorized Firebase domain. Added canonical host redirect mapping acamedy.courtmastr.com -> academy.courtmastr.com. Focused test node --no-warnings --test lib/canonical-host.node-test.mjs passed; frontend pnpm build passed; local next start smoke with --resolve acamedy.courtmastr.com:3002 returned 308 Location https://academy.courtmastr.com/login?next=%2Fadmin while academy.courtmastr.com returned 200.
- 2026-06-09T15:45:24: `curl -I https://blno-academy.courtmastr.com/__/auth/handler` returned HTTP/2 404; auth proxy flag left unset.
- 2026-06-09T16:31:15: After PR #157, proxy returned HTTP/2 200 and Firebase authorized domains included blno-academy.courtmastr.com, but Google OAuth still returned redirect_uri_mismatch.
- 2026-06-09T17:04:08: After OAuth client propagation, Google OAuth no longer returned redirect_uri_mismatch. Production workflow run 27238406975 passed; deployed login bundle contains `proxyEnabled:!0`.
## Reusable Lessons

- Mobile Firebase Google sign-in needs the first-party `/__/auth/*` proxy plus matching Google OAuth redirect URI and JS origin for each tenant domain.
- To verify a baked `NEXT_PUBLIC_*` flag, grep the served chunk for a surviving call-site value such as `proxyEnabled:!0`.
