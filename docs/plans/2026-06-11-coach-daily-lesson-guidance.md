# Automatic Daily Coach Lesson Guidance — Phased Implementation Plan

Date: 2026-06-11
Status: proposed (awaiting approval)
Ledger: `docs/test-results/active/2026-06-11-coach-daily-lesson-guidance.md`

## Context

Coaches currently open the skill board and decide ad hoc what to teach. Goal: when a coach logs in, the app automatically shows **what to teach each kid in each assigned session today**, generated from existing Skill Pathway progress (no admin prep), enriched with BWF Shuttle Time lesson references and YouTube links, plus a daily coach email digest. The Skill Pathway stays — we enrich it, not replace it.

**Confirmed decisions (user, 2026-06-11):**
- PDF button = **citation chip only** (manual name, lesson range, page range; no hosted file, no link). The Shuttle Time PDF is "all rights reserved" and exists only on the local laptop.
- Lesson cards = **original-wording summaries** (goal, teaching points, equipment, activity, safety in our own words), not verbatim markdown conversion.
- **YouTube links at level and skill granularity** (in addition to per-lesson-card links): each level and each skill can carry curated YouTube refs, surfaced on the level group and on each student's next skill in the UI and the email digest.

## 1. Current behavior found

All inspected paths exist (none missing):

- **Curriculum** (`backend/v2/contexts/curriculum/`): `domain/models.py` has `Program`, `Level`, `Skill` (sequence, is_required, scoring_type, pass_threshold_pct), `SkillCriterion`, and `ExternalLessonReference` (metadata-only by docstring contract: source `BWF_SHUTTLE_TIME`, module_name, lesson_range, reference_title, page_hint — never copied lesson text). `application/use_cases/seed_curriculum.py` seeds the 6-level Badminton pathway (33 skills: 6/6/5/5/5/6) with Shuttle Time refs per level exactly matching the requested mapping (L1→Lessons 1-2 p.9-15 … L6→Lessons 19-22 p.86-102). Repos: `mongo_{program,level,skill,criterion,ext_ref}_repo.py`. Indexes via `migrations/0120_curriculum_indexes.py`.
- **Student progress** (`backend/v2/contexts/student_progress/`): `SkillStatus` = NOT_STARTED/INTRODUCED/LEARNING/PRACTICING/TEST_READY/PASSED/NEEDS_REVIEW. `get_skill_board.py` groups a session roster by current level with per-skill statuses (batched, no N+1). `update_skill_status.py` accepts only coach-settable statuses (PASSED excluded); `record_test_attempt.py` auto-sets PASSED at threshold (quick-pass = 1 attempt/1 success); `get_pathway_placement.py` has `_next_action`; `recommend_level_up.py` exists.
- **Coach BFF** (`backend/v2/interfaces/coach/`): `today_routes.py` (GET `/api/v2/coach/today` → `ListCoachOccurrencesForDate` + `GetSessionRoster`), `skill_routes.py` (status/test/level-up/skill notes, `_resolve_program_id` helper, session-assignment guard), `notes_routes.py`, `views.py` DTOs, `deps.py` (`CoachUseCases` on `app.state.coach`; `require_persona("coach")` → 404 on wrong persona; `AuthClaims` carries user_id + academy_id).
- **Composition**: `composition/pathway.py` (`CurriculumComposition`, `StudentProgressComposition`), `composition/coach.py` wires both into `CoachUseCases`.
- **Communications** (`backend/v2/contexts/communications/`): Campaign/Delivery models, audiences incl. `AcademyAudience(role="coach")`, `SendCampaign`, `ResendEmailSendPort` gated by `email_delivery_enabled and resend_api_key` (else `StubEmailSendPort`) — local/test email safety-blocked by default.
- **Scheduler**: `backend/v2/main.py:220-254` — `AsyncIOScheduler(timezone=settings.scheduler_tz)`, existing daily cron `_process_scheduled_resumes` looping all academies. Pattern to copy.
- **Migrations**: `backend/v2/migrations/NNNN_*.py` with `up(db)`; index-only by convention — curriculum *data* is seeded via use case + admin route (`seed_badminton` at `POST /programs/{program_id}/seed-badminton`, idempotent), not migrations.
- **Frontend**: `app/(coach)/coach/today` (date picker + session list, React Query `getCoachToday`), `sessions/[id]/progress/page.tsx` → `getCoachSessionSkillBoard` → `components/pathway/skill-board.tsx` (SkillCellEditor: status buttons, quickPass, record test). `lib/api/client.ts` `apiFetch` (Bearer + X-Academy-Id); hand-written types in `lib/api/coach.ts` / `curriculum.ts`. Mobile-first cards, bottom nav, 44px touch targets, skeletons, inline error+retry. No PDF viewer exists; external links are plain `<a>`.
- **Reference materials**: both PDFs exist locally at `/Users/ramc/Documents/Badminton/` (Shuttle-Time-Manual.pdf 2.9 MB; Developmental-Sports lesson plans 1.6 MB, 112 pages landscape, 22 lessons: Starter 1-10, Swing/Throw 11-12, Throw/Hit 13-18, Learn to Win 19-22). They are authoring inputs only — never committed, hosted, or attached. YouTube playlist supplied; prior discovery found live YouTube fetch throttled → store explicit video refs, never scrape at runtime.

