# Plan: Skill Pathway — Gap Closure (post-MVP, pre-/post-merge)

**Date:** 2026-06-05
**Branch:** `feat/skill-pathway-mvp` (worktree `.worktrees/skill-pathway`)
**Source of gaps:** original plan `wise-purring-cherny.md` vs. what shipped at
commit `9065940`, plus the 2026-06-05 stabilization pass.

This plan covers only **things the plan called for that were not built (or were
built incompletely)**. It excludes the work already done in stabilization
(seed fix, two test files, dead-wiring removal, composition/deps regressions,
lint/format, validation). Items already in
`docs/tickets/post-mvp-skill-pathway-backlog.md` are referenced, not duplicated.

Priorities:
- **P0** — should be resolved or consciously accepted **before merge** (security / correctness).
- **P1** — complete the MVP's stated contract; do soon after merge.
- **P2** — plan items safe to defer; schedule explicitly.
- **P3** — already-tracked backlog (pointers only).

---

## P0 — Before merge

### P0.1 — Coach authorization: enforce coach-is-assigned-to-student
**Gap.** `interfaces/coach/skill_routes.py` guards every endpoint with
`require_persona("coach")` only. It does **not** check that the calling coach is
assigned to the student's session. Any authenticated coach can read/write **any**
student's passport, record test attempts, recommend level-ups, and read/write
skill notes for anyone **in the same academy**. (Cross-tenant is still protected
by tenant-scoped repos; this is a cross-coach, within-tenant exposure.) The plan
explicitly required: *"Coach cannot update skill for student not in their session
(→403)."*

**Approach.**
- Reuse the existing assignment lookup already on `CoachUseCases.assigned_sessions`
  (`is_coach_assigned`) — the same mechanism attendance/roster routes use.
- Add a shared dependency/helper in `skill_routes.py` that resolves the student's
  active session(s) and asserts the coach is assigned; raise **404** (per the
  security matrix — never leak) on mismatch. Decide the rule: coach must be
  assigned to a current/recent session that contains the student.
- Apply to: `get_passport`, `update_skill_status`, `record_test`,
  `recommend_level_up`, `create_skill_note`, `list_skill_notes`.

**Files.** `backend/v2/interfaces/coach/skill_routes.py` (+ possibly a small
lookup on the coach composition if "which sessions is this student in" isn't
already available).

**Tests.** `backend/v2/tests/interface/test_coach_skill_routes.py`:
- coach assigned to student's session → 200/201 (existing happy paths).
- coach **not** assigned to the student → 404 for each mutating endpoint.

**Acceptance.** A coach token not assigned to a student gets 404 on all six
skill endpoints; assigned coach unaffected; full suite green.

**Est.** ~0.5 day. **Risk if skipped:** real data-exposure/integrity gap.

---

## P1 — Complete the stated MVP contract (soon after merge)

