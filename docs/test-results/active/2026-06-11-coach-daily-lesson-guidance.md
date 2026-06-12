# coach daily lesson guidance

## Current State

Status: active

## Problem

Design automatic coach daily lesson guidance from pathway progress, with email summary and YouTube/PDF references.

## Changed Files

- None recorded yet.

## Log

- 2026-06-11T15:21:30 main/NA: Task ledger created.
- 2026-06-11T15:21:53 main/working: Discovery: daily lesson guidance can build on coach today, session skill board, pathway progress, curriculum external refs, and existing communications/email infrastructure. YouTube playlist URL supplied; direct YouTube fetch was throttled, so design should store playlist/video refs explicitly rather than relying on live scraping.
- 2026-06-11T15:33:55 main/working: PDF discovery: Shuttle Time lesson plan PDF is 112 pages landscape with 22 lessons: Starter 1-10, Swing/Throw 11-12, Throw/Hit 13-18, Learn to Win 19-22. Existing seeded pathway already maps six levels to those lesson ranges via external refs, so recommended approach is to keep pathway and enrich references with lesson/video/mobile-summary metadata.
- 2026-06-11T15:36:25 main/working: Licensing/design check: official Shuttle Time pages describe free teaching resources, lesson plans, and video clips. Local PDF copyright page still says all rights reserved, so safest implementation is structured metadata + mobile summaries + links; full markdown storage only if academy confirms permitted internal redistribution/use.
- 2026-06-11T17:39:56 main/working: Phase 0 (plan registration): plan stored at docs/plans/2026-06-11-coach-daily-lesson-guidance.md. Verified plan's codebase claims via 3 parallel subagents (curriculum, student_progress+coach BFF, communications+scheduler+frontend). Nearly all CONFIRMED. Notes: actual badminton skill count is 33 (plan said ~29); admin route is seed_badminton at /programs/{id}/seed-badminton (plan called it seed_badminton_pathway); migrations 0124+0125 confirmed free; new models LessonCard/CurriculumVideoRef/DigestSend and teaching_plan_routes.py confirmed absent; coach_digest settings absent; content/ dir absent (all as plan expects for new work). Exit gate: awaiting user approval.
- 2026-06-12T06:37:22 main/working: Phase 1 (lesson card foundation) complete on branch feat/coach-lesson-cards. Added: LessonCard/LessonResourceLink/CurriculumVideoRef domain models (original-wording licensing docstrings); LessonCardRepository + CurriculumVideoRefRepository ports + mongo_lesson_card_repo.py + mongo_video_ref_repo.py (idempotent upsert); migration 0124 indexes; content/badminton_lesson_cards.json (22 original-wording cards, lessons 1-22, per-level 2/4/4/2/6/4, every skill covered, PDF citation chips url=null, 6 level-scoped playlist video refs, skill_videos empty/best-effort); seed_lesson_cards.py (sequence resolution, content_hash idempotency) + manage_lesson_cards.py (ListLessonCards, GetLessonCardForSkill); wired into CurriculumComposition; admin route POST /api/v2/admin/pathway/seed-lesson-cards (409 if pathway unseeded, 422 on unresolved sequence). Tests: test_lesson_cards.py (5), test_lesson_card_seed.py (9), test_lesson_card_repo_mongo.py (1 mongomock end-to-end). Full suite 1051 passed, ruff clean.
## Verification

- No verification recorded yet.
- 2026-06-12T06:37:22: Phase 1 exit gate: pytest v2/tests -q green (1051 passed); ruff check/format clean on all new/changed files; mongomock round-trip seeds 22 cards + 6 video refs and reseed is a no-op (idempotent). Manual local-stack seed deferred to PR review (covered by mongomock end-to-end test).
## Reusable Lessons

- None recorded yet.