## 2. Proposed architecture

Reuse > build:

1. **`LessonCard` aggregate (curriculum context)** — new model (NOT an extension of `ExternalLessonReference`, which is pointer-only per its licensing contract and per-skill; cards carry original teaching content and map one lesson → one level + N skills). Seeded from a curated JSON file in the repo, idempotently, per academy.
2. **`GetTeachingFocus` (student_progress)** — pure next-skill selection per student, reusing the same ports and level-grouping/batching as `GetSkillBoard`. Pathway/status truth stays in student_progress; nothing duplicated.
3. **`GenerateDailyTeachingPlan` (new `coaching` use case)** — orchestrates `ListCoachOccurrencesForDate` → `GetSessionRoster` → `GetTeachingFocus` → lesson-card + video-ref lookup (level- and skill-scoped YouTube links attached to groups and next skills); returns the Today's Teaching Plan DTO. Exposed via coach BFF.
4. **Outcome buttons reuse existing write paths** — no new write endpoints. Introduced/Practicing/Needs review → existing `update_skill_status`; **Mastered → existing quick-pass `record_test_attempt` (1/1) → PASSED**, preserving the invariant that PASSED only comes from test attempts (audit trail intact). NEEDS_REVIEW keeps the skill queued because next-skill selection prioritizes it.
5. **`SendCoachDailyDigest` (communications)** — per-coach personalized email built from the same plan generator, sent through the existing `EmailSendPort` (Resend/Stub gating reused — no separate email system), claim-based idempotency, APScheduler morning cron.

## 3. Backend data model additions

**`LessonCard`** (append to `backend/v2/contexts/curriculum/domain/models.py`, frozen pydantic like `Skill`):
`card_id, academy_id, program_id, level_id, skill_ids: list[str], slug (stable content key e.g. "bwf-st-lesson-03"), lesson_number, title, goal_summary, teaching_points: list[str], equipment: list[str], activity_summary, safety_notes: list[str], source ("BWF_SHUTTLE_TIME"), module_name, lesson_range, page_hint, resource_links: list[LessonResourceLink], content_hash (sha256 of source JSON entry → idempotent reseed), display_order, is_active, created_at/updated_at/created_by`.
`LessonResourceLink`: `kind: "YOUTUBE" | "PDF_REFERENCE"`, `title`, `url: str | None` (PDF_REFERENCE has `url=None` — citation chip only). Docstring mirrors `ExternalLessonReference`'s licensing warning: all prose must be original wording.