### P1.1 — Emit domain events to the outbox
**Gap.** All 7 `student_progress` events exist as classes
(`StudentPlacedInLevel`, `SkillStatusUpdated`, `SkillPassed`, `LevelCompleted`,
`LevelUpRecommended`, `StudentLeveledUp`, `CertificateIssued`) but **no use case
publishes any of them**. The plan said `review_level_up` emits `StudentLeveledUp`
+ `CertificateIssued`, `record_test` emits `SkillPassed`/`LevelCompleted`, etc.
Assumption #7's "event-hook stubs" are not wired. **This blocks Notifications
(backlog #8): nothing to consume.** The planned `SkillTestAttempted` event was
also never created.

**Approach.**
- Add an `Outbox` port to the affected use case constructors (mirror how other
  contexts inject the outbox), default-None so existing tests keep working.
- Emit at the right moments: place → `StudentPlacedInLevel`; record_test →
  `SkillTestAttempted` (create it) + `SkillPassed` + `LevelCompleted` (when
  detected); recommend → `LevelUpRecommended`; review approve →
  `StudentLeveledUp` + `CertificateIssued`; status change → `SkillStatusUpdated`.
- Wire the real outbox in `composition/pathway.py`.

**Files.** `student_progress/application/use_cases/{place_student,record_test_attempt,recommend_level_up,review_level_up,update_skill_status}.py`,
`student_progress/domain/events.py` (+`SkillTestAttempted`),
`composition/pathway.py`.

**Tests.** Extend domain/use-case tests to assert events appended to a fake outbox.

**Acceptance.** Each lifecycle action appends the documented event(s); fakes
assert payloads; full suite green.

**Est.** ~1 day.

### P1.2 — Populate certificate display fields at issue time
**Gap.** `review_level_up` approve issues a `SkillCertificate` with blank
`student_name`/`level_name`/`program_name` and `level_sequence` defaulting to 1
(the admin approve route passes none of them). See ADR-0010 #10. Overlaps
backlog #7 but the **blank-name correctness** part belongs here, not "nice-to-have."

**Approach.**
- At approve time, look up: student name (enrollment/admin directory), level name
  + sequence and program name (curriculum). This is the **purposeful**
  re-introduction of the lookup that was removed as dead code in stabilization —
  reintroduce it wired this time, or resolve names in the route before calling
  the use case.
- Pass real `student_name`, `level_name`, `program_name`, `level_sequence` into
  `ReviewLevelUpCommand`.

**Files.** `interfaces/admin/progress_routes.py` (resolve + pass), possibly a new
purposeful lookup adapter + composition wiring.

**Tests.** Extend `test_admin_progress_routes.py`: issued cert has non-empty
`student_name`/`level_name`/`program_name` and correct `level_sequence`/`cert_number`.

**Acceptance.** Approving a level-up issues a certificate with correct display
fields; test asserts them.

**Est.** ~0.5–1 day. (PDF generation stays in backlog #7.)

### P1.3 — Missing authorization tests
**Gap.** Plan required (a) coach-not-in-session → covered by P0.1 tests, and
(b) **cross-tenant functional isolation** (academy A data not reachable under
academy B context). Only the static raw-access guard test exists.

**Approach.** Add a functional cross-tenant test: seed/place a student under
academy A, hit progress/passport/cert routes with academy-B claims → 404/empty.

**Files.** `test_admin_progress_routes.py` and/or `test_coach_skill_routes.py`.

**Acceptance.** Cross-tenant access returns 404/empty; full suite green.

**Est.** ~0.25 day.

### P1.4 — Correct ADR-0010 (ClassPlan/Station claim)
**Gap.** ADR-0010 #3 states the `ClassPlan`/`Station` **data model is defined**.
It is not — neither model exists. The ADR overstates delivery.

**Approach.** Edit ADR-0010 #3 to say the station-based class-planning model is
**deferred entirely** (model + UI), pointing to backlog #5.

**Files.** `docs/adr/0010-skill-pathway-module.md`.

**Est.** ~5 min.

---

## P2 — Plan items safe to defer (schedule explicitly)

### P2.1 — Coach "roster with skill status" endpoint
**Gap.** Plan listed `GET /coach/sessions/{session_id}/students-progress`
(roster + per-student skill status). Not implemented, though the frontend page
`coach/sessions/[id]/progress/page.tsx` exists. **Verify** what that page calls —
if it depends on a missing endpoint it's a live bug (promote to P1); if it
composes existing roster + per-student passport calls, this is purely additive.

**Files.** `interfaces/coach/skill_routes.py` (new endpoint), composition if a
new read is needed; frontend wiring if applicable.

**Est.** ~0.5 day (after the verify).

### P2.2 — `InsufficientTestData` domain error
**Gap.** Planned error not implemented; `record_test_attempt` relies on a
pydantic `Field(ge=1)` constraint instead (returns 422 on bad input). Decide:
accept the constraint as the contract (and drop the error from the plan), or add
the explicit domain error for a clearer message. Low value.

**Est.** ~0.25 day or **won't-do**.

### P2.3 — `ClassPlan` / `Station` data model
**Gap.** Deferred by design (assumption #3). Only needed when backlog #5 (station
planner UI) is picked up. Track with #5; do not build standalone.

---

## P3 — Already-tracked backlog (pointers only)
See `docs/tickets/post-mvp-skill-pathway-backlog.md`:
1 Curriculum versioning · 2 Assessment workflow · 3 Skill prerequisites ·
4 Progress timeline · 5 Station planner UI (incl. P2.3 model) ·
6 Parent monthly reports · 7 Better certificates / PDF (P1.2 covers the
blank-name correctness part) · 8 Notifications (depends on **P1.1**).

---

## Suggested execution order
1. **P0.1** (coach authorization + tests) — gate for merge.
2. **P1.4** (ADR correction) — 5-min truth-in-docs.
3. **P1.3** (cross-tenant test) — cheap safety net.
4. **P1.2** (certificate names) — visible product correctness.
5. **P1.1** (event emission) — unblocks notifications.
6. **P2.1** (verify coach progress page → endpoint if needed).
7. Re-run full gate: `ruff check v2 && ruff format --check v2 && pytest v2/tests -q`,
   `pnpm typecheck && pnpm lint`.

## Verification (each task)
```bash
cd backend && source .venv/bin/activate
pytest v2/tests -q && ruff check v2 && ruff format --check v2
cd ../frontend && pnpm typecheck && pnpm lint
```

## Decisions needed from owner
- Is **P0.1** a hard merge gate, or accept cross-coach access for the MVP and
  fix immediately after? (Recommend: hard gate.)
- **P2.2**: add the error, or accept the 422 constraint as the contract?
