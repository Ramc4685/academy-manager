# Admin + Parent UI Follow-ups to PR #184 — Parallel Workstream Plan

Date: 2026-06-12
Status: Planned (execute after PR #184 merges to main)

## Context

PR #184 shipped the coach lesson guidance feature (BWF lesson cards → teaching plan backend → coach mobile UI → daily email digest + scheduler), but it is coach-only. Research confirmed the admin and parent surfaces are missing:

- Admin cannot seed or even see lesson cards from the UI (`POST /seed-lesson-cards` is the only endpoint — no GET exists, and cards are tenant-scoped so seeding recurs per academy).
- Digest settings (`coach_digest_enabled`/`coach_digest_hour`) are **global env vars** (`backend/v2/shared/config/settings.py:82-91`), and the scheduler cron only registers at startup if the env flag is true (`backend/v2/main.py:325-335`) — admins can't control it, and there's no test-send or delivery visibility.
- Admin session detail shows roster/waitlist/skill-board but not the teaching plan the coach received.
- Parents have no window into per-session skill focus, even though coach-recorded outcomes (Introduced/Practicing/Mastered/Needs review) persist in the student_progress context.

**Branching:** all work lands as new branches off `main` AFTER PR #184 merges. Four parallel workstreams, each its own worktree + PR, designed so no two streams modify the same files (one trivial known merge point, noted below).

Verified reuse wins (no new backend logic needed):
- `ListLessonCards` / `GetLessonCardForSkill` use cases already exist and are wired into `CurriculumComposition` (`backend/v2/composition/pathway.py:203,273`) — Stream 1's backend is route-only.
- `GenerateDailyTeachingPlan` is a reusable cross-context use case (composed at `backend/v2/composition/coach.py:294`) — Stream 3 just needs an admin route around it.
- Coach UI components `frontend/components/teaching/lesson-card.tsx` and `student-focus-row.tsx` exist for admin read-only reuse.
- `coach_digest_sends` collection (unique `(academy_id, coach_id, digest_date)` index) already provides idempotency + free delivery-log data.

---

## Workstream overview

| Stream | Items | Size | Branch |
|---|---|---|---|
| 1 | A: Lesson card seed button + seeded-status | S | `feat/admin-lesson-card-seeding` |
| 2 | B+C+D: Per-academy digest settings, test-send, delivery log | L | `feat/per-academy-coach-digest` |
| 3 | E (+G stretch): Admin teaching-plan tab (+ coach engagement stats) | M (L w/ G) | `feat/admin-teaching-plan-visibility` |
| 4 | F (+H stretch): Parent recent skill updates (+ practice videos) | M | `feat/parent-skill-updates` |

### Conflict analysis (why this grouping)
- B, C, D all touch `comms_routes.py`/`academy_routes.py`, `frontend/components/admin/settings/notify-panel.tsx`, and the notifications section of `frontend/lib/api/admin.ts` → one stream.
- E and G both add admin use-case wiring (`interfaces/admin/deps.py`, `composition/admin.py`) → one stream.
- H depends on F; both touch parent progress routes/page → one stream. Stream 4 is fully disjoint from the others.
- Stream 1 touches only `pathway_routes.py`, `frontend/lib/api/curriculum.ts`, and the pathway page — disjoint.
- **Known merge points (Streams 2 vs 3 only):**
  - `backend/v2/interfaces/admin/deps.py` (`AdminUseCases`): both add optional fields with `= None` defaults (existing pattern, deps.py:237). Additive; trivial rebase. Default-None means `tests/interface/conftest.py` needs no edits.
  - `backend/v2/composition/admin.py`: Stream 2 puts ALL its composition in `composition/digests.py` and wires one line into `compose_admin`; Stream 3 adds its own wiring there. One-line additive conflict at worst.
  - `frontend/lib/query/keys.ts`: each stream adds a distinct namespaced key — 1-line additive.
  - `frontend/lib/api/admin.ts`: **only Stream 2 edits it.** Stream 3 creates a new `frontend/lib/api/admin-teaching.ts`; Streams 1/4 use `curriculum.ts`/`parent.ts`.
- **Merge order preference:** Stream 2 before Stream 3 (Stream 2's deps/composition edits are larger; Stream 3 rebases trivially). Streams 1 and 4 merge anytime.

---

## Stream 1 — Lesson card seeding UI (S)

1. **Backend route:** add `GET /programs/{program_id}/lesson-cards` to `backend/v2/interfaces/admin/pathway_routes.py` (next to seed route at :330). Calls `use_cases.curriculum.list_lesson_cards.execute(program_id)` (already wired). Response: `{count, cards: [{card_id, slug, lesson_number, title, module_name, lesson_range, skill_ids}]}` — summary fields only; `count > 0` doubles as the seeded-status signal.
2. **Frontend API:** add `listLessonCards(programId)` + `seedLessonCards(programId)` to `frontend/lib/api/curriculum.ts`.
3. **Frontend UI:** in `frontend/app/(admin)/admin/pathway/[programId]/page.tsx`, add a "Lesson cards" card: badge ("22 cards seeded" / "Not seeded") + "Seed lesson cards" button → POST mutation, invalidate list query on success. Seeding is idempotent (content_hash upsert) — show created/updated/unchanged counts from the seed response.
4. **Tests:** extend `backend/v2/tests/interface/test_admin_pathway.py` — contract test for GET (mock use case, assert shape, 503 when `curriculum is None`).
5. **Verify:** `pytest backend/v2/tests/interface/test_admin_pathway.py`; frontend `npx tsc --noEmit`; manual: seed → badge flips with count.

## Stream 2 — Per-academy digest settings + test-send + delivery log (L)

Sequential within the stream: B → C → D (C/D don't functionally depend on B but share files).

### B — settings migration + scheduler refactor
1. **Identity context:** add `coach_digest_enabled: bool` / `coach_digest_hour: int` (validate 0–23) to `get_academy_notifications_use_case.py`, `update_academy_notifications_use_case.py`, and defaults in `mongo_academy_repo.py`.
2. **BFF:** extend `AdminNotificationsView` (`backend/v2/interfaces/admin/views.py:1175`) + `UpdateAdminNotificationsRequest`; `academy_routes.py:138-156` passes through via `model_dump(exclude_unset=True)` — no logic change.
3. **Scheduler refactor (`backend/v2/main.py:278-336`):**
   - Compose `app.state.coach_digest` **unconditionally**.
   - Replace the conditional daily cron with an **always-registered hourly cron** (`hour="*", minute=0, max_instances=1`).
   - In the job: compute current hour in `scheduler_tz`; per academy, load notification settings; effective `enabled`/`hour` = per-academy value if set, else env fallback (env vars become deprecated defaults — **zero behavior change for existing deployments** until an admin saves per-academy values). Skip unless `enabled and hour == current_hour`; else run `SendCoachDailyDigest` under `tenant_scope`.
   - Idempotency preserved for free via existing `try_claim` on `(academy_id, coach_id, digest_date)`.
   - Extract the enabled/hour resolution into a small pure helper (in `composition/digests.py`) so it's unit-testable without APScheduler.
   - PR note: hour interpreted in scheduler TZ, not academy TZ — flagged as explicit future work.
4. **Frontend:** `notify-panel.tsx` — "Coach daily digest" toggle + hour `<select>` (0–23), reusing the existing dirty-flag/mutation pattern; extend types in `frontend/lib/api/admin.ts`.

### C — test-send
5. New use case `send_coach_digest_test.py` in `backend/v2/contexts/communications/application/use_cases/`: reuses `render_coach_digest` + `PlanProvider` from `send_coach_daily_digest.py`; bypasses the enabled flag and does NOT consume the daily idempotency claim (record send with a `kind="test"` marker so the unique index isn't blocked). Target: named coach, or "self" (admin's email via existing `AudienceResolver`).
6. Compose in `backend/v2/composition/digests.py`; expose via one optional `AdminUseCases` field.
7. Route `POST /comms/digests/test-send` in `comms_routes.py`; "Send test digest" button + coach picker in notify panel.

### D — delivery log
8. Add `list_recent(academy_id, limit)` to the `DigestSendRepository` port + `mongo_digest_send_repo.py`; thin use case `get_digest_delivery_log.py`; route `GET /comms/digests/log`.
9. Notify tab: "Last sent" line + small recent-sends table (date, coach, status sent/skipped_empty/failed).

10. **Tests:** `test_admin_settings.py` (new notification fields contract), `test_admin_comms.py` (test-send + log), keep `test_send_coach_daily_digest.py` green, unit tests for the hour/fallback resolution helper.
11. **Verify:** full `pytest backend/v2/tests`; manual: enable digest at current hour, test-send, confirm log row appears.

## Stream 3 — Admin teaching-plan visibility (+ engagement stats) (M)

1. **Backend (E):** new `backend/v2/interfaces/admin/teaching_plan_routes.py` with `GET /sessions/{occurrence_id}/teaching-plan`, mirroring coach view models in `backend/v2/interfaces/coach/teaching_plan_routes.py:78-127`. Reuse `GenerateDailyTeachingPlan`; admin variant resolves the session's assigned coach instead of `claims.user_id`. Wire via optional `AdminUseCases` field, compose in `composition/admin.py`, register in `interfaces/admin/router.py`.
2. **Frontend (E):** new `frontend/lib/api/admin-teaching.ts` (NOT admin.ts — avoids Stream 2 conflict). New read-only component `frontend/components/teaching/admin-teaching-plan.tsx` reusing `lesson-card.tsx` + `student-focus-row.tsx` (lift shared types into `components/teaching/` if they import coach API types; render focus rows without outcome buttons). Add a "Teaching plan" tab to `frontend/app/(admin)/admin/sessions/[id]/page.tsx` — tab registration + render branch only; content lives in the new component.
3. **Backend (G, stretch — stacked PR on E's branch):** skill progress docs already carry `last_updated_by`/`last_updated_at` (`mongo_skill_progress_repo.py`). Add an aggregation method (count grouped by `last_updated_by` over a date range) + use case `get_coach_engagement_stats.py`; route `GET /progress/coach-engagement` in `progress_routes.py`.
4. **Frontend (G):** "outcomes recorded (7d/30d)" stats strip on `frontend/app/(admin)/admin/coaches/page.tsx` — above the generic `AdminUsersDirectory`, not inside it.
5. **Tests:** new `tests/interface/test_admin_teaching_plan.py` (mocked plan use case, 404 unknown occurrence, persona guard); extend `test_admin_progress_routes.py` for G.
6. **Verify:** pytest interface suite; manual: open admin session detail, compare plan with coach `/coach/today/plan` for the same occurrence.

## Stream 4 — Parent recent skill updates (+ practice videos) (M)

Privacy rule for both items: expose only `{skill_id, skill_name, status, updated_at}` / `resource_links` — **never** teaching_points, safety_notes, goal_summary, or any plan internals.

1. **Backend (F):** use case `get_recent_skill_updates.py` in `student_progress/application/use_cases/` — student's skill-progress entries sorted by `last_updated_at` desc (add `list_recent_for_student` to the repo port + `mongo_skill_progress_repo.py`), skill names via `curriculum_lookup_adapter.py`.
2. Route `GET /students/{student_id}/skill-updates` in `backend/v2/interfaces/parent/progress_skill_routes.py` (alongside `/skill-progress`), reusing the parent-owns-student guard. Wire via `ParentUseCases` + `composition/parent.py`.
3. **Frontend (F):** `listSkillUpdates(studentId)` in `frontend/lib/api/parent.ts`; "Recent skill updates" timeline on `frontend/app/(parent)/parent/progress/page.tsx` (date + skill + status chip, reuse passport status styling).
4. **Backend (H, stretch — stacked commit after F):** `GET /students/{student_id}/practice-resources` — for in-progress skills, call existing `GetLessonCardForSkill`, return only `{skill_id, skill_name, resource_links}` filtered to video links.
5. **Frontend (H):** "Practice at home" video-links card under in-progress skills on the parent progress page.
6. **Tests:** extend `tests/interface/test_parent_progress_routes.py`, including a **negative assertion** that responses contain no teaching-plan fields; application test for ordering.
7. **Verify:** pytest parent interface tests; manual: record an outcome as coach → see it on parent progress page.

---

## Sequencing summary

- All four streams branch from main independently after PR #184 merges — no cross-stream ordering required for correctness.
- Stretch items (G, H) ship as stacked second PRs so core work lands even if stretch slips.
- If Streams 2 and 3 land close together, merge Stream 2 first; Stream 3's rebase conflicts are 1-line additive (deps.py field, composition line, keys.ts).
- Execution: each stream in its own git worktree; can be driven by parallel agents.

## Verification (end-to-end, post-merge)

1. `pytest backend/v2/tests` green on each branch.
2. Frontend `npx tsc --noEmit` + lint on each branch.
3. Manual smoke per stream: (1) seed → count badge; (2) toggle digest + hour, test-send, log row appears; (3) admin session "Teaching plan" tab matches coach view; (4) coach records outcome → parent sees skill update.
4. After all merge: run `graphify update .` to refresh the knowledge graph.