**`CurriculumVideoRef`** (same file): curated YouTube refs at level/skill granularity — `ref_id, academy_id, program_id, scope: "LEVEL" | "SKILL", level_id, skill_id: str | None, title, url, display_order, content_hash, is_active, created_at/created_by`. Seeded from the same content JSON; repo port `CurriculumVideoRefRepository` (`list_for_level`, `list_for_skills(skill_ids)`), collection `curriculum_video_refs`, idempotent upsert by `(academy_id, program_id, scope, level_id, skill_id, url)`.

**`DigestSend`** (communications `domain/models.py`, like `Delivery`): `digest_id, academy_id, coach_id, coach_email, digest_date (ISO date), status (queued|sent|failed|skipped_empty), provider_message_id, sent_at, failed_reason`.

Mongo collections: `lesson_cards`, `curriculum_video_refs`, `coach_digest_sends`.

## 4. API route shape

New `backend/v2/interfaces/coach/teaching_plan_routes.py` (registered in `interfaces/coach/router.py`, `require_persona("coach")`, 404 on wrong persona):

**`GET /api/v2/coach/today/plan?date=YYYY-MM-DD&program_id=...`** (date defaults today; program via existing `_resolve_program_id` pattern):

```json
{
  "date": "2026-06-11", "program_id": "…", "program_name": "Badminton Skill Pathway",
  "pathway_configured": true,
  "sessions": [{
    "session_id": "s-1", "occurrence_id": "occ-1", "title": "U11 Beginners",
    "start_at": "…", "end_at": "…", "location": "Court 2",
    "groups": [{
      "level_id": "lvl-1", "level_name": "Grip and Control", "level_sequence": 1,
      "youtube_links": [{"title": "Level 1 overview", "url": "https://www.youtube.com/watch?v=…"}],
      "lesson_card": {
        "card_id": "…", "lesson_number": 3, "title": "…", "goal_summary": "…",
        "teaching_points": ["…"], "equipment": ["…"], "activity_summary": "…",
        "safety_notes": ["…"], "source": "BWF_SHUTTLE_TIME",
        "module_name": "Starter Lessons", "lesson_range": "3-6", "page_hint": "p.16-30",
        "resource_links": [
          {"kind": "YOUTUBE", "title": "Grip demo", "url": "https://www.youtube.com/watch?v=…"},
          {"kind": "PDF_REFERENCE", "title": "Shuttle Time Lesson Plans", "url": null}
        ]
      },
      "students": [{
        "student_id": "stu-1", "student_name": "Alice",
        "next_skill": {"skill_id": "sk-2", "name": "V grip", "sequence": 2, "level_id": "lvl-1",
                        "status": "PRACTICING", "is_review": false, "criteria": ["…"],
                        "youtube_links": [{"title": "V grip drill", "url": "https://www.youtube.com/watch?v=…"}]},
        "focus": "practice"
      }]
    }],
    "unplaced": [{"student_id": "stu-9", "student_name": "Zed"}]
  }]
}
```

`focus` ∈ `"practice" | "review" | "ready_for_level_up"`.

**`GET /api/v2/coach/sessions/{session_id}/teaching-plan`** — same groups/unplaced payload for one session (existing session-assignment guard; 404 if not assigned). `/today/plan` loops this builder across occurrences with `asyncio.gather`.

**Outcome writes — existing endpoints, no new ones:**
- Introduced/Practicing/Needs review → `POST /api/v2/coach/students/{sid}/skills/{skill_id}/status` `{status, level_id, program_id}`
- Mastered → `POST /api/v2/coach/students/{sid}/skills/{skill_id}/test` `{attempts_count: 1, success_count: 1, program_id, level_id, session_id}` (existing quick-pass → auto-PASSED)

Admin seed route: `POST /api/v2/admin/pathway/seed-lesson-cards` beside `seed_badminton` in `interfaces/admin/pathway_routes.py`.

## 5. Frontend UX changes

**New lightweight page `frontend/app/(coach)/coach/today/plan/page.tsx`**, deep-linked via a "View teaching plan" button on each session card in `/coach/today` (only change to existing pages; bottom nav untouched).

