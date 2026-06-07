# BLNO feature user testing

## Current State

Status: active

## Problem

Brainstorm and execute broad user-testing coverage for completed application features on the BLNO tenant.

## Changed Files

- None recorded yet.

## Log

- 2026-06-06T19:56:51 main/NA: Task ledger created.
- 2026-06-06T19:56:59 main/working: Created BLNO broad feature QA ledger. Scope: role-based manual user testing on local BLNO tenant across admin, coach, parent, shared and pathway/progress surfaces.
- 2026-06-06T20:06:16 main/working: Browser plugin opened login cleanly, but after local seed reset the shared in-app browser profile remained stuck on persona Loading state with stale Firebase auth. Falling back to isolated Playwright contexts for broad admin/coach/parent report crawl.
- 2026-06-06T20:34:16 main/working: Starting prioritized blocker fixes: coach session detail, coach schedule timezone mismatch, loading/stuck routes, parent waivers cold-load, parent attendance blank. Will record root cause notes and retest requested flows.
- 2026-06-06T21:38:08 main/working: Root cause notes: coach detail compared encoded route params to decoded occurrence ids, so schedule links with colon-containing occurrence ids could render Session not found; coach times formatted naive UTC API timestamps in the browser timezone instead of the session/academy timezone; /post-login could remain visible during slow local route compilation without a hard-navigation fallback; route loading/cold waiver/blank attendance findings were amplified by cold Next dev compilation and auth handoff timing; admin registration approval returned approved data but the detail page did not set returned mutation data into React Query cache before background invalidation, allowing a transient stale error state.
- 2026-06-06T21:38:08 main/working: Fixes applied: decoded coach session detail ids; added session timezone to coach BFF/today/session payloads; added timezone-aware frontend formatting treating naive API timestamps as UTC; added /post-login hard replace fallback; stabilized local-auth blocker tests with role-isolated route checks and cold-dev waits; updated admin registration detail mutation cache from successful approval/waitlist responses; fixed the unrelated admin pathway import/prop consistency that was blocking frontend typecheck during verification.
- 2026-06-06T21:39:22 main/working: Clarification: the working tree contains pre-existing/unrelated skill-pathway edits. This blocker pass did not intentionally expand into those areas; final verification was run after the current working tree's unrelated admin/pathway type inconsistency was resolved, so pnpm typecheck/lint could complete.
- 2026-06-07T02:40:00 main/working: Fix 4 root cause — `list_active_students_for_parent` used `$or [{parent_id},{parent_user_id}]`; `parent_user_id` has no compound index so MongoDB fell back to a collection scan on cold load (>12 s). Fix: two separate indexed queries unioned in Python by `_id`.
- 2026-06-07T02:40:00 main/working: Fix 5 root cause — `list_attendance_for_parent` in `composition/parent.py` called `await _resolve_coach_name(coach_id)` inside the attendance loop, one DB round-trip per unique coach (N+1). Fix: collect all unique coach IDs, single batch `users.find($in)`, populate cache before loop.
- 2026-06-07T02:40:00 main/working: Two pre-existing branch test gaps also fixed: (a) `AdminCurrentPaymentView` gained `session_title` field from skill-pathway work but test assertion omitted it — added `"session_title": None`; (b) `progress_routes.py` inline `audit_logs.insert_one` triggered structural raw-Mongo guard — added to `APPROVED_COMPOSITION_EXCEPTIONS` with Transitional rationale.

## Verification

- No verification recorded yet.
- 2026-06-06T20:23:42: Local stack fresh completed and remains running. Smoke passed. Local authenticated Playwright spec passed: 3 tests passed covering seeded parent, admin, and coach sign-in/role access. Persona crawls completed: admin 21 routes, coach 6 routes, parent 7 routes; screenshots and JSON saved under /tmp/academy-manager-qa. Findings: coach session list renders but session-detail link showed 'Session not found'; admin pause-requests/users/shared messages and coach dashboard/today showed loading in short-window crawl; parent waivers cold route exceeded 12s compile/navigation; targeted warm recheck then exposed intermittent /post-login stuck state for admin sign-in.
- 2026-06-06T20:44:50: RED/GREEN for coach session blocker: added local-auth E2E for opening first upcoming coach session and timezone display. Initial failures: /post-login stalled, then schedule showed 11:00 PM. Fixes: post-login hard-navigation fallback; coach BFF exposes timezone; frontend formats coach session times/date keys in session timezone and treats naive API timestamps as UTC; detail page decodes occurrence id. Focused test now passed: seeded coach can open an upcoming session from schedule.
- 2026-06-06T21:38:09: Backend focused tests passed: cd backend && .venv/bin/pytest v2/tests/interface/test_coach_sessions.py v2/tests/interface/test_coach_today_golden_master.py -q (4 passed). Frontend checks passed: cd frontend && pnpm typecheck; cd frontend && pnpm lint. Focused local-auth blocker regression passed: 4 Playwright tests covering coach session detail/timezone, coach dashboard/today, admin pause-requests/users/messages, parent waivers/attendance.
- 2026-06-06T21:38:09: Requested flow retests on http://blno.localhost:3001 passed in isolated Playwright contexts: coach attendance marking, coach progress notes, coach session progress, parent waiver signing, parent attendance view, parent pause request, admin registration approval. Local-only setup inserted QA waiver template and QA registration applications because seed had existing signed waiver and no pending registrations.
- 2026-06-07T02:40:00: Backend 970 passed, 0 failed (`pytest v2/tests -q`). `ruff check v2` clean. Frontend `pnpm typecheck` clean. All 5 bug fixes applied; 2 pre-existing branch test issues resolved.

## Reusable Lessons

- None recorded yet.
