# Birthdays and Profile Nudges Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automate two DOB-driven family touchpoints — a switchable per-student birthday email plus an always-on staff digest block, and a three-step profile-completion nudge email to parents — on top of the existing scheduler, digest-claim, and `ProfileGaps` infrastructure.

**Architecture:** A pure `birth_month_day` derivation and a pure nudge-step scheduler live in `backend/v2/shared/profile/` (no context imports, per `completeness.py`'s existing rule); two new `SendBirthdayNotes` / `SendProfileNudges` use cases live in the `communications` context and reach across the enrollment/identity boundary only through duck-typed Protocol ports (mirroring `PlanProvider` in `send_coach_daily_digest.py`); both are wired in new composition modules (never `composition/admin.py`, which is capped at 4500 lines and already at 4318) and registered as `main.py` scheduler jobs following the existing `_run_leased_job` + `SCHEDULED_JOB_MONITORS` + `JOB_STALE_AFTER` triple-registration pattern.

**Tech Stack:** FastAPI/Pydantic v2, Motor (async Mongo), APScheduler (`AsyncIOScheduler`), pytest, Next.js 16/TanStack Query on the frontend.

**Test layout (verified — do not invent directories):** `backend/v2/tests/unit/` is **flat** (no subpackages: no `unit/shared/`, no `unit/contexts/`); pure-logic and renderer tests go straight in it. Use-case tests with fakes go in `backend/v2/tests/application/` (that is where `test_send_coach_daily_digest.py` actually lives). Anything needing a database uses `backend/v2/tests/contract/`, whose `conftest.py` provides the `db` and `acad` fixtures. Migration tests import via `importlib` and need `db`, so they belong in `contract/` too.

## Global Constraints

- Birthday note audience: every student with a DOB **and** at least one enrollment in `active|held|paused` — students whose only enrollments are terminal appear on the staff digest only (spec §2, §4.2). Use the canonical status vocabulary from migration 0171 (`dropped`/`deleted`, not `withdrawn`/`cancelled`) and prefer the existing `SEATLESS` set / `canonical_status()` in `contexts/enrollment/domain/models.py` over hand-written status lists, since legacy rows still carry both spellings.
- Soft-deleted students are excluded with `{"is_deleted": {"$ne": True}}` — the repo-wide idiom (`mongo_student_repo.py` lines 811, 856, 989, …). Note `is_deleted` is a raw Mongo convention: it is **not** a field on the `Student` pydantic model, so `MongoStudentWriter.upsert`'s `model_dump()` never writes it and an `is_deleted: False` equality filter would miss every row.
- Parent birthdays are never collected or emailed (spec §2).
- Nudge cadence: step 1 at day 7, step 2 at day 21 from step 1 (day 28 from gap-seen), step 3 at day 60 from step 2 (day 88 from gap-seen); no step 4; stops early the moment `ProfileGaps.is_complete` (spec §5).
- A brand-new family (gap first seen < 7 days ago) gets no nudge yet (spec §5).
- `birthday_emails_enabled` defaults to **off** per academy; the family birthday email must never send before an admin turns it on (spec §4.2).
- Both email jobs use `EmailCategory.NOTIFICATION`, honour unsubscribe, and append the standard unsubscribe footer (spec §4.2, §5).
- `students.date_of_birth` stays a string, validated `YYYY-MM-DD` on every write path (spec §3).
- `students.birth_month_day` is `"MM-DD"`, derived whenever `date_of_birth` is set, Feb 29 stored as itself but **listed as Feb 28** in non-leap years for both birthday selection and the staff digest (spec §3, §7).
- `profile_nudges` is unique on `(academy_id, parent_id)` (spec §3).
- Every scheduled job is idempotent under re-run via a claim/record (birthday sends through `digest_claim` keyed `(academy_id, student_id, year)`; nudges through the existing-record `sends` array) (spec §3, §7).
- Every v2 route 404s (never 403s) for wrong persona / other tenant (repo fact). This plan adds **no** new routes — the only interface change is two fields on the existing `GET/PATCH /admin/academy/notifications` behind `require_persona("admin")`, so no new persona gate and **no** `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json` update is needed (that rule fires only for new `frontend/app/` routes, and this plan adds none).
- **Build order / migration numbering.** These four 2026-09-10 admin-UX plans land in the order 1 → 2 → 4 → 3, and this is plan 3 (last). `0173` is claimed by plan 1 (`docs/superpowers/plans/2026-09-10-departure-actions-from-student-page.md`, `0173_withdrawal_notice_sends`), so this plan's migrations are **0174 / 0175 / 0176**. If plan 1 has not merged when this plan executes, re-check the highest migration number on `main` before creating files and shift these three together — never reuse a number another open PR already took.
- `composition/admin.py` is at 4318/4500 lines **on `main` as of 2026-09-10**; plan 2 (`2026-09-10-families-directory-consolidation.md`, Task 2) removes ~225 lines from it and lands before this plan, so expect ~4093/4500 by the time this executes (budget enforced in `tests/structural/test_composition_is_wiring.py`). Either way: no new composition there; only the two-line default-kwarg extension to the existing notifications use cases is acceptable.
- **Datetimes read back from Mongo are NAIVE** (the Motor client is not `tz_aware`). `profile_nudges.first_gap_seen_at` and every `sends[].at` MUST be normalised with `backend.v2.shared.time.mongo.ensure_utc` **at the repository read boundary** before they reach `next_nudge_step`, or the `now - first_gap_seen_at` subtraction raises `TypeError: can't subtract offset-naive and offset-aware datetimes` — exactly the #706 absence-notice 500 (project memory: "fix at the repo boundary with ensure_utc").
- Adding scheduler jobs is a **four**-place change, not three: `SCHEDULED_JOB_MONITORS`, `JOB_STALE_AFTER`, `scheduler.add_job(id=...)`, **and** the hard-coded count in `backend/v2/tests/unit/test_scheduler_academies.py::test_scheduler_job_tables_cover_every_registered_job` (`assert len(registered) == 13` → `15`). That test also asserts every `_run_leased_job("<id>")` string matches a registered id.
- Every migration module MUST expose a module-level `version = "<filename stem>"` (NOT `MIGRATION_ID`) — `migrations/runner.py::_run_pending_locked` reads `module.version` and would `AttributeError` otherwise. `up(db)`'s return value is ignored by the runner.
- Migration modules cannot be imported with `from ... import <name>` (their names start with a digit). Tests import them with `importlib.import_module("backend.v2.migrations.0174_...")` — see `tests/unit/test_0171_enrollment_status_vocabulary.py` for the idiom. There is **no** `tests/migrations/` directory. Put migration tests that need a real database in `backend/v2/tests/contract/` (where the `db` fixture lives); pure ones may sit flat in `tests/unit/`.
- Contract-test fixtures are **`db`** (mongomock-motor database) and **`acad`** (activates the tenant ContextVar, yields `"test-academy"`) — see `backend/v2/tests/contract/conftest.py`. There is no `mongo_db` or `academy_id` fixture anywhere in the suite.

## File structure

| Path | Responsibility |
|---|---|
| `backend/v2/shared/profile/birth_month_day.py` | **Create.** Pure `derive_birth_month_day(date_of_birth) -> str \| None`, leap-day (Feb 29 → "02-28" outside leap years) lookup helper `birth_month_day_for_date(on_date)`. |
| `backend/v2/shared/profile/nudge_schedule.py` | **Create.** Pure nudge-step scheduling: `next_nudge_step(first_gap_seen_at, sends, now) -> int \| None`. |
| `backend/v2/contexts/enrollment/domain/onboarding_dob.py` | Not needed — validation added directly in `onboarding/domain/models.py` (Task 2). |
| `backend/v2/migrations/0174_student_birth_month_day.py` | **Create.** Backfills `students.birth_month_day` from parseable `date_of_birth`, builds `(academy_id, birth_month_day)` index, reports unparseable DOBs. |
| `backend/v2/migrations/0175_profile_nudges_collection.py` | **Create.** Creates `profile_nudges` with a unique index on `(academy_id, parent_id)`. |
| `backend/v2/migrations/0176_birthday_sends_collection.py` | **Create.** Unique index on `birthday_sends (academy_id, student_id, digest_date)`. Non-optional: `digest_claim`'s no-double-send guarantee degrades without it, and prod shipped the 2026-09-02 hourly-resend incident precisely because migrations 0125/0148 never built the digest indexes. |
| `backend/v2/contexts/enrollment/infrastructure/mongo_student_writer.py` | **Modify.** `upsert()` derives and stores `birth_month_day` alongside `date_of_birth`. |
| `backend/v2/contexts/enrollment/infrastructure/mongo_student_repo.py` | **Modify.** `UpdateAdminStudentCommand` handling (~line 524-525) derives and stores `birth_month_day` when `date_of_birth` changes. |
| `backend/v2/contexts/onboarding/domain/models.py` | **Modify.** `ChildProfile.date_of_birth` gets a `field_validator` enforcing `YYYY-MM-DD` (the one write path spec §3 calls out as currently unchecked). |
| `backend/v2/contexts/communications/infrastructure/mongo_birthday_send_repo.py` | **Create.** `MongoBirthdaySendRepository` over `digest_claim.claim_digest_send`, keyed `(academy_id, student_id, str(year))` — collection `birthday_sends`. The Protocol it satisfies (`BirthdayClaims`) lives with its consumer in `application/use_cases/send_birthday_notes.py`; no `domain/` module is added. |
| `backend/v2/contexts/communications/application/birthday_renderer.py` | **Create.** `render_birthday_note(student_name, brand, unsubscribe_url) -> tuple[str, str]`. |
| `backend/v2/contexts/communications/application/use_cases/send_birthday_notes.py` | **Create.** `SendBirthdayNotes` use case: resolves today's birthday students via a duck-typed `BirthdayStudentProvider` port, claims, sends. |
| `backend/v2/contexts/enrollment/application/use_cases/birthday_students_today.py` | **Create.** `BirthdayStudentsTodayQuery` — enrollment-side query the composition root wires as the `BirthdayStudentProvider`. |
| `backend/v2/contexts/communications/infrastructure/mongo_profile_nudge_repo.py` | **Create.** `profile_nudges` repo: `get(academy_id, parent_id)`, `upsert`, `close`. |
| `backend/v2/contexts/communications/application/profile_nudge_renderer.py` | **Create.** `render_profile_nudge(step, parent_name, gap_labels, deep_link, unsubscribe_url) -> tuple[str, str]`. |
| `backend/v2/contexts/communications/application/use_cases/send_profile_nudges.py` | **Create.** `SendProfileNudges` use case: resolves families with active/held/paused students via a `FamilyProfileProvider` port, computes `ProfileGaps`, schedules/sends. |
| `backend/v2/contexts/enrollment/application/use_cases/family_profiles_for_nudges.py` | **Create.** `FamilyProfilesForNudgesQuery` — enrollment/identity-joined query wired as the `FamilyProfileProvider`. |
| `backend/v2/composition/birthday_notes.py` | **Create.** `compose_send_birthday_notes(db)`. Gets its sender from `composition.digests._build_email_sender(get_settings(), db)` — the ONLY construction site allowed to build a real `ResendEmailSendPort` (`tests/structural/test_email_sender_construction.py`). There is no `compose_email_send_port`. |
| `backend/v2/composition/profile_nudges.py` | **Create.** `compose_send_profile_nudges(db)`. Same sender rule as above. |
| `backend/v2/main.py` | **Modify.** Register `send_birthday_notes` and `send_profile_nudges` jobs (`SCHEDULED_JOB_MONITORS`, `_run_leased_job` wrappers, `scheduler.add_job`). |
| `backend/v2/tests/unit/test_scheduler_academies.py` | **Modify.** Bump `assert len(registered) == 13` to `15` (two new jobs). Verified: this assertion exists at line 121 and would fail otherwise. |
| `backend/v2/tests/structural/test_email_category_threading.py` | **Modify.** Add `send_birthday_notes.py` / `send_profile_nudges.py` to the sweep (their names contain neither `digest` nor `campaign`, so `BULK_MODULE_MARKERS` misses them today). These are exactly the bulk suppressible loops that tripwire exists for. |
| `backend/v2/shared/observability/ops_digest.py` | **Modify.** Add both job ids to `JOB_STALE_AFTER`; add a cross-tenant `_birthdays_this_week_counts` (or full block) for the admin ops digest, folded into `OpsDigestSnapshot` and `render_ops_digest`. |
| `backend/v2/contexts/communications/application/digest_renderer.py` | **Modify.** `render_coach_digest` gains an optional `birthdays_this_week: Sequence[UpcomingBirthday] = ()` param, rendered as a card when non-empty. |
| `backend/v2/main.py` (`_send_coach_daily_digests_body` area) | **Modify.** On Mondays (scheduler-local), resolve the week's birthdays for the coach's classes and pass them into the digest send. |
| `backend/v2/contexts/identity/application/get_academy_notifications_use_case.py` | **Modify.** Add `birthday_emails_enabled: bool = False` to `GetAcademyNotificationsOutput` / `_notifications_output`. |
| `backend/v2/contexts/identity/application/update_academy_notifications_use_case.py` | **Modify.** Accept `birthday_emails_enabled` in the patch (already generic — no change needed beyond the default kwarg threading, verified in Task 7). |
| `backend/v2/contexts/identity/infrastructure/mongo_academy_repo.py` | **Modify.** `upsert_defaults` seeds `notifications.birthday_emails_enabled: False`. |
| `backend/v2/interfaces/admin/views.py` | **Modify.** `AdminNotificationsView` / `UpdateAdminNotificationsRequest` gain `birthday_emails_enabled`. |
| `backend/v2/composition/admin.py` | **Modify (2 lines only).** Thread `default_birthday_emails_enabled=False` into the two existing `GetAcademyNotificationsUseCase` / `UpdateAcademyNotificationsUseCase` constructions (~lines 1673, 1680). |
| `frontend/lib/api/admin.ts` | **Modify.** `AdminNotificationsView` interface gains `birthday_emails_enabled: boolean`. |
| `frontend/components/admin/settings/notify-panel.tsx` | **Modify.** New toggle beside the existing digest toggles. |
| `backend/v2/interfaces/admin/directory_routes.py` | No change — `missing=` filter (line 329) already reads `CHILD_REQUIRED`/`ProfileGaps`; profile nudges reuse it unmodified (spec §5). |
| `docs/release-notes/2026-09-10-birthdays-and-profile-nudges.md` | **Create.** Release note (Task 12). |

## Task 1: `birth_month_day` derivation

**Files:**
- Create: `backend/v2/shared/profile/birth_month_day.py`
- Test: `backend/v2/tests/unit/test_birth_month_day.py`

**Interfaces:**
- Produces: `derive_birth_month_day(date_of_birth: str | None) -> str | None`
- Produces: `birth_month_day_for_date(on_date: date) -> str` (used by both the birthday-selection query and the leap-day digest rule)
- Produces: `is_feb_28_in_non_leap_year(on_date: date) -> bool` — the third public symbol; Tasks 6, 9 and 10 all import it, so it must be in this module's public surface and covered by a test (the sketch below has an implementation but no test for it: add `is_feb_28_in_non_leap_year(date(2026, 2, 28)) is True`, `date(2028, 2, 28) is False`, `date(2100, 2, 28) is True`, `date(2000, 2, 28) is False`, and a non-Feb-28 date is `False`).

- [ ] Write the failing test:

```python
# backend/v2/tests/unit/test_birth_month_day.py
from datetime import date

from backend.v2.shared.profile.birth_month_day import (
    birth_month_day_for_date,
    derive_birth_month_day,
)


def test_derives_month_day_from_valid_dob():
    assert derive_birth_month_day("2015-03-04") == "03-04"


def test_derives_leap_day_as_itself():
    assert derive_birth_month_day("2012-02-29") == "02-29"


def test_returns_none_for_missing_or_blank():
    assert derive_birth_month_day(None) is None
    assert derive_birth_month_day("") is None
    assert derive_birth_month_day("   ") is None


def test_returns_none_for_unparseable():
    assert derive_birth_month_day("not-a-date") is None
    assert derive_birth_month_day("03/04/2015") is None


def test_birth_month_day_for_date_is_plain_month_day():
    assert birth_month_day_for_date(date(2026, 3, 4)) == "03-04"


def test_birth_month_day_for_date_on_feb_29_in_leap_year():
    assert birth_month_day_for_date(date(2028, 2, 29)) == "02-29"
```

- [ ] Run it (expect failure — module does not exist):
  `cd backend && .venv/bin/pytest v2/tests/unit/test_birth_month_day.py -q`
  Expected: `ModuleNotFoundError: No module named 'backend.v2.shared.profile.birth_month_day'`

- [ ] Minimal implementation:

```python
# backend/v2/shared/profile/birth_month_day.py
"""Derives the ``"MM-DD"`` key used for birthday selection and the staff
digest (2026-09-10 birthdays spec, §3).

Feb 29 is stored as itself (``derive_birth_month_day`` never rewrites the
source DOB) but ``birth_month_day_for_date`` — used both by the daily
birthday-selection query and by the "birthdays this week" digest block — asks
"whose birth_month_day matches THIS calendar date", and a Feb-29 child's
birthday is celebrated on Feb 28 in a non-leap year (spec §7). That rule
therefore lives at lookup time, not at storage time: storing "02-28" would
silently and permanently lose the child's real birth date.
"""

from __future__ import annotations

from datetime import date


def derive_birth_month_day(date_of_birth: str | None) -> str | None:
    """``"YYYY-MM-DD"`` -> ``"MM-DD"``, or ``None`` if blank/unparseable."""
    if date_of_birth is None or not date_of_birth.strip():
        return None
    try:
        parsed = date.fromisoformat(date_of_birth.strip())
    except ValueError:
        return None
    return parsed.strftime("%m-%d")


def birth_month_day_for_date(on_date: date) -> str:
    """The plain ``"MM-DD"`` for a calendar date — no leap-day substitution.

    Callers matching "does this child's birthday fall on ``on_date``" must
    query for BOTH this value AND, only when ``on_date`` is Feb 28 in a
    non-leap year, "02-29" as well (spec §7) — done at the query site so this
    function stays a pure, unconditional formatter.
    """
    return on_date.strftime("%m-%d")


def is_feb_28_in_non_leap_year(on_date: date) -> bool:
    """True when a Feb-29 child's birthday should be folded into ``on_date``."""
    if on_date.month != 2 or on_date.day != 28:
        return False
    year = on_date.year
    is_leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    return not is_leap
```

- [ ] Run it (expect PASS):
  `cd backend && .venv/bin/pytest v2/tests/unit/test_birth_month_day.py -q`

- [ ] Commit:
  `git add backend/v2/shared/profile/birth_month_day.py backend/v2/tests/unit/test_birth_month_day.py`
  Message: `feat(profile): derive birth_month_day with leap-day lookup rule`

## Task 2: DOB format validation + migration 0174 backfill

**Files:**
- Modify: `backend/v2/contexts/onboarding/domain/models.py` (`ChildProfile` at lines 44-57; `date_of_birth: str = ""` is line 48)
- Modify: `backend/v2/contexts/enrollment/infrastructure/mongo_student_writer.py` (`upsert`, lines 23-42 — verified)
- Modify: `backend/v2/contexts/enrollment/infrastructure/mongo_student_repo.py` (`update_student_profile`'s `set_doc`, lines 524-525 — verified verbatim)
- Create: `backend/v2/migrations/0174_student_birth_month_day.py`
- Test: `backend/v2/tests/unit/test_child_profile_dob_validation.py`
- Test: `backend/v2/tests/unit/test_0174_student_birth_month_day.py`

**Interfaces:**
- Consumes: `derive_birth_month_day` (Task 1)
- Produces: `ChildProfile` rejects a non-`YYYY-MM-DD` `date_of_birth` at construction; `MongoStudentWriter.upsert` and the admin-edit path always write `birth_month_day` in step with `date_of_birth`.

Verified: `admin/views.py` (lines 150, 178) and `parent/views.py` (line 540) already type `date_of_birth` as `date`, so Pydantic rejects malformed admin/parent input before it reaches Mongo, and `parent/views.py`'s `ChildProfileView` (lines 25-44) already carries an ISO `field_validator` at the wizard's HTTP edge. The remaining gap is the **domain** model `onboarding/domain/models.py:48` (`date_of_birth: str = ""`), which any non-HTTP construction path bypasses the view validator to reach — that is what this task closes.

Verified (and contradicting an earlier draft of this plan): `contexts/onboarding/domain/models.py` imports only `BaseModel, EmailStr, Field` from pydantic — **`field_validator` is NOT imported and no other model in that file uses one.** The import line must be widened to `from pydantic import BaseModel, EmailStr, Field, field_validator` as part of this edit.

Verified write paths for `students.date_of_birth` — there are exactly two, and both are covered here: `MongoStudentWriter.upsert` (registration approval + checkout confirm) and `MongoStudentRepository.update_student_profile` (admin edit *and* parent self-service, which delegates to it). `MongoStudentWriter.ensure_exists` is `$setOnInsert` on identity fields only and never touches DOB.

- [ ] Write the failing test:

```python
# backend/v2/tests/unit/test_child_profile_dob_validation.py
import pytest
from pydantic import ValidationError

from backend.v2.contexts.onboarding.domain.models import ChildProfile


def test_accepts_valid_iso_date():
    child = ChildProfile(first_name="A", last_name="B", date_of_birth="2015-03-04")
    assert child.date_of_birth == "2015-03-04"


def test_accepts_blank_as_not_yet_supplied():
    child = ChildProfile(first_name="A", last_name="B", date_of_birth="")
    assert child.date_of_birth == ""


def test_rejects_malformed_date():
    with pytest.raises(ValidationError):
        ChildProfile(first_name="A", last_name="B", date_of_birth="03/04/2015")


def test_rejects_impossible_date():
    with pytest.raises(ValidationError):
        ChildProfile(first_name="A", last_name="B", date_of_birth="2015-02-30")
```

- [ ] Run it (expect failure — no validator yet, malformed value passes through):
  `cd backend && .venv/bin/pytest v2/tests/unit/test_child_profile_dob_validation.py -q`

- [ ] Minimal implementation — in `backend/v2/contexts/onboarding/domain/models.py`, **first widen the pydantic import** (line 18) to `from pydantic import BaseModel, EmailStr, Field, field_validator`, then add to `ChildProfile` (after `medical_notes`, line 57):

```python
    @field_validator("date_of_birth")
    @classmethod
    def _validate_date_of_birth(cls, value: str) -> str:
        """Blank means "not yet supplied" (issue #380 autosave); anything
        else must be a real YYYY-MM-DD date (2026-09-10 birthdays spec §3).

        Mirrors ``interfaces/parent/views.py::ChildProfileView`` so a
        non-HTTP construction path cannot get past the same rule.
        """
        if not value:
            return value
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("date_of_birth must be YYYY-MM-DD") from exc
        return value
```
  The module already imports `datetime` from `datetime` (line 15); widen that to
  `from datetime import date, datetime` rather than importing inside the method.

- [ ] Run it (expect PASS):
  `cd backend && .venv/bin/pytest v2/tests/unit/test_child_profile_dob_validation.py -q`

- [ ] Wire `birth_month_day` into the write paths. In `mongo_student_writer.py`, change `upsert`:

```python
    async def upsert(self, student: Student) -> None:
        doc = student.model_dump(mode="python")
        doc["birth_month_day"] = derive_birth_month_day(student.date_of_birth)
        await self._update_one(
            {"student_id": student.student_id},
            {"$set": {k: v for k, v in doc.items() if k != "academy_id"}},
            upsert=True,
        )
```
  adding `from backend.v2.shared.profile.birth_month_day import derive_birth_month_day` to the imports.

  In `mongo_student_repo.py`, immediately after the existing `if command.date_of_birth is not None:` block (~line 524-525):

```python
        if command.date_of_birth is not None:
            set_doc["date_of_birth"] = command.date_of_birth.isoformat()
            set_doc["birth_month_day"] = derive_birth_month_day(set_doc["date_of_birth"])
```
  adding the same import.

- [ ] Write a focused contract test for the writer. Fixtures are `db` and `acad` (from `backend/v2/tests/contract/conftest.py`); `acad` sets the tenant ContextVar and yields `"test-academy"`, which `TenantScopedRepository._scoped` reads — there is no `mongo_db`/`academy_id` fixture:

```python
# backend/v2/tests/contract/test_mongo_student_writer_birth_month_day.py
import pytest

from backend.v2.contexts.enrollment.domain.models import Student
from backend.v2.contexts.enrollment.infrastructure.mongo_student_writer import (
    MongoStudentWriter,
)


@pytest.mark.asyncio
async def test_upsert_derives_birth_month_day(db, acad):
    writer = MongoStudentWriter(db)
    await writer.upsert(
        Student(
            student_id="stu_1",
            academy_id=acad,
            parent_id="par_1",
            full_name="Aanya K",
            date_of_birth="2015-06-17",
        )
    )
    doc = await db["students"].find_one({"student_id": "stu_1"})
    assert doc["birth_month_day"] == "06-17"


@pytest.mark.asyncio
async def test_upsert_clears_birth_month_day_when_dob_is_absent(db, acad):
    """`upsert` re-sends every unsupplied optional field as None (see its
    docstring), so birth_month_day must move in lockstep — a stale
    "03-04" left behind by a cleared DOB would mail a birthday note for a
    date the record no longer claims."""
    writer = MongoStudentWriter(db)
    await writer.upsert(
        Student(
            student_id="stu_1",
            academy_id=acad,
            parent_id="par_1",
            full_name="Aanya K",
            date_of_birth="2015-06-17",
        )
    )
    await writer.upsert(
        Student(student_id="stu_1", academy_id=acad, parent_id="par_1", full_name="Aanya K")
    )
    doc = await db["students"].find_one({"student_id": "stu_1"})
    assert doc["birth_month_day"] is None
```

- [ ] Run the writer test (expect PASS):
  `cd backend && .venv/bin/pytest v2/tests/contract/test_mongo_student_writer_birth_month_day.py -q`

- [ ] Write the migration test:

```python
# backend/v2/tests/unit/test_0174_student_birth_month_day.py
"""Migration modules start with a digit, so they can only be reached through
importlib — mirrors tests/unit/test_0171_enrollment_status_vocabulary.py."""

import importlib

import pytest

MIGRATION = importlib.import_module("backend.v2.migrations.0174_student_birth_month_day")


@pytest.mark.asyncio
async def test_backfills_parseable_dob(db):
    await db["students"].insert_many(
        [
            {"student_id": "s1", "academy_id": "a1", "date_of_birth": "2015-06-17"},
            {"student_id": "s2", "academy_id": "a1", "date_of_birth": "not-a-date"},
            {"student_id": "s3", "academy_id": "a1", "date_of_birth": None},
        ]
    )
    report = await MIGRATION.up(db)
    s1 = await db["students"].find_one({"student_id": "s1"})
    s2 = await db["students"].find_one({"student_id": "s2"})
    assert s1["birth_month_day"] == "06-17"
    assert s2.get("birth_month_day") is None
    assert report.unparseable == ["s2"]


def test_declares_the_version_the_runner_reads():
    assert MIGRATION.version == "0174_student_birth_month_day"
```
  The `db` fixture lives in `backend/v2/tests/contract/conftest.py`, so put this
  file under `backend/v2/tests/contract/` **or** copy that fixture — do not
  invent a `mongo_db` fixture. Recommended: `backend/v2/tests/contract/test_0174_student_birth_month_day.py`
  and drop the `tests/unit/` path above; adjust the commit/run commands to match.

- [ ] Run it (expect failure — migration module doesn't exist):
  `cd backend && .venv/bin/pytest v2/tests/contract/test_0174_student_birth_month_day.py -q`

- [ ] Minimal implementation. `0172_absence_notice_sends.py` is the template, and it has already been read for this plan: module docstring ending with the "Production does NOT run migrations on boot (`V2_RUN_MIGRATIONS_ON_BOOT` is false, #629) — apply with `run_pending_migrations` by hand after deploy" paragraph, a module-level `version = "<filename stem>"`, and `async def up(db: AsyncIOMotorDatabase) -> None`. **`version` is the attribute `runner.py::_run_pending_locked` reads — `MIGRATION_ID` would `AttributeError` at boot.** The runner ignores `up`'s return value, so returning a report for the test is safe. Then create:

```python
# backend/v2/migrations/0174_student_birth_month_day.py
"""Backfill students.birth_month_day and index it (2026-09-10 birthdays spec §3).

Every student whose date_of_birth already parses as YYYY-MM-DD gets a
derived birth_month_day; anything else is reported, not written — an
unparseable DOB already counts as a DOB gap under ProfileGaps and must stay
that way rather than silently becoming a fabricated birth_month_day.

Production does NOT run migrations on boot (``V2_RUN_MIGRATIONS_ON_BOOT`` is
false there, #629): apply with ``run_pending_migrations`` by hand after
deploy. Until then ``birth_month_day`` is absent on existing rows, so the
birthday job simply finds nobody — it never mails the wrong child.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.shared.profile.birth_month_day import derive_birth_month_day

version = "0174_student_birth_month_day"


@dataclass(frozen=True)
class BackfillReport:
    updated: int = 0
    unparseable: list[str] = field(default_factory=list)


async def up(db: AsyncIOMotorDatabase[Any]) -> BackfillReport:
    updated = 0
    unparseable: list[str] = []
    cursor = db["students"].find({}, projection={"student_id": 1, "date_of_birth": 1})
    async for doc in cursor:
        derived = derive_birth_month_day(doc.get("date_of_birth"))
        if derived is None:
            if doc.get("date_of_birth"):
                unparseable.append(doc["student_id"])
            continue
        await db["students"].update_one(
            {"_id": doc["_id"]}, {"$set": {"birth_month_day": derived}}
        )
        updated += 1
    await db["students"].create_index(
        [("academy_id", 1), ("birth_month_day", 1)], name="academy_birth_month_day"
    )
    return BackfillReport(updated=updated, unparseable=unparseable)
```
  Note: `create_index` under `mongomock-motor` is a no-op that neither enforces
  uniqueness nor always reports back through `index_information()`. Assert the
  **backfill**, not the index, in this test — index presence is a production
  concern covered by running the migration by hand (see the release note).

- [ ] Run both tests (expect PASS):
  `cd backend && .venv/bin/pytest v2/tests/contract/test_0174_student_birth_month_day.py v2/tests/unit/test_child_profile_dob_validation.py -q`

- [ ] Commit:
  `git add backend/v2/contexts/onboarding/domain/models.py backend/v2/contexts/enrollment/infrastructure/mongo_student_writer.py backend/v2/contexts/enrollment/infrastructure/mongo_student_repo.py backend/v2/migrations/0174_student_birth_month_day.py backend/v2/tests/unit/test_child_profile_dob_validation.py backend/v2/tests/contract/test_0174_student_birth_month_day.py backend/v2/tests/contract/test_mongo_student_writer_birth_month_day.py`
  Message: `feat(profile): validate onboarding DOB format and backfill birth_month_day`

## Task 3: `profile_nudges` collection + repo

**Files:**
- Create: `backend/v2/migrations/0175_profile_nudges_collection.py`
- Create: `backend/v2/contexts/communications/infrastructure/mongo_profile_nudge_repo.py`
- Test: `backend/v2/tests/contract/test_mongo_profile_nudge_repo.py`
- Test: `backend/v2/tests/contract/test_0175_profile_nudges_collection.py`

**Interfaces:**
- Produces: `ProfileNudgeRecord` (dataclass: `academy_id`, `parent_id`, `first_gap_seen_at`, `sends: list[NudgeSend]`, `closed_at: datetime | None`), `MongoProfileNudgeRepository.get(academy_id, parent_id) -> ProfileNudgeRecord | None`, `.create(academy_id, parent_id, first_gap_seen_at) -> ProfileNudgeRecord`, `.record_send(academy_id, parent_id, step, at, fields) -> None`, `.close(academy_id, parent_id) -> None`.
- Consumes: `backend.v2.shared.time.mongo.ensure_utc` — **every** `datetime` leaving this repo goes through it. Motor is not `tz_aware`, so `first_gap_seen_at`/`sends[].at` come back naive and `next_nudge_step`'s `now - first_gap_seen_at` would raise `TypeError` (issue #706's exact failure). The normalisation belongs here, at the read boundary — never in `SendProfileNudges`.

- [ ] Write the failing repo test:

```python
# backend/v2/tests/contract/test_mongo_profile_nudge_repo.py
from datetime import UTC, datetime

import pytest

from backend.v2.contexts.communications.infrastructure.mongo_profile_nudge_repo import (
    MongoProfileNudgeRepository,
)


@pytest.mark.asyncio
async def test_create_then_get_round_trips(db, acad):
    repo = MongoProfileNudgeRepository(db)
    now = datetime.now(UTC)
    await repo.create(academy_id="a1", parent_id="p1", first_gap_seen_at=now)
    record = await repo.get(academy_id="a1", parent_id="p1")
    assert record is not None
    assert record.first_gap_seen_at == now
    assert record.sends == []
    assert record.closed_at is None


@pytest.mark.asyncio
async def test_record_send_appends(db, acad):
    repo = MongoProfileNudgeRepository(db)
    now = datetime.now(UTC)
    await repo.create(academy_id="a1", parent_id="p1", first_gap_seen_at=now)
    await repo.record_send(
        academy_id="a1", parent_id="p1", step=1, at=now, fields=["date_of_birth"]
    )
    record = await repo.get(academy_id="a1", parent_id="p1")
    assert len(record.sends) == 1
    assert record.sends[0].step == 1
    assert record.sends[0].fields == ["date_of_birth"]


@pytest.mark.asyncio
async def test_close_stamps_closed_at(db, acad):
    repo = MongoProfileNudgeRepository(db)
    now = datetime.now(UTC)
    await repo.create(academy_id="a1", parent_id="p1", first_gap_seen_at=now)
    await repo.close(academy_id="a1", parent_id="p1")
    record = await repo.get(academy_id="a1", parent_id="p1")
    assert record.closed_at is not None


@pytest.mark.asyncio
async def test_create_is_idempotent_per_parent(db, acad):
    """Unique (academy_id, parent_id): a second create for an already-open
    record must not create a duplicate row or reset first_gap_seen_at."""
    repo = MongoProfileNudgeRepository(db)
    first = datetime(2026, 1, 1, tzinfo=UTC)
    later = datetime(2026, 2, 1, tzinfo=UTC)
    await repo.create(academy_id="a1", parent_id="p1", first_gap_seen_at=first)
    await repo.create(academy_id="a1", parent_id="p1", first_gap_seen_at=later)
    record = await repo.get(academy_id="a1", parent_id="p1")
    assert record.first_gap_seen_at == first
    assert await db["profile_nudges"].count_documents({"parent_id": "p1"}) == 1


@pytest.mark.asyncio
async def test_reads_are_timezone_aware(db, acad):
    """Motor is not tz_aware, so a stored datetime comes back naive and any
    `now - first_gap_seen_at` in the scheduler would raise TypeError (#706).
    ensure_utc at this boundary is what stops that."""
    repo = MongoProfileNudgeRepository(db)
    await repo.create(
        academy_id="a1", parent_id="p1", first_gap_seen_at=datetime.now(UTC)
    )
    await repo.record_send(
        academy_id="a1", parent_id="p1", step=1, at=datetime.now(UTC), fields=["phone"]
    )
    record = await repo.get(academy_id="a1", parent_id="p1")
    assert record.first_gap_seen_at.tzinfo is not None
    assert record.sends[0].at.tzinfo is not None
    # The subtraction the scheduler actually performs must not raise.
    assert (datetime.now(UTC) - record.first_gap_seen_at).total_seconds() >= 0
```

- [ ] Run it (expect failure — module doesn't exist):
  `cd backend && .venv/bin/pytest v2/tests/contract/test_mongo_profile_nudge_repo.py -q`

- [ ] Minimal implementation:

```python
# backend/v2/contexts/communications/infrastructure/mongo_profile_nudge_repo.py
"""profile_nudges — one open-or-closed nudge record per (academy_id, parent_id).

2026-09-10 birthdays-and-profile-nudges spec §3: the record tracks when a
parent's gap was first observed and every step sent, so the daily
send_profile_nudges job can compute the next due step without re-deriving
history from the digest_claim collections (which are per-day, not
per-gap-lifetime).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.v2.shared.tenancy import TenantScopedRepository
from backend.v2.shared.time.mongo import ensure_utc


@dataclass(frozen=True)
class NudgeSend:
    at: datetime
    step: int
    fields: list[str]


@dataclass(frozen=True)
class ProfileNudgeRecord:
    academy_id: str
    parent_id: str
    first_gap_seen_at: datetime
    sends: list[NudgeSend] = field(default_factory=list)
    closed_at: datetime | None = None


def _to_record(doc: dict[str, Any]) -> ProfileNudgeRecord:
    """Every datetime is normalised here — Motor hands back naive UTC and the
    scheduler compares against an aware ``now`` (#706)."""
    closed_at = doc.get("closed_at")
    return ProfileNudgeRecord(
        academy_id=doc["academy_id"],
        parent_id=doc["parent_id"],
        first_gap_seen_at=ensure_utc(doc["first_gap_seen_at"]),
        sends=[
            NudgeSend(
                at=ensure_utc(s["at"]), step=s["step"], fields=list(s.get("fields") or [])
            )
            for s in doc.get("sends") or []
        ],
        closed_at=ensure_utc(closed_at) if closed_at else None,
    )


class MongoProfileNudgeRepository(TenantScopedRepository):
    collection_name = "profile_nudges"

    async def get(self, *, academy_id: str, parent_id: str) -> ProfileNudgeRecord | None:
        doc = await self.collection.find_one(
            {"academy_id": academy_id, "parent_id": parent_id}
        )
        return _to_record(doc) if doc else None

    async def create(
        self, *, academy_id: str, parent_id: str, first_gap_seen_at: datetime
    ) -> ProfileNudgeRecord:
        """$setOnInsert only — an existing open record keeps its original
        first_gap_seen_at (unique index on (academy_id, parent_id) makes this
        safe under concurrency)."""
        await self.collection.update_one(
            {"academy_id": academy_id, "parent_id": parent_id},
            {
                "$setOnInsert": {
                    "academy_id": academy_id,
                    "parent_id": parent_id,
                    "first_gap_seen_at": first_gap_seen_at,
                    "sends": [],
                    "closed_at": None,
                }
            },
            upsert=True,
        )
        record = await self.get(academy_id=academy_id, parent_id=parent_id)
        assert record is not None
        return record

    async def record_send(
        self, *, academy_id: str, parent_id: str, step: int, at: datetime, fields: list[str]
    ) -> None:
        await self.collection.update_one(
            {"academy_id": academy_id, "parent_id": parent_id},
            {"$push": {"sends": {"at": at, "step": step, "fields": fields}}},
        )

    async def close(self, *, academy_id: str, parent_id: str) -> None:
        await self.collection.update_one(
            {"academy_id": academy_id, "parent_id": parent_id, "closed_at": None},
            {"$set": {"closed_at": datetime.now(UTC)}},
        )
```
  Both queries pass `academy_id` explicitly rather than going through
  `TenantScopedRepository._scoped`, because the scheduler calls this repo per
  academy from `_scheduler_academy_ids` and `SendProfileNudges` already knows
  the academy. That satisfies `tests/test_no_raw_tenant_mongo_access.py`
  (`academy_id` is a scoping token), and `profile_nudges` is not in
  `TENANT_OWNED_COLLECTIONS` anyway. Note the job body still runs inside
  `tenant_scope(academy_id)`, so `_scoped` would also work — pick one and be
  consistent with the other collaborators in the same use case.

- [ ] Run it (expect PASS):
  `cd backend && .venv/bin/pytest v2/tests/contract/test_mongo_profile_nudge_repo.py -q`

- [ ] Write the migration test. `0172_absence_notice_sends.py` is the template (index-only `up`, module-level `version`, and the "prod applies migrations by hand" docstring paragraph). Do **not** assert index shape through `index_information()` — under `mongomock-motor` `create_index` is a no-op and `spec["key"]` is an unhashable list, so the earlier draft of this test raised `TypeError` before it could assert anything. Assert the two things that are real: the module runs, and it declares the `version` the runner reads.

```python
# backend/v2/tests/contract/test_0175_profile_nudges_collection.py
import importlib

import pytest

MIGRATION = importlib.import_module("backend.v2.migrations.0175_profile_nudges_collection")


@pytest.mark.asyncio
async def test_up_is_idempotent(db):
    await MIGRATION.up(db)
    await MIGRATION.up(db)  # re-run after a partial deploy must not raise


def test_declares_the_version_the_runner_reads():
    assert MIGRATION.version == "0175_profile_nudges_collection"
```

- [ ] Minimal implementation:

```python
# backend/v2/migrations/0175_profile_nudges_collection.py
"""Creates profile_nudges with its unique (academy_id, parent_id) index
(2026-09-10 birthdays-and-profile-nudges spec §3).

Production does NOT run migrations on boot (``V2_RUN_MIGRATIONS_ON_BOOT`` is
false there, #629): apply with ``run_pending_migrations`` by hand after
deploy. Until then ``MongoProfileNudgeRepository.create`` is still
``$setOnInsert``-only, so the worst a missing index costs is a duplicate row
under a concurrent tick — never a duplicate email, which the ``sends`` array
guards.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0175_profile_nudges_collection"


async def up(db: AsyncIOMotorDatabase[Any]) -> None:
    await db["profile_nudges"].create_index(
        [("academy_id", 1), ("parent_id", 1)],
        name="academy_parent_unique",
        unique=True,
    )
```

- [ ] Create `backend/v2/migrations/0176_birthday_sends_collection.py` the same way — same docstring paragraph, `version = "0176_birthday_sends_collection"`, and:

```python
async def up(db: AsyncIOMotorDatabase[Any]) -> None:
    await db["birthday_sends"].create_index(
        [("academy_id", 1), ("student_id", 1), ("digest_date", 1)],
        unique=True,
        name="birthday_sends_key_unique",
    )
```
  This index is what `digest_claim.claim_digest_send` degrades without. The
  claim's insert-then-verify path keeps it correct even with no index, but the
  2026-09-02 hourly-resend incident is on record precisely because prod never
  built the digest indexes — do not ship the birthday job without this
  migration and without listing it in the release note's deploy steps. Add a
  matching `test_0176_birthday_sends_collection.py` alongside 0174's.

- [ ] Run the migration/repo tests (expect PASS):
  `cd backend && .venv/bin/pytest v2/tests/contract/test_0175_profile_nudges_collection.py v2/tests/contract/test_0176_birthday_sends_collection.py v2/tests/contract/test_mongo_profile_nudge_repo.py -q`

- [ ] Commit:
  `git add backend/v2/migrations/0175_profile_nudges_collection.py backend/v2/migrations/0176_birthday_sends_collection.py backend/v2/contexts/communications/infrastructure/mongo_profile_nudge_repo.py backend/v2/tests/contract/test_mongo_profile_nudge_repo.py backend/v2/tests/contract/test_0175_profile_nudges_collection.py backend/v2/tests/contract/test_0176_birthday_sends_collection.py`
  Message: `feat(communications): add profile_nudges and birthday_sends collections`

## Task 4: Nudge step scheduling (pure logic)

**Files:**
- Create: `backend/v2/shared/profile/nudge_schedule.py`
- Test: `backend/v2/tests/unit/test_nudge_schedule.py`

**Interfaces:**
- Consumes: `NudgeSend` shape (duck-typed: any object with **both** `.step: int` and `.at: datetime` — the implementation reads `.at` for steps 2 and 3, so a `.step`-only double is not enough)
- Produces: `next_nudge_step(first_gap_seen_at: datetime, sends: Sequence[Any], now: datetime) -> int | None`
- Precondition: `first_gap_seen_at`, every `.at`, and `now` are all tz-aware. The repo (Task 3) guarantees this via `ensure_utc`; this function does not defend against naive input, so a caller that bypasses the repo gets the #706 `TypeError`.

- [ ] Write the failing test:

```python
# backend/v2/tests/unit/test_nudge_schedule.py
from datetime import UTC, datetime, timedelta

from backend.v2.shared.profile.nudge_schedule import next_nudge_step

_SEEN = datetime(2026, 1, 1, tzinfo=UTC)


class _Send:
    """A recorded send needs BOTH fields: next_nudge_step reads `.at` to
    space step 2 off step 1 and step 3 off step 2."""

    def __init__(self, step: int, at: datetime) -> None:
        self.step = step
        self.at = at


def _step_1_at() -> datetime:
    return _SEEN + timedelta(days=7)


def test_no_step_before_day_7():
    assert next_nudge_step(_SEEN, [], _SEEN + timedelta(days=6)) is None


def test_step_1_at_day_7():
    assert next_nudge_step(_SEEN, [], _SEEN + timedelta(days=7)) == 1


def test_step_2_at_day_21_after_step_1():
    sends = [_Send(1, _step_1_at())]
    now = _step_1_at() + timedelta(days=21)
    assert next_nudge_step(_SEEN, sends, now) == 2


def test_no_step_2_before_its_own_day_21():
    sends = [_Send(1, _step_1_at())]
    now = _step_1_at() + timedelta(days=20)
    assert next_nudge_step(_SEEN, sends, now) is None


def test_step_3_at_day_60_after_step_2():
    step_2_at = _step_1_at() + timedelta(days=21)
    sends = [_Send(1, _step_1_at()), _Send(2, step_2_at)]
    assert next_nudge_step(_SEEN, sends, step_2_at + timedelta(days=60)) == 3


def test_no_step_3_before_its_own_day_60():
    step_2_at = _step_1_at() + timedelta(days=21)
    sends = [_Send(1, _step_1_at()), _Send(2, step_2_at)]
    assert next_nudge_step(_SEEN, sends, step_2_at + timedelta(days=59)) is None


def test_no_step_4():
    step_2_at = _step_1_at() + timedelta(days=21)
    step_3_at = step_2_at + timedelta(days=60)
    sends = [_Send(1, _step_1_at()), _Send(2, step_2_at), _Send(3, step_3_at)]
    assert next_nudge_step(_SEEN, sends, _SEEN + timedelta(days=5000)) is None
```
  Spec §5's cadence in absolute terms — day 7, day 28, day 88 from
  `first_gap_seen_at` — only holds when each step fires on its due day. The
  implementation deliberately spaces off the *actual* send time, so a job
  outage that delays step 1 shifts steps 2 and 3 with it rather than firing
  two nudges back to back. That is the behaviour these tests pin.

- [ ] Run it (expect failure):
  `cd backend && .venv/bin/pytest v2/tests/unit/test_nudge_schedule.py -q`

- [ ] Minimal implementation:

```python
# backend/v2/shared/profile/nudge_schedule.py
"""Which nudge step (if any) is due today (2026-09-10 birthdays spec §5).

Steps: 1 at day 7 from first_gap_seen_at; 2 at day 21 from step 1's send
time; 3 at day 60 from step 2's send time. No step 4. Pure — the caller
(SendProfileNudges) supplies "now" and the record's existing sends; this
function only decides the next due step, never whether the gap still exists.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

_STEP_1_DELAY = timedelta(days=7)
_STEP_2_DELAY = timedelta(days=21)
_STEP_3_DELAY = timedelta(days=60)


def next_nudge_step(
    first_gap_seen_at: datetime, sends: Sequence[Any], now: datetime
) -> int | None:
    sent_steps = {s.step for s in sends}
    if 3 in sent_steps:
        return None
    if 2 in sent_steps:
        step_2_at = next(s for s in sends if s.step == 2).at
        return 3 if now - step_2_at >= _STEP_3_DELAY else None
    if 1 in sent_steps:
        step_1_at = next(s for s in sends if s.step == 1).at
        return 2 if now - step_1_at >= _STEP_2_DELAY else None
    return 1 if now - first_gap_seen_at >= _STEP_1_DELAY else None
```

- [ ] Run it (expect PASS):
  `cd backend && .venv/bin/pytest v2/tests/unit/test_nudge_schedule.py -q`

- [ ] Commit:
  `git add backend/v2/shared/profile/nudge_schedule.py backend/v2/tests/unit/test_nudge_schedule.py`
  Message: `feat(profile): add pure profile-nudge step scheduling`

## Task 5: Birthday send claim (digest_claim adapter)

**Files:**
- Create: `backend/v2/contexts/communications/infrastructure/mongo_birthday_send_repo.py`
- Test: `backend/v2/tests/contract/test_mongo_birthday_send_repo.py`

**Interfaces:**
- Consumes: `backend.v2.contexts.communications.infrastructure.digest_claim.claim_digest_send` (verified signature: `collection, *, doc, academy_id, recipient_field, recipient_id, digest_date`; returns the claiming document — the freshly inserted `doc` (which pymongo has stamped with `_id`) or the re-claimed row from `reclaim_retryable_send` — and `None` when the recipient is already sent/in-flight/non-retryable/out of attempts).
- Consumes: `DigestSendStatus` / `MAX_DIGEST_SEND_ATTEMPTS` from `contexts/communications/domain/models.py` (lines 288-300). The claim's re-claim query matches on `str(DigestSendStatus.FAILED)` / `.QUEUED` and on `attempt_count < MAX_DIGEST_SEND_ATTEMPTS`, so the inserted `doc` MUST carry `status`, `attempt_count`, `retryable` and `created_at`, and `mark_sent`/`mark_failed` MUST write the same status vocabulary. Use the enum, not bare string literals.
- Produces: `MongoBirthdaySendRepository.try_claim(*, academy_id, student_id, year) -> ClaimedBirthdaySend | None`, `.mark_sent(claim_id, provider_message_id)`, `.mark_failed(claim_id, reason, *, retryable=True)`. This is a **deliberately narrower** shape than the `DigestSendRepository` Protocol (`ports.py` line 207 — verified), which has six methods, positional `try_claim(academy_id, coach_id, digest_date)` and a `digest_id` handle. Do not try to satisfy that Protocol; only the claim *rule* is shared, via `digest_claim`.

- [ ] Write the failing test:

```python
# backend/v2/tests/contract/test_mongo_birthday_send_repo.py
import pytest

from backend.v2.contexts.communications.infrastructure.mongo_birthday_send_repo import (
    MongoBirthdaySendRepository,
)


@pytest.mark.asyncio
async def test_first_claim_succeeds(db, acad):
    repo = MongoBirthdaySendRepository(db)
    claim = await repo.try_claim(academy_id="a1", student_id="s1", year=2026)
    assert claim is not None


@pytest.mark.asyncio
async def test_second_claim_same_year_is_blocked_after_sent(db, acad):
    repo = MongoBirthdaySendRepository(db)
    claim = await repo.try_claim(academy_id="a1", student_id="s1", year=2026)
    assert claim is not None
    await repo.mark_sent(claim.claim_id, "msg_1")
    second = await repo.try_claim(academy_id="a1", student_id="s1", year=2026)
    assert second is None


@pytest.mark.asyncio
async def test_next_year_is_a_fresh_claim(db, acad):
    repo = MongoBirthdaySendRepository(db)
    claim = await repo.try_claim(academy_id="a1", student_id="s1", year=2026)
    await repo.mark_sent(claim.claim_id, "msg_1")
    next_year = await repo.try_claim(academy_id="a1", student_id="s1", year=2027)
    assert next_year is not None
```

- [ ] Run it (expect failure — module doesn't exist):
  `cd backend && .venv/bin/pytest v2/tests/contract/test_mongo_birthday_send_repo.py -q`

- [ ] Minimal implementation. `backend/v2/contexts/communications/infrastructure/mongo_digest_send_repo.py` is the reference implementation for the queued-doc shape; read it for the field names it writes, then: 

```python
# backend/v2/contexts/communications/infrastructure/mongo_birthday_send_repo.py
"""birthday_sends — one claim per (academy_id, student_id, year) (spec §3, §4.2).

Reuses digest_claim.claim_digest_send with digest_date := str(year) so a
birthday note can never double-send within one calendar year, on the same
idempotency invariant the coach/parent digests rely on (see digest_claim.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from backend.v2.contexts.communications.domain.models import DigestSendStatus
from backend.v2.contexts.communications.infrastructure.digest_claim import (
    claim_digest_send,
)
from backend.v2.shared.tenancy import TenantScopedRepository


@dataclass(frozen=True)
class ClaimedBirthdaySend:
    claim_id: Any


class MongoBirthdaySendRepository(TenantScopedRepository):
    collection_name = "birthday_sends"

    async def try_claim(
        self, *, academy_id: str, student_id: str, year: int
    ) -> ClaimedBirthdaySend | None:
        doc = {
            "academy_id": academy_id,
            "student_id": student_id,
            "digest_date": str(year),
            "status": str(DigestSendStatus.QUEUED),
            "attempt_count": 1,  # the insert IS attempt 1 (see MAX_DIGEST_SEND_ATTEMPTS)
            "retryable": True,
            "created_at": datetime.now(UTC),
        }
        claimed = await claim_digest_send(
            self.collection,
            doc=doc,
            academy_id=academy_id,
            recipient_field="student_id",
            recipient_id=student_id,
            digest_date=str(year),
        )
        if claimed is None:
            return None
        return ClaimedBirthdaySend(claim_id=claimed["_id"])

    async def mark_sent(self, claim_id: Any, provider_message_id: str | None) -> None:
        await self.collection.update_one(
            {"_id": claim_id},
            {
                "$set": {
                    "status": str(DigestSendStatus.SENT),
                    "provider_message_id": provider_message_id,
                }
            },
        )

    async def mark_failed(
        self, claim_id: Any, reason: str, *, retryable: bool = True
    ) -> None:
        await self.collection.update_one(
            {"_id": claim_id},
            {
                "$set": {
                    "status": str(DigestSendStatus.FAILED),
                    "failed_reason": reason,
                    "retryable": retryable,
                }
            },
        )
```
  `claimed["_id"]` is correct on both return paths (verified in
  `digest_claim.py`): the insert path returns the same `doc` object, which
  pymongo has mutated to carry `_id`, and the re-claim path returns the
  `find_one_and_update` result. A `KeyError` here would mean `digest_claim`
  changed — assert on it rather than defaulting.

  `birthday_sends` is NOT in `TENANT_OWNED_COLLECTIONS`
  (`tests/test_no_raw_tenant_mongo_access.py`), and every query above names
  `academy_id`, so the raw-Mongo ratchet is satisfied either way.

- [ ] Run it (expect PASS):
  `cd backend && .venv/bin/pytest v2/tests/contract/test_mongo_birthday_send_repo.py -q`

- [ ] Commit:
  `git add backend/v2/contexts/communications/infrastructure/mongo_birthday_send_repo.py backend/v2/tests/contract/test_mongo_birthday_send_repo.py`
  Message: `feat(communications): add birthday_sends claim repository`

## Task 6: `SendBirthdayNotes` use case + renderer + composition + scheduler

**Files:**
- Create: `backend/v2/contexts/communications/application/birthday_renderer.py`
- Create: `backend/v2/contexts/enrollment/application/use_cases/birthday_students_today.py`
- Create: `backend/v2/contexts/communications/application/use_cases/send_birthday_notes.py`
- Create: `backend/v2/composition/birthday_notes.py`
- Modify: `backend/v2/main.py` (scheduler registration)
- Modify: `backend/v2/shared/observability/ops_digest.py` (`JOB_STALE_AFTER`)
- Test: `backend/v2/tests/application/test_send_birthday_notes.py`

**Interfaces:**
- Consumes: `derive_birth_month_day`/`birth_month_day_for_date`/`is_feb_28_in_non_leap_year` (Task 1), `MongoBirthdaySendRepository` (Task 5), `EmailSendPort`/`EmailCategory.NOTIFICATION` (verified `ports.py`), `render_unsubscribe_footer` (verified `unsubscribe_footer.py`)
- Produces: `SendBirthdayNotes.execute(academy_id, on_date) -> SendBirthdayNotesResult(total=int, claimed=int, already_claimed=int, sent=int, failed=int)`

- [ ] First read `backend/v2/contexts/enrollment/application/use_cases/admin_directory.py` (imported at the top of `mongo_student_repo.py`) to confirm the shape returned by the repo's existing student-list queries, so `BirthdayStudentsTodayQuery` below reuses those field names rather than inventing new ones for `student_id`/`full_name`/`parent_id`/enrollment-status join.

- [ ] Write the failing unit test (use case tested against fakes, not Mongo). Open `backend/v2/tests/application/test_send_coach_daily_digest.py` first — that is the real path (there is no `tests/unit/contexts/` tree) — and copy its fake `EmailSendPort`/`AudienceResolver` doubles verbatim rather than re-deriving them:

```python
# backend/v2/tests/application/test_send_birthday_notes.py
from dataclasses import dataclass, field
from datetime import date

import pytest

from backend.v2.contexts.communications.application.use_cases.send_birthday_notes import (
    SendBirthdayNotes,
    SendBirthdayNotesCommand,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory


@dataclass
class _BirthdayStudent:
    student_id: str
    full_name: str
    parent_id: str
    parent_email: str | None


class _FakeStudentProvider:
    def __init__(self, students):
        self._students = students

    async def students_born_on(self, academy_id: str, on_date: date):
        return self._students


@dataclass
class _Claim:
    claim_id: str


class _FakeClaims:
    def __init__(self):
        self.claimed: list[str] = []
        self.sent: list[str] = []
        self.failed: list[str] = []

    async def try_claim(self, *, academy_id, student_id, year):
        if student_id in self.claimed:
            return None
        self.claimed.append(student_id)
        return _Claim(claim_id=student_id)

    async def mark_sent(self, claim_id, provider_message_id):
        self.sent.append(claim_id)

    async def mark_failed(self, claim_id, reason, *, retryable=True):
        self.failed.append(claim_id)


@dataclass
class _Outcome:
    ok: bool
    suppressed: bool = False
    failed_reason: str | None = None
    provider_message_id: str | None = None


class _FakeSender:
    def __init__(self, outcome: _Outcome):
        self.outcome = outcome
        self.sends: list[dict] = []

    async def send(self, **kwargs):
        self.sends.append(kwargs)
        return self.outcome


@pytest.mark.asyncio
async def test_sends_one_email_per_birthday_student():
    students = [_BirthdayStudent("s1", "Aanya", "p1", "parent1@example.com")]
    claims = _FakeClaims()
    sender = _FakeSender(_Outcome(ok=True, provider_message_id="m1"))
    use_case = SendBirthdayNotes(
        students=_FakeStudentProvider(students), claims=claims, sender=sender
    )
    result = await use_case.execute(
        SendBirthdayNotesCommand(academy_id="a1", on_date=date(2026, 6, 17))
    )
    assert result.sent == 1
    assert sender.sends[0]["category"] == EmailCategory.NOTIFICATION
    assert claims.sent == ["s1"]


@pytest.mark.asyncio
async def test_skips_student_with_no_parent_email():
    students = [_BirthdayStudent("s1", "Aanya", "p1", None)]
    claims = _FakeClaims()
    sender = _FakeSender(_Outcome(ok=True))
    use_case = SendBirthdayNotes(
        students=_FakeStudentProvider(students), claims=claims, sender=sender
    )
    result = await use_case.execute(
        SendBirthdayNotesCommand(academy_id="a1", on_date=date(2026, 6, 17))
    )
    assert result.sent == 0
    assert result.failed == 1
    assert sender.sends == []


@pytest.mark.asyncio
async def test_already_claimed_is_not_resent():
    students = [_BirthdayStudent("s1", "Aanya", "p1", "parent1@example.com")]
    claims = _FakeClaims()
    claims.claimed.append("s1")  # simulate an earlier tick's claim
    sender = _FakeSender(_Outcome(ok=True))
    use_case = SendBirthdayNotes(
        students=_FakeStudentProvider(students), claims=claims, sender=sender
    )
    result = await use_case.execute(
        SendBirthdayNotesCommand(academy_id="a1", on_date=date(2026, 6, 17))
    )
    assert result.already_claimed == 1
    assert result.sent == 0
```

- [ ] Run it (expect failure — module doesn't exist):
  `cd backend && .venv/bin/pytest v2/tests/application/test_send_birthday_notes.py -q`

- [ ] Minimal implementation:

```python
# backend/v2/contexts/communications/application/birthday_renderer.py
"""Renders one "Happy birthday" note (spec §4.2): student name, academy
branding, no call to action, standard unsubscribe footer."""

from __future__ import annotations

import html

from backend.v2.contexts.communications.application.unsubscribe_footer import (
    render_unsubscribe_footer,
)
from backend.v2.shared.comms.email_theme import INK, EmailBrand, shell


def render_birthday_note(
    student_first_name: str,
    *,
    brand: EmailBrand | None,
    unsubscribe_url: str | None,
) -> tuple[str, str]:
    """Subject + HTML body. Academy-branded (spec §4.2), no call to action."""
    # `shell` requires a brand; `render_coach_digest` uses the same fallback.
    resolved_brand = brand or EmailBrand(academy_name="Your academy")
    safe_name = html.escape(student_first_name)
    safe_academy = html.escape(resolved_brand.academy_name)
    subject = f"Happy birthday, {student_first_name}!"
    inner = (
        f'<p style="font-size:16px;color:{INK};margin:0 0 12px;">'
        f"Happy birthday, {safe_name}! "
        f"Everyone at {safe_academy} hopes you have a wonderful day.</p>"
    )
    return subject, shell(
        brand=resolved_brand,
        inner_html=inner,
        footer_html=render_unsubscribe_footer(unsubscribe_url),
    )
```
  Verified against `backend/v2/shared/comms/email_theme.py` (line 61): `shell`
  is keyword-only — `shell(*, brand: EmailBrand, inner_html: str,
  date_label: str | None = None, footer_html: str = "") -> str` — and `brand`
  is **required**, not optional, which is why the fallback `EmailBrand` above
  is constructed rather than passing `None`.

```python
# backend/v2/contexts/enrollment/application/use_cases/birthday_students_today.py
"""Enrollment-side query for today's birthday students (spec §4.2): DOB
matches on_date's birth_month_day (with the Feb-29-in-non-leap-year fold,
spec §7), is_deleted false, at least one active|held|paused enrollment.
Wired into communications as the duck-typed BirthdayStudentProvider so
communications never imports the enrollment context (ADR-0005)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from backend.v2.shared.profile.birth_month_day import (
    birth_month_day_for_date,
    is_feb_28_in_non_leap_year,
)


@dataclass(frozen=True)
class BirthdayStudent:
    student_id: str
    full_name: str
    parent_id: str
    parent_email: str | None


class BirthdayStudentsRepo(Protocol):
    async def find_by_birth_month_days(
        self, academy_id: str, month_days: tuple[str, ...]
    ) -> list[BirthdayStudent]: ...


@dataclass
class BirthdayStudentsTodayQuery:
    repo: BirthdayStudentsRepo

    async def students_born_on(
        self, academy_id: str, on_date: date
    ) -> list[BirthdayStudent]:
        month_days = [birth_month_day_for_date(on_date)]
        if is_feb_28_in_non_leap_year(on_date):
            month_days.append("02-29")
        return await self.repo.find_by_birth_month_days(academy_id, tuple(month_days))
```
  `find_by_birth_month_days` is a new method to add to `MongoStudentRepository`
  in `mongo_student_repo.py` (read the file's existing tenant-scoped query
  helpers, e.g. the pattern around line 811/856, before adding it, so it
  reuses the same `is_deleted`/enrollment-join idiom rather than a new one) —
  it must join against `enrollments` for `status in (active, held, paused)`
  and the student's `parent_id`'s email from the identity/users collection
  exactly as the existing admin-directory queries already do.

```python
# backend/v2/contexts/communications/application/use_cases/send_birthday_notes.py
"""SendBirthdayNotes use case (2026-09-10 birthdays spec §4.2).

One email per birthday student, claimed through birthday_sends so a job
re-run this year can never double-send. Structurally mirrors
SendCoachDailyDigest (claim -> build -> send -> mark)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from backend.v2.contexts.communications.application.birthday_renderer import (
    render_birthday_note,
)
from backend.v2.contexts.communications.application.ports import (
    AcademyBrandLookup,
    AcademySlugLookup,
    EmailSendPort,
    ResolvedRecipient,
)
from backend.v2.contexts.communications.application.unsubscribe_token import (
    UnsubscribeLinkBuilder,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory


class BirthdayStudentProvider(Protocol):
    async def students_born_on(self, academy_id: str, on_date: date) -> list[Any]: ...


class BirthdayClaims(Protocol):
    async def try_claim(self, *, academy_id: str, student_id: str, year: int) -> Any | None: ...
    async def mark_sent(self, claim_id: Any, provider_message_id: str | None) -> None: ...
    async def mark_failed(self, claim_id: Any, reason: str, *, retryable: bool = True) -> None: ...


@dataclass(frozen=True, slots=True)
class SendBirthdayNotesCommand:
    academy_id: str
    on_date: date


@dataclass(frozen=True, slots=True)
class SendBirthdayNotesResult:
    total: int = 0
    claimed: int = 0
    already_claimed: int = 0
    sent: int = 0
    failed: int = 0


@dataclass
class SendBirthdayNotes:
    students: BirthdayStudentProvider
    claims: BirthdayClaims
    sender: EmailSendPort
    # Optional, and each degrades to a safe default on failure — the same
    # "a lookup failure is not a reason to withhold the send" rule
    # SendCoachDailyDigest applies in _brand/_academy_slug (lines 122-159).
    unsubscribe_links: UnsubscribeLinkBuilder | None = None
    brands: AcademyBrandLookup | None = None
    academy_slugs: AcademySlugLookup | None = None

    async def _brand(self, academy_id: str):
        if self.brands is None:
            return None
        try:
            return await self.brands.brand_for(academy_id)
        except Exception:
            return None

    async def _academy_slug(self, academy_id: str) -> str | None:
        if self.academy_slugs is None:
            return None
        try:
            return await self.academy_slugs.slug_for(academy_id)
        except Exception:
            return None

    async def execute(self, command: SendBirthdayNotesCommand) -> SendBirthdayNotesResult:
        students = await self.students.students_born_on(command.academy_id, command.on_date)
        # Resolved ONCE per run, never per recipient (same rule as the coach digest).
        brand = await self._brand(command.academy_id)
        academy_slug = await self._academy_slug(command.academy_id)
        total = claimed = already_claimed = sent = failed = 0
        for student in students:
            total += 1
            claim = await self.claims.try_claim(
                academy_id=command.academy_id,
                student_id=student.student_id,
                year=command.on_date.year,
            )
            if claim is None:
                already_claimed += 1
                continue
            claimed += 1
            if not student.parent_email:
                await self.claims.mark_failed(claim.claim_id, "no parent email", retryable=False)
                failed += 1
                continue
            first_name = student.full_name.split(" ")[0] if student.full_name else "there"
            unsubscribe_url = (
                self.unsubscribe_links.build(
                    academy_id=command.academy_id,
                    user_id=student.parent_id,
                    academy_slug=academy_slug,
                )
                if self.unsubscribe_links
                else None
            )
            subject, body = render_birthday_note(
                first_name, brand=brand, unsubscribe_url=unsubscribe_url
            )
            outcome = await self.sender.send(
                recipient=ResolvedRecipient(
                    user_id=student.parent_id, email=student.parent_email, display_name=None
                ),
                subject=subject,
                body=body,
                category=EmailCategory.NOTIFICATION,
            )
            if outcome.ok:
                await self.claims.mark_sent(claim.claim_id, outcome.provider_message_id)
                sent += 1
            else:
                await self.claims.mark_failed(
                    claim.claim_id, outcome.failed_reason or "unknown", retryable=not outcome.suppressed
                )
                failed += 1
        return SendBirthdayNotesResult(
            total=total, claimed=claimed, already_claimed=already_claimed, sent=sent, failed=failed
        )
```

- [ ] Run the unit test (expect PASS):
  `cd backend && .venv/bin/pytest v2/tests/application/test_send_birthday_notes.py -q`

- [ ] Composition — create `backend/v2/composition/birthday_notes.py`:

```python
# backend/v2/composition/birthday_notes.py
"""Wires SendBirthdayNotes (2026-09-10 birthdays spec §4.2). Its own module,
never composition/admin.py (capped at 4500 lines, already 4318)."""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.composition.digests import (
    _AcademyBrandLookup,
    _AcademySlugLookup,
    _build_email_sender,
    compose_unsubscribe_link_builder,
)
from backend.v2.contexts.communications.application.use_cases.send_birthday_notes import (
    SendBirthdayNotes,
)
from backend.v2.contexts.communications.infrastructure.mongo_birthday_send_repo import (
    MongoBirthdaySendRepository,
)
from backend.v2.contexts.enrollment.application.use_cases.birthday_students_today import (
    BirthdayStudentsTodayQuery,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
    MongoAcademyRepository,
)
from backend.v2.shared.config import get_settings


def compose_send_birthday_notes(db: AsyncIOMotorDatabase[Any]) -> SendBirthdayNotes:
    settings = get_settings()
    academies = MongoAcademyRepository(db)
    return SendBirthdayNotes(
        students=BirthdayStudentsTodayQuery(repo=MongoStudentRepository(db)),
        claims=MongoBirthdaySendRepository(db),
        sender=_build_email_sender(settings, db),
        unsubscribe_links=compose_unsubscribe_link_builder(settings),
        brands=_AcademyBrandLookup(academies),
        academy_slugs=_AcademySlugLookup(academies),
    )
```
  **There is no `compose_email_send_port`, and `composition/email_adapters.py`
  exposes only `build_user_facing_invite_sender`.** `digests._build_email_sender`
  is the single construction site allowed to build a real `ResendEmailSendPort`
  — `tests/structural/test_email_sender_construction.py` fails the build on any
  other site, and it is where the environment gate (staging/prod only) plus the
  `GatedEmailSendPort` unsubscribe/suppression gates live. Confirm the exact
  import names of `_AcademyBrandLookup` / `_AcademySlugLookup` /
  `compose_unsubscribe_link_builder` in `composition/digests.py`
  (`compose_send_coach_daily_digest`, ~line 446, uses all three) and, if
  importing underscore-prefixed helpers across composition modules is
  unpalatable, rename them there rather than duplicating the gate.

- [ ] Scheduler wiring in `backend/v2/main.py`. Add to `SCHEDULED_JOB_MONITORS` (near the `send_hold_reminders` entry, ~line 288):

```python
    "send_birthday_notes": {
        "schedule": {"type": "crontab", "value": "30 7 * * *"},
        "checkin_margin": 30,
        "max_runtime": 30,
    },
```

  Add a job body following the `_send_hold_reminders`/`_send_hold_reminders_body` pair (~line 764-784):

```python
    app.state.send_birthday_notes = compose_send_birthday_notes(db)

    async def _send_birthday_notes() -> None:
        await _run_leased_job(
            "send_birthday_notes", timedelta(minutes=5), _send_birthday_notes_body
        )

    async def _send_birthday_notes_body() -> None:
        # Read the raw notifications subdoc, exactly as
        # `_send_coach_daily_digests_body` does (main.py ~line 1074): an unset
        # key means "off", and this avoids pulling an identity use case onto
        # app.state just for one boolean. `birthday_emails_enabled` has NO env
        # default — spec §2 requires an explicit per-academy opt-in after the
        # owner's consent check, so absence must never fall back to "on".
        academy_repo = MongoAcademyRepository(db)
        on_date = datetime.now(scheduler.timezone).date()
        totals = {"academy_count": 0, "sent": 0, "failed": 0}
        for academy_id in await _scheduler_academy_ids(
            academy_repo,
            runtime_academy_id,
        ):
            doc = await academy_repo.find_by_id(academy_id)
            notifs = (doc or {}).get("notifications") or {}
            if not bool(notifs.get("birthday_emails_enabled", False)):
                continue
            with tenant_scope(academy_id):
                result = await app.state.send_birthday_notes.execute(
                    SendBirthdayNotesCommand(academy_id=academy_id, on_date=on_date)
                )
            totals["academy_count"] += 1
            totals["sent"] += result.sent
            totals["failed"] += result.failed
        if totals["sent"] or totals["failed"]:
            log.info("birthday_notes_sent", extra=totals)
```
  Verified: `app.state.get_academy_notifications_use_case` does not exist —
  `GetAcademyNotificationsUseCase` is constructed inside `composition/admin.py`
  (line 1673) and reached through the admin `use_cases` dependency, not
  `app.state`. `MongoAcademyRepository`, `_scheduler_academy_ids`,
  `tenant_scope`, `runtime_academy_id` and `datetime.now(scheduler.timezone)`
  are all already in scope in `_lifespan` (verified at main.py lines 211,
  1055, 1067-1069, 1759).

  Then add the `scheduler.add_job` call beside the other daily crons (~line 1247):

```python
    scheduler.add_job(
        _send_birthday_notes,
        "cron",
        hour=7,
        minute=30,
        id="send_birthday_notes",
        replace_existing=True,
        max_instances=1,
    )
```
  and import `compose_send_birthday_notes` / `SendBirthdayNotesCommand` at
  the top of `main.py` alongside the other composition imports.

- [ ] Add `"send_birthday_notes": timedelta(hours=26)` to `JOB_STALE_AFTER` in `backend/v2/shared/observability/ops_digest.py` (lines 92-113), next to the other daily jobs — this keeps `assert SCHEDULED_JOB_MONITORS.keys() == JOB_STALE_AFTER.keys()` (main.py line 303, verified) passing.

- [ ] Update `backend/v2/tests/unit/test_scheduler_academies.py::test_scheduler_job_tables_cover_every_registered_job`: `assert len(registered) == 13` → `14` here (and `15` after Task 8). Verified: without this the whole scheduler-table test fails, and neither the module-scope `assert` nor a bare `import backend.v2.main` catches it.

- [ ] Add `send_birthday_notes.py` to the sweep in `backend/v2/tests/structural/test_email_category_threading.py`. Its filename contains neither `digest` nor `campaign`, so `BULK_MODULE_MARKERS` misses it — and a NOTIFICATION loop that lost its `category=` would silently be gated as TRANSACTIONAL, which is the exact bug that file exists to prevent. Either widen `BULK_MODULE_MARKERS` or add an explicit module list; document the choice in that file's docstring.

- [ ] Run the assertions + boot smoke test:
  `cd backend && .venv/bin/pytest v2/tests/application/test_send_birthday_notes.py v2/tests/unit/test_scheduler_academies.py v2/tests/structural -q && .venv/bin/python -c "import backend.v2.main"`
  Expected: all pass and the import succeeds (the `assert` at module scope does not raise).

- [ ] Commit:
  `git add backend/v2/contexts/communications/application/birthday_renderer.py backend/v2/contexts/enrollment/application/use_cases/birthday_students_today.py backend/v2/contexts/communications/application/use_cases/send_birthday_notes.py backend/v2/composition/birthday_notes.py backend/v2/main.py backend/v2/shared/observability/ops_digest.py backend/v2/tests/application/test_send_birthday_notes.py backend/v2/tests/unit/test_scheduler_academies.py backend/v2/tests/structural/test_email_category_threading.py`
  Message: `feat(communications): send switchable per-student birthday emails`

## Task 7: `birthday_emails_enabled` academy setting (backend + frontend)

**Files:**
- Modify: `backend/v2/contexts/identity/application/get_academy_notifications_use_case.py`
- Modify: `backend/v2/contexts/identity/application/update_academy_notifications_use_case.py`
- Modify: `backend/v2/contexts/identity/infrastructure/mongo_academy_repo.py` (`upsert_defaults`, ~line 42-60)
- Modify: `backend/v2/interfaces/admin/views.py` (`AdminNotificationsView`/`UpdateAdminNotificationsRequest`, lines 1707-1724)
- Modify: `backend/v2/composition/admin.py` (2 lines, ~1673, ~1680)
- Modify: `frontend/lib/api/admin.ts` (`AdminNotificationsView`, ~line 1431 — **pre-plan-1/2 numbering**; plans 1 and 2 both add fields higher up in this file, so find `AdminNotificationsView` by name, not by line)
- Modify: `frontend/components/admin/settings/notify-panel.tsx`
- Test: `backend/v2/tests/unit/test_academy_notifications_birthday_emails.py`

**Interfaces:**
- Produces: `GET/PATCH /admin/academy/notifications` (verified route, `academy_routes.py` lines 147-165) now round-trips `birthday_emails_enabled`.

- [ ] Write the failing use-case test:

```python
# backend/v2/tests/unit/test_academy_notifications_birthday_emails.py
import pytest

from backend.v2.contexts.identity.application.get_academy_notifications_use_case import (
    GetAcademyNotificationsUseCase,
)
from backend.v2.contexts.identity.application.update_academy_notifications_use_case import (
    UpdateAcademyNotificationsUseCase,
)


class _FakeAcademyRepo:
    def __init__(self):
        self.docs = {}

    async def find_by_id(self, academy_id):
        return self.docs.get(academy_id)

    async def upsert_defaults(self, academy_id):
        doc = {"notifications": {"birthday_emails_enabled": False}}
        self.docs[academy_id] = doc
        return doc

    async def update_by_id(self, academy_id, fields):
        doc = self.docs.setdefault(academy_id, {"notifications": {}})
        for key, value in fields.items():
            _, field = key.split(".", 1)
            doc["notifications"][field] = value
        return doc


@pytest.mark.asyncio
async def test_defaults_to_off():
    repo = _FakeAcademyRepo()
    use_case = GetAcademyNotificationsUseCase(repo)
    out = await use_case.execute("a1")
    assert out.birthday_emails_enabled is False


@pytest.mark.asyncio
async def test_can_be_switched_on():
    repo = _FakeAcademyRepo()
    await GetAcademyNotificationsUseCase(repo).execute("a1")
    update = UpdateAcademyNotificationsUseCase(repo)
    out = await update.execute("a1", {"birthday_emails_enabled": True})
    assert out.birthday_emails_enabled is True
```

- [ ] Run it (expect failure — `AttributeError: 'GetAcademyNotificationsOutput' object has no attribute 'birthday_emails_enabled'`):
  `cd backend && .venv/bin/pytest v2/tests/unit/test_academy_notifications_birthday_emails.py -q`

- [ ] Minimal implementation. In `get_academy_notifications_use_case.py`, add the field to `GetAcademyNotificationsOutput`:

```python
    birthday_emails_enabled: bool = False
```
  and to `_notifications_output`'s return (and its `default_...` kwarg, matching the existing `coach_digest_enabled` pattern):

```python
        birthday_emails_enabled=bool(
            notifs.get("birthday_emails_enabled", default_birthday_emails_enabled)
        ),
```
  adding `default_birthday_emails_enabled: bool = False` to both `_notifications_output`'s
  and `GetAcademyNotificationsUseCase.__init__`'s parameter lists, threading it
  the same way `default_coach_digest_enabled` already is.

  `UpdateAcademyNotificationsUseCase` needs no code change — its `fields` dict
  is already generic (`patch = {f"notifications.{k}": v for k, v in
  fields.items() if v is not None}`) — but add
  `default_birthday_emails_enabled: bool = False` to its `__init__` and thread
  it into the `_notifications_output(...)` call at the end of `execute`, for
  symmetry with `GetAcademyNotificationsUseCase`.

  In `mongo_academy_repo.py`, `upsert_defaults` (~line 42-60), add
  `"birthday_emails_enabled": False,` inside the `"notifications": {...}` dict
  (~line 52-55).

- [ ] Run it (expect PASS):
  `cd backend && .venv/bin/pytest v2/tests/unit/test_academy_notifications_birthday_emails.py -q`

- [ ] Wire the API view. In `backend/v2/interfaces/admin/views.py`:

```python
class AdminNotificationsView(BaseModel):
    ...
    birthday_emails_enabled: bool = False


class UpdateAdminNotificationsRequest(BaseModel):
    ...
    birthday_emails_enabled: bool | None = None
```

- [ ] Wire composition. In `backend/v2/composition/admin.py`, at the two call sites (~1673, ~1680), add `default_birthday_emails_enabled=False,` to both constructor calls — no other change to `admin.py`.

- [ ] Run the full backend suite for this slice:
  `cd backend && .venv/bin/pytest v2/tests/unit/test_academy_notifications_birthday_emails.py -q`

- [ ] Frontend. In `frontend/lib/api/admin.ts` (~line 1431-1441):

```typescript
export interface AdminNotificationsView {
  ...
  birthday_emails_enabled: boolean;
}
```
  (`UpdateAdminNotificationsRequest` is already `Partial<AdminNotificationsView>` — no separate edit needed there.)

- [ ] In `frontend/components/admin/settings/notify-panel.tsx` (369 lines — read the relevant parts, not "it is short"; verified anchors: `normalize()` at line 24, `coach_digest_enabled` default at line 29, form state at 59, `original` memo at 65, the toggle rows at 87-135, the local `Toggle` component at 349). Add:
  1. `birthday_emails_enabled: data?.birthday_emails_enabled ?? false,` to `normalize()`.
  2. A `<Toggle>` row beside the `coach_digest_enabled` one, copying its exact `checked` / `onCheckedChange` wiring.
  There is **no** `isDirty()` helper in this file (an earlier draft claimed one): dirty state is derived by comparing `form` against the `original` memo, which picks up the new key automatically once `normalize()` knows about it.

- [ ] Frontend query keys: none added. The panel reads through the existing notifications query — check `frontend/lib/query/keys.ts` and reuse whatever key `notify-panel.tsx` already passes to `useQuery`; do not mint a new one for a field on an existing payload.

- [ ] Verification: `cd frontend && pnpm typecheck` (expected: no new errors). No new e2e spec and no `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json` change — that manifest tracks `frontend/app/` **routes**, and this task adds none.

- [ ] Commit:
  `git add backend/v2/contexts/identity/application/get_academy_notifications_use_case.py backend/v2/contexts/identity/application/update_academy_notifications_use_case.py backend/v2/contexts/identity/infrastructure/mongo_academy_repo.py backend/v2/interfaces/admin/views.py backend/v2/composition/admin.py frontend/lib/api/admin.ts frontend/components/admin/settings/notify-panel.tsx backend/v2/tests/unit/test_academy_notifications_birthday_emails.py`
  Message: `feat(settings): add birthday_emails_enabled academy toggle (default off)`

## Task 8: `SendProfileNudges` use case + renderer + composition + scheduler

**Files:**
- Create: `backend/v2/contexts/enrollment/application/use_cases/family_profiles_for_nudges.py`
- Create: `backend/v2/contexts/communications/application/profile_nudge_renderer.py`
- Create: `backend/v2/contexts/communications/application/use_cases/send_profile_nudges.py`
- Create: `backend/v2/composition/profile_nudges.py`
- Modify: `backend/v2/main.py` (scheduler registration)
- Modify: `backend/v2/shared/observability/ops_digest.py` (`JOB_STALE_AFTER`)
- Test: `backend/v2/tests/application/test_send_profile_nudges.py`

**Interfaces:**
- Consumes: `ParentFacts`, `ChildFacts`, `evaluate`, `ProfileGaps.is_complete` (all verified in `shared/profile/completeness.py`; `ParentFacts`/`ChildFacts` are **frozen pydantic models**, not dataclasses — construct them with keywords), `next_nudge_step` (Task 4), `MongoProfileNudgeRepository` (Task 3), `UnsubscribeLinkBuilder` + `academy_frontend_url`.
- Produces: `SendProfileNudges.execute(*, academy_id, now) -> SendProfileNudgesResult(total_families=int, closed=int, sent=int, failed=int)`. (An earlier draft also listed `skipped_too_new`; the dataclass below does not define it and nothing needs it — the "brand-new family" case is simply a `create` with no send. Keep the four fields, or add the fifth to *both* the dataclass and this line.)
- Gap keys are the stable strings from `PARENT_REQUIRED` / `CHILD_REQUIRED`: `display_name`, `phone`, `email_confirmed`, `full_name`, `date_of_birth`, `emergency_contact_name`, `emergency_contact_phone`, `medical_notes`. `medical_notes` counts as answered when it holds the `MEDICAL_NONE_SENTINEL` — do not re-implement the blank check.

- [ ] Write the failing unit test:

```python
# backend/v2/tests/application/test_send_profile_nudges.py
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.communications.application.use_cases.send_profile_nudges import (
    SendProfileNudges,
)
from backend.v2.shared.profile.completeness import ChildFacts, ParentFacts


@dataclass
class _Family:
    parent_id: str
    parent_email: str | None
    parent: ParentFacts
    children: list


class _FakeFamilyProvider:
    def __init__(self, families):
        self._families = families

    async def families_with_active_students(self, academy_id: str):
        return self._families


class _FakeNudgeRepo:
    def __init__(self):
        self.records = {}

    async def get(self, *, academy_id, parent_id):
        return self.records.get((academy_id, parent_id))

    async def create(self, *, academy_id, parent_id, first_gap_seen_at):
        record = type(
            "R", (), {"first_gap_seen_at": first_gap_seen_at, "sends": [], "closed_at": None}
        )()
        self.records[(academy_id, parent_id)] = record
        return record

    async def record_send(self, *, academy_id, parent_id, step, at, fields):
        record = self.records[(academy_id, parent_id)]
        record.sends = [*record.sends, type("S", (), {"step": step, "at": at, "fields": fields})()]

    async def close(self, *, academy_id, parent_id):
        record = self.records.get((academy_id, parent_id))
        if record:
            record.closed_at = datetime.now(UTC)


@dataclass
class _Outcome:
    ok: bool
    suppressed: bool = False
    failed_reason: str | None = None
    provider_message_id: str | None = None


class _FakeSender:
    def __init__(self, outcome):
        self.outcome = outcome
        self.sends = []

    async def send(self, **kwargs):
        self.sends.append(kwargs)
        return self.outcome


@pytest.mark.asyncio
async def test_new_gap_creates_record_but_does_not_send_before_day_7():
    parent = ParentFacts(display_name="A", phone=None, email_confirmed_at=None)
    child = ChildFacts(student_id="s1", full_name="Kid", date_of_birth=None)
    family = _Family("p1", "p1@example.com", parent, [child])
    repo = _FakeNudgeRepo()
    sender = _FakeSender(_Outcome(ok=True))
    use_case = SendProfileNudges(
        families=_FakeFamilyProvider([family]), records=repo, sender=sender
    )
    result = await use_case.execute(academy_id="a1", now=datetime.now(UTC))
    assert result.sent == 0
    assert repo.records[("a1", "p1")] is not None


@pytest.mark.asyncio
async def test_sends_step_1_at_day_7():
    parent = ParentFacts(display_name="A", phone=None, email_confirmed_at=None)
    child = ChildFacts(student_id="s1", full_name="Kid", date_of_birth=None)
    family = _Family("p1", "p1@example.com", parent, [child])
    repo = _FakeNudgeRepo()
    now = datetime.now(UTC)
    repo.records[("a1", "p1")] = type(
        "R", (), {"first_gap_seen_at": now - timedelta(days=7), "sends": [], "closed_at": None}
    )()
    sender = _FakeSender(_Outcome(ok=True, provider_message_id="m1"))
    use_case = SendProfileNudges(
        families=_FakeFamilyProvider([family]), records=repo, sender=sender
    )
    result = await use_case.execute(academy_id="a1", now=now)
    assert result.sent == 1
    assert len(sender.sends) == 1


@pytest.mark.asyncio
async def test_closed_gap_stops_nudging():
    parent = ParentFacts(display_name="A", phone="555", email_confirmed_at=datetime.now(UTC))
    child = ChildFacts(
        student_id="s1",
        full_name="Kid",
        date_of_birth="2015-01-01",
        emergency_contact_name="X",
        emergency_contact_phone="555",
        medical_notes="none",
    )
    family = _Family("p1", "p1@example.com", parent, [child])
    repo = _FakeNudgeRepo()
    now = datetime.now(UTC)
    repo.records[("a1", "p1")] = type(
        "R", (), {"first_gap_seen_at": now - timedelta(days=30), "sends": [], "closed_at": None}
    )()
    sender = _FakeSender(_Outcome(ok=True))
    use_case = SendProfileNudges(
        families=_FakeFamilyProvider([family]), records=repo, sender=sender
    )
    result = await use_case.execute(academy_id="a1", now=now)
    assert result.closed == 1
    assert result.sent == 0
    assert repo.records[("a1", "p1")].closed_at is not None
```

- [ ] Run it (expect failure — module doesn't exist):
  `cd backend && .venv/bin/pytest v2/tests/application/test_send_profile_nudges.py -q`

- [ ] Minimal implementation:

```python
# backend/v2/contexts/communications/application/profile_nudge_renderer.py
"""Renders one profile-nudge step email (spec §5): every missing field
across all children, why it matters, a deep link to /parent/profile."""

from __future__ import annotations

import html

from backend.v2.contexts.communications.application.unsubscribe_footer import (
    render_unsubscribe_footer,
)

_WHY = {
    "display_name": "so we know what to call you",
    "phone": "so we can reach you about your child's classes",
    "email_confirmed": "so account and billing emails reach you",
    "full_name": "so your child's roster entry is correct",
    "date_of_birth": "for birthday notes and correct age-group placement",
    "emergency_contact_name": "for your child's safety",
    "emergency_contact_phone": "for your child's safety",
    "medical_notes": "so coaches know about any conditions or allergies",
}

_LABELS = {
    "display_name": "your name",
    "phone": "your phone number",
    "email_confirmed": "email confirmation",
    "full_name": "child's name",
    "date_of_birth": "child's date of birth",
    "emergency_contact_name": "emergency contact name",
    "emergency_contact_phone": "emergency contact phone",
    "medical_notes": "medical notes",
}


def render_profile_nudge(
    step: int,
    *,
    parent_name: str | None,
    gap_labels: list[str],
    deep_link: str,
    unsubscribe_url: str | None,
) -> tuple[str, str]:
    greeting = f"Hi {html.escape(parent_name)}," if parent_name else "Hi there,"
    subject = "A couple of details we're still missing"
    items = "".join(
        f'<li>{html.escape(_LABELS.get(key, key))} — {html.escape(_WHY.get(key, ""))}</li>'
        for key in gap_labels
    )
    body = (
        f'<p style="margin:0 0 12px;">{greeting}</p>'
        f'<p style="margin:0 0 12px;">We are still missing a few details for your family:</p>'
        f'<ul style="margin:0 0 16px;">{items}</ul>'
        f'<p style="margin:0 0 16px;">'
        f'<a href="{html.escape(deep_link, quote=True)}">Update your profile</a></p>'
    )
    return subject, body + render_unsubscribe_footer(unsubscribe_url)
```

```python
# backend/v2/contexts/enrollment/application/use_cases/family_profiles_for_nudges.py
"""Enrollment/identity-joined query for profile-nudge families (spec §5):
every parent with >=1 active|held|paused student, with ParentFacts and every
child's ChildFacts. Wired into communications as the duck-typed
FamilyProfileProvider so communications never imports enrollment/identity
directly (ADR-0005)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from backend.v2.shared.profile.completeness import ChildFacts, ParentFacts


@dataclass(frozen=True)
class NudgeFamily:
    parent_id: str
    parent_email: str | None
    parent: ParentFacts
    children: list[ChildFacts]


class NudgeFamiliesRepo(Protocol):
    async def list_active_families(self, academy_id: str) -> list[NudgeFamily]: ...


@dataclass
class FamilyProfilesForNudgesQuery:
    repo: NudgeFamiliesRepo

    async def families_with_active_students(self, academy_id: str) -> list[NudgeFamily]:
        return await self.repo.list_active_families(academy_id)
```
  `list_active_families` is a new cross-repo query. It must join `students`
  (`status`-carrying enrollments in `active|held|paused`) with the parent's
  identity-context user record for `display_name`/`phone`/`email_confirmed_at`/
  `email`. Read `mongo_student_repo.py`'s existing `AdminStudentParentSummary`
  construction (imported at the top of that file) and the identity context's
  user-lookup repo (`mongo_academy_repo.py`'s sibling user repo — search
  `v2/contexts/identity/infrastructure` for the users collection accessor)
  before writing this repo's Mongo implementation, so it reuses the same
  join idiom rather than inventing a new cross-collection read.

```python
# backend/v2/contexts/communications/application/use_cases/send_profile_nudges.py
"""SendProfileNudges use case (2026-09-10 birthdays spec §5).

Daily. For each parent with >=1 active/held/paused student: compute
ProfileGaps. Empty -> close any open record. Non-empty and no record -> open
one, first_gap_seen_at = now (no send yet — a brand-new family gets no nudge
the day they register). Non-empty and a record exists -> ask
next_nudge_step; send and record if due.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from backend.v2.contexts.communications.application.profile_nudge_renderer import (
    render_profile_nudge,
)
from backend.v2.contexts.communications.application.ports import (
    AcademySlugLookup,
    EmailSendPort,
    ResolvedRecipient,
)
from backend.v2.contexts.communications.application.unsubscribe_token import (
    UnsubscribeLinkBuilder,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.shared.profile.completeness import evaluate
from backend.v2.shared.profile.nudge_schedule import next_nudge_step
from backend.v2.shared.tenancy.academy_url import academy_frontend_url

#: Path only — joined onto the recipient academy's own frontend origin below.
#: A bare "/parent/profile" in an e-mail is a dead link; and the origin must be
#: the academy's subdomain (same rule as the unsubscribe link, see
#: `UnsubscribeLinkBuilder`'s docstring), because TenantResolver reads the
#: tenant from the host's first label.
_PROFILE_PATH = "/parent/profile"


class FamilyProfileProvider(Protocol):
    async def families_with_active_students(self, academy_id: str) -> list[Any]: ...


class NudgeRecords(Protocol):
    async def get(self, *, academy_id: str, parent_id: str) -> Any | None: ...
    async def create(self, *, academy_id: str, parent_id: str, first_gap_seen_at: datetime) -> Any: ...
    async def record_send(
        self, *, academy_id: str, parent_id: str, step: int, at: datetime, fields: list[str]
    ) -> None: ...
    async def close(self, *, academy_id: str, parent_id: str) -> None: ...


@dataclass(frozen=True, slots=True)
class SendProfileNudgesResult:
    total_families: int = 0
    closed: int = 0
    sent: int = 0
    failed: int = 0


def _all_gap_labels(gaps: Any) -> list[str]:
    """Flatten parent gaps + the union of every child's gaps.

    NOTE (spec §5 fidelity): this deliberately de-duplicates across children,
    so a family with two children each missing a DOB sees "child's date of
    birth" ONCE and with no name attached. That is fine for a one-child
    family and misleading for a multi-child one. If the owner wants the child
    named, the renderer needs `(child_name, gap_key)` pairs, not a flat key
    list — `evaluate()` already returns `children: dict[student_id, list[str]]`,
    and `NudgeFamily.children` carries `full_name`, so the data is there.
    Decide before writing the renderer; do not ship the flat list and call it
    "every missing field across all children" if the academy is multi-child.
    """
    labels = list(gaps.parent)
    for child_gaps in gaps.children.values():
        for label in child_gaps:
            if label not in labels:
                labels.append(label)
    return labels


@dataclass
class SendProfileNudges:
    families: FamilyProfileProvider
    records: NudgeRecords
    sender: EmailSendPort
    # Spec §5 requires an honoured unsubscribe; the footer is only a real
    # opt-out when it carries a real link. Degrades to the portal-pointer
    # fallback (never a dead link) when the secret/frontend_url is unset.
    unsubscribe_links: UnsubscribeLinkBuilder | None = None
    academy_slugs: AcademySlugLookup | None = None
    frontend_url: str | None = None

    async def _academy_slug(self, academy_id: str) -> str | None:
        if self.academy_slugs is None:
            return None
        try:
            return await self.academy_slugs.slug_for(academy_id)
        except Exception:
            return None

    async def execute(self, *, academy_id: str, now: datetime | None = None) -> SendProfileNudgesResult:
        moment = now or datetime.now(UTC)
        academy_slug = await self._academy_slug(academy_id)
        base = academy_frontend_url(
            frontend_url=self.frontend_url, academy_slug=academy_slug
        )
        deep_link = f"{base}{_PROFILE_PATH}" if base else _PROFILE_PATH
        families = await self.families.families_with_active_students(academy_id)
        total = closed = sent = failed = 0
        for family in families:
            total += 1
            gaps = evaluate(family.parent, family.children)
            if gaps.is_complete:
                existing = await self.records.get(academy_id=academy_id, parent_id=family.parent_id)
                if existing and existing.closed_at is None:
                    await self.records.close(academy_id=academy_id, parent_id=family.parent_id)
                    closed += 1
                continue

            record = await self.records.get(academy_id=academy_id, parent_id=family.parent_id)
            if record is None:
                await self.records.create(
                    academy_id=academy_id, parent_id=family.parent_id, first_gap_seen_at=moment
                )
                continue  # brand-new gap: no send this run (spec §5)

            step = next_nudge_step(record.first_gap_seen_at, record.sends, moment)
            if step is None:
                continue

            if not family.parent_email:
                failed += 1
                continue

            gap_labels = _all_gap_labels(gaps)
            unsubscribe_url = (
                self.unsubscribe_links.build(
                    academy_id=academy_id,
                    user_id=family.parent_id,
                    academy_slug=academy_slug,
                )
                if self.unsubscribe_links
                else None
            )
            subject, body = render_profile_nudge(
                step,
                parent_name=family.parent.display_name,
                gap_labels=gap_labels,
                deep_link=deep_link,
                unsubscribe_url=unsubscribe_url,
            )
            outcome = await self.sender.send(
                recipient=ResolvedRecipient(
                    user_id=family.parent_id, email=family.parent_email, display_name=family.parent.display_name
                ),
                subject=subject,
                body=body,
                category=EmailCategory.NOTIFICATION,
            )
            if outcome.ok:
                await self.records.record_send(
                    academy_id=academy_id,
                    parent_id=family.parent_id,
                    step=step,
                    at=moment,
                    fields=gap_labels,
                )
                sent += 1
            else:
                failed += 1
        return SendProfileNudgesResult(total_families=total, closed=closed, sent=sent, failed=failed)
```

- [ ] Run the unit tests (expect PASS):
  `cd backend && .venv/bin/pytest v2/tests/application/test_send_profile_nudges.py -q`

- [ ] Composition — create `backend/v2/composition/profile_nudges.py`:

```python
# backend/v2/composition/profile_nudges.py
"""Wires SendProfileNudges (2026-09-10 birthdays spec §5). Its own module,
never composition/admin.py."""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.composition.digests import (
    _AcademySlugLookup,
    _build_email_sender,
    compose_unsubscribe_link_builder,
)
from backend.v2.contexts.communications.application.use_cases.send_profile_nudges import (
    SendProfileNudges,
)
from backend.v2.contexts.communications.infrastructure.mongo_profile_nudge_repo import (
    MongoProfileNudgeRepository,
)
from backend.v2.contexts.enrollment.application.use_cases.family_profiles_for_nudges import (
    FamilyProfilesForNudgesQuery,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
    MongoAcademyRepository,
)
from backend.v2.shared.config import get_settings


def compose_send_profile_nudges(db: AsyncIOMotorDatabase[Any]) -> SendProfileNudges:
    settings = get_settings()
    return SendProfileNudges(
        families=FamilyProfilesForNudgesQuery(repo=MongoStudentRepository(db)),
        records=MongoProfileNudgeRepository(db),
        sender=_build_email_sender(settings, db),
        unsubscribe_links=compose_unsubscribe_link_builder(settings),
        academy_slugs=_AcademySlugLookup(MongoAcademyRepository(db)),
        frontend_url=settings.frontend_url,
    )
```
  Same rule as Task 6: `_build_email_sender` is the only sanctioned sender
  factory (`tests/structural/test_email_sender_construction.py`); there is no
  `compose_email_send_port`.
  (`MongoStudentRepository` implementing `NudgeFamiliesRepo.list_active_families`
  is added alongside `find_by_birth_month_days` from Task 6 — confirm both new
  methods land on the same repo class without exceeding any file-level line
  guidance the codebase enforces via CI, by checking for a line-count test
  on `mongo_student_repo.py` the way `composition/admin.py`'s 4500 cap is
  enforced — search for `mongo_student_repo` in `v2/tests/structural/` before
  assuming none exists.)

- [ ] Scheduler wiring in `main.py`, following the exact `SCHEDULED_JOB_MONITORS` / `_run_leased_job` / `scheduler.add_job` triple from Task 6:

```python
    "send_profile_nudges": {
        "schedule": {"type": "crontab", "value": "0 8 * * *"},
        "checkin_margin": 30,
        "max_runtime": 30,
    },
```

```python
    app.state.send_profile_nudges = compose_send_profile_nudges(db)

    async def _send_profile_nudges() -> None:
        await _run_leased_job(
            "send_profile_nudges", timedelta(minutes=5), _send_profile_nudges_body
        )

    async def _send_profile_nudges_body() -> None:
        totals = {"academy_count": 0, "sent": 0, "closed": 0, "failed": 0}
        for academy_id in await _scheduler_academy_ids(
            MongoAcademyRepository(db),
            runtime_academy_id,
        ):
            with tenant_scope(academy_id):
                result = await app.state.send_profile_nudges.execute(
                    academy_id=academy_id, now=datetime.now(scheduler.timezone)
                )
            totals["academy_count"] += 1
            totals["sent"] += result.sent
            totals["closed"] += result.closed
            totals["failed"] += result.failed
        if totals["sent"] or totals["closed"] or totals["failed"]:
            log.info("profile_nudges_sent", extra=totals)
```

```python
    scheduler.add_job(
        _send_profile_nudges,
        "cron",
        hour=8,
        minute=0,
        id="send_profile_nudges",
        replace_existing=True,
        max_instances=1,
    )
```

- [ ] Add `"send_profile_nudges": timedelta(hours=26)` to `JOB_STALE_AFTER` in `ops_digest.py`, next to `send_birthday_notes` from Task 6.

- [ ] Bump `assert len(registered) == 14` to `15` in `backend/v2/tests/unit/test_scheduler_academies.py` (Task 6 took it 13 → 14). Same file also pins that every `_run_leased_job("<id>")` literal matches a registered job id, so keep the wrapper name and the `add_job(id=...)` string identical.

- [ ] Add `send_profile_nudges.py` to `backend/v2/tests/structural/test_email_category_threading.py`'s sweep, alongside `send_birthday_notes.py` from Task 6.

- [ ] Run the scheduler + structural + boot-time smoke tests:
  `cd backend && .venv/bin/pytest v2/tests/unit/test_scheduler_academies.py v2/tests/structural -q && .venv/bin/python -c "import backend.v2.main"`

- [ ] Commit:
  `git add backend/v2/contexts/enrollment/application/use_cases/family_profiles_for_nudges.py backend/v2/contexts/communications/application/profile_nudge_renderer.py backend/v2/contexts/communications/application/use_cases/send_profile_nudges.py backend/v2/composition/profile_nudges.py backend/v2/main.py backend/v2/shared/observability/ops_digest.py backend/v2/tests/application/test_send_profile_nudges.py backend/v2/tests/unit/test_scheduler_academies.py backend/v2/tests/structural/test_email_category_threading.py`
  Message: `feat(communications): send three-step profile-completion nudges`

## Task 9: Staff digest "Birthdays this week" — coach digest (Mondays)

**Files:**
- Modify: `backend/v2/contexts/communications/application/digest_renderer.py` (`render_coach_digest`, line 83 — verified)
- Modify: `backend/v2/contexts/communications/application/use_cases/send_coach_daily_digest.py` (new optional `birthdays` provider field + `_birthdays` degrade helper + the `render_coach_digest(...)` call at line 199)
- Modify: `backend/v2/composition/digests.py` (`_build_digest_parts` ~line 434 / `compose_send_coach_daily_digest` ~line 446 — inject the provider)
- Create: `backend/v2/contexts/enrollment/application/use_cases/birthdays_this_week_for_coach.py`
- Test: `backend/v2/tests/unit/test_digest_renderer_birthdays.py`
- Test: `backend/v2/tests/application/test_send_coach_daily_digest.py` (extend)

**`main.py` is NOT modified by this task.** An earlier draft pointed at "the coach-digest job body near line 1296-1312" and asked it to resolve birthdays per coach; both are wrong. The coach-digest body is at main.py lines 1043-1110, it does not loop coaches (`SendCoachDailyDigest.execute` does, at lines 161-199), and it already passes the only thing needed — `digest_date`. The Monday test therefore belongs **inside** the use case, keyed on `command.digest_date.weekday() == 0`, which is also what the unit test below asserts. Keeping it there means no scheduler-timezone reasoning leaks into the use case and no per-coach loop is duplicated in `main.py`.

**Interfaces:**
- Consumes: `birth_month_day_for_date`/`is_feb_28_in_non_leap_year` (Task 1)
- Produces: `render_coach_digest(..., birthdays_this_week: Sequence[UpcomingBirthday] = ())`; a card rendered only when non-empty.

- [ ] Read `render_coach_digest`'s full body (past line 110, already partially read) to find where existing cards are concatenated, so the new block is inserted in the same list-of-html-fragments pattern.

- [ ] Write the failing renderer test:

```python
# backend/v2/tests/unit/test_digest_renderer_birthdays.py
from types import SimpleNamespace

from backend.v2.contexts.communications.application.digest_renderer import (
    UpcomingBirthday,
    render_coach_digest,
)


def _plan():
    return SimpleNamespace(date="2026-06-15", program_name="Badminton", sessions=[])


def test_no_block_when_no_birthdays():
    _, body = render_coach_digest(_plan())
    assert "Birthdays this week" not in body


def test_block_lists_student_name_and_day():
    birthdays = [
        UpcomingBirthday(
            student_name="Aanya K",
            turning=9,
            on_date="2026-06-17",
            class_names=("U10 Badminton",),
            parent_name="Priya K",
            enrolled=True,
        )
    ]
    _, body = render_coach_digest(_plan(), birthdays_this_week=birthdays)
    assert "Birthdays this week" in body
    assert "Aanya K" in body
    assert "U10 Badminton" in body


def test_withdrawn_student_shows_left_on_note():
    birthdays = [
        UpcomingBirthday(
            student_name="Ravi P",
            turning=8,
            on_date="2026-06-18",
            class_names=(),
            parent_name="Sunita P",
            enrolled=False,
            left_on="2026-04-01",
        )
    ]
    _, body = render_coach_digest(_plan(), birthdays_this_week=birthdays)
    assert "left on" in body.lower()
```

- [ ] Run it (expect failure — `UpcomingBirthday` doesn't exist / param unsupported):
  `cd backend && .venv/bin/pytest v2/tests/unit/test_digest_renderer_birthdays.py -q`

- [ ] Minimal implementation. Add near the top of `digest_renderer.py` (alongside `ExpectedAbsence`):

```python
@dataclass(frozen=True, slots=True)
class UpcomingBirthday:
    student_name: str
    turning: int
    on_date: str
    class_names: tuple[str, ...] = ()
    parent_name: str | None = None
    enrolled: bool = True
    left_on: str | None = None


def _render_birthdays_block(birthdays: Sequence[UpcomingBirthday]) -> str:
    if not birthdays:
        return ""
    rows = []
    for b in birthdays:
        classes = ", ".join(html.escape(c) for c in b.class_names) or "not enrolled"
        left_note = (
            f' <span style="color:{_TEXT_MUTED};">(left on {html.escape(b.left_on)})</span>'
            if not b.enrolled and b.left_on
            else ""
        )
        parent = f" — parent: {html.escape(b.parent_name)}" if b.parent_name else ""
        rows.append(
            f'<li>{html.escape(b.student_name)} turns {b.turning} on '
            f'{html.escape(b.on_date)} — {classes}{parent}{left_note}</li>'
        )
    return (
        f'<h3 style="color:{_TEXT_PRIMARY};margin:24px 0 8px;">Birthdays this week</h3>'
        f'<ul style="margin:0 0 16px;">{"".join(rows)}</ul>'
    )
```
  then thread `birthdays_this_week: Sequence[UpcomingBirthday] = ()` into
  `render_coach_digest`'s signature and splice
  `_render_birthdays_block(birthdays_this_week)` into the returned body at
  the same point the existing `expected_absences`/`whatsapp_groups` blocks
  are spliced in (read that exact insertion point in the function body
  before editing).

- [ ] Run it (expect PASS):
  `cd backend && .venv/bin/pytest v2/tests/unit/test_digest_renderer_birthdays.py -q`

- [ ] Create the enrollment-side query (structurally identical to Task 6's `BirthdayStudentsTodayQuery` but for a 7-day window and coach-scoped, admins/owners see all per spec §4.1):

```python
# backend/v2/contexts/enrollment/application/use_cases/birthdays_this_week_for_coach.py
"""Coach- and admin-scoped "birthdays this week" query (spec §4.1): every
student (any status) whose birth_month_day falls in the next 7 days,
including the Feb-29-in-non-leap-year fold from Task 1. Coaches see only
their classes' students; admins/owners see all — filtered by the caller
passing coach_id=None for the admin case."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

from backend.v2.shared.profile.birth_month_day import (
    birth_month_day_for_date,
    is_feb_28_in_non_leap_year,
)


@dataclass(frozen=True)
class WeeklyBirthday:
    student_name: str
    turning: int
    on_date: str
    class_names: tuple[str, ...]
    parent_name: str | None
    enrolled: bool
    left_on: str | None


class WeeklyBirthdaysRepo(Protocol):
    async def find_birthdays_in_window(
        self, academy_id: str, month_days: tuple[str, ...], *, coach_id: str | None
    ) -> list[WeeklyBirthday]: ...


@dataclass
class BirthdaysThisWeekQuery:
    repo: WeeklyBirthdaysRepo

    async def for_week_of(
        self, academy_id: str, week_start: date, *, coach_id: str | None = None
    ) -> list[WeeklyBirthday]:
        month_days: list[str] = []
        for offset in range(7):
            on_date = week_start + timedelta(days=offset)
            month_days.append(birth_month_day_for_date(on_date))
            if is_feb_28_in_non_leap_year(on_date):
                month_days.append("02-29")
        return await self.repo.find_birthdays_in_window(
            academy_id, tuple(month_days), coach_id=coach_id
        )
```
  `find_birthdays_in_window` is a new `MongoStudentRepository` method — same
  caveat as Task 6/8: read the file's existing coach-scoping query (search
  `mongo_student_repo.py` for how it already restricts results to a coach's
  own classes, likely reused from the roster query) before adding it, so
  coach-scoping is not reinvented.

- [ ] Wire it into `SendCoachDailyDigest` (`send_coach_daily_digest.py`) — **not** into `main.py`:
  1. Add an optional field `birthdays: BirthdaysThisWeekProvider | None = None`, mirroring the existing optional `group_links` / `expected_absences` fields.
  2. Add a `_birthdays(coach_id, on_date)` helper copying the `_absences` / `_groups` try/except-degrade shape verbatim (lines 130-147, verified): `None` provider → `()`, any exception → `()`. A birthday lookup must never cost a coach their teaching plan.
  3. In `execute`, resolve the week's list **once per run** before the coach loop (like `brand` and `academy_slug` at lines 162-164), guarded by `command.digest_date.weekday() == 0`; per-coach scoping is the provider's `coach_id` argument inside the loop.
  4. Pass `birthdays_this_week=await self._birthdays(coach.user_id, command.digest_date)` into the existing `render_coach_digest(...)` call at line 199.

- [ ] Inject the provider in `composition/digests.py`: add it to the `_DigestParts` dataclass built by `_build_digest_parts` (~line 434, next to `expected_absences=_CoachExpectedAbsenceProvider(...)`) and pass it through in `compose_send_coach_daily_digest` (~line 446). Leave `compose_send_coach_digest_test` (~line 461) alone unless the admin test-send should also show birthdays — it currently omits `expected_absences` too, so omitting is the consistent choice.

- [ ] Add `SendCoachDailyDigest` tests in `backend/v2/tests/application/test_send_coach_daily_digest.py` asserting: (a) on a non-Monday `command.digest_date`, the renderer receives an empty `birthdays_this_week`; (b) on a Monday, the provider's result is passed through; (c) a provider that raises still sends the plan with an empty block.

- [ ] Run the coach-digest test suite:
  `cd backend && .venv/bin/pytest v2/tests/unit/test_digest_renderer_birthdays.py v2/tests/application/test_send_coach_daily_digest.py -q`

- [ ] Commit:
  `git add backend/v2/contexts/communications/application/digest_renderer.py backend/v2/contexts/communications/application/use_cases/send_coach_daily_digest.py backend/v2/contexts/enrollment/application/use_cases/birthdays_this_week_for_coach.py backend/v2/composition/digests.py backend/v2/tests/unit/test_digest_renderer_birthdays.py backend/v2/tests/application/test_send_coach_daily_digest.py`
  Message: `feat(digests): add weekly birthdays block to the Monday coach digest`

## Task 10: Staff digest "Birthdays this week" — admin ops digest

**Files:**
- Modify: `backend/v2/shared/observability/ops_digest.py` (`OpsDigestSnapshot`, `collect_ops_digest`, `render_ops_digest`)
- Test: `backend/v2/tests/contract/test_ops_digest_birthdays.py`

**Interfaces:**
- Produces: `OpsDigestSnapshot.birthdays_this_week: list[dict]`; `render_ops_digest` includes a "Birthdays this week" section per academy when non-empty.
- Verified shapes: `OpsDigestSnapshot` is a frozen dataclass whose only required fields are `generated_at` and `lookback_hours` (line 152); `collect_ops_digest(db, *, now=None, lookback=LOOKBACK)` (line 332); `render_ops_digest(snapshot) -> tuple[str, str]` (line 411). `has_attention_items` deliberately flags only *actionable* signals — birthdays are informational, so do **not** add `birthdays_this_week` to it, or every academy with a birthday this week raises a false ops alert.

**Spec §4.1 coverage gap in the sketch below:** §4.1 asks the staff digest for "student name, age turning, day, class(es) or 'not enrolled', parent name", with a "left on `<date>`" note for departed students. The probe below returns only `student_name` and the raw `birth_month_day` — no age (needs the full DOB), no calendar day, no classes, no parent, no departure note. Either enrich the projection (`date_of_birth`, `parent_id`, plus a lookup into `enrollments`/`sessions`/`users`) so the admin digest carries the same columns the coach digest's `UpcomingBirthday` does, or record explicitly that the admin ops digest ships a name-only list in v1 and the coach digest carries the full row. Do not ship the sketch as-is and tick §4.1 as covered.

- [ ] Read `collect_ops_digest`'s full body (lines 332-386, already partially read) and `render_ops_digest` (from line 411) in full before editing, since both are single functions this task extends rather than files this task creates.

- [ ] Write the failing test:

```python
# backend/v2/tests/contract/test_ops_digest_birthdays.py
from datetime import UTC, datetime

import pytest

from backend.v2.shared.observability.ops_digest import collect_ops_digest, render_ops_digest


@pytest.mark.asyncio
async def test_snapshot_includes_birthdays_this_week(db):
    await db["students"].insert_many(
        [
            {
                "student_id": "s1",
                "academy_id": "a1",
                "full_name": "Aanya K",
                "birth_month_day": "06-17",
                "is_deleted": False,
            }
        ]
    )
    now = datetime(2026, 6, 15, tzinfo=UTC)  # week of June 15-21
    snapshot = await collect_ops_digest(db, now=now)
    assert any(b["student_name"] == "Aanya K" for b in snapshot.birthdays_this_week)


def test_render_includes_birthdays_section_when_present():
    from backend.v2.shared.observability.ops_digest import OpsDigestSnapshot

    snapshot = OpsDigestSnapshot(
        generated_at=datetime.now(UTC),
        lookback_hours=24,
        birthdays_this_week=[
            {"academy_id": "a1", "student_name": "Aanya K", "on_date": "2026-06-17"}
        ],
    )
    _, html = render_ops_digest(snapshot)
    assert "Birthdays this week" in html
    assert "Aanya K" in html
```

- [ ] Run it (expect failure — `birthdays_this_week` field doesn't exist):
  `cd backend && .venv/bin/pytest v2/tests/contract/test_ops_digest_birthdays.py -q`

- [ ] Minimal implementation. Add to `OpsDigestSnapshot`:

```python
    birthdays_this_week: list[dict[str, Any]] = field(default_factory=list)
```

  Add a collection-name-driven helper next to `_dead_letter_counts` (this module's documented cross-tenant exception, per its module docstring lines 8-12):

```python
async def _birthdays_this_week(db: AsyncIOMotorDatabase[Any], now: datetime) -> list[dict[str, Any]]:
    """Cross-tenant "birthdays this week" for the admin ops digest (spec
    §4.1). Reads students/enrollments by collection name, like every other
    probe in this module — see the module docstring for why."""
    # `timedelta` is already imported at module scope (JOB_STALE_AFTER);
    # import birth_month_day helpers at module scope too — `shared` may import
    # `shared`, so there is no cycle to dodge with a function-local import.
    month_days: set[str] = set()
    for offset in range(7):
        on_date = (now + timedelta(days=offset)).date()
        month_days.add(birth_month_day_for_date(on_date))
        if is_feb_28_in_non_leap_year(on_date):
            month_days.add("02-29")
    cursor = db["students"].find(
        {"birth_month_day": {"$in": sorted(month_days)}, "is_deleted": {"$ne": True}},
        projection={"student_id": 1, "academy_id": 1, "full_name": 1, "birth_month_day": 1},
    )
    results: list[dict[str, Any]] = []
    async for doc in cursor:
        results.append(
            {
                "academy_id": doc["academy_id"],
                "student_name": doc.get("full_name", ""),
                "on_date": doc.get("birth_month_day", ""),
            }
        )
    return results
```

  Wire it into `collect_ops_digest` (append the call alongside the other
  `await _xxx(...)` calls already there, assigning into the snapshot kwargs)
  and add a `_render_birthdays_section(snapshot.birthdays_this_week)` call
  inside `render_ops_digest`, following the exact HTML-fragment-list pattern
  the function already uses for its other sections (visible at line 476 in
  the excerpt already read: `f"<h3>Scheduled jobs</h3>..."`).

- [ ] Run it (expect PASS):
  `cd backend && .venv/bin/pytest v2/tests/contract/test_ops_digest_birthdays.py -q`

- [ ] **Do NOT add `students` to any collection list in `v2/tests/test_no_raw_tenant_mongo_access.py`.** Verified: that file has no per-module collection list. `students` is in `TENANT_OWNED_COLLECTIONS`, and moving it to `GLOBAL_COLLECTIONS` would blanket-exempt every raw student query in the codebase — the opposite of what the ratchet is for. `shared/observability/ops_digest.py` is already a **whole-file** entry in `APPROVED_CROSS_TENANT_EXCEPTIONS`, so this new probe is allowed as-is. The only change to make there is to widen that entry's **rationale string** to name `students` alongside the collections it already lists, keeping the "cross-tenant" and "read-only" words the two guard tests assert on. Both remain true: this probe is a projection-only `find`.

- [ ] Commit:
  `git add backend/v2/shared/observability/ops_digest.py backend/v2/tests/contract/test_ops_digest_birthdays.py`
  (add the test_no_raw_tenant_mongo_access.py change here too if made)
  Message: `feat(ops-digest): add birthdays-this-week section to the admin digest`

## Task 11: Admin visibility — last nudge date

**Files (only if the OPEN QUESTION below resolves to (b)):**
- Modify: `backend/v2/contexts/billing/application/use_cases/billing_setup_registration.py` — `BillingSetupRow` is the row model the Families list renders after plan 2 lands; `last_nudge_sent_at` goes there, next to `login_state`.
- Modify: `backend/v2/composition/families.py` — plan 2 moves the Families-list wiring (`ListBillingSetup` + its `_BillingSetup*` adapters) here, out of `composition/admin.py`. Any new lookup adapter for this field goes here too, **never** in `composition/admin.py`.
- Modify: `backend/v2/interfaces/admin/billing_setup_routes.py` — `BillingSetupRowDto` passthrough.
- Modify: `frontend/lib/api/admin.ts` (`BillingSetupRow`) and `frontend/app/(admin)/admin/families/page.tsx` — the Families list component's final path after plan 2; plan 2 does not move or rename it.
- Test: `backend/v2/tests/contract/test_admin_directory_last_nudge_date.py`

**Interfaces:**
- Produces: `last_nudge_sent_at: datetime | None` on `BillingSetupRow` — the row model behind `/admin/families`, which is what any "Needs attention" ordering would sort on.
- Explicitly unchanged: the `missing=` filter on `GET /admin/students` (verified `directory_routes.py` lines 322-330, backed by `CHILD_REQUIRED`/`child_gaps` in `mongo_student_repo.py`). Spec §5 says it stays as-is — do not touch it.

> **OPEN QUESTION (owner): who owns "profile incomplete" + "last nudge date" on the Families list?**
> Verified 2026-09-10 against the actual files, and the earlier draft of this
> task guessed wrong in both directions:
> * Spec 3 §5 says the Families "Needs attention" sort *(spec 2)* "includes
>   'profile incomplete' and shows the last nudge date".
> * Spec 2 (`2026-09-10-families-directory-consolidation-design.md`, line 39)
>   defines that sort as "outstanding-balance and never-invited rows first" —
>   it says nothing about profile completeness or nudges.
> * `docs/superpowers/plans/2026-09-10-families-directory-consolidation.md`
>   contains **zero** occurrences of "nudge", "profile incomplete" or
>   "attention". It does not build this.
>
> * Neither does spec 2's plan build a *sort* at all: `/admin/families` after
>   plan 2 has a registration-state filter, a `login_state` filter and a
>   name/email/phone/child search, and `ListBillingSetup.execute` returns rows
>   in roster order. There is no "Needs attention" ordering in the code today
>   and none is added by any of these four plans — so this task cannot
>   "extend" one; it would have to create it.
>
> So the field is currently owned by nobody. The owner must pick one:
> **(a)** spec 2's plan absorbs it (this task becomes "nothing further — Task 3
> already creates `profile_nudges` with the right shape"); **(b)** this plan
> builds it, in which case it must land on `BillingSetupRow` and be wired in
> `composition/families.py` — the file spec 2's plan names as the Families-list
> wiring home — and **not** in `composition/admin.py`; or **(c)** it is cut from v1 and
> spec 3 §5's sentence is corrected, since the in-app banner and the existing
> `missing=` filter already give admins a "who is incomplete" answer.
>
> Until that is answered, **do not write code for this task.** Two plans
> independently adding a "profile incomplete" signal to the same list is the
> exact duplicate-read-model failure this note exists to prevent.

- [ ] Get the owner's answer to the OPEN QUESTION above and record it here.

- [ ] If (a) or (c): delete this task, tick nothing, and note in the release note that admin visibility of nudge history is deferred.

- [ ] If (b): write the failing contract test first. Fixtures are `db` and `acad` (there is no `mongo_db`/`academy_id` fixture). Target `ListBillingSetup` / `BillingSetupRow` (`backend/v2/contexts/billing/application/use_cases/billing_setup_registration.py`) wired through `composition/families.py` — the read model plan 2 leaves behind `/admin/families` — rather than adding a parallel one:

```python
# backend/v2/tests/contract/test_admin_directory_last_nudge_date.py
import pytest

from datetime import UTC, datetime


@pytest.mark.asyncio
async def test_family_summary_includes_last_nudge_sent_at(db, acad):
    await db["students"].insert_one(
        {"student_id": "s1", "academy_id": acad, "parent_id": "p1", "full_name": "Kid"}
    )
    await db["profile_nudges"].insert_one(
        {
            "academy_id": acad,
            "parent_id": "p1",
            "first_gap_seen_at": datetime(2026, 1, 1, tzinfo=UTC),
            "sends": [{"at": datetime(2026, 1, 8, tzinfo=UTC), "step": 1, "fields": ["phone"]}],
            "closed_at": None,
        }
    )
    # Call ListBillingSetup.execute(academy_id=acad) — the read model behind
    # /admin/families after plan 2 — and assert the BillingSetupRow for parent
    # p1 reports last_nudge_sent_at == 2026-01-08 (aware — normalise with
    # ensure_utc at the repo boundary, as in Task 3).
```

- [ ] If (b): implement, then commit:
  `git add <files touched>`
  Message: `feat(admin): surface last profile-nudge date for the Needs attention sort`

## Task 12: Release note

**Files:**
- Create: `docs/release-notes/2026-09-10-birthdays-and-profile-nudges.md`

- [ ] Write the release note. Verified against `scripts/dev/release_notes_check.py`: the gate finds a note by grepping every `docs/release-notes/*.md` for the literal string `PR: #<the real number>`, and requires exactly the three headings `## What changed`, `## Deploy notes`, `## Risk / rollback` with non-placeholder bodies. The house layout (see `docs/release-notes/2026-09-10-absence-notice-706.md`) puts the `PR:` line directly **under the title, before the first section** — not at the end. So:
  1. Write the note now with `PR: #TBD` under the title.
  2. **The gate WILL fail until the real number replaces it** — a literal `#<number>` or `#TBD` matches nothing. Amend the note with the real PR number as the first thing after opening the PR; this is a required step, not a nicety.

```markdown
# Birthdays and profile nudges

PR: #TBD  <!-- replace with the real number the moment the PR is opened -->

## What changed

- A daily `send_birthday_notes` job e-mails a "Happy birthday" note to the
  parent of every student turning a year older that day, for students with
  at least one active/held/paused enrollment. Off by default per academy
  (`birthday_emails_enabled`, Settings → Notifications) until an admin turns
  it on.
- A "Birthdays this week" block always appears in the Monday coach digest
  and the daily admin ops digest — including withdrawn students (with a
  "left on" note) and students with no DOB gap.
- A daily `send_profile_nudges` job e-mails parents with an incomplete
  profile (missing DOB, emergency contact, medical answer, or parent phone)
  up to three times — day 7, day 28, day 88 after the gap is first seen —
  then stops, or stops early the moment the gap closes.
- `students.date_of_birth` is now validated `YYYY-MM-DD` on the onboarding
  wizard's child-profile step (admin and parent edit paths already enforced
  this via typed `date` fields).
- New `students.birth_month_day` derived field (migration 0174, backfilled),
  `profile_nudges` collection (migration 0175) and `birthday_sends` claim
  collection (migration 0176).

## Deploy notes

- Prod runs with `V2_RUN_MIGRATIONS_ON_BOOT=false` (#629) — after this deploy,
  run migrations 0174, 0175 **and 0176** by hand via `run_pending_migrations`,
  the same way 0170-0172 were applied (0173 belongs to the departure-actions
  PR — `0173_withdrawal_notice_sends`, spec 1 — and must be applied before
  these three). 0176 builds the unique
  `birthday_sends (academy_id, student_id, digest_date)` index; skipping it
  leaves the birthday job leaning entirely on `digest_claim`'s
  insert-then-verify fallback, which is the configuration that produced the
  2026-09-02 hourly-digest resend incident. Until 0174 runs, no student has a
  `birth_month_day`, so the birthday job simply finds nobody — it cannot mail
  the wrong child.
- `birthday_emails_enabled` defaults to **off** for every academy. Per spec
  §2, do not enable it for an academy until the owner has confirmed the
  registration wording covers birthday emails as a use of the child's DOB —
  the staff digest block needs no such consent and is already live once this
  deploys.
- Two new scheduled jobs (`send_birthday_notes` at 07:30, `send_profile_nudges`
  at 08:00, scheduler-local) are added to `SCHEDULED_JOB_MONITORS` and
  `JOB_STALE_AFTER` — no action needed, but the first ops digest after
  deploy will show them freshly seeded (not stale).

## Risk / rollback

- Both new jobs are read-mostly and additive; the worst-case failure mode is
  "no email sent this tick", not incorrect billing or roster state — same
  failure class as the existing hold-reminder/digest jobs they're modeled
  on.
- `birth_month_day` backfill only writes a derived field; it never rewrites
  `date_of_birth` and is safe to re-run (idempotent `$set`).
- Rollback: revert the PR and stop the two new scheduler jobs on the next
  deploy. `birth_month_day` and `profile_nudges` are additive collections/
  fields and can be left in place — no destructive down-migration needed
  before rollback (data cleanup, if desired, can follow separately).

```

- [ ] After the PR is opened, replace `PR: #TBD` with the real number and amend the release-note commit. The Release Notes Gate stays red until then — this is a required follow-up step, not optional.

- [ ] Commit:
  `git add docs/release-notes/2026-09-10-birthdays-and-profile-nudges.md`
  Message: `docs(release-notes): add release note for birthdays and profile nudges`

## Self-review

| Spec section | Covered by |
|---|---|
| §1 Purpose (birthday notes + profile nudges) | Tasks 6, 8 |
| §2 Owner decisions — students only, all statuses, cadence, consent | Tasks 6 (audience filter), 8 (cadence via Task 4), 7 (default-off switch) |
| §3 Data — DOB validation, `birth_month_day`, `profile_nudges`, digest_claim key | Tasks 1, 2, 3, 5 |
| §4.1 Staff digest — coach Monday block, admin ops digest, withdrawn note, coach/admin scoping | Tasks 9, 10 — **partial**: Task 9 carries the full row (name, age, day, classes, parent, "left on"); Task 10's ops-digest probe as sketched returns name + `MM-DD` only. See the coverage note in Task 10 and either enrich it or record the reduction explicitly. |
| §4.2 Family email — job, audience, one email per student, unsubscribe, `birthday_emails_enabled` | Tasks 6, 7 |
| §5 Profile nudges — job, cadence, gap-closes-stops, deep link | Tasks 4, 8 |
| §5 Profile nudges — **admin visibility** (Families "Needs attention" + last nudge date) | Task 11 — **BLOCKED on an OPEN QUESTION**: spec 2's design and its plan do not build a "profile incomplete" signal, so this field is currently unowned. See the note in Task 11. |
| §2 Consent — owner confirms registration wording before the family email is enabled | Not a code task. Task 7 ships the switch **default-off**; the release note carries the "do not enable until the owner confirms" instruction. Enabling it is a human step this plan deliberately does not automate. |
| §6 Out of scope | Not built: parent birthdays, never-enrolled siblings, SMS/WhatsApp, DOB-driven age-group auto-placement — none appear in any task above. |
| §7 Testing — leap-day, nudge scheduling table, idempotency, migration test | Tasks 1 (leap day), 4 (scheduling table), 5/6/8 (idempotency), 2/3 (migration tests) |

**Deferred / explicitly out of scope (per spec §6, not gaps):**
- Parent birthdays and never-enrolled-sibling birthdays — spec explicitly excludes both; no task touches them.
- SMS/WhatsApp nudge channels — email only, per spec §2.
- Age-group auto-placement from DOB — spec §6 defers this to a later, separate change once DOBs are clean; this plan only makes DOBs clean (validation + backfill), it does not build placement logic.
- Task 11 (admin "Needs attention" surfacing) is **blocked**, not deferred. Verified 2026-09-10: spec 2's design defines its sort as outstanding-balance + never-invited only, and spec 2's plan never mentions nudges or profile completeness — so neither plan owns this field. The owner must choose an owner before anyone writes code; see the OPEN QUESTION in Task 11.

**Open questions (must be answered before the affected task runs):**
1. **Who owns "profile incomplete" + last nudge date on the Families list?** (Task 11 — blocks that task only; Tasks 1-10 and 12 are unaffected.)
2. **Does the admin ops digest need the full §4.1 row, or is a name-only list acceptable for v1?** (Task 10 — decides whether that probe joins `enrollments`/`sessions`/`users` or stays a one-collection projection.)
3. **Multi-child families: does the nudge email name which child each gap belongs to?** (Task 8's `_all_gap_labels` — the flat, de-duplicated key list reads correctly only for a one-child family.)