- `page.tsx` — React Query on `getCoachTodayPlan(date)`; skeleton/error/retry patterns from `today/page.tsx`; sessions → level groups → **lesson card first**, then student rows. Empty state when no sessions; `pathway_configured: false` banner state.
- `frontend/components/teaching/lesson-card.tsx` — lesson number chip + title, goal, collapsible teaching points/equipment/activity/safety; footer: YouTube buttons for the card and the level (`<a target="_blank" rel="noopener noreferrer">`) + PDF **citation chip** ("Shuttle Time · Starter Lessons · L3–6 · p.16–30", non-interactive).
- `frontend/components/teaching/student-focus-row.tsx` — student name, next skill + status badge (NEEDS_REVIEW highlighted), a compact YouTube button when the next skill has `youtube_links` (skill-level video beats card-level for relevance), 4 outcome buttons ≥44px: Introduced / Practicing / Mastered / Needs review. Mutations call existing `updateSkillStatus` / `recordTestAttempt` from `lib/api/curriculum.ts`; on settle, invalidate `["coach-today-plan", date]` (and skill-board keys); row shows a done ✓ state.
- `frontend/lib/api/coach.ts` — add `TeachingPlanResponse` and related types, `getCoachTodayPlan(date?)`, `getSessionTeachingPlan(sessionId)` via `apiFetch`.

Mobile-first throughout (390px target); no admin-heavy imports into coach routes.

## 6. Email/scheduler approach

- **`SendCoachDailyDigest`** (`communications/application/use_cases/send_coach_daily_digest.py`): deps = `DigestSendRepository`, `EmailSendPort` (same port as campaigns → Resend/Stub gating reused), `AudienceResolver` (`AcademyAudience(role="coach")`), `plan_provider` protocol `(coach_id, date) → DailyTeachingPlan | None`, plain-text renderer.
  Flow per coach: `try_claim(academy_id, coach_id, digest_date)` (insert against unique index; None ⇒ already handled, skip) → generate plan → empty ⇒ mark `skipped_empty`, no email → else send → `mark_sent`/`mark_failed`.
  *Why not `SendCampaign`*: campaigns send one shared body to all recipients; the digest is personalized per coach. Reusing the port + resolver keeps safety gating and email resolution without contorting the campaign model.
- **Renderer** (`communications/application/digest_renderer.py`): plain text — per session: time/title/location; per group: level + lesson title + reference line ("Shuttle Time, Starter Lessons, Lessons 3–6, p.16–30"); per student: "Alice — V grip (practicing)" with the skill's YouTube URL when one exists; card/level YouTube URLs verbatim; playlist link in footer. No PDF attachment, no copied lesson text.
- **Scheduler job** in `backend/v2/main.py` beside `_process_scheduled_resumes`: cron `hour=settings.coach_digest_hour` (default 6, scheduler TZ), `id="send_coach_daily_digests"`, loops academies with tenant scope. New settings in `shared/config/settings.py`: `coach_digest_enabled: bool = False` (job registered only when True), `coach_digest_hour: int = 6`.
- **Local/test safety**: defaults mean no job and stub sender; tests assert no real provider call. Never enable live email locally.

## 7. PDF/markdown/video ingestion strategy

- Local PDFs are authoring inputs only: during Phase 1 the implementer reads the 22 lessons and writes **original-wording** summaries into the content JSON. PDFs never committed/hosted/attached.
- PDF surfaces in product only as a citation (manual name, module, lesson range, page range).
- YouTube: explicit video refs (title + URL) curated from the playlist `https://www.youtube.com/playlist?list=PLYqPBxMmvqpLGSmMr4a7GZTmxBLlV78B1` at **three scopes** — per lesson card, per level (`level_videos`), and per skill (`skill_videos`, keyed by `level_sequence` + `skill_sequence`); playlist URL as fallback/footer link. Skill/level coverage is best-effort: where the playlist has no matching clip, the scope simply has no links (UI hides the button). No live scraping.
- Format: **JSON, not markdown** — every field is structured lists/short strings (pydantic-validated at seed, zero new deps). JSON includes a `_license_note` header field.

