# Skill Pathway MVP — Stabilization & Merge-Readiness Report

**Date:** 2026-06-05
**Branch:** `feat/skill-pathway-mvp` (worktree `.worktrees/skill-pathway`)
**Base commit under review:** `9065940` (Skill Pathway MVP)
**Goal:** Close gaps, add the missing risky-flow tests, remove dead wiring, and
verify the MVP is safe to merge. No new product scope was added except where
required to fix a correctness/merge regression.

---

## 1. Files changed (stabilization pass, on top of `9065940`)

**Source fixes**
- `backend/v2/contexts/curriculum/application/use_cases/seed_curriculum.py`
  — seed now actually persists the per-level external reference (was built then
  discarded with `_ = ref`); anchored to each level's first skill.
- `backend/v2/composition/pathway.py`
  — `compose_curriculum` now passes the 5 repos to `MongoPathwayQuery(...)`
  (was `MongoPathwayQuery(db)` → `TypeError` at app startup);
  `compose_student_progress` now passes `skill_repo`/`level_repo` to
  `CurriculumSkillLookup(...)` (was `CurriculumSkillLookup(db)` → `TypeError`).
- `backend/v2/interfaces/parent/deps.py`
  — `ParentUseCases.student_progress` made `| None = None` (was required, broke
  every existing parent test/use-case construction).
- `backend/v2/interfaces/coach/deps.py`
  — `CoachUseCases.{student_progress,create_skill_note,list_skill_notes}` made
  `| None = None` (were required, broke the shared coach test fixture).
- `backend/v2/contexts/student_progress/application/ports.py`
  — removed the unused `StudentLookup` protocol.
- `backend/v2/contexts/student_progress/infrastructure/enrollment_student_lookup_adapter.py`
  — **deleted** (dead adapter, no consumer).

**Lint/format normalization** (auto-fix, `ruff check --fix` + `ruff format`)
- `backend/v2/composition/{admin,coach,parent}.py`,
  `backend/v2/interfaces/{admin,coach,parent}/router.py`,
  `backend/v2/interfaces/admin/deps.py`,
  `backend/v2/tests/interface/{test_admin_pathway,test_coach_skill_routes,test_parent_progress_routes}.py`
  — import sorting (I001), unused import (F401), `getattr` constant (B009).

**Docs**
- `docs/adr/0010-skill-pathway-module.md` — added decision #10 (no cross-context
  student lookup in MVP; blank certificate display names deferred).
- `docs/tickets/post-mvp-skill-pathway-backlog.md` — 8 backlog tickets (new).
- `docs/test-results/archive/2026-06-05-skill-pathway-stabilization.md` — this report (new).

## 2. Tests added
- `backend/v2/tests/seed/test_badminton_seed.py` (7 tests) — fresh-load,
  idempotency, no-duplicate-on-rerun, program/6-levels/skills/refs created,
  refs-contain-only-metadata, no forbidden content fields on any model, no BWF
  body text in seeded values. **Copyright guard.**
- `backend/v2/tests/interface/test_admin_progress_routes.py` (3 tests) — full
  place → test → level-complete → recommend → approve → certificate flow over
  the real admin routes; rejection flow (no level-up, no cert, reason saved);
  non-admin persona → 404.

## 3. Bugs fixed
1. **Copyright-relevant seed bug:** external references were never persisted, so
   `external_lesson_refs` was empty. Now correctly seeded (metadata only).
2. **`compose_curriculum` broken** — `MongoPathwayQuery(db)` missing 4 args;
   real admin app would fail at startup. Fixed.
3. **`compose_student_progress` broken** — `CurriculumSkillLookup(db)` violated
   the adapter's keyword-only `skill_repo`/`level_repo` constructor. Fixed.
4. **`ParentUseCases` / `CoachUseCases` required new fields with no defaults** —
   broke ~126 pre-existing tests (parent billing/activity/etc. + all coach
   tests). Made the skill-pathway fields optional, matching the admin pattern.
5. **Dead wiring removed** — unused `StudentLookup` port + `EnrollmentStudentLookup`
   adapter deleted (Option B); rationale documented in ADR-0010 #10.