## 8. Shuttle Time reference seeding strategy

- Content file: `backend/v2/contexts/curriculum/content/badminton_lesson_cards.json`. 22 cards: Starter 1–10 → levels 1–2, Swing/Throw 11–12 → level 3, Throw/Hit 13–18 → levels 4–5, Learn to Win 19–22 → level 6 — aligned with the lesson_range→level mapping already in `seed_curriculum.py`.
- Entries reference curriculum by **sequence** (`level_sequence`, `skill_sequences`) because IDs are per-academy ULIDs; resolved at seed time.
- Seed mechanism: **use case, not data migration** (matches `seed_badminton`): `seed_lesson_cards.py` — find active badminton program (clear error if pathway not seeded) → validate JSON → resolve sequences → **idempotent upsert by `(academy_id, program_id, slug)`** with `content_hash` comparison. The same seed pass upserts `level_videos`/`skill_videos` entries into `curriculum_video_refs`. Wired into `CurriculumComposition` + admin route; local seed flow chains it after pathway seeding.
- Update path: edit JSON in a PR → re-run seed endpoint per academy.

## 9. Migration strategy

Index-only migrations (repo convention; no data migrations):
- `backend/v2/migrations/0124_lesson_card_indexes.py` — `lesson_cards`: unique `card_id`; unique `(academy_id, program_id, slug)`; `(academy_id, level_id, display_order)`; multikey `(academy_id, skill_ids)`. Also `curriculum_video_refs`: unique `ref_id`; unique `(academy_id, program_id, scope, level_id, skill_id, url)`; `(academy_id, skill_id)`; `(academy_id, level_id)`.
- `backend/v2/migrations/0125_coach_digest_send_indexes.py` — `coach_digest_sends`: unique `digest_id`; **unique `(academy_id, coach_id, digest_date)`** (idempotency backbone); `(academy_id, digest_date, status)`.
(Use the next free numbers if taken by implementation time.)

## 10. Testing strategy

Backend unit (fake repos, existing style under `backend/v2/tests/`):
- `test_teaching_focus.py` — NEEDS_REVIEW-first precedence among required skills; first non-PASSED required by sequence; missing progress row = NOT_STARTED; all-required-passed → optional fallback → `ready_for_level_up`; unplaced students; per-level batching.
- `test_generate_daily_teaching_plan.py` — grouping by level then lesson card; null-card group for level-up-ready; empty day; card fallback to level card when a skill has no card.
- `test_lesson_cards.py` — `GetLessonCardForSkill` resolution + display_order tiebreak.
- `test_lesson_card_seed.py` — real JSON parses; every sequence resolves against the seeded pathway; all 22 lessons covered; level/skill video refs resolve and upsert idempotently; reseed no-op; hash-change updates in place; refs stay pointer-only.
- `test_send_coach_daily_digest.py` — one send per coach; second run sends zero; failure marked; empty plan → `skipped_empty`; stub sender when delivery disabled (covers "no real email in local/test").

Backend interface (`v2/tests/interface/`): `test_coach_teaching_plan.py` — response shape; date param; empty day; parent/admin persona → 404 and anon → 401 (coach authorization); unassigned session → 404; composition-missing → 503. Existing `test_coach_skill_routes.py` covers outcome writes (pathway progress update behavior); add quick-pass-sets-PASSED assertion if absent.

Frontend: `frontend/e2e/specs/coach-teaching-plan.spec.ts` (mock-API fixture pattern from `coach-today.spec.ts` / `skill-board.spec.ts`) — renders plan with lesson card + students; "Mastered" issues `POST …/test` with `success_count: 1`; "Needs review" issues status POST; YouTube href correct; error retry. Plus `pnpm typecheck` / `pnpm lint`.

## 11. Risks and decisions

- **Licensing (highest)**: all card prose original wording; PDF citation-only; guard rails = model docstring, JSON `_license_note`, seed test, PR checklist.
- **Mastered = quick-pass test attempt, not a status write** — preserves PASSED-only-via-RecordTestAttempt invariant and audit history.
- **Skill-id drift**: cards store resolved skill_ids; pathway restructuring requires reseed (re-resolves by sequence). Runtime sequence resolution rejected (hides breakage, costs reads).
- **Timezone**: digest "today" computed in scheduler TZ; per-academy TZ deferred.
- **Crash-after-claim** leaves a `queued` digest row unsent — accepted v1; `retry_failed_for_date` specified for later.
- **No pathway seeded** → plan returns sessions with empty groups + `pathway_configured: false` instead of 5xx.
- **Perf**: plan endpoint gathers per session like today_routes; per-level batching like GetSkillBoard; criteria fetched once per distinct next skill.
- **Authoring effort**: 22 original-wording cards is the long pole of Phase 1; content work, reviewable in PR like code.

## 12. Phased implementation

Each phase is independently shippable (own PR(s)), lands with tests green, and has an exit gate. Update the ledger (`scripts/dev/test_result.py log/verify`) at every phase boundary.

### Phase 0 — Plan registration (this PR)
- Store this plan in `docs/plans/2026-06-11-coach-daily-lesson-guidance.md`; log to the active ledger.
- Exit gate: plan approved by user.

### Phase 1 — Lesson card foundation (curriculum context)
Tasks:
1. `LessonCard` + `LessonResourceLink` domain models; `LessonCardRepository` port; `mongo_lesson_card_repo.py`; migration 0124; unit tests.
2. Author `badminton_lesson_cards.json` (22 cards, original wording; YouTube refs from playlist at card, level, and skill scope; PDFs read locally as authoring input).
3. `CurriculumVideoRef` model + `CurriculumVideoRefRepository` + `mongo_video_ref_repo.py` (indexes share migration 0124).
4. `seed_lesson_cards.py` use case (cards + video refs) + `manage_lesson_cards.py` (`ListLessonCards`, `GetLessonCardForSkill`); wire into `CurriculumComposition`; admin route `POST /api/v2/admin/pathway/seed-lesson-cards`; seed tests.
- Exit gate: `pytest v2/tests -q` green; seed run against local stack creates 22 cards + video refs idempotently; content reviewed for original wording in PR.

### Phase 2 — Teaching plan backend (student_progress + coaching + coach BFF)
Tasks:
4. `GetTeachingFocus` (student_progress) + read models + unit tests.
5. `GenerateDailyTeachingPlan` (coaching) + unit tests.
6. Composition wiring: `pathway.py`, `coach.py`, `deps.py` (`CoachUseCases` optional fields).
7. Coach BFF: `teaching_plan_routes.py` + `views.py` DTOs + router registration + interface tests (shape, authz 401/404, empty day, 503).
- Exit gate: `GET /api/v2/coach/today/plan` returns a correct plan for the seeded demo coach on the local stack; interface + unit tests green.

### Phase 3 — Coach mobile UI (frontend)
Tasks:
8. API client types + `getCoachTodayPlan` / `getSessionTeachingPlan` in `lib/api/coach.ts`.
9. `/coach/today/plan` page + `lesson-card.tsx` + `student-focus-row.tsx` + "View teaching plan" link on Today session cards.
10. e2e spec `coach-teaching-plan.spec.ts`; `pnpm typecheck && pnpm lint`.
- Exit gate: on mobile viewport, coach sees per-session plan (lesson card first, students grouped by level); Mastered tap → skill board shows PASSED; Needs review keeps skill queued; e2e green.

### Phase 4 — Daily email digest (communications + scheduler)
Tasks:
11. `DigestSend` model + `DigestSendRepository` + `mongo_digest_send_repo.py` + migration 0125 + unit tests.
12. `SendCoachDailyDigest` + `digest_renderer.py` + `composition/digests.py` + idempotency tests.
13. Scheduler job + settings (`coach_digest_enabled` default False, `coach_digest_hour` default 6) in `main.py`; verify via stub logs locally.
- Exit gate: digest job run locally produces stub-logged personalized email per coach with sessions/students/skills/PDF citations/YouTube links; second run sends zero; no real email possible with default flags.