6. **Test isolation bug (introduced while authoring):** the new admin progress
   test originally used `asyncio.run()`, whose teardown calls
   `set_event_loop(None)` and corrupted the default loop relied on by sibling
   coach/parent tests. Replaced with a private `new_event_loop()` helper.

## 4. Frontend validation result ✅
Worktree `frontend/`, `pnpm install` (deps were absent in the worktree).
- `pnpm typecheck` (`tsc --noEmit`) → **pass, 0 errors.**
- `pnpm lint` (`next lint`) → **pass, no ESLint warnings or errors.**
  (`next lint` prints a deprecation notice — informational, not a failure.)

## 5. Backend validation result ✅
Backend `.venv` (per AGENTS.md, system ruff differs).
- `ruff check v2` → **All checks passed.**
- `ruff format --check v2` → **555 files already formatted.**
- `pytest v2/tests -q` → **918 passed, 0 failed, 0 errors** (~19s).
  Tests use `mongomock`; no live Mongo required.
- One benign warning remains (pre-existing): pytest tries to collect the domain
  model `TestAttempt` as a test class. Harmless; renaming the model is out of
  scope.

## 6. Manual smoke test — checklist + result

**Checklist (run against a live stack with a seeded academy):**
1. Seed badminton pathway (admin `POST /api/v2/admin/programs/{id}/seed-badminton`).
2. Admin views pathway (`GET .../pathway` → program + 6 levels + skills + refs).
3. Admin places a student into Level 1 (`POST .../students/{id}/place-in-level`).
4. Coach opens the student passport (coach skill routes).
5. Coach records a skill test (passing).
6. Student completes Level 1 (all required skills PASSED).
7. Coach recommends level-up.
8. Admin approves level-up (current level completed, next created, cert issued).
9. Parent sees progress (`/parent/progress` skill section).
10. Parent sees certificate (`GET /parent/students/{id}/certificates`).

**Result:** The full flow (steps 3–10 at the route + use-case layer) is now
covered by the automated integration test `test_admin_progress_routes.py`, which
passes. A **manual UI click-through was NOT executed in this session** — it
requires the running Next.js + FastAPI + Mongo stack with a seeded academy and
authenticated personas. Recommended as the final pre-merge gate by a human
reviewer; no blocking issues are expected given automated coverage.

## 7. Remaining risks
- **Blank certificate display names (medium).** The admin approve route issues
  certificates without `student_name` / `level_name` / `program_name`
  (defaults blank; `level_sequence` defaults to 1). Certificates are valid and
  retrievable but display fields are empty. Tracked as backlog #7
  ("Better certificates") and documented in ADR-0010 #10. Not a merge blocker.
- **Manual UI smoke not executed (low/medium).** See §6 — do a human walkthrough
  before release.
- **`.venv` not gitignored in the worktree (low).** `backend/.venv` shows as
  untracked here; ensure it is excluded from any commit.
- **`TestAttempt` pytest collection warning (low).** Cosmetic.
- **Parent skill routes assume `student_progress` is wired (low).** It is
  `Optional` for back-compat but the routes do not null-check it (unlike the
  admin routes). Production composition always sets it; a misconfiguration would
  surface as a 500 rather than a 503. Consider a guard in a follow-up.

## 8. Merge recommendation

**Recommendation: SAFE TO MERGE** once a human runs the manual UI smoke (§6).

The original "Do not merge yet" call was correct: the branch as committed at
`9065940` had **two startup-breaking composition bugs**, **~126 broken
pre-existing tests** from non-defaulted use-case fields, an **empty
`external_lesson_refs`** (copyright-relevant), and the two **highest-risk flows
were untested**. All of these are now fixed and covered:

- Backend: 918 tests pass, lint + format clean.
- Frontend: typecheck + lint pass.
- Seed copyright guard and full level-up/certificate flow are tested.
- Dead wiring removed; decisions documented.

The only residual product gap (blank certificate names) is documented and
deferred to the backlog; it does not block merge.