Phases 1 and 2 tasks 4–5 can proceed in parallel; Phase 3 depends on Phase 2; Phase 4 depends on Phase 2 (not 3).

## 13. Exact files likely changed

New backend (under `backend/v2/`): `contexts/curriculum/application/use_cases/{manage_lesson_cards.py, seed_lesson_cards.py}`, `contexts/curriculum/infrastructure/mongo_lesson_card_repo.py`, `contexts/curriculum/infrastructure/mongo_video_ref_repo.py`, `contexts/curriculum/content/badminton_lesson_cards.json`, `contexts/student_progress/application/use_cases/get_teaching_focus.py`, `contexts/coaching/application/use_cases/generate_daily_teaching_plan.py`, `contexts/communications/application/use_cases/send_coach_daily_digest.py`, `contexts/communications/application/digest_renderer.py`, `contexts/communications/infrastructure/mongo_digest_send_repo.py`, `interfaces/coach/teaching_plan_routes.py`, `composition/digests.py`, `migrations/0124_lesson_card_indexes.py`, `migrations/0125_coach_digest_send_indexes.py`.
Modified backend: `contexts/curriculum/{domain/models.py, application/ports.py}`, `contexts/student_progress/domain/models.py`, `contexts/communications/{domain/models.py, application/ports.py}`, `interfaces/coach/{router.py, views.py, deps.py}`, `interfaces/admin/pathway_routes.py`, `composition/{pathway.py, coach.py}`, `shared/config/settings.py`, `main.py`.
New frontend: `app/(coach)/coach/today/plan/page.tsx`, `components/teaching/lesson-card.tsx`, `components/teaching/student-focus-row.tsx`, `e2e/specs/coach-teaching-plan.spec.ts`.
Modified frontend: `lib/api/coach.ts`, `app/(coach)/coach/today/page.tsx`.
Tests: per section 10 under `backend/v2/tests/`.

## 14. Exact commands to run

```bash
# backend
cd backend && source .venv/bin/activate
ruff format v2 && ruff check v2          # .venv ruff, not system
pytest v2/tests -q                        # full
pytest v2/tests/interface -q              # focused

# frontend
cd frontend && pnpm typecheck && pnpm lint
pnpm e2e                                  # when e2e/ files change

# manual verification
scripts/local_test_stack.sh fresh         # reset + seed demo data
# seed lesson cards (admin auth):  POST /api/v2/admin/pathway/seed-lesson-cards
# open http://blno.localhost:3001/coach/today → "View teaching plan"
# digest dry-run: V2_COACH_DIGEST_ENABLED=true with email delivery off → stub logs

# ledger
scripts/dev/test_result.py log coach-daily-lesson-guidance --agent main --status working --message "..."
scripts/dev/test_result.py verify coach-daily-lesson-guidance --message "..."

# before push
scripts/dev/pre-push-checks.sh
```

## Acceptance criteria mapping

| Criterion | Where satisfied |
| --- | --- |
| Coach opens today's session and sees what each kid should work on | Phase 2 endpoint + Phase 3 UI |
| Plan generated automatically from pathway progress | `GetTeachingFocus` + `GenerateDailyTeachingPlan` (Phase 2) |
| Coach can mark lesson outcome | Phase 3 outcome buttons → existing endpoints |
| Mastered updates pathway progress | quick-pass `record_test_attempt` → PASSED (existing) |
| Needs review stays in future queue | NEEDS_REVIEW prioritized by next-skill selection |
| Daily email for assigned coach with sessions/students/skills/PDF refs/YouTube | Phase 4 digest |
| Tests: plan generation, coach authz, progress update, frontend rendering | Section 10 / phase exit gates |
