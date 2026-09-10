# Birthdays and Profile Nudges Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wish every enrolled-or-was-enrolled child a birthday and nudge parents by email to close their profile gaps, without any admin doing it by hand.

**Architecture:** Two new daily scheduler jobs (`send_birthday_notes`, `send_profile_nudges`) plus a Monday-only extension to the existing `send_coach_daily_digests` job, all composed outside `composition/admin.py` (at its 4500-line cap) in new `composition/` modules that bridge the `enrollment`, `communications` and `identity` contexts the way `composition/absence_notifications.py` already does. Sends reuse the existing `digest_claim.claim_digest_send` idempotency primitive and the existing `GatedEmailSendPort` (unsubscribe + suppression gating on `EmailCategory.NOTIFICATION`); nudge *scheduling* (day 7/21/60) is new state in a dedicated `profile_nudges` collection because its cadence is not "once per day", unlike every other claim in this codebase.

**Tech Stack:** FastAPI/Pydantic v2, Motor (async Mongo), APScheduler (`AsyncIOScheduler` in `backend/v2/main.py`), pytest + pytest-asyncio, Next.js/TanStack Query for the one settings toggle.

## Global Constraints

- Vocabulary: enrollment statuses counted as "current" for both birthday and nudge eligibility are exactly `active`, `held`, `paused` — reuse `MongoEnrollmentRepository.departable_for_student` (`backend/v2/contexts/enrollment/infrastructure/mongo_enrollment_repo.py:94-102`), which already returns exactly this set.
- `students.birth_month_day` format is `"MM-DD"`, written whenever `date_of_birth` is set at any write path that mutates it (registration-approval upsert, admin/parent profile edit) — never backfilled lazily on read.
- Leap day: `birth_month_day` is stored as the DOB's true `"02-29"` and is never rewritten. The *query* that resolves "today's birthdays" additionally matches `"02-29"` when today is `"02-28"` in a non-leap year, per spec §7.
- Nudge steps: step 1 fires when `now >= first_gap_seen_at + 7 days`; step 2 fires when `now >= step1.sent_at + 21 days`; step 3 fires when `now >= step2.sent_at + 60 days`; there is no step 4. A brand-new gap (record just created this tick) never fires step 1 on the same tick.
- Nudge eligibility gate: a parent is only considered when at least one of their children has a current (`active|held|paused`) enrollment; gap *content* still lists every missing field across **all** the parent's children regardless of those children's own status.
- Family birthday email: one per student per year, `EmailCategory.NOTIFICATION`, claimed via `digest_claim.claim_digest_send` keyed `(academy_id, student_id, year-as-digest_date)`, gated behind the new academy setting `birthday_emails_enabled` (default `False`).
- Staff "Birthdays this week" block: always on (no setting), no unsubscribe gate for the coach-embedded copy (it rides the coach digest's own footer), `EmailCategory.NOTIFICATION` with its own unsubscribe footer for the new standalone admin/owner weekly email.
- **Unsubscribe footers are mandatory on every new send.** `GatedEmailSendPort` (`contexts/communications/infrastructure/gated_send_port.py`) *blocks* a send for an opted-out recipient but never appends a footer — the footer is the caller's job, exactly as `render_coach_digest`/`render_parent_digest` do it via `unsubscribe_footer.render_unsubscribe_footer` / `append_unsubscribe_footer`. All three new NOTIFICATION emails (family birthday note, profile nudge, staff weekly digest) therefore take an `unsubscribe_url` minted by `compose_unsubscribe_link_builder(get_settings())` and append the footer; spec §4.2 ("unsubscribe footer") and §5 ("unsubscribe honoured") are not satisfied by the gate alone.
- **No circular imports between composition modules.** `composition/digests.py` is imported by `composition/birthdays.py` (for `_build_email_sender`, defined at `digests.py:954`). Task 12 needs the reverse direction too, so `digests.py` MUST import from `composition.birthdays` *inside the function body*, never at module top level — a top-level pair would resolve `digests` while it is still partially initialised and raise `ImportError: cannot import name '_build_email_sender'`.
- Two new scheduled jobs only (`send_birthday_notes`, `send_profile_nudges`); the staff digest block extends the *existing* `send_coach_daily_digests` job — no third cron entry — see Task 12 for why and the interpretation of "admin ops digest".
- `composition/admin.py` is 4318/4500 lines: **no edits to it** in this plan. Every new use case is composed in new `composition/*.py` files, following `composition/absence_notifications.py`.
- Production does not run migrations on boot (`V2_RUN_MIGRATIONS_ON_BOOT=false`); every migration's docstring and the release note both say to run `run_pending_migrations` by hand after deploy.

## File structure

| File | Responsibility |
|---|---|
| `backend/v2/shared/profile/birthdays.py` (new) | Pure functions: `derive_birth_month_day`, `todays_birthday_month_days` (leap-day rule), `next_nudge_step` (day 7/21/60 table). No Mongo, no contexts import (mirrors `shared/profile/completeness.py`). |
| `backend/v2/migrations/0173_backfill_student_birth_month_day.py` (new) | Backfills `students.birth_month_day` from parseable `date_of_birth`, reports unparseable ones, creates the `(academy_id, birth_month_day)` index. |
| `backend/v2/migrations/0174_birthday_and_nudge_indexes.py` (new) | Unique indexes for the three new claim/record collections: `profile_nudges`, `birthday_notice_sends`, `birthday_staff_digest_sends`. |
| `backend/v2/contexts/enrollment/infrastructure/mongo_student_writer.py` (modify) | `upsert()` now also writes `birth_month_day` derived from the student's `date_of_birth`. |
| `backend/v2/contexts/enrollment/infrastructure/mongo_student_repo.py` (modify) | `update_student_profile()` now also sets `birth_month_day` whenever `command.date_of_birth` is supplied. |
| `backend/v2/contexts/communications/application/use_cases/send_profile_nudges.py` (new) | `SendProfileNudges` use case: per-parent gap evaluation, nudge-record lifecycle, step selection, send. |
| `backend/v2/contexts/communications/application/profile_nudge_renderer.py` (new) | Renders the nudge email body (per-child missing fields, deep link, copy) and appends the unsubscribe footer. |
| `backend/v2/contexts/communications/infrastructure/mongo_nudge_record_repo.py` (new) | `MongoNudgeRecordRepository` on `profile_nudges` (get/upsert/close, no digest_claim reuse — different cadence). |
| `backend/v2/contexts/communications/application/use_cases/send_birthday_notes.py` (new) | `SendBirthdayNotes` use case: one email per birthday student, claimed via `digest_claim`. |
| `backend/v2/contexts/communications/application/birthday_renderer.py` (new) | Renders the single-child birthday email (with unsubscribe footer), the shared "Birthdays this week" HTML fragment (reused by the coach-embedded block and the standalone staff email), and `render_birthday_staff_digest` (Task 12). |
| `backend/v2/composition/birthday_notice_send_repo.py` (new) | `MongoBirthdayNoticeSendRepository` (family email claim) and `MongoBirthdayStaffDigestSendRepository` (admin/owner weekly claim) — both thin wrappers over `digest_claim.claim_digest_send`, mirroring `composition/absence_notifications.py`'s `MongoAbsenceNoticeSendRepository`. |
| `backend/v2/composition/birthdays.py` (new) | `compose_send_birthday_notes(db, *, today, academy_slug)`, the testable `birthday_emails_enabled(academy_doc)` gate predicate, `_BirthdayCandidateProvider` and `_WeeklyBirthdayProvider` bridging `enrollment` (students + enrollments + sessions) into `communications`. **Imports `_build_email_sender` from `composition/digests.py`, so `digests.py` must import back from here only inside a function body.** |
| `backend/v2/composition/profile_nudges.py` (new) | `compose_send_profile_nudges(db)`, `ProfileFactsProvider` bridging `enrollment` (students, parents) into `communications`'s `evaluate()`/`ParentFacts`/`ChildFacts`. |
| `backend/v2/contexts/communications/application/digest_renderer.py` (modify) | `render_coach_digest` gains a `birthdays: Sequence[BirthdayEntry] = ()` param, rendered only when non-empty (Mondays). |
| `backend/v2/contexts/communications/application/use_cases/send_coach_daily_digest.py` (modify) | `SendCoachDailyDigest` gains an optional `birthday_provider`; on Monday ticks, fetches the coach-filtered block and (once per academy per week) sends the admin/owner "sees all" email directly. |
| `backend/v2/composition/digests.py` (modify) | Wires the new `birthday_provider`/`admin_birthday_recipients` into `compose_send_coach_daily_digest`. |
| `backend/v2/contexts/identity/application/get_academy_notifications_use_case.py` (modify) | Adds `birthday_emails_enabled: bool = False` to `GetAcademyNotificationsOutput`. |
| `backend/v2/contexts/identity/application/update_academy_notifications_use_case.py` | **Not modified.** Verified: `execute` builds `{f"notifications.{k}": v for k, v in fields.items() if v is not None}` and re-projects through the shared `_notifications_output`, so a new boolean needs no code here. (`False` is not `None`, so turning the toggle *off* persists.) |
| `backend/v2/interfaces/admin/views.py` (modify) | `AdminNotificationsView` / `UpdateAdminNotificationsRequest` gain `birthday_emails_enabled`. |
| `backend/v2/main.py` (modify) | Registers `send_birthday_notes` and `send_profile_nudges` scheduler jobs; updates `SCHEDULED_JOB_MONITORS`. |
| `backend/v2/shared/observability/ops_digest.py` (modify) | Adds both new job ids to `JOB_STALE_AFTER`. |
| `frontend/lib/api/admin.ts` (modify) | `AdminNotificationsView` TS type gains `birthday_emails_enabled`. |
| `frontend/components/admin/settings/notify-panel.tsx` (modify) | New toggle + consent-reminder copy. |
| `docs/release-notes/2026-09-10-birthdays-and-profile-nudges.md` (new) | Release note (Task 14). |

---

### Task 1: Birthday and nudge pure-logic module

**Files:**
- Create: `backend/v2/shared/profile/birthdays.py`
- Test: `backend/v2/tests/unit/test_birthdays.py`

**Interfaces:**
- Produces: `derive_birth_month_day(date_of_birth: str | None) -> str | None`; `todays_birthday_month_days(today: date) -> tuple[str, ...]`; `NudgeSend` (`step: int`, `at: datetime`); `next_nudge_step(first_gap_seen_at: datetime, sends: Sequence[NudgeSend], now: datetime) -> int | None`.

- [ ] Write the failing test file:

```python
# backend/v2/tests/unit/test_birthdays.py
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from backend.v2.shared.profile.birthdays import (
    NudgeSend,
    derive_birth_month_day,
    next_nudge_step,
    todays_birthday_month_days,
)


def test_derive_birth_month_day_parses_iso_date() -> None:
    assert derive_birth_month_day("2016-03-07") == "03-07"


def test_derive_birth_month_day_none_for_missing_or_unparseable() -> None:
    assert derive_birth_month_day(None) is None
    assert derive_birth_month_day("") is None
    assert derive_birth_month_day("not-a-date") is None
    assert derive_birth_month_day("03/07/2016") is None


def test_derive_birth_month_day_keeps_feb_29_as_is() -> None:
    assert derive_birth_month_day("2016-02-29") == "02-29"


def test_todays_birthday_month_days_is_just_today_on_an_ordinary_day() -> None:
    assert todays_birthday_month_days(date(2026, 3, 7)) == ("03-07",)


def test_todays_birthday_month_days_includes_leap_day_on_feb_28_non_leap_year() -> None:
    # 2026 is not a leap year: a Feb-29 birthday is celebrated on Feb 28.
    assert todays_birthday_month_days(date(2026, 2, 28)) == ("02-28", "02-29")


def test_todays_birthday_month_days_feb_28_in_a_leap_year_is_just_itself() -> None:
    # 2028 is a leap year: Feb 29 exists and gets its own day, so Feb 28
    # must not also catch it.
    assert todays_birthday_month_days(date(2028, 2, 28)) == ("02-28",)


def test_todays_birthday_month_days_feb_29_in_a_leap_year_is_just_itself() -> None:
    assert todays_birthday_month_days(date(2028, 2, 29)) == ("02-29",)


def _at(days: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=days)


def test_next_nudge_step_is_none_before_day_7() -> None:
    assert next_nudge_step(_at(0), [], now=_at(6)) is None


def test_next_nudge_step_is_1_at_day_7() -> None:
    assert next_nudge_step(_at(0), [], now=_at(7)) == 1


def test_next_nudge_step_is_none_between_step_1_and_day_21_after_it() -> None:
    sends = [NudgeSend(step=1, at=_at(7))]
    assert next_nudge_step(_at(0), sends, now=_at(27)) is None


def test_next_nudge_step_is_2_at_21_days_after_step_1() -> None:
    sends = [NudgeSend(step=1, at=_at(7))]
    assert next_nudge_step(_at(0), sends, now=_at(28)) == 2


def test_next_nudge_step_is_3_at_60_days_after_step_2() -> None:
    sends = [NudgeSend(step=1, at=_at(7)), NudgeSend(step=2, at=_at(28))]
    assert next_nudge_step(_at(0), sends, now=_at(88)) == 3


def test_next_nudge_step_is_none_after_step_3_forever() -> None:
    sends = [
        NudgeSend(step=1, at=_at(7)),
        NudgeSend(step=2, at=_at(28)),
        NudgeSend(step=3, at=_at(88)),
    ]
    assert next_nudge_step(_at(0), sends, now=_at(500)) is None
```

- [ ] Run it — expect an import error (the module does not exist yet):

```bash
cd backend && .venv/bin/pytest v2/tests/unit/test_birthdays.py -q
```

- [ ] Implement the module:

```python
# backend/v2/shared/profile/birthdays.py
"""Birthday derivation and the profile-nudge step schedule.

Pure functions only — no Mongo, no `contexts` import (see
`shared/profile/completeness.py`'s docstring for why: this lives in
`shared/` precisely so both the enrollment-owned `Student.date_of_birth`
and the communications-owned nudge scheduler can use it without either
context importing the other).
"""

from __future__ import annotations

from calendar import isleap
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

#: Day offsets, each measured from the PREVIOUS step's send (or from
#: `first_gap_seen_at` for step 1). There is deliberately no step 4.
_NUDGE_STEP_DELAYS: dict[int, timedelta] = {
    1: timedelta(days=7),
    2: timedelta(days=21),
    3: timedelta(days=60),
}
MAX_NUDGE_STEP = 3


def derive_birth_month_day(date_of_birth: str | None) -> str | None:
    """`"YYYY-MM-DD"` -> `"MM-DD"`, or `None` when absent/unparseable.

    An unparseable value counts as a DOB gap (spec §3) — this function never
    raises, it only ever returns `None` for anything it cannot parse.
    """
    if not date_of_birth:
        return None
    try:
        parsed = date.fromisoformat(date_of_birth)
    except ValueError:
        return None
    return f"{parsed.month:02d}-{parsed.day:02d}"


def todays_birthday_month_days(today: date) -> tuple[str, ...]:
    """`birth_month_day` values that should be celebrated today.

    Ordinarily just `today`'s own `"MM-DD"`. On Feb 28 of a non-leap year
    this ALSO includes `"02-29"`, so a leap-day birthday is celebrated on
    the 28th instead of being skipped for three years running (spec §7).
    """
    values = [f"{today.month:02d}-{today.day:02d}"]
    if today.month == 2 and today.day == 28 and not isleap(today.year):
        values.append("02-29")
    return tuple(values)


@dataclass(frozen=True, slots=True)
class NudgeSend:
    step: int
    at: datetime


def next_nudge_step(
    first_gap_seen_at: datetime,
    sends: Sequence[NudgeSend],
    *,
    now: datetime,
) -> int | None:
    """Which step (1, 2 or 3) is due to send now, or `None` if none is.

    Step 1 is due `now >= first_gap_seen_at + 7d`. Step 2 is due 21 days
    after step 1 actually sent; step 3 is due 60 days after step 2 actually
    sent — each step's clock starts at the PRIOR step's real send time, not
    a fixed offset from `first_gap_seen_at`, so a late-running job never
    skips a step. There is no step 4: once 3 sends exist, this returns
    `None` forever.
    """
    completed = len(sends)
    if completed >= MAX_NUDGE_STEP:
        return None
    next_step = completed + 1
    anchor = sends[-1].at if sends else first_gap_seen_at
    if now >= anchor + _NUDGE_STEP_DELAYS[next_step]:
        return next_step
    return None
```

- [ ] Run again — expect PASS:

```bash
cd backend && .venv/bin/pytest v2/tests/unit/test_birthdays.py -q
```

- [ ] Commit:

```bash
git add backend/v2/shared/profile/birthdays.py backend/v2/tests/unit/test_birthdays.py
git commit -m "$(cat <<'EOF'
feat(profile): add birth_month_day derivation and nudge step schedule

Pure functions backing the birthday and profile-nudge jobs: DOB -> MM-DD
(including the leap-day query rule) and the day-7/21/60 nudge step table.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Backfill migration for `students.birth_month_day`

**Files:**
- Create: `backend/v2/migrations/0173_backfill_student_birth_month_day.py`
- Test: `backend/v2/tests/unit/test_0173_backfill_student_birth_month_day.py`

**Interfaces:**
- Consumes: `derive_birth_month_day` (Task 1).
- Produces: `up(db)`, exported `version = "0173_backfill_student_birth_month_day"`.

- [ ] Write the failing test:

```python
# backend/v2/tests/unit/test_0173_backfill_student_birth_month_day.py
from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, MagicMock

import pytest

MIGRATION = importlib.import_module(
    "backend.v2.migrations.0173_backfill_student_birth_month_day"
)


class _FakeCursor:
    def __init__(self, docs: list[dict[str, object]]) -> None:
        self._docs = docs

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for doc in self._docs:
            yield doc


@pytest.mark.asyncio
async def test_backfills_parseable_dobs_and_skips_bad_ones() -> None:
    docs = [
        {"student_id": "s1", "academy_id": "a1", "date_of_birth": "2016-03-07"},
        {"student_id": "s2", "academy_id": "a1", "date_of_birth": "not-a-date"},
        {"student_id": "s3", "academy_id": "a1", "date_of_birth": None},
        {"student_id": "s4", "academy_id": "a1", "date_of_birth": "2016-02-29"},
    ]
    students = MagicMock()
    students.find = MagicMock(return_value=_FakeCursor(docs))
    students.update_one = AsyncMock()
    students.create_index = AsyncMock()
    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=students)

    report = await MIGRATION.up(db)

    update_calls = students.update_one.await_args_list
    assert len(update_calls) == 2  # only s1 and s4 are parseable
    # Filtered by (student_id, academy_id), never bare student_id: migration
    # 0010's `student_id_unique` was GLOBAL, 0160 scoped it per academy, so a
    # bare-id update can cross tenants on any post-0160 collision (#610).
    assert update_calls[0].args[0] == {"student_id": "s1", "academy_id": "a1"}
    assert update_calls[0].args[1] == {"$set": {"birth_month_day": "03-07"}}
    assert update_calls[1].args[0] == {"student_id": "s4", "academy_id": "a1"}
    assert update_calls[1].args[1] == {"$set": {"birth_month_day": "02-29"}}
    assert report.unparseable == ["s2"]
    assert report.updated == 2

    students.create_index.assert_awaited_once()
    index_args = students.create_index.await_args
    assert index_args.args[0] == [("academy_id", 1), ("birth_month_day", 1)]
    assert index_args.kwargs["unique"] is False


@pytest.mark.asyncio
async def test_is_idempotent_on_a_rerun() -> None:
    """A second run recomputes the same value and writes it again — cheap and
    harmless — rather than skipping already-set rows, so a mid-migration
    crash never leaves a row half-backfilled."""
    docs = [{"student_id": "s1", "academy_id": "a1", "date_of_birth": "2016-03-07"}]
    students = MagicMock()
    students.find = MagicMock(side_effect=lambda *_a, **_k: _FakeCursor(docs))
    students.update_one = AsyncMock()
    students.create_index = AsyncMock()
    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=students)

    await MIGRATION.up(db)
    await MIGRATION.up(db)

    assert students.update_one.await_count == 2
```

- [ ] Run — expect an import error:

```bash
cd backend && .venv/bin/pytest v2/tests/unit/test_0173_backfill_student_birth_month_day.py -q
```

- [ ] Implement the migration:

```python
# backend/v2/migrations/0173_backfill_student_birth_month_day.py
"""Backfill `students.birth_month_day` (birthdays-and-profile-nudges spec).

`students.date_of_birth` stays a free-form `"YYYY-MM-DD"` string; this
migration derives the new `birth_month_day` (`"MM-DD"`) field on every row
that has a parseable DOB, and reports the ones it could not parse — those
already count as a DOB gap under `shared/profile/completeness.py` and need
no repair here, just visibility.

Not unique (unlike migration 0174's claim indexes): many students legitimately
share a birthday. The compound `(academy_id, birth_month_day)` index is what
`send_birthday_notes` scans daily.

Safe to re-run: every row is recomputed from `date_of_birth`, not skipped
when `birth_month_day` is already present, so a crash mid-run never leaves a
partially-backfilled academy.

Production does NOT run migrations on boot (`V2_RUN_MIGRATIONS_ON_BOOT` is
false, #629): apply with `run_pending_migrations` by hand after deploy —
before turning `birthday_emails_enabled` on for any academy, since
`send_birthday_notes` reads `birth_month_day`, not `date_of_birth`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.shared.profile.birthdays import derive_birth_month_day

log = logging.getLogger(__name__)

version = "0173_backfill_student_birth_month_day"


@dataclass
class BackfillReport:
    updated: int = 0
    unparseable: list[str] = field(default_factory=list)


async def up(db: AsyncIOMotorDatabase) -> BackfillReport:  # type: ignore[type-arg]
    students = db["students"]
    report = BackfillReport()
    async for doc in students.find({}, {"student_id": 1, "academy_id": 1, "date_of_birth": 1}):
        student_id = str(doc.get("student_id") or "")
        month_day = derive_birth_month_day(doc.get("date_of_birth"))
        if month_day is None:
            if doc.get("date_of_birth"):
                report.unparseable.append(student_id)
            continue
        await students.update_one(
            {"student_id": student_id, "academy_id": doc.get("academy_id")},
            {"$set": {"birth_month_day": month_day}},
        )
        report.updated += 1

    await students.create_index(
        [("academy_id", 1), ("birth_month_day", 1)],
        unique=False,
        name="students_academy_birth_month_day",
    )
    log.info(
        "0173: backfilled birth_month_day on %d student(s); %d unparseable: %s",
        report.updated,
        len(report.unparseable),
        report.unparseable[:50],
    )
    return report
```

- [ ] Run — expect PASS:

```bash
cd backend && .venv/bin/pytest v2/tests/unit/test_0173_backfill_student_birth_month_day.py -q
```

- [ ] Commit:

```bash
git add backend/v2/migrations/0173_backfill_student_birth_month_day.py backend/v2/tests/unit/test_0173_backfill_student_birth_month_day.py
git commit -m "$(cat <<'EOF'
feat(migrations): backfill students.birth_month_day (0173)

Derives birth_month_day from the existing date_of_birth string on every
student and indexes (academy_id, birth_month_day). Report-only for rows it
cannot parse — those already count as a profile gap.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Keep `birth_month_day` in sync on every student write

**Files:**
- Modify: `backend/v2/contexts/enrollment/infrastructure/mongo_student_writer.py` (`upsert`, lines 23-40)
- Modify: `backend/v2/contexts/enrollment/infrastructure/mongo_student_repo.py` (`update_student_profile`, lines 511-542)
- Test: `backend/v2/tests/contract/test_student_birth_month_day_sync.py`

**Interfaces:**
- Consumes: `derive_birth_month_day` (Task 1).

- [ ] Write the failing contract test:

```python
# backend/v2/tests/contract/test_student_birth_month_day_sync.py
"""birth_month_day must never drift from date_of_birth on any write path
that sets date_of_birth (spec §3): registration-approval upsert (mirrored
here by MongoStudentWriter.upsert) and the admin/parent shared edit path
(MongoStudentRepository.update_student_profile)."""

from __future__ import annotations

from datetime import date

import pytest

from backend.v2.contexts.enrollment.domain.models import Student
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_student_writer import (
    MongoStudentWriter,
)
from backend.v2.contexts.enrollment.application.use_cases.admin_directory import (
    UpdateAdminStudentCommand,
)
from backend.v2.shared.tenancy.context import tenant_scope

ACADEMY_ID = "acad-bmd-sync"


@pytest.mark.asyncio
async def test_upsert_writes_birth_month_day_from_date_of_birth(db) -> None:
    with tenant_scope(ACADEMY_ID):
        writer = MongoStudentWriter(db)
        student = Student(
            student_id="s-upsert-1",
            academy_id=ACADEMY_ID,
            parent_id="p1",
            full_name="Aanya K",
            date_of_birth="2016-03-07",
        )
        await writer.upsert(student)

    doc = await db["students"].find_one({"student_id": "s-upsert-1"})
    assert doc is not None
    assert doc["birth_month_day"] == "03-07"


@pytest.mark.asyncio
async def test_update_student_profile_refreshes_birth_month_day(db) -> None:
    with tenant_scope(ACADEMY_ID):
        writer = MongoStudentWriter(db)
        student = Student(
            student_id="s-update-1",
            academy_id=ACADEMY_ID,
            parent_id="p1",
            full_name="Kabir R",
            date_of_birth="2015-01-01",
        )
        await writer.upsert(student)

        repo = MongoStudentRepository(db)
        await repo.update_student_profile(
            "s-update-1",
            UpdateAdminStudentCommand(
                date_of_birth=date(2015, 12, 25),
                actor_id="admin-1",
                reason="test",
            ),
        )

    doc = await db["students"].find_one({"student_id": "s-update-1"})
    assert doc is not None
    assert doc["date_of_birth"] == "2015-12-25"
    assert doc["birth_month_day"] == "12-25"
```

- [ ] Run — expect the second assertion in each test to fail (`birth_month_day` absent/stale):

```bash
cd backend && .venv/bin/pytest v2/tests/contract/test_student_birth_month_day_sync.py -q
```

- [ ] Edit `mongo_student_writer.py`:

```python
# backend/v2/contexts/enrollment/infrastructure/mongo_student_writer.py
# add import near the top:
from backend.v2.shared.profile.birthdays import derive_birth_month_day
```

then in `upsert`:

```python
    async def upsert(self, student: Student) -> None:
        """..."""  # docstring unchanged
        doc = student.model_dump(mode="python")
        doc["birth_month_day"] = derive_birth_month_day(student.date_of_birth)
        await self._update_one(
            {"student_id": student.student_id},
            {"$set": {k: v for k, v in doc.items() if k != "academy_id"}},
            upsert=True,
        )
```

- [ ] Edit `mongo_student_repo.py`'s `update_student_profile` — replace:

```python
        if command.date_of_birth is not None:
            set_doc["date_of_birth"] = command.date_of_birth.isoformat()
```

with:

```python
        if command.date_of_birth is not None:
            set_doc["date_of_birth"] = command.date_of_birth.isoformat()
            set_doc["birth_month_day"] = derive_birth_month_day(set_doc["date_of_birth"])
```

and add the import near the top of the file:

```python
from backend.v2.shared.profile.birthdays import derive_birth_month_day
```

- [ ] Run — expect PASS:

```bash
cd backend && .venv/bin/pytest v2/tests/contract/test_student_birth_month_day_sync.py -q
```

- [ ] Commit:

```bash
git add backend/v2/contexts/enrollment/infrastructure/mongo_student_writer.py \
        backend/v2/contexts/enrollment/infrastructure/mongo_student_repo.py \
        backend/v2/tests/contract/test_student_birth_month_day_sync.py
git commit -m "$(cat <<'EOF'
fix(enrollment): keep students.birth_month_day in sync on every write

Both write paths that can set date_of_birth (registration-approval upsert,
the shared admin/parent profile edit) now also derive birth_month_day, so
the 0173 backfill's invariant never drifts on the next edit.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Claim/record collection indexes

**Files:**
- Create: `backend/v2/migrations/0174_birthday_and_nudge_indexes.py`
- Test: `backend/v2/tests/unit/test_0174_birthday_and_nudge_indexes.py`

**Interfaces:**
- Produces: `up(db)`, `version = "0174_birthday_and_nudge_indexes"`.

- [ ] Write the failing test (mirrors the only existing migration unit test, `backend/v2/tests/unit/test_0171_enrollment_status_vocabulary.py` — `importlib.import_module` for the digit-prefixed module name, `MagicMock`/`AsyncMock` collections. There is no `test_0172` file; 0172 is index-only and untested):

```python
# backend/v2/tests/unit/test_0174_birthday_and_nudge_indexes.py
from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, MagicMock

import pytest

MIGRATION = importlib.import_module("backend.v2.migrations.0174_birthday_and_nudge_indexes")


@pytest.mark.asyncio
async def test_creates_all_three_unique_indexes() -> None:
    collections: dict[str, MagicMock] = {}

    def _get(name: str) -> MagicMock:
        collections.setdefault(name, MagicMock(create_index=AsyncMock()))
        return collections[name]

    db = MagicMock()
    db.__getitem__ = MagicMock(side_effect=_get)

    await MIGRATION.up(db)

    assert set(collections) == {
        "profile_nudges",
        "birthday_notice_sends",
        "birthday_staff_digest_sends",
    }
    collections["profile_nudges"].create_index.assert_awaited_once_with(
        [("academy_id", 1), ("parent_id", 1)],
        unique=True,
        name="profile_nudges_academy_parent_unique",
    )
    collections["birthday_notice_sends"].create_index.assert_awaited_once_with(
        [("academy_id", 1), ("student_id", 1), ("digest_date", 1)],
        unique=True,
        name="birthday_notice_sends_key_unique",
    )
    collections["birthday_staff_digest_sends"].create_index.assert_awaited_once_with(
        [("academy_id", 1), ("user_id", 1), ("digest_date", 1)],
        unique=True,
        name="birthday_staff_digest_sends_key_unique",
    )
```

- [ ] Run — expect an import error:

```bash
cd backend && .venv/bin/pytest v2/tests/unit/test_0174_birthday_and_nudge_indexes.py -q
```

- [ ] Implement:

```python
# backend/v2/migrations/0174_birthday_and_nudge_indexes.py
"""Unique indexes for the birthdays-and-profile-nudges spec's three new
collections. No data change — same "index-only" shape as migration 0172.

* ``profile_nudges``: one open record per parent, unique on
  ``(academy_id, parent_id)`` — see ``mongo_nudge_record_repo.py``.
* ``birthday_notice_sends``: the family birthday email's claim, unique on
  ``(academy_id, student_id, digest_date)`` where ``digest_date`` carries the
  year (spec §3: "claim ... with key (academy_id, student_id, year)").
* ``birthday_staff_digest_sends``: the admin/owner weekly "Birthdays this
  week" email's claim, unique on ``(academy_id, user_id, digest_date)`` where
  ``digest_date`` carries the ISO date of that week's Monday.

Both claim collections reuse ``communications/infrastructure/digest_claim.py``
(``claim_digest_send``), which is already safe without the unique index (see
its own docstring) — the index only turns a rare concurrent double-insert
into a fast rejected write instead of a slower app-level self-withdraw.

Production does NOT run migrations on boot (#629): apply by hand after
deploy.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0174_birthday_and_nudge_indexes"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    await db["profile_nudges"].create_index(
        [("academy_id", 1), ("parent_id", 1)],
        unique=True,
        name="profile_nudges_academy_parent_unique",
    )
    await db["birthday_notice_sends"].create_index(
        [("academy_id", 1), ("student_id", 1), ("digest_date", 1)],
        unique=True,
        name="birthday_notice_sends_key_unique",
    )
    await db["birthday_staff_digest_sends"].create_index(
        [("academy_id", 1), ("user_id", 1), ("digest_date", 1)],
        unique=True,
        name="birthday_staff_digest_sends_key_unique",
    )
```

- [ ] Run — expect PASS:

```bash
cd backend && .venv/bin/pytest v2/tests/unit/test_0174_birthday_and_nudge_indexes.py -q
```

- [ ] Commit:

```bash
git add backend/v2/migrations/0174_birthday_and_nudge_indexes.py backend/v2/tests/unit/test_0174_birthday_and_nudge_indexes.py
git commit -m "$(cat <<'EOF'
feat(migrations): index the birthday and profile-nudge claim collections (0174)

profile_nudges (academy_id, parent_id) unique, birthday_notice_sends and
birthday_staff_digest_sends each unique on their digest_claim key.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Nudge record repository

**Files:**
- Create: `backend/v2/contexts/communications/infrastructure/mongo_nudge_record_repo.py`
- Test: `backend/v2/tests/contract/test_mongo_nudge_record_repo.py`

**Interfaces:**
- Produces: `NudgeRecord` (dataclass: `parent_id`, `first_gap_seen_at`, `sends: list[NudgeSend]`, `closed_at: datetime | None`); `MongoNudgeRecordRepository.get(parent_id) -> NudgeRecord | None`; `.open_or_reopen(parent_id, *, now) -> NudgeRecord`; `.record_send(parent_id, *, step, at) -> None`; `.close(parent_id) -> None`.

- [ ] Write the failing test:

```python
# backend/v2/tests/contract/test_mongo_nudge_record_repo.py
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.communications.infrastructure.mongo_nudge_record_repo import (
    MongoNudgeRecordRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope

ACADEMY_ID = "acad-nudge-repo"


@pytest.mark.asyncio
async def test_get_is_none_before_any_record_exists(db) -> None:
    with tenant_scope(ACADEMY_ID):
        repo = MongoNudgeRecordRepository(db)
        assert await repo.get("parent-1") is None


@pytest.mark.asyncio
async def test_open_or_reopen_creates_a_fresh_record_once(db) -> None:
    with tenant_scope(ACADEMY_ID):
        repo = MongoNudgeRecordRepository(db)
        now = datetime(2026, 1, 1, tzinfo=UTC)
        first = await repo.open_or_reopen("parent-2", now=now)
        assert first.first_gap_seen_at == now
        assert first.sends == []
        assert first.closed_at is None

        # A second open_or_reopen on an already-open record is a no-op: the
        # clock must not reset every tick, or step 1 would never come due.
        later = datetime(2026, 1, 10, tzinfo=UTC)
        second = await repo.open_or_reopen("parent-2", now=later)
        assert second.first_gap_seen_at == now


@pytest.mark.asyncio
async def test_record_send_appends_a_step(db) -> None:
    with tenant_scope(ACADEMY_ID):
        repo = MongoNudgeRecordRepository(db)
        now = datetime(2026, 1, 1, tzinfo=UTC)
        await repo.open_or_reopen("parent-3", now=now)
        sent_at = datetime(2026, 1, 8, tzinfo=UTC)
        await repo.record_send("parent-3", step=1, at=sent_at)

        record = await repo.get("parent-3")
        assert record is not None
        assert [(s.step, s.at) for s in record.sends] == [(1, sent_at)]


@pytest.mark.asyncio
async def test_close_stamps_closed_at(db) -> None:
    with tenant_scope(ACADEMY_ID):
        repo = MongoNudgeRecordRepository(db)
        await repo.open_or_reopen("parent-4", now=datetime(2026, 1, 1, tzinfo=UTC))
        closed_at = datetime(2026, 1, 5, tzinfo=UTC)
        await repo.close("parent-4", now=closed_at)

        record = await repo.get("parent-4")
        assert record is not None
        assert record.closed_at == closed_at


@pytest.mark.asyncio
async def test_open_or_reopen_after_close_starts_a_fresh_episode(db) -> None:
    """A closed record (gap closed) whose gap reappears later gets a brand
    new day-7/21/60 cycle, not a resumed one."""
    with tenant_scope(ACADEMY_ID):
        repo = MongoNudgeRecordRepository(db)
        await repo.open_or_reopen("parent-5", now=datetime(2026, 1, 1, tzinfo=UTC))
        await repo.record_send("parent-5", step=1, at=datetime(2026, 1, 8, tzinfo=UTC))
        await repo.close("parent-5", now=datetime(2026, 1, 20, tzinfo=UTC))

        reopened_at = datetime(2026, 3, 1, tzinfo=UTC)
        record = await repo.open_or_reopen("parent-5", now=reopened_at)
        assert record.first_gap_seen_at == reopened_at
        assert record.sends == []
        assert record.closed_at is None
```

- [ ] Run — expect an import error:

```bash
cd backend && .venv/bin/pytest v2/tests/contract/test_mongo_nudge_record_repo.py -q
```

- [ ] Implement:

```python
# backend/v2/contexts/communications/infrastructure/mongo_nudge_record_repo.py
"""Persistence for the profile-nudge schedule (birthdays-and-profile-nudges
spec §3/§5): one open record per parent, tracking when their gap was first
seen and which of the three nudge steps have fired.

Deliberately NOT built on `digest_claim.py` — that primitive answers "may I
send today's recurring digest", a once-per-calendar-day question. A nudge
step is due on a day-7/21/60 SCHEDULE, so the record itself (not a daily
claim row) is the state machine; `next_nudge_step` (shared/profile/birthdays)
reads it to decide whether today is that day.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from backend.v2.shared.profile.birthdays import NudgeSend
from backend.v2.shared.tenancy import TenantScopedRepository


@dataclass(frozen=True, slots=True)
class NudgeRecord:
    parent_id: str
    first_gap_seen_at: datetime
    sends: list[NudgeSend] = field(default_factory=list)
    closed_at: datetime | None = None


def _to_domain(doc: dict[str, Any]) -> NudgeRecord:
    return NudgeRecord(
        parent_id=str(doc["parent_id"]),
        first_gap_seen_at=doc["first_gap_seen_at"],
        sends=[NudgeSend(step=int(s["step"]), at=s["at"]) for s in doc.get("sends") or []],
        closed_at=doc.get("closed_at"),
    )


class MongoNudgeRecordRepository(TenantScopedRepository):
    collection_name = "profile_nudges"

    async def get(self, parent_id: str) -> NudgeRecord | None:
        doc = await self._find_one({"parent_id": parent_id})
        return _to_domain(doc) if doc else None

    async def open_or_reopen(self, parent_id: str, *, now: datetime) -> NudgeRecord:
        """Return the parent's open nudge episode, starting a fresh one if
        none exists or the existing one was closed (gap reappeared)."""
        existing = await self.get(parent_id)
        if existing is not None and existing.closed_at is None:
            return existing
        await self._update_one(
            {"parent_id": parent_id},
            {
                "$set": {
                    "first_gap_seen_at": now,
                    "sends": [],
                    "closed_at": None,
                }
            },
            upsert=True,
        )
        result = await self.get(parent_id)
        assert result is not None
        return result

    async def record_send(self, parent_id: str, *, step: int, at: datetime) -> None:
        await self._update_one(
            {"parent_id": parent_id},
            {"$push": {"sends": {"step": step, "at": at}}},
        )

    async def close(self, parent_id: str, *, now: datetime) -> None:
        await self._update_one({"parent_id": parent_id}, {"$set": {"closed_at": now}})
```

- [ ] Run — expect PASS:

```bash
cd backend && .venv/bin/pytest v2/tests/contract/test_mongo_nudge_record_repo.py -q
```

- [ ] Commit:

```bash
git add backend/v2/contexts/communications/infrastructure/mongo_nudge_record_repo.py \
        backend/v2/tests/contract/test_mongo_nudge_record_repo.py
git commit -m "$(cat <<'EOF'
feat(communications): add the profile-nudge record repository

profile_nudges tracks one open episode per parent (first_gap_seen_at,
sends, closed_at); open_or_reopen starts a fresh episode when none is open
or the last one closed, so a reappearing gap gets a new day-7/21/60 cycle.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: `SendProfileNudges` use case

**Files:**
- Create: `backend/v2/contexts/communications/application/use_cases/send_profile_nudges.py`
- Test: `backend/v2/tests/unit/test_send_profile_nudges.py`

**Interfaces:**
- Consumes: `evaluate`, `ParentFacts`, `ChildFacts`, `ProfileGaps` (`backend/v2/shared/profile/completeness.py`); `next_nudge_step` (Task 1); `NudgeRecord`, `MongoNudgeRecordRepository`-shaped protocol (Task 5); `AudienceResolver`, `EmailSendPort`, `ResolvedRecipient` (`communications/application/ports.py`).
- Produces: `ProfileFactsProvider` protocol (`async def facts_for_parent(parent_id) -> tuple[ParentFacts, list[ChildFacts]] | None`, `async def has_current_student(parent_id) -> bool`); `SendProfileNudgesCommand`, `SendProfileNudgesResult`, `SendProfileNudges`.

- [ ] Write the failing test:

```python
# backend/v2/tests/unit/test_send_profile_nudges.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import pytest

from backend.v2.contexts.communications.application.ports import (
    AcademyAudience,
    ResolvedRecipient,
)
from backend.v2.contexts.communications.application.use_cases.send_profile_nudges import (
    SendProfileNudges,
    SendProfileNudgesCommand,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.shared.profile.birthdays import NudgeSend
from backend.v2.shared.profile.completeness import ChildFacts, ParentFacts


@dataclass
class _FakeResolver:
    parents: list[ResolvedRecipient]

    async def resolve_academy_audience(self, audience: AcademyAudience) -> list[ResolvedRecipient]:
        assert audience.role == "parent"
        return self.parents

    async def resolve_session_audience(self, *a, **k): ...
    async def resolve_coach_audience(self, *a, **k): ...
    async def resolve_selected_audience(self, *a, **k): ...
    async def resolve_payment_risk_audience(self, *a, **k): ...


@dataclass
class _FakeFactsProvider:
    facts: dict[str, tuple[ParentFacts, list[ChildFacts]]]
    current: set[str] = field(default_factory=set)

    async def facts_for_parent(self, parent_id: str):
        return self.facts.get(parent_id)

    async def has_current_student(self, parent_id: str) -> bool:
        return parent_id in self.current


@dataclass
class _NudgeRecord:
    parent_id: str
    first_gap_seen_at: datetime
    sends: list[NudgeSend] = field(default_factory=list)
    closed_at: datetime | None = None


class _FakeRecords:
    def __init__(self) -> None:
        self.by_parent: dict[str, _NudgeRecord] = {}
        self.closed: list[str] = []

    async def get(self, parent_id: str):
        return self.by_parent.get(parent_id)

    async def open_or_reopen(self, parent_id: str, *, now: datetime):
        existing = self.by_parent.get(parent_id)
        if existing is not None and existing.closed_at is None:
            return existing
        record = _NudgeRecord(parent_id=parent_id, first_gap_seen_at=now)
        self.by_parent[parent_id] = record
        return record

    async def record_send(self, parent_id: str, *, step: int, at: datetime) -> None:
        self.by_parent[parent_id].sends.append(NudgeSend(step=step, at=at))

    async def close(self, parent_id: str, *, now: datetime) -> None:
        self.closed.append(parent_id)
        self.by_parent[parent_id].closed_at = now


class _FakeSender:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    async def send(self, *, recipient, subject, body, cc=None, bcc=None, reply_to=None, category):
        self.sent.append(
            {"recipient": recipient, "subject": subject, "category": category}
        )
        from backend.v2.contexts.communications.application.ports import SendOutcome

        return SendOutcome(ok=True, provider_message_id="msg-1", failed_reason=None)


def _child(student_id: str, *, complete: bool) -> ChildFacts:
    if complete:
        return ChildFacts(
            student_id=student_id,
            full_name="Kid",
            date_of_birth="2016-01-01",
            emergency_contact_name="Aunt",
            emergency_contact_phone="555-0100",
            medical_notes="__none_declared__",
        )
    return ChildFacts(student_id=student_id, full_name="Kid")


@pytest.mark.asyncio
async def test_ineligible_parent_with_no_current_student_is_skipped() -> None:
    parent = ResolvedRecipient(user_id="parent-x", email="x@example.com", display_name="X")
    resolver = _FakeResolver(parents=[parent])
    facts = _FakeFactsProvider(
        facts={"parent-x": (ParentFacts(display_name="X", phone="555", email_confirmed_at=None), [])},
        current=set(),  # no current student
    )
    records = _FakeRecords()
    sender = _FakeSender()
    use_case = SendProfileNudges(resolver=resolver, facts=facts, records=records, sender=sender)

    result = await use_case.execute(
        SendProfileNudgesCommand(academy_id="a1", now=datetime(2026, 1, 1, tzinfo=UTC))
    )

    assert result.eligible_parents == 0
    assert sender.sent == []
    assert records.by_parent == {}


@pytest.mark.asyncio
async def test_complete_profile_closes_any_open_record_and_sends_nothing() -> None:
    parent = ResolvedRecipient(user_id="parent-y", email="y@example.com", display_name="Y")
    resolver = _FakeResolver(parents=[parent])
    facts = _FakeFactsProvider(
        facts={
            "parent-y": (
                ParentFacts(display_name="Y", phone="555", email_confirmed_at=datetime(2025, 1, 1, tzinfo=UTC)),
                [_child("s1", complete=True)],
            )
        },
        current={"parent-y"},
    )
    records = _FakeRecords()
    records.by_parent["parent-y"] = _NudgeRecord(
        parent_id="parent-y", first_gap_seen_at=datetime(2025, 12, 1, tzinfo=UTC)
    )
    sender = _FakeSender()
    use_case = SendProfileNudges(resolver=resolver, facts=facts, records=records, sender=sender)

    await use_case.execute(
        SendProfileNudgesCommand(academy_id="a1", now=datetime(2026, 1, 1, tzinfo=UTC))
    )

    assert records.closed == ["parent-y"]
    assert sender.sent == []


@pytest.mark.asyncio
async def test_gap_older_than_7_days_with_no_record_sends_nothing_this_tick() -> None:
    """spec §5: a brand-new family is not nudged the day their gap is first
    seen — the record is opened but step 1 only fires on a LATER tick."""
    parent = ResolvedRecipient(user_id="parent-z", email="z@example.com", display_name="Z")
    resolver = _FakeResolver(parents=[parent])
    facts = _FakeFactsProvider(
        facts={
            "parent-z": (
                ParentFacts(display_name="Z", phone="555", email_confirmed_at=datetime(2025, 1, 1, tzinfo=UTC)),
                [_child("s1", complete=False)],
            )
        },
        current={"parent-z"},
    )
    records = _FakeRecords()
    sender = _FakeSender()
    use_case = SendProfileNudges(resolver=resolver, facts=facts, records=records, sender=sender)

    await use_case.execute(
        SendProfileNudgesCommand(academy_id="a1", now=datetime(2026, 1, 1, tzinfo=UTC))
    )

    assert sender.sent == []
    assert records.by_parent["parent-z"].first_gap_seen_at == datetime(2026, 1, 1, tzinfo=UTC)


@pytest.mark.asyncio
async def test_step_1_sends_at_day_7_and_is_recorded() -> None:
    parent = ResolvedRecipient(user_id="parent-w", email="w@example.com", display_name="W")
    resolver = _FakeResolver(parents=[parent])
    facts = _FakeFactsProvider(
        facts={
            "parent-w": (
                ParentFacts(display_name="W", phone="555", email_confirmed_at=datetime(2025, 1, 1, tzinfo=UTC)),
                [_child("s1", complete=False)],
            )
        },
        current={"parent-w"},
    )
    records = _FakeRecords()
    records.by_parent["parent-w"] = _NudgeRecord(
        parent_id="parent-w", first_gap_seen_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    sender = _FakeSender()
    use_case = SendProfileNudges(resolver=resolver, facts=facts, records=records, sender=sender)

    result = await use_case.execute(
        SendProfileNudgesCommand(academy_id="a1", now=datetime(2026, 1, 8, tzinfo=UTC))
    )

    assert result.sent == 1
    assert sender.sent[0]["category"] == EmailCategory.NOTIFICATION
    assert [s.step for s in records.by_parent["parent-w"].sends] == [1]


@pytest.mark.asyncio
async def test_step_not_yet_due_sends_nothing() -> None:
    parent = ResolvedRecipient(user_id="parent-v", email="v@example.com", display_name="V")
    resolver = _FakeResolver(parents=[parent])
    facts = _FakeFactsProvider(
        facts={
            "parent-v": (
                ParentFacts(display_name="V", phone="555", email_confirmed_at=datetime(2025, 1, 1, tzinfo=UTC)),
                [_child("s1", complete=False)],
            )
        },
        current={"parent-v"},
    )
    records = _FakeRecords()
    records.by_parent["parent-v"] = _NudgeRecord(
        parent_id="parent-v", first_gap_seen_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    sender = _FakeSender()
    use_case = SendProfileNudges(resolver=resolver, facts=facts, records=records, sender=sender)

    result = await use_case.execute(
        SendProfileNudgesCommand(academy_id="a1", now=datetime(2026, 1, 5, tzinfo=UTC))
    )

    assert result.sent == 0
    assert sender.sent == []
```

- [ ] Run — expect an import error:

```bash
cd backend && .venv/bin/pytest v2/tests/unit/test_send_profile_nudges.py -q
```

- [ ] Implement:

```python
# backend/v2/contexts/communications/application/use_cases/send_profile_nudges.py
"""SendProfileNudges use case (birthdays-and-profile-nudges spec §5).

For each parent with at least one current (active/held/paused) student,
computes ProfileGaps; an empty result closes any open nudge episode, a
non-empty one opens/keeps one and sends whichever step is due today. One
email per parent per step, listing every missing field across ALL of that
parent's children (not just the current ones) — see the spec's §5 wording.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from backend.v2.contexts.communications.application.ports import (
    AcademyAudience,
    AudienceResolver,
    EmailSendPort,
    ResolvedRecipient,
)
from backend.v2.contexts.communications.application.profile_nudge_renderer import (
    render_profile_nudge,
)
from backend.v2.contexts.communications.application.unsubscribe_token import (
    UnsubscribeLinkBuilder,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.shared.profile.birthdays import NudgeSend, next_nudge_step
from backend.v2.shared.profile.completeness import ChildFacts, ParentFacts, evaluate


class ProfileFactsProvider(Protocol):
    async def facts_for_parent(
        self, parent_id: str
    ) -> tuple[ParentFacts, list[ChildFacts]] | None: ...

    async def has_current_student(self, parent_id: str) -> bool: ...


class NudgeRecordLike(Protocol):
    """The three fields the scheduler reads off a nudge record.

    Typed explicitly (rather than `object`) because mypy runs `strict` on
    everything outside `tests/`: a bare `object` would force
    `# type: ignore` on every attribute read, and `strict` turns on
    `warn_unused_ignores`, so a mis-coded ignore fails CI twice over.
    """

    @property
    def first_gap_seen_at(self) -> datetime: ...

    @property
    def sends(self) -> Sequence[NudgeSend]: ...

    @property
    def closed_at(self) -> datetime | None: ...


class NudgeRecordStore(Protocol):
    async def get(self, parent_id: str) -> NudgeRecordLike | None: ...
    async def open_or_reopen(self, parent_id: str, *, now: datetime) -> NudgeRecordLike: ...
    async def record_send(self, parent_id: str, *, step: int, at: datetime) -> None: ...
    async def close(self, parent_id: str, *, now: datetime) -> None: ...


@dataclass(frozen=True, slots=True)
class SendProfileNudgesCommand:
    academy_id: str
    now: datetime
    profile_url: str | None = None
    #: The academy's subdomain label, so the unsubscribe link lands on the
    #: host `TenantResolver` can resolve. Same field, same reason, as
    #: `SendCoachDailyDigest._academy_slug` (#555).
    academy_slug: str | None = None


@dataclass(frozen=True, slots=True)
class SendProfileNudgesResult:
    total_parents: int = 0
    eligible_parents: int = 0
    sent: int = 0
    closed: int = 0
    failed: int = 0


@dataclass
class SendProfileNudges:
    resolver: AudienceResolver
    facts: ProfileFactsProvider
    records: NudgeRecordStore
    sender: EmailSendPort
    # Fail-closed with no signing secret: `build` returns None and the footer
    # degrades to a portal pointer rather than a forgeable link (#555).
    unsubscribe_links: UnsubscribeLinkBuilder = field(default_factory=UnsubscribeLinkBuilder)

    async def execute(self, command: SendProfileNudgesCommand) -> SendProfileNudgesResult:
        parents = await self.resolver.resolve_academy_audience(AcademyAudience(role="parent"))
        eligible = sent = closed = failed = 0

        for parent in parents:
            if not await self.facts.has_current_student(parent.user_id):
                continue
            eligible += 1

            pair = await self.facts.facts_for_parent(parent.user_id)
            if pair is None:
                continue
            parent_facts, child_facts = pair
            gaps = evaluate(parent_facts, child_facts)

            existing = await self.records.get(parent.user_id)
            if gaps.is_complete:
                if existing is not None and existing.closed_at is None:
                    await self.records.close(parent.user_id, now=command.now)
                    closed += 1
                continue

            record = await self.records.open_or_reopen(parent.user_id, now=command.now)
            step = next_nudge_step(record.first_gap_seen_at, record.sends, now=command.now)
            if step is None:
                continue

            if not parent.email:
                failed += 1
                continue

            subject, body = render_profile_nudge(
                gaps=gaps,
                children=child_facts,
                step=step,
                profile_url=command.profile_url,
                # spec §5: "Category NOTIFICATION, unsubscribe honoured".
                # The gate only BLOCKS an opted-out recipient; the visible
                # opt-out link has to be rendered here.
                unsubscribe_url=self.unsubscribe_links.build(
                    academy_id=command.academy_id,
                    user_id=parent.user_id,
                    academy_slug=command.academy_slug,
                ),
            )
            outcome = await self.sender.send(
                recipient=ResolvedRecipient(
                    user_id=parent.user_id, email=parent.email, display_name=parent.display_name
                ),
                subject=subject,
                body=body,
                category=EmailCategory.NOTIFICATION,
            )
            if outcome.ok:
                await self.records.record_send(parent.user_id, step=step, at=command.now)
                sent += 1
            else:
                failed += 1

        return SendProfileNudgesResult(
            total_parents=len(parents),
            eligible_parents=eligible,
            sent=sent,
            closed=closed,
            failed=failed,
        )
```

This module imports `render_profile_nudge`, which Task 7 creates. **Do Task 7's implementation step first**, then come back here — there is no stub, and no step of this plan is allowed to leave a red import behind. The two files ship in one commit (below) because the use case does not import cleanly without the renderer.

- [ ] Do Task 7's implementation step now (`profile_nudge_renderer.py` + its test), then return.

- [ ] Run — expect PASS:

```bash
cd backend && .venv/bin/pytest v2/tests/unit/test_send_profile_nudges.py -q
```

- [ ] Commit (together with Task 7's renderer, since the use case does not import cleanly without it):

```bash
git add backend/v2/contexts/communications/application/use_cases/send_profile_nudges.py \
        backend/v2/contexts/communications/application/profile_nudge_renderer.py \
        backend/v2/tests/unit/test_send_profile_nudges.py \
        backend/v2/tests/unit/test_profile_nudge_renderer.py
git commit -m "$(cat <<'EOF'
feat(communications): add SendProfileNudges use case and email renderer

Per-parent gap evaluation against the day-7/21/60 schedule: closes an open
nudge episode the moment gaps clear, opens/advances one otherwise, and
sends the step whose delay has elapsed. NOTIFICATION category, one email
per parent listing every missing field across all their children.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Profile-nudge email renderer

**Files:**
- Create: `backend/v2/contexts/communications/application/profile_nudge_renderer.py`
- Test: `backend/v2/tests/unit/test_profile_nudge_renderer.py`

**Interfaces:**
- Consumes: `ProfileGaps`, `ChildFacts` (`shared/profile/completeness.py`); `shell`, `INK`/`LINE`/`MUTED`, `EmailBrand` (`shared/comms/email_theme.py`); `append_unsubscribe_footer` (`contexts/communications/application/unsubscribe_footer.py:39`). The renderer takes `unsubscribe_url: str | None = None` and appends the footer itself — exactly like `render_coach_digest`, which takes `unsubscribe_url` and calls `render_unsubscribe_footer`. With `None` the footer degrades to a portal pointer, so the renderer stays testable without a link builder.
- Produces: `FIELD_COPY: dict[str, tuple[str, str]]` (label, why-it-matters); `render_profile_nudge(*, gaps, children, step, profile_url, unsubscribe_url=None) -> tuple[str, str]`.

- [ ] Write the failing test:

```python
# backend/v2/tests/unit/test_profile_nudge_renderer.py
from __future__ import annotations

from backend.v2.contexts.communications.application.profile_nudge_renderer import (
    render_profile_nudge,
)
from backend.v2.shared.profile.completeness import ChildFacts, ProfileGaps


def test_subject_names_the_step() -> None:
    gaps = ProfileGaps(parent=[], children={"s1": ["date_of_birth"]})
    children = [ChildFacts(student_id="s1", full_name="Aanya")]

    subject, _ = render_profile_nudge(gaps=gaps, children=children, step=1, profile_url=None)

    assert "Aanya" in subject or "profile" in subject.lower()


def test_body_lists_every_missing_field_across_children() -> None:
    gaps = ProfileGaps(
        parent=["phone"],
        children={
            "s1": ["date_of_birth", "emergency_contact_name"],
            "s2": ["medical_notes"],
        },
    )
    children = [
        ChildFacts(student_id="s1", full_name="Aanya"),
        ChildFacts(student_id="s2", full_name="Kabir"),
    ]

    _, body = render_profile_nudge(gaps=gaps, children=children, step=2, profile_url=None)

    assert "Aanya" in body
    assert "Kabir" in body
    assert "date of birth" in body.lower()
    assert "emergency contact" in body.lower()
    assert "medical" in body.lower()
    assert "phone" in body.lower()


def test_body_links_to_the_profile_url_when_given() -> None:
    gaps = ProfileGaps(parent=[], children={"s1": ["date_of_birth"]})
    children = [ChildFacts(student_id="s1", full_name="Aanya")]

    _, body = render_profile_nudge(
        gaps=gaps, children=children, step=1, profile_url="https://acad.example.com/parent/profile"
    )

    assert "https://acad.example.com/parent/profile" in body


def test_body_explains_why_date_of_birth_matters() -> None:
    gaps = ProfileGaps(parent=[], children={"s1": ["date_of_birth"]})
    children = [ChildFacts(student_id="s1", full_name="Aanya")]

    _, body = render_profile_nudge(gaps=gaps, children=children, step=1, profile_url=None)

    assert "birthday" in body.lower() or "age" in body.lower()


def test_no_call_to_action_button_beyond_the_profile_link() -> None:
    """spec §4.2 says the birthday note has no CTA; the nudge email's only
    action is the profile deep link itself, not a separate button."""
    gaps = ProfileGaps(parent=[], children={"s1": ["date_of_birth"]})
    children = [ChildFacts(student_id="s1", full_name="Aanya")]

    _, body = render_profile_nudge(gaps=gaps, children=children, step=1, profile_url=None)

    assert body.count("<a ") <= 1
```

- [ ] Run — expect an import error:

```bash
cd backend && .venv/bin/pytest v2/tests/unit/test_profile_nudge_renderer.py -q
```

- [ ] Implement:

```python
# backend/v2/contexts/communications/application/profile_nudge_renderer.py
"""Renders the profile-nudge email (birthdays-and-profile-nudges spec §5).

One email per parent per step, listing every missing field across all their
children with a plain-language reason it matters, and a deep link to
`/parent/profile`. No unsubscribe footer here — the use case appends it once
an unsubscribe URL is available, the same split `render_coach_digest` uses.
"""

from __future__ import annotations

import html
from collections.abc import Sequence

from backend.v2.contexts.communications.application.unsubscribe_footer import (
    append_unsubscribe_footer,
)
from backend.v2.shared.comms.email_theme import INK, LINE, MUTED, EmailBrand, shell
from backend.v2.shared.profile.completeness import ChildFacts, ProfileGaps

#: gap key -> (human label, why it matters). Keys match
#: shared/profile/completeness.py's PARENT_REQUIRED/CHILD_REQUIRED exactly.
FIELD_COPY: dict[str, tuple[str, str]] = {
    "display_name": ("your name", "so we know who we're emailing"),
    "phone": ("your phone number", "so we can reach you about a class change"),
    "email_confirmed": ("confirming your email", "so you don't miss an important notice"),
    "full_name": ("their name", "so we know who's on the roster"),
    "date_of_birth": (
        "their date of birth",
        "so we can wish them a happy birthday and place them in the right age group",
    ),
    "emergency_contact_name": ("an emergency contact", "for their safety at every class"),
    "emergency_contact_phone": (
        "an emergency contact phone number",
        "for their safety at every class",
    ),
    "medical_notes": (
        "a medical answer (or 'none')",
        "so a coach knows about any condition or allergy before class",
    ),
}

_STEP_SUBJECTS = {
    1: "A couple of details would help us take care of {child}",
    2: "Still missing a few details for {child}",
    3: "Last reminder: a few details for {child}",
}


def _first_child_name(children: Sequence[ChildFacts]) -> str:
    for child in children:
        if child.full_name:
            return child.full_name
    return "your family"


def render_profile_nudge(
    *,
    gaps: ProfileGaps,
    children: Sequence[ChildFacts],
    step: int,
    profile_url: str | None,
    unsubscribe_url: str | None = None,
) -> tuple[str, str]:
    subject = _STEP_SUBJECTS.get(step, _STEP_SUBJECTS[1]).format(child=_first_child_name(children))

    names_by_id = {c.student_id: (c.full_name or "your child") for c in children}
    rows: list[str] = []
    if gaps.parent:
        rows.append(_row("You", gaps.parent))
    for student_id, keys in gaps.children.items():
        if keys:
            rows.append(_row(names_by_id.get(student_id, "your child"), keys))

    link_html = ""
    if profile_url:
        safe_url = html.escape(profile_url, quote=True)
        link_html = (
            f'<p style="margin:16px 0 0;">'
            f'<a href="{safe_url}" style="color:{INK};text-decoration:underline;">'
            f"Update your profile</a></p>"
        )

    inner = (
        f'<p style="font-size:15px;margin:0 0 12px;">A couple of details would help us '
        f"take care of your family:</p>"
        f'<div style="border-top:1px solid {LINE};">{"".join(rows)}</div>'
        f"{link_html}"
    )
    body = shell(
        brand=EmailBrand(academy_name="Your academy"),
        inner_html=inner,
        footer_html="",
    )
    return subject, append_unsubscribe_footer(body, unsubscribe_url)


def _row(who: str, keys: Sequence[str]) -> str:
    items = "".join(
        f'<li style="margin:0 0 4px;">{html.escape(label)} — {html.escape(why)}</li>'
        for label, why in (FIELD_COPY[k] for k in keys if k in FIELD_COPY)
    )
    return (
        f'<div style="padding:10px 0;border-bottom:1px solid {LINE};">'
        f'<strong style="color:{INK};">{html.escape(who)}</strong>'
        f'<ul style="margin:6px 0 0;padding-left:18px;color:{MUTED};font-size:13px;">{items}</ul>'
        f"</div>"
    )
```

- [ ] Run — expect PASS:

```bash
cd backend && .venv/bin/pytest v2/tests/unit/test_profile_nudge_renderer.py v2/tests/unit/test_send_profile_nudges.py -q
```

- [ ] Commit together with Task 6 as instructed there.

---

### Task 8: Compose and schedule `send_profile_nudges`

**Files:**
- Create: `backend/v2/composition/profile_nudges.py`
- Modify: `backend/v2/main.py` (add job registration, `SCHEDULED_JOB_MONITORS`)
- Modify: `backend/v2/shared/observability/ops_digest.py` (`JOB_STALE_AFTER`)
- Modify: `backend/v2/tests/unit/test_scheduler_academies.py` (`registered` count)
- Test: `backend/v2/tests/contract/test_compose_profile_nudges.py`

**Interfaces:**
- Consumes: `SendProfileNudges` (Task 6), `MongoNudgeRecordRepository` (Task 5), `MongoStudentRepository.list_for_parent`, `get_parent_user_doc`; `MongoEnrollmentRepository.departable_for_student`; `_build_email_sender`, `compose_unsubscribe_link_builder` (`composition/digests.py`); `academy_frontend_url`.
- Produces: `compose_send_profile_nudges(db) -> SendProfileNudges`.

- [ ] Write the failing contract test (exercises the real Mongo-backed wiring end to end for one parent):

```python
# backend/v2/tests/contract/test_compose_profile_nudges.py
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.composition.profile_nudges import compose_send_profile_nudges
from backend.v2.contexts.communications.application.use_cases.send_profile_nudges import (
    SendProfileNudgesCommand,
)
from backend.v2.shared.tenancy.context import tenant_scope

ACADEMY_ID = "acad-nudge-compose"


async def _seed_family(db, *, dob_present: bool) -> None:
    # ProfileGaps spans BOTH sides: PARENT_REQUIRED is
    # (display_name, phone, email_confirmed) and CHILD_REQUIRED is
    # (full_name, date_of_birth, emergency_contact_name,
    # emergency_contact_phone, medical_notes). Seeding only the child fields
    # would leave `phone`/`email_confirmed` missing, so the "complete" case
    # would never actually be complete and the second test would be vacuous.
    await db["users"].insert_one(
        {
            "academy_id": ACADEMY_ID,
            "user_id": "parent-9",
            "email": "parent9@example.com",
            "display_name": "Parent Nine",
            "roles": ["parent"],
            "phone": "555-0199" if dob_present else None,
            "email_confirmed_at": datetime(2025, 6, 1, tzinfo=UTC) if dob_present else None,
        }
    )
    # `status: "active"` is load-bearing: MongoAudienceResolver's
    # `_membership_role_filter` requires it. Without it the resolver silently
    # falls through to its legacy `users.roles` query and this test stops
    # exercising the membership path at all.
    await db["academy_memberships"].insert_one(
        {"academy_id": ACADEMY_ID, "user_id": "parent-9", "role": "parent", "status": "active"}
    )
    await db["students"].insert_one(
        {
            "academy_id": ACADEMY_ID,
            "student_id": "student-9",
            "parent_id": "parent-9",
            "full_name": "Nina",
            "date_of_birth": "2016-01-01" if dob_present else None,
            "emergency_contact_name": "Uncle" if dob_present else None,
            "emergency_contact_phone": "555-0000" if dob_present else None,
            "medical_notes": "__none_declared__" if dob_present else None,
        }
    )
    await db["enrollments"].insert_one(
        {
            "academy_id": ACADEMY_ID,
            "enrollment_id": "enr-9",
            "student_id": "student-9",
            "session_id": "sess-9",
            "status": "active",
        }
    )


@pytest.mark.asyncio
async def test_incomplete_profile_opens_a_record_and_does_not_send_before_day_7(db) -> None:
    with tenant_scope(ACADEMY_ID):
        await _seed_family(db, dob_present=False)
        use_case = compose_send_profile_nudges(db)
        result = await use_case.execute(
            SendProfileNudgesCommand(academy_id=ACADEMY_ID, now=datetime(2026, 1, 1, tzinfo=UTC))
        )

    assert result.eligible_parents == 1
    assert result.sent == 0
    record = await db["profile_nudges"].find_one({"parent_id": "parent-9"})
    assert record is not None


@pytest.mark.asyncio
async def test_complete_profile_never_opens_a_record(db) -> None:
    with tenant_scope(ACADEMY_ID):
        await _seed_family(db, dob_present=True)
        use_case = compose_send_profile_nudges(db)
        await use_case.execute(
            SendProfileNudgesCommand(academy_id=ACADEMY_ID, now=datetime(2026, 1, 1, tzinfo=UTC))
        )

    assert await db["profile_nudges"].find_one({"parent_id": "parent-9"}) is None
```

- [ ] Run — expect an import error:

```bash
cd backend && .venv/bin/pytest v2/tests/contract/test_compose_profile_nudges.py -q
```

- [ ] Implement the composition module:

```python
# backend/v2/composition/profile_nudges.py
"""Compose SendProfileNudges (birthdays-and-profile-nudges spec §5).

Bridges enrollment (students, enrollments) and identity (parent users) into
communications' ProfileFactsProvider, exactly the way composition/digests.py
bridges data for the parent daily digest — communications imports nothing
from either context (ADR-0005).
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.composition.digests import _build_email_sender, compose_unsubscribe_link_builder
from backend.v2.contexts.communications.application.use_cases.send_profile_nudges import (
    SendProfileNudges,
)
from backend.v2.contexts.communications.infrastructure.mongo_audience_resolver import (
    MongoAudienceResolver,
)
from backend.v2.contexts.communications.infrastructure.mongo_nudge_record_repo import (
    MongoNudgeRecordRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_repo import (
    MongoEnrollmentRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)
from backend.v2.shared.config.settings import get_settings
from backend.v2.shared.profile.completeness import ChildFacts, ParentFacts
from backend.v2.shared.tenancy.academy_url import academy_frontend_url


class _ProfileFactsProvider:
    def __init__(
        self,
        students: MongoStudentRepository,
        enrollments: MongoEnrollmentRepository,
    ) -> None:
        self._students = students
        self._enrollments = enrollments

    async def has_current_student(self, parent_id: str) -> bool:
        for student in await self._students.list_for_parent(parent_id):
            if await self._enrollments.departable_for_student(student.student_id):
                return True
        return False

    async def facts_for_parent(self, parent_id: str):
        user = await self._students.get_parent_user_doc(parent_id)
        if user is None:
            return None
        parent_facts = ParentFacts(
            display_name=user.get("display_name"),
            phone=user.get("phone"),
            email_confirmed_at=user.get("email_confirmed_at"),
        )
        children = await self._students.list_for_parent(parent_id)
        child_facts = [
            ChildFacts(
                student_id=c.student_id,
                full_name=c.full_name,
                date_of_birth=c.date_of_birth,
                emergency_contact_name=c.emergency_contact_name,
                emergency_contact_phone=c.emergency_contact_phone,
                medical_notes=c.medical_notes,
            )
            for c in children
        ]
        return parent_facts, child_facts


def compose_send_profile_nudges(db: AsyncIOMotorDatabase[Any]) -> SendProfileNudges:
    settings = get_settings()
    return SendProfileNudges(
        resolver=MongoAudienceResolver(db),
        facts=_ProfileFactsProvider(
            students=MongoStudentRepository(db),
            enrollments=MongoEnrollmentRepository(db),
        ),
        records=MongoNudgeRecordRepository(db),
        sender=_build_email_sender(settings, db),
        unsubscribe_links=compose_unsubscribe_link_builder(settings),
    )


def profile_url_for(academy_slug: str | None) -> str | None:
    base = academy_frontend_url(
        frontend_url=get_settings().frontend_url, academy_slug=academy_slug
    )
    return f"{base}/parent/profile" if base else None
```

`MEDICAL_NONE_SENTINEL` is deliberately NOT imported: this module never branches on it (`completeness.medical_notes_answered` already treats the sentinel as "answered"), and ruff's `F` ruleset — enabled repo-wide in `backend/pyproject.toml` — fails the build on an unused import.

- [ ] Run — expect PASS:

```bash
cd backend && .venv/bin/pytest v2/tests/contract/test_compose_profile_nudges.py -q
cd backend && .venv/bin/ruff check v2/composition/profile_nudges.py
```

- [ ] Wire the scheduled job in `main.py`. Add near the other composition imports:

```python
from backend.v2.composition.profile_nudges import compose_send_profile_nudges, profile_url_for
```

Add inside `_lifespan`, alongside the other leased jobs (near `_send_hold_reminders`):

```python
    app.state.profile_nudges = compose_send_profile_nudges(db)

    async def _send_profile_nudges() -> None:
        await _run_leased_job(
            "send_profile_nudges", timedelta(minutes=20), _send_profile_nudges_body
        )

    async def _send_profile_nudges_body() -> None:
        now = datetime.now(scheduler.timezone)  # type: ignore[union-attr]
        academy_repo = MongoAcademyRepository(db)
        totals = {"eligible_parents": 0, "sent": 0, "closed": 0, "failed": 0, "academy_count": 0}
        for academy_id in await _scheduler_academy_ids(academy_repo, runtime_academy_id):
            # MongoAcademyRepository is NOT tenant-scoped (it filters on
            # academy_id itself), so this read is legal outside tenant_scope.
            doc = await academy_repo.find_by_id(academy_id)
            slug = str((doc or {}).get("slug") or "") or None
            with tenant_scope(academy_id):
                result = await app.state.profile_nudges.execute(
                    SendProfileNudgesCommand(
                        academy_id=academy_id,
                        now=now,
                        profile_url=profile_url_for(slug),
                        academy_slug=slug,
                    )
                )
            totals["academy_count"] += 1
            totals["eligible_parents"] += result.eligible_parents
            totals["sent"] += result.sent
            totals["closed"] += result.closed
            totals["failed"] += result.failed
        if totals["sent"] or totals["closed"]:
            log.info("profile_nudges_processed", extra=totals)
```

Add the import for `SendProfileNudgesCommand` next to the other use-case imports, and register the job next to `send_hold_reminders`:

```python
    scheduler.add_job(
        _send_profile_nudges,
        "cron",
        hour=5,
        minute=0,
        id="send_profile_nudges",
        replace_existing=True,
        max_instances=1,
    )
```

- [ ] Add the two new tables. In `main.py`'s `SCHEDULED_JOB_MONITORS`:

```python
    "send_profile_nudges": {
        "schedule": {"type": "crontab", "value": "0 5 * * *"},
        "checkin_margin": 30,
        "max_runtime": 30,
    },
```

In `backend/v2/shared/observability/ops_digest.py`'s `JOB_STALE_AFTER`:

```python
    "send_profile_nudges": timedelta(hours=26),
```

- [ ] Update the hardcoded job count in `backend/v2/tests/unit/test_scheduler_academies.py`:

```python
    assert len(registered) == 13
```

becomes (this task only adds one job; Task 10 adds the second and bumps it again to 15):

```python
    assert len(registered) == 14
```

- [ ] Run the scheduler-table structural test and the new contract test:

```bash
cd backend && .venv/bin/pytest v2/tests/unit/test_scheduler_academies.py v2/tests/contract/test_compose_profile_nudges.py -q
```

- [ ] Commit:

```bash
git add backend/v2/composition/profile_nudges.py backend/v2/main.py \
        backend/v2/shared/observability/ops_digest.py \
        backend/v2/tests/unit/test_scheduler_academies.py \
        backend/v2/tests/contract/test_compose_profile_nudges.py
git commit -m "$(cat <<'EOF'
feat(communications): schedule the daily send_profile_nudges job

Composes SendProfileNudges over the real enrollment/identity repos and
registers it as a new daily 05:00 scheduler-timezone cron, with its own
dead-man threshold and Sentry Crons monitor config.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Birthday send claim repositories and `SendBirthdayNotes` use case

**Files:**
- Create: `backend/v2/composition/birthday_notice_send_repo.py`
- Create: `backend/v2/contexts/communications/application/birthday_renderer.py`
- Create: `backend/v2/contexts/communications/application/use_cases/send_birthday_notes.py`
- Test: `backend/v2/tests/unit/test_birthday_renderer.py`
- Test: `backend/v2/tests/unit/test_send_birthday_notes.py`
- Test: `backend/v2/tests/contract/test_birthday_notice_send_repo.py`

**Interfaces:**
- Consumes: `claim_digest_send` (`communications/infrastructure/digest_claim.py`); `DigestSendStatus` (`communications/domain/models.py`); `EmailSendPort`, `ResolvedRecipient` (`ports.py`).
- Produces: `MongoBirthdayNoticeSendRepository.try_claim(academy_id, student_id, year) -> dict|None`, `.mark_sent`, `.mark_failed`; `render_birthday_note(first_name, *, brand) -> tuple[str,str]`; `BirthdayCandidate` (dataclass); `BirthdayRecipientProvider` protocol; `SendBirthdayNotes`.

- [ ] Write the failing repo contract test:

```python
# backend/v2/tests/contract/test_birthday_notice_send_repo.py
from __future__ import annotations

import pytest

from backend.v2.composition.birthday_notice_send_repo import MongoBirthdayNoticeSendRepository
from backend.v2.shared.tenancy.context import tenant_scope

ACADEMY_ID = "acad-bday-claim"


@pytest.mark.asyncio
async def test_claim_succeeds_once_per_student_per_year(db) -> None:
    with tenant_scope(ACADEMY_ID):
        repo = MongoBirthdayNoticeSendRepository(db)
        first = await repo.try_claim(academy_id=ACADEMY_ID, student_id="s1", year=2026)
        assert first is not None
        await repo.mark_sent(first["send_id"])

        second = await repo.try_claim(academy_id=ACADEMY_ID, student_id="s1", year=2026)
        assert second is None  # already sent this year — no duplicate


@pytest.mark.asyncio
async def test_next_years_birthday_claims_independently(db) -> None:
    with tenant_scope(ACADEMY_ID):
        repo = MongoBirthdayNoticeSendRepository(db)
        first = await repo.try_claim(academy_id=ACADEMY_ID, student_id="s2", year=2026)
        assert first is not None
        await repo.mark_sent(first["send_id"])

        next_year = await repo.try_claim(academy_id=ACADEMY_ID, student_id="s2", year=2027)
        assert next_year is not None
```

- [ ] Write the failing renderer test:

```python
# backend/v2/tests/unit/test_birthday_renderer.py
from __future__ import annotations

from backend.v2.contexts.communications.application.birthday_renderer import (
    render_birthday_note,
)
from backend.v2.shared.comms.email_theme import EmailBrand


def test_subject_greets_the_child_by_first_name() -> None:
    subject, _ = render_birthday_note("Aanya", brand=EmailBrand(academy_name="Smash Academy"))
    assert "Happy birthday" in subject
    assert "Aanya" in subject


def test_body_has_no_call_to_action_button() -> None:
    _, body = render_birthday_note("Aanya", brand=EmailBrand(academy_name="Smash Academy"))
    assert "<a " not in body  # no CTA link, per spec §4.2


def test_body_is_academy_branded() -> None:
    _, body = render_birthday_note("Aanya", brand=EmailBrand(academy_name="Smash Academy"))
    assert "Smash Academy" in body


def test_body_always_carries_the_unsubscribe_notice() -> None:
    """spec §4.2: "unsubscribe footer". With no URL the footer degrades to
    the portal sentence (`unsubscribe_footer._FALLBACK_TEXT`) — never absent."""
    _, plain = render_birthday_note("Aanya", brand=EmailBrand(academy_name="Smash Academy"))
    assert "email preferences" in plain

    _, linked = render_birthday_note(
        "Aanya",
        brand=EmailBrand(academy_name="Smash Academy"),
        unsubscribe_url="https://smash.example.com/unsubscribe?t=abc",
    )
    assert "https://smash.example.com/unsubscribe?t=abc" in linked
    assert "Unsubscribe from these emails" in linked
```

- [ ] Write the failing use-case test:

```python
# backend/v2/tests/unit/test_send_birthday_notes.py
from __future__ import annotations

from dataclasses import dataclass

import pytest

from backend.v2.contexts.communications.application.ports import ResolvedRecipient, SendOutcome
from backend.v2.contexts.communications.application.use_cases.send_birthday_notes import (
    BirthdayCandidate,
    SendBirthdayNotes,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory


@dataclass
class _FakeCandidates:
    candidates: list[BirthdayCandidate]

    async def todays_candidates(self):
        return self.candidates


class _FakeClaims:
    def __init__(self, allow: bool = True) -> None:
        self.allow = allow
        self.marked_sent: list[str] = []
        self.marked_failed: list[tuple[str, str]] = []

    async def try_claim(self, *, academy_id: str, student_id: str, year: int):
        if not self.allow:
            return None
        return {"send_id": f"send-{student_id}-{year}"}

    async def mark_sent(self, send_id: str) -> None:
        self.marked_sent.append(send_id)

    async def mark_failed(self, send_id: str, reason: str, *, retryable: bool = True) -> None:
        self.marked_failed.append((send_id, reason))


class _FakeSender:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    async def send(self, *, recipient, subject, body, cc=None, bcc=None, reply_to=None, category):
        self.sent.append({"recipient": recipient, "category": category})
        return SendOutcome(ok=True, provider_message_id="m1", failed_reason=None)


@pytest.mark.asyncio
async def test_sends_one_email_per_candidate_and_claims_it() -> None:
    candidates = _FakeCandidates(
        [
            BirthdayCandidate(
                student_id="s1",
                first_name="Aanya",
                parent_id="p1",
                parent_email="p1@example.com",
                parent_name="Parent One",
                year=2026,
            )
        ]
    )
    claims = _FakeClaims()
    sender = _FakeSender()
    use_case = SendBirthdayNotes(candidates=candidates, claims=claims, sender=sender)

    result = await use_case.execute(academy_id="a1")

    assert result.sent == 1
    assert claims.marked_sent == ["send-s1-2026"]
    assert sender.sent[0]["category"] == EmailCategory.NOTIFICATION
    assert sender.sent[0]["recipient"].email == "p1@example.com"


@pytest.mark.asyncio
async def test_already_claimed_student_is_skipped() -> None:
    candidates = _FakeCandidates(
        [
            BirthdayCandidate(
                student_id="s1",
                first_name="Aanya",
                parent_id="p1",
                parent_email="p1@example.com",
                parent_name="Parent One",
                year=2026,
            )
        ]
    )
    claims = _FakeClaims(allow=False)
    sender = _FakeSender()
    use_case = SendBirthdayNotes(candidates=candidates, claims=claims, sender=sender)

    result = await use_case.execute(academy_id="a1")

    assert result.sent == 0
    assert sender.sent == []


@pytest.mark.asyncio
async def test_no_parent_email_is_a_non_retryable_failure() -> None:
    candidates = _FakeCandidates(
        [
            BirthdayCandidate(
                student_id="s1",
                first_name="Aanya",
                parent_id="p1",
                parent_email=None,
                parent_name="Parent One",
                year=2026,
            )
        ]
    )
    claims = _FakeClaims()
    sender = _FakeSender()
    use_case = SendBirthdayNotes(candidates=candidates, claims=claims, sender=sender)

    result = await use_case.execute(academy_id="a1")

    assert result.failed == 1
    assert claims.marked_failed == [("send-s1-2026", "no email address")]
```

- [ ] Run all three new tests — expect import errors:

```bash
cd backend && .venv/bin/pytest v2/tests/unit/test_birthday_renderer.py v2/tests/unit/test_send_birthday_notes.py v2/tests/contract/test_birthday_notice_send_repo.py -q
```

- [ ] Implement the claim repository (mirrors `composition/absence_notifications.py::MongoAbsenceNoticeSendRepository`):

```python
# backend/v2/composition/birthday_notice_send_repo.py
"""Send claims for the two birthday-related emails (family note, staff
weekly digest). Structurally MongoAbsenceNoticeSendRepository with a
different recipient field per collection. Lives in composition/ because it
bridges enrollment-derived facts (student_id, or the admin/owner user_id)
into communications' digest_claim — neither context may import the other.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.v2.contexts.communications.domain.models import DigestSendStatus
from backend.v2.contexts.communications.infrastructure.digest_claim import claim_digest_send
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoBirthdayNoticeSendRepository(TenantScopedRepository):
    """Family birthday email claim. Migration 0174 indexes
    (academy_id, student_id, digest_date) unique, where digest_date carries
    the YEAR (spec §3: "key (academy_id, student_id, year)")."""

    collection_name = "birthday_notice_sends"

    async def try_claim(
        self, *, academy_id: str, student_id: str, year: int
    ) -> dict[str, Any] | None:
        digest_date = str(year)
        doc = {
            "send_id": str(new_ulid()),
            "academy_id": academy_id,
            "student_id": student_id,
            "digest_date": digest_date,
            "status": str(DigestSendStatus.QUEUED),
            "provider_message_id": None,
            "failed_reason": None,
            "created_at": datetime.now(UTC),
            "attempt_count": 1,
            "retryable": True,
        }
        return await claim_digest_send(
            self.collection,
            doc=doc,
            academy_id=academy_id,
            recipient_field="student_id",
            recipient_id=student_id,
            digest_date=digest_date,
        )

    async def mark_sent(self, send_id: str) -> None:
        await self.collection.update_one(
            {"send_id": send_id},
            {"$set": {"status": str(DigestSendStatus.SENT), "failed_reason": None}},
        )

    async def mark_failed(self, send_id: str, reason: str, *, retryable: bool = True) -> None:
        await self.collection.update_one(
            {"send_id": send_id},
            {
                "$set": {
                    "status": str(DigestSendStatus.FAILED),
                    "failed_reason": reason,
                    "retryable": retryable,
                }
            },
        )


class MongoBirthdayStaffDigestSendRepository(TenantScopedRepository):
    """Admin/owner weekly "Birthdays this week" email claim. Migration 0174
    indexes (academy_id, user_id, digest_date) unique, where digest_date
    carries the ISO date of that week's Monday."""

    collection_name = "birthday_staff_digest_sends"

    async def try_claim(
        self, *, academy_id: str, user_id: str, week_of: str
    ) -> dict[str, Any] | None:
        doc = {
            "send_id": str(new_ulid()),
            "academy_id": academy_id,
            "user_id": user_id,
            "digest_date": week_of,
            "status": str(DigestSendStatus.QUEUED),
            "provider_message_id": None,
            "failed_reason": None,
            "created_at": datetime.now(UTC),
            "attempt_count": 1,
            "retryable": True,
        }
        return await claim_digest_send(
            self.collection,
            doc=doc,
            academy_id=academy_id,
            recipient_field="user_id",
            recipient_id=user_id,
            digest_date=week_of,
        )

    async def mark_sent(self, send_id: str) -> None:
        await self.collection.update_one(
            {"send_id": send_id},
            {"$set": {"status": str(DigestSendStatus.SENT), "failed_reason": None}},
        )

    async def mark_failed(self, send_id: str, reason: str, *, retryable: bool = True) -> None:
        await self.collection.update_one(
            {"send_id": send_id},
            {
                "$set": {
                    "status": str(DigestSendStatus.FAILED),
                    "failed_reason": reason,
                    "retryable": retryable,
                }
            },
        )
```

- [ ] Run the repo contract test — expect PASS:

```bash
cd backend && .venv/bin/pytest v2/tests/contract/test_birthday_notice_send_repo.py -q
```

- [ ] Implement `birthday_renderer.py`:

```python
# backend/v2/contexts/communications/application/birthday_renderer.py
"""Renders the family birthday note and the shared "Birthdays this week"
HTML fragment (reused by the coach-digest block and the standalone staff
email — Task 12)."""

from __future__ import annotations

import html
from collections.abc import Sequence
from dataclasses import dataclass

from backend.v2.contexts.communications.application.unsubscribe_footer import (
    append_unsubscribe_footer,
)
from backend.v2.shared.comms.email_theme import INK, LINE, MUTED, EmailBrand, shell


def render_birthday_note(
    first_name: str, *, brand: EmailBrand, unsubscribe_url: str | None = None
) -> tuple[str, str]:
    """One email, one student, no call to action (spec §4.2).

    "No call to action" means no button and no link into the app — it does
    NOT mean no unsubscribe footer: spec §4.2 asks for one explicitly, and
    `GatedEmailSendPort` blocks opted-out recipients without ever rendering
    the opt-out notice for everyone else.
    """
    safe_name = html.escape(first_name)
    subject = f"Happy birthday, {safe_name}!"
    inner = (
        f'<p style="font-size:16px;margin:0;">'
        f"Happy birthday, {safe_name}! Everyone at {html.escape(brand.academy_name)} "
        f"hopes you have a wonderful day.</p>"
    )
    body = shell(brand=brand, inner_html=inner, footer_html="")
    return subject, append_unsubscribe_footer(body, unsubscribe_url)


@dataclass(frozen=True, slots=True)
class BirthdayEntry:
    student_name: str
    age_turning: int
    day_label: str
    class_names: tuple[str, ...]
    parent_name: str
    withdrawn_on: str | None = None


def render_birthdays_block(entries: Sequence[BirthdayEntry]) -> str:
    """An HTML fragment: a heading plus one row per birthday. Empty when
    ``entries`` is empty, so callers can always splice this in unconditionally."""
    if not entries:
        return ""
    rows = "".join(_entry_row(e) for e in entries)
    return (
        f'<h3 style="color:{INK};font-size:16px;margin:20px 0 8px;">Birthdays this week</h3>'
        f'<div style="border-top:1px solid {LINE};">{rows}</div>'
    )


def _entry_row(entry: BirthdayEntry) -> str:
    classes = ", ".join(entry.class_names) if entry.class_names else "not enrolled"
    left_note = f" — left on {html.escape(entry.withdrawn_on)}" if entry.withdrawn_on else ""
    return (
        f'<div style="padding:8px 0;border-bottom:1px solid {LINE};font-size:13px;">'
        f'<strong style="color:{INK};">{html.escape(entry.student_name)}</strong> '
        f'turns {entry.age_turning} on {html.escape(entry.day_label)} '
        f'<span style="color:{MUTED};">({html.escape(classes)}, '
        f'parent: {html.escape(entry.parent_name)}){left_note}</span>'
        f"</div>"
    )
```

- [ ] Run the renderer test — expect PASS:

```bash
cd backend && .venv/bin/pytest v2/tests/unit/test_birthday_renderer.py -q
```

- [ ] Implement `send_birthday_notes.py`:

```python
# backend/v2/contexts/communications/application/use_cases/send_birthday_notes.py
"""SendBirthdayNotes use case (birthdays-and-profile-nudges spec §4.2).

One email per student with a birthday today, to their parent, claimed
per (academy_id, student_id, year) so a job re-run can never double-send.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from backend.v2.contexts.communications.application.birthday_renderer import (
    render_birthday_note,
)
from backend.v2.contexts.communications.application.ports import EmailSendPort, ResolvedRecipient
from backend.v2.contexts.communications.application.unsubscribe_token import (
    UnsubscribeLinkBuilder,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.shared.comms.email_theme import EmailBrand


@dataclass(frozen=True, slots=True)
class BirthdayCandidate:
    student_id: str
    first_name: str
    parent_id: str
    parent_email: str | None
    parent_name: str | None
    year: int


class BirthdayCandidateProvider(Protocol):
    async def todays_candidates(self) -> list[BirthdayCandidate]: ...


class BirthdayNoticeClaims(Protocol):
    # `dict[str, Any]`, not `dict[str, object]`: the claim row's `send_id`
    # is passed straight into `mark_sent(send_id: str)`, and under
    # `mypy --strict` an `object` value there is an arg-type error.
    async def try_claim(
        self, *, academy_id: str, student_id: str, year: int
    ) -> dict[str, Any] | None: ...

    async def mark_sent(self, send_id: str) -> None: ...

    async def mark_failed(self, send_id: str, reason: str, *, retryable: bool = True) -> None: ...


@dataclass(frozen=True, slots=True)
class SendBirthdayNotesResult:
    total_candidates: int = 0
    sent: int = 0
    already_claimed: int = 0
    failed: int = 0


@dataclass
class SendBirthdayNotes:
    candidates: BirthdayCandidateProvider
    claims: BirthdayNoticeClaims
    sender: EmailSendPort
    brand: EmailBrand | None = None
    # spec §4.2 asks for an unsubscribe footer on the family note; the gate
    # only blocks opted-out recipients, it renders nothing.
    unsubscribe_links: UnsubscribeLinkBuilder = field(default_factory=UnsubscribeLinkBuilder)
    academy_slug: str | None = None

    async def execute(self, *, academy_id: str) -> SendBirthdayNotesResult:
        candidates = await self.candidates.todays_candidates()
        sent = already_claimed = failed = 0

        for candidate in candidates:
            claim = await self.claims.try_claim(
                academy_id=academy_id, student_id=candidate.student_id, year=candidate.year
            )
            if claim is None:
                already_claimed += 1
                continue

            send_id = str(claim["send_id"])
            if not candidate.parent_email:
                await self.claims.mark_failed(send_id, "no email address", retryable=False)
                failed += 1
                continue

            subject, body = render_birthday_note(
                candidate.first_name,
                brand=self.brand or EmailBrand(academy_name="Your academy"),
                unsubscribe_url=self.unsubscribe_links.build(
                    academy_id=academy_id,
                    user_id=candidate.parent_id,
                    academy_slug=self.academy_slug,
                ),
            )
            outcome = await self.sender.send(
                recipient=ResolvedRecipient(
                    user_id=candidate.parent_id,
                    email=candidate.parent_email,
                    display_name=candidate.parent_name,
                ),
                subject=subject,
                body=body,
                category=EmailCategory.NOTIFICATION,
            )
            if outcome.ok:
                await self.claims.mark_sent(send_id)
                sent += 1
            else:
                await self.claims.mark_failed(
                    send_id,
                    outcome.failed_reason or "unknown",
                    retryable=not outcome.suppressed,
                )
                failed += 1

        return SendBirthdayNotesResult(
            total_candidates=len(candidates),
            sent=sent,
            already_claimed=already_claimed,
            failed=failed,
        )
```

- [ ] Run all three tests — expect PASS:

```bash
cd backend && .venv/bin/pytest v2/tests/unit/test_birthday_renderer.py v2/tests/unit/test_send_birthday_notes.py v2/tests/contract/test_birthday_notice_send_repo.py -q
```

- [ ] Commit:

```bash
git add backend/v2/composition/birthday_notice_send_repo.py \
        backend/v2/contexts/communications/application/birthday_renderer.py \
        backend/v2/contexts/communications/application/use_cases/send_birthday_notes.py \
        backend/v2/tests/unit/test_birthday_renderer.py \
        backend/v2/tests/unit/test_send_birthday_notes.py \
        backend/v2/tests/contract/test_birthday_notice_send_repo.py
git commit -m "$(cat <<'EOF'
feat(communications): add SendBirthdayNotes and the birthday claim repos

One email per birthday student per year, claimed via digest_claim keyed
(academy_id, student_id, year); no call-to-action, NOTIFICATION category.
Also adds the shared BirthdayEntry/render_birthdays_block fragment used by
the staff digest in Task 12.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: Birthday candidate query, composition, and the `send_birthday_notes` job

**Files:**
- Create: `backend/v2/composition/birthdays.py`
- Modify: `backend/v2/main.py` (job registration)
- Modify: `backend/v2/shared/observability/ops_digest.py` (`JOB_STALE_AFTER`)
- Modify: `backend/v2/tests/unit/test_scheduler_academies.py` (`registered` count -> 15)
- Test: `backend/v2/tests/contract/test_compose_birthdays.py`

**Interfaces:**
- Consumes: `todays_birthday_month_days` (Task 1); `MongoEnrollmentRepository.departable_for_student`; `MongoStudentRepository.get_parent_user_doc`; `MongoBirthdayNoticeSendRepository` (Task 9); `SendBirthdayNotes` (Task 9); `birthday_emails_enabled` setting (produced in Task 11 — read defensively here as `False` when absent, since Task 10 lands before Task 11).
- Produces: `compose_send_birthday_notes(db) -> SendBirthdayNotes`.

- [ ] Write the failing contract test:

```python
# backend/v2/tests/contract/test_compose_birthdays.py
from __future__ import annotations

from datetime import date

import pytest

from backend.v2.composition.birthdays import (
    birthday_emails_enabled,
    compose_send_birthday_notes,
)
from backend.v2.shared.tenancy.context import tenant_scope

ACADEMY_ID = "acad-bday-compose"


async def _seed_birthday_student(db, *, today: date, status: str = "active") -> None:
    await db["students"].insert_one(
        {
            "academy_id": ACADEMY_ID,
            "student_id": "student-bday-1",
            "parent_id": "parent-bday-1",
            "full_name": "Aanya Kapoor",
            "date_of_birth": f"2016-{today.month:02d}-{today.day:02d}",
            "birth_month_day": f"{today.month:02d}-{today.day:02d}",
        }
    )
    await db["users"].insert_one(
        {
            "academy_id": ACADEMY_ID,
            "user_id": "parent-bday-1",
            "email": "parent-bday-1@example.com",
            "display_name": "Kapoor Family",
        }
    )
    await db["enrollments"].insert_one(
        {
            "academy_id": ACADEMY_ID,
            "enrollment_id": "enr-bday-1",
            "student_id": "student-bday-1",
            "session_id": "sess-bday-1",
            "status": status,
        }
    )


@pytest.mark.asyncio
async def test_sends_to_an_enrolled_students_parent(db) -> None:
    today = date(2026, 3, 7)
    with tenant_scope(ACADEMY_ID):
        await _seed_birthday_student(db, today=today)
        use_case = compose_send_birthday_notes(db, today=today)
        result = await use_case.execute(academy_id=ACADEMY_ID)

    assert result.sent == 1


@pytest.mark.asyncio
async def test_withdrawn_only_student_is_not_emailed(db) -> None:
    today = date(2026, 3, 7)
    with tenant_scope(ACADEMY_ID):
        await _seed_birthday_student(db, today=today, status="dropped")
        use_case = compose_send_birthday_notes(db, today=today)
        result = await use_case.execute(academy_id=ACADEMY_ID)

    assert result.total_candidates == 0
    assert result.sent == 0


def test_birthday_emails_are_off_unless_the_academy_turned_them_on() -> None:
    """spec §7: "setting off -> no family email". This is the predicate the
    scheduler job in main.py gates on; it lives in composition/birthdays.py
    precisely so it is reachable from a test."""
    assert birthday_emails_enabled(None) is False
    assert birthday_emails_enabled({}) is False
    assert birthday_emails_enabled({"notifications": {}}) is False
    assert birthday_emails_enabled({"notifications": {"birthday_emails_enabled": False}}) is False
    assert birthday_emails_enabled({"notifications": {"birthday_emails_enabled": True}}) is True
```

- [ ] Run — expect an import error:

```bash
cd backend && .venv/bin/pytest v2/tests/contract/test_compose_birthdays.py -q
```

- [ ] Implement:

```python
# backend/v2/composition/birthdays.py
"""Compose SendBirthdayNotes (birthdays-and-profile-nudges spec §4.2).

Bridges enrollment (students, enrollments) and identity (parent users) into
communications' BirthdayCandidateProvider. Lives here, not in
contexts/communications, for the same cross-context reason as
composition/digests.py and composition/absence_notifications.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.composition.birthday_notice_send_repo import MongoBirthdayNoticeSendRepository
from backend.v2.composition.digests import _build_email_sender, compose_unsubscribe_link_builder
from backend.v2.contexts.communications.application.use_cases.send_birthday_notes import (
    BirthdayCandidate,
    SendBirthdayNotes,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_repo import (
    MongoEnrollmentRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)
from backend.v2.shared.config.settings import get_settings
from backend.v2.shared.profile.birthdays import todays_birthday_month_days


@dataclass
class _BirthdayCandidateProvider:
    students: MongoStudentRepository
    enrollments: MongoEnrollmentRepository
    today: date

    async def todays_candidates(self) -> list[BirthdayCandidate]:
        month_days = todays_birthday_month_days(self.today)
        # `_find_many` (tenant-scoped) is the established composition-layer
        # read helper — see composition/coach.py:382 and composition/admin.py.
        # Do NOT add `# noqa: SLF001`: ruff's select list in
        # backend/pyproject.toml is ["E","F","I","W","UP","B","ASYNC","RUF"],
        # SLF is not enabled, and RUF100 fails the build on an unknown noqa.
        cursor = self.students._find_many(
            {"birth_month_day": {"$in": list(month_days)}, "is_deleted": {"$ne": True}}
        )
        out: list[BirthdayCandidate] = []
        async for doc in cursor:
            student_id = str(doc.get("student_id") or "")
            if not await self.enrollments.departable_for_student(student_id):
                continue
            parent_id = str(doc.get("parent_id") or doc.get("parent_user_id") or "")
            parent = await self.students.get_parent_user_doc(parent_id)
            full_name = str(doc.get("full_name") or "").strip()
            first_name = full_name.split(" ", 1)[0] if full_name else "there"
            out.append(
                BirthdayCandidate(
                    student_id=student_id,
                    first_name=first_name,
                    parent_id=parent_id,
                    parent_email=(parent or {}).get("email"),
                    parent_name=(parent or {}).get("display_name"),
                    year=self.today.year,
                )
            )
        return out


def birthday_emails_enabled(academy_doc: dict[str, Any] | None) -> bool:
    """The per-academy gate for the FAMILY birthday email (spec §4.2).

    Read off the raw ``notifications`` subdoc exactly as ``main.py`` reads
    ``coach_digest_enabled``. Extracted as a named function purely so spec
    §7's "setting off -> no family email" case is testable: the alternative
    is a two-line ``if`` buried in a ``main.py`` job body that no test
    reaches. Default False — an academy that has never saved the setting
    sends nothing.
    """
    notifs = (academy_doc or {}).get("notifications") or {}
    return bool(notifs.get("birthday_emails_enabled", False))


def compose_send_birthday_notes(
    db: AsyncIOMotorDatabase[Any],
    *,
    today: date | None = None,
    academy_slug: str | None = None,
) -> SendBirthdayNotes:
    settings = get_settings()
    return SendBirthdayNotes(
        candidates=_BirthdayCandidateProvider(
            students=MongoStudentRepository(db),
            enrollments=MongoEnrollmentRepository(db),
            today=today or datetime.now(UTC).date(),
        ),
        claims=MongoBirthdayNoticeSendRepository(db),
        sender=_build_email_sender(settings, db),
        unsubscribe_links=compose_unsubscribe_link_builder(settings),
        academy_slug=academy_slug,
    )
```

- [ ] Run — expect PASS:

```bash
cd backend && .venv/bin/pytest v2/tests/contract/test_compose_birthdays.py -q
```

- [ ] Wire the job in `main.py`. Import:

```python
from backend.v2.composition.birthdays import (
    birthday_emails_enabled,
    compose_send_birthday_notes,
)
```

Inside `_lifespan`, gate the send on the (Task 11) `birthday_emails_enabled` setting, read per-academy from the raw academy doc the same way `coach_digest_enabled` is read:

```python
    async def _send_birthday_notes() -> None:
        await _run_leased_job(
            "send_birthday_notes", timedelta(minutes=15), _send_birthday_notes_body
        )

    async def _send_birthday_notes_body() -> None:
        academy_repo = MongoAcademyRepository(db)
        totals = {"sent": 0, "already_claimed": 0, "failed": 0, "academy_count": 0}
        for academy_id in await _scheduler_academy_ids(academy_repo, runtime_academy_id):
            doc = await academy_repo.find_by_id(academy_id)
            if not birthday_emails_enabled(doc):
                continue
            slug = str((doc or {}).get("slug") or "") or None
            with tenant_scope(academy_id):
                use_case = compose_send_birthday_notes(db, academy_slug=slug)
                result = await use_case.execute(academy_id=academy_id)
            totals["academy_count"] += 1
            totals["sent"] += result.sent
            totals["already_claimed"] += result.already_claimed
            totals["failed"] += result.failed
        if totals["sent"] or totals["failed"]:
            log.info("birthday_notes_processed", extra=totals)
```

Register it next to `send_hold_reminders`:

```python
    scheduler.add_job(
        _send_birthday_notes,
        "cron",
        hour=6,
        minute=0,
        id="send_birthday_notes",
        replace_existing=True,
        max_instances=1,
    )
```

- [ ] Add to `SCHEDULED_JOB_MONITORS`:

```python
    "send_birthday_notes": {
        "schedule": {"type": "crontab", "value": "0 6 * * *"},
        "checkin_margin": 30,
        "max_runtime": 30,
    },
```

Add to `JOB_STALE_AFTER` in `ops_digest.py`:

```python
    "send_birthday_notes": timedelta(hours=26),
```

- [ ] Bump `test_scheduler_academies.py`'s count again:

```python
    assert len(registered) == 15
```

- [ ] Run the scheduler and contract tests:

```bash
cd backend && .venv/bin/pytest v2/tests/unit/test_scheduler_academies.py v2/tests/contract/test_compose_birthdays.py -q
```

- [ ] Commit:

```bash
git add backend/v2/composition/birthdays.py backend/v2/main.py \
        backend/v2/shared/observability/ops_digest.py \
        backend/v2/tests/unit/test_scheduler_academies.py \
        backend/v2/tests/contract/test_compose_birthdays.py
git commit -m "$(cat <<'EOF'
feat(communications): schedule the daily send_birthday_notes job

Candidates are students whose birth_month_day matches today (leap-day
aware) with a current (active/held/paused) enrollment; gated per-academy on
notifications.birthday_emails_enabled (default off, wired in the next
commit) so nothing sends until an owner turns it on.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: `birthday_emails_enabled` setting, end to end

**Files:**
- Modify: `backend/v2/contexts/identity/application/get_academy_notifications_use_case.py`
- Modify: `backend/v2/interfaces/admin/views.py` (`AdminNotificationsView`, `UpdateAdminNotificationsRequest`)
- Modify: `frontend/lib/api/admin.ts` (`AdminNotificationsView`)
- Modify: `frontend/components/admin/settings/notify-panel.tsx`
- Test: extend `backend/v2/tests/application/identity/test_academy_use_cases.py` — verified: that is where `GetAcademyNotificationsUseCase` / `UpdateAcademyNotificationsUseCase` are already tested. Do **not** create `tests/unit/test_academy_notifications.py`; there is no such file and no `notif`-named file under `tests/unit/`. `backend/v2/tests/interface/test_admin_settings.py` covers the route round-trip.
- No frontend test. `frontend/components/admin/settings/` has no `__tests__/` directory, no sibling panel is unit-tested, and frontend vitest files run in no CI job today. The toggle's coverage is `pnpm typecheck` (the `AdminNotificationsView` field is required, so a missed `normalize()` key is a compile error) plus the backend round-trip test above. Do not invent a test harness for one checkbox.

**Interfaces:**
- Produces: `GetAcademyNotificationsOutput.birthday_emails_enabled: bool = False`.

- [ ] Append the failing tests to the existing suite (already verified to live here; the fakes below are self-contained, so they can be pasted at the end of the file):

```python
# appended to backend/v2/tests/application/identity/test_academy_use_cases.py
from __future__ import annotations

import pytest

from backend.v2.contexts.identity.application.get_academy_notifications_use_case import (
    GetAcademyNotificationsUseCase,
)
from backend.v2.contexts.identity.application.update_academy_notifications_use_case import (
    UpdateAcademyNotificationsUseCase,
)


class _FakeAcademyRepo:
    def __init__(self, doc: dict[str, object] | None = None) -> None:
        self.doc = doc or {"academy_id": "a1", "notifications": {}}

    async def find_by_id(self, academy_id: str):
        return self.doc

    async def upsert_defaults(self, academy_id: str):
        return self.doc

    async def update_by_id(self, academy_id: str, fields: dict[str, object]):
        for key, value in fields.items():
            _, _, leaf = key.partition(".")
            self.doc.setdefault("notifications", {})[leaf] = value
        return self.doc


@pytest.mark.asyncio
async def test_birthday_emails_enabled_defaults_to_false() -> None:
    use_case = GetAcademyNotificationsUseCase(_FakeAcademyRepo())
    out = await use_case.execute("a1")
    assert out.birthday_emails_enabled is False


@pytest.mark.asyncio
async def test_birthday_emails_enabled_can_be_turned_on() -> None:
    repo = _FakeAcademyRepo()
    update = UpdateAcademyNotificationsUseCase(repo)
    out = await update.execute("a1", {"birthday_emails_enabled": True})
    assert out.birthday_emails_enabled is True

    get_use_case = GetAcademyNotificationsUseCase(repo)
    out2 = await get_use_case.execute("a1")
    assert out2.birthday_emails_enabled is True
```

- [ ] Run — expect `AttributeError`:

```bash
cd backend && .venv/bin/pytest v2/tests/application/identity/test_academy_use_cases.py -q
```

- [ ] Edit `get_academy_notifications_use_case.py` — add the field and thread it through `_notifications_output`:

```python
@dataclass(frozen=True)
class GetAcademyNotificationsOutput:
    dues_reminders: bool = False
    attendance_alerts: bool = False
    daily_digest_to_admin: bool = False
    coach_digest_enabled: bool = False
    coach_digest_hour: int = 6
    parent_digest_enabled: bool = False
    parent_digest_hour: int = 6
    # Birthdays-and-profile-nudges spec §4.2: off by default everywhere,
    # no env-level default (unlike the digest flags) — the owner turns it
    # on per academy after confirming registration consent covers it.
    birthday_emails_enabled: bool = False
```

and in `_notifications_output`, add one line to the constructed object:

```python
        birthday_emails_enabled=bool(notifs.get("birthday_emails_enabled", False)),
```

- [ ] Edit `backend/v2/interfaces/admin/views.py`:

```python
class AdminNotificationsView(BaseModel):
    dues_reminders: bool = False
    attendance_alerts: bool = False
    daily_digest_to_admin: bool = False
    coach_digest_enabled: bool = False
    coach_digest_hour: int = 6
    parent_digest_enabled: bool = False
    parent_digest_hour: int = 6
    birthday_emails_enabled: bool = False


class UpdateAdminNotificationsRequest(BaseModel):
    dues_reminders: bool | None = None
    attendance_alerts: bool | None = None
    daily_digest_to_admin: bool | None = None
    coach_digest_enabled: bool | None = None
    coach_digest_hour: int | None = Field(default=None, ge=0, le=23)
    parent_digest_enabled: bool | None = None
    parent_digest_hour: int | None = Field(default=None, ge=0, le=23)
    birthday_emails_enabled: bool | None = None
```

- [ ] Run — expect PASS:

```bash
cd backend && .venv/bin/pytest v2/tests/application/identity/test_academy_use_cases.py -q
```

- [ ] Also run the existing academy-routes contract test (if any) to confirm the route still round-trips via `asdict(out)`:

```bash
cd backend && .venv/bin/pytest v2/tests -k academy_notifications -q
```

- [ ] Edit `frontend/lib/api/admin.ts`:

```typescript
export interface AdminNotificationsView {
  dues_reminders: boolean;
  attendance_alerts: boolean;
  daily_digest_to_admin: boolean;
  coach_digest_enabled: boolean;
  coach_digest_hour: number;
  parent_digest_enabled: boolean;
  parent_digest_hour: number;
  birthday_emails_enabled: boolean;
}
```

- [ ] Edit `frontend/components/admin/settings/notify-panel.tsx` — extend `normalize()`:

```typescript
function normalize(data: AdminNotificationsView | null | undefined): AdminNotificationsView {
  return {
    dues_reminders: data?.dues_reminders ?? false,
    attendance_alerts: data?.attendance_alerts ?? false,
    daily_digest_to_admin: data?.daily_digest_to_admin ?? false,
    coach_digest_enabled: data?.coach_digest_enabled ?? false,
    coach_digest_hour: data?.coach_digest_hour ?? 6,
    parent_digest_enabled: data?.parent_digest_enabled ?? false,
    parent_digest_hour: data?.parent_digest_hour ?? 6,
    birthday_emails_enabled: data?.birthday_emails_enabled ?? false,
  };
}
```

and add a toggle row (find the existing `<Toggle ... />` block for `parent_digest_enabled` and add this immediately after it, reusing the same `Toggle` component already defined in this file):

```tsx
          <Toggle
            label="Birthday emails to families"
            checked={form.birthday_emails_enabled}
            onChange={(checked) =>
              setForm((prev) => ({ ...prev, birthday_emails_enabled: checked }))
            }
          />
          <p className="text-xs text-muted-foreground -mt-2">
            Sends one email per student on their birthday. Confirm your registration wording
            covers this use of a child&apos;s date of birth before turning this on.
          </p>
```

- [ ] Run the frontend checks:

```bash
cd frontend && pnpm typecheck && pnpm lint
```

- [ ] Commit:

```bash
git add backend/v2/contexts/identity/application/get_academy_notifications_use_case.py \
        backend/v2/interfaces/admin/views.py \
        backend/v2/tests/application/identity/test_academy_use_cases.py \
        frontend/lib/api/admin.ts \
        frontend/components/admin/settings/notify-panel.tsx
git commit -m "$(cat <<'EOF'
feat(admin): add the birthday_emails_enabled notification setting

Off by default; the owner turns it on per academy after confirming the
registration wording covers birthday emails as a use of a child's DOB.
Threaded through GetAcademyNotificationsOutput / the admin notifications
DTOs / the frontend settings panel — admin.py is untouched (its GET/PATCH
routes already spread the use-case output generically).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 12: "Birthdays this week" — coach digest block and the admin/owner weekly email

**Files:**
- Modify: `backend/v2/contexts/communications/application/digest_renderer.py`
- Modify: `backend/v2/contexts/communications/application/use_cases/send_coach_daily_digest.py`
- Modify: `backend/v2/composition/digests.py`
- Modify: `backend/v2/composition/birthdays.py` (add the weekly-candidates provider)
- Test: `backend/v2/tests/unit/test_digest_renderer_birthdays.py`
- Test: `backend/v2/tests/application/test_send_coach_daily_digest_birthdays.py` (use-case tests live in `tests/application/`, next to the existing `test_send_coach_daily_digest.py` — not in `tests/unit/`)

**Interfaces:**
- Consumes: `BirthdayEntry`, `render_birthdays_block` (Task 9); `departable_for_student`, `MongoSessionRepository.get_many`/`assigned_session_ids_for_coach` (existing); `MongoBirthdayStaffDigestSendRepository` (Task 9).
- Produces: `render_coach_digest(..., birthdays: Sequence[BirthdayEntry] = ())`; `BirthdayProvider` protocol (`async def for_week(self, on_date: date, *, coach_id: str | None) -> Sequence[BirthdayEntry]`) consumed by `SendCoachDailyDigest`.

> **Known limitation, ACCEPTED** (call it out in the PR description): riding `send_coach_daily_digests` means the staff "Birthdays this week" email only fires for academies whose *coach digest* is enabled — `_send_coach_daily_digests_body` `continue`s on `digest_window_open(schedule, current_hour)` before ever calling `execute`. Spec §4.1 calls the staff digest "always on". The alternative (a third cron) was rejected in Global Constraints; the cost is that an academy with the coach digest switched off gets no staff birthday email. It is not silent: the release note records it. If an owner objects, the fix is a separate weekly cron, not a change here.
>
> **Interpretation note** (documented per Global Constraints): the spec's §4.1 wording — "a block in the existing coach daily digest on Mondays and in the admin ops digest ... coaches see only their classes' students; admins/owners see all" — cannot literally mean the internal `send_ops_digest` job (that job's one recipient is `OPS_ALERT_EMAIL`, a platform-ops address with no per-academy admin/owner audience or class-membership concept). This task instead extends the existing `send_coach_daily_digests` job, which already resolves per-academy admin/owner recipients via `admin_cc_enabled` (`notifications.daily_digest_to_admin`) and already knows "today is Monday" per-academy is meaningless (the job ticks hourly cross-timezone) — so the Monday gate here uses `command.digest_date.weekday() == 0` in the scheduler's own timezone, consistent with how `billing_day`/`coach_digest_hour` already interpret "day" in `settings.scheduler_tz`, not each academy's local zone (documented limitation, not new here). Admins/owners get one **separate, full-roster** email (not a BCC copy of a coach's filtered one — a BCC cannot carry different content than the primary recipient's copy), claimed independently so it fires once per academy per week regardless of how many coaches exist.

- [ ] Write the failing renderer test:

```python
# backend/v2/tests/unit/test_digest_renderer_birthdays.py
from __future__ import annotations

from backend.v2.contexts.communications.application.birthday_renderer import BirthdayEntry
from backend.v2.contexts.communications.application.digest_renderer import render_coach_digest


class _Plan:
    date = "2026-03-09"
    program_name = "Smash Academy"
    sessions: list[object] = []


def test_birthdays_block_is_absent_when_no_entries() -> None:
    _, body = render_coach_digest(_Plan())
    assert "Birthdays this week" not in body


def test_birthdays_block_appears_when_entries_given() -> None:
    entries = [
        BirthdayEntry(
            student_name="Aanya Kapoor",
            age_turning=10,
            day_label="Wednesday",
            class_names=("U10 Advanced",),
            parent_name="Kapoor Family",
        )
    ]
    _, body = render_coach_digest(_Plan(), birthdays=entries)
    assert "Birthdays this week" in body
    assert "Aanya Kapoor" in body
    assert "U10 Advanced" in body
```

- [ ] Write the failing use-case test:

```python
# backend/v2/tests/application/test_send_coach_daily_digest_birthdays.py
# (v2/tests/application/, NOT v2/tests/unit/ — that is where the existing
# use-case suite lives, at test_send_coach_daily_digest.py.)
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from backend.v2.contexts.communications.application.birthday_renderer import BirthdayEntry
from backend.v2.contexts.communications.application.ports import ResolvedRecipient, SendOutcome
from backend.v2.contexts.communications.application.use_cases.send_coach_daily_digest import (
    SendCoachDailyDigest,
    SendCoachDailyDigestCommand,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory


class _FakeDigests:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def try_claim(self, academy_id, coach_id, digest_date):
        from backend.v2.contexts.communications.domain.models import DigestSend

        # Use the `queued` factory, exactly as the existing
        # tests/application/test_send_coach_daily_digest.py fake does.
        # `DigestSend` is a frozen dataclass with ten required fields
        # (coach_email, provider_message_id, sent_at, failed_reason,
        # created_at ...), so a hand-rolled constructor call raises TypeError.
        return DigestSend.queued(
            digest_id=f"d-{coach_id}",
            academy_id=academy_id,
            coach_id=coach_id,
            coach_email=None,
            digest_date=digest_date,
            created_at=datetime(2026, 3, 9, tzinfo=UTC),
        )

    async def mark_sent(self, digest_id, provider_message_id):
        self.sent.append(digest_id)

    async def mark_failed(self, *a, **k): ...
    async def mark_skipped_empty(self, *a, **k): ...


class _FakeResolver:
    async def resolve_academy_audience(self, audience):
        if audience.role == "coach":
            return [ResolvedRecipient(user_id="coach-1", email="c1@example.com")]
        if audience.role == "admin":
            return [ResolvedRecipient(user_id="admin-1", email="admin1@example.com")]
        if audience.role == "owner":
            return []
        return []

    async def resolve_session_audience(self, *a, **k): ...
    async def resolve_coach_audience(self, *a, **k): ...
    async def resolve_selected_audience(self, *a, **k): ...
    async def resolve_payment_risk_audience(self, *a, **k): ...


class _FakeSender:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    async def send(self, *, recipient, subject, body, cc=None, bcc=None, reply_to=None, category):
        self.sent.append({"recipient": recipient, "subject": subject, "category": category})
        return SendOutcome(ok=True, provider_message_id="m1", failed_reason=None)


class _FakePlanProvider:
    async def execute(self, coach_id, on_date):
        return None  # empty plan is fine; birthdays are independent of it


class _FakeBirthdayProvider:
    def __init__(self, entries: list[BirthdayEntry]) -> None:
        self.entries = entries
        self.calls: list[str | None] = []

    async def for_week(self, on_date, *, coach_id):
        self.calls.append(coach_id)
        return self.entries


class _FakeStaffClaims:
    async def try_claim(self, *, academy_id, user_id, week_of):
        return {"send_id": f"staff-{user_id}"}

    async def mark_sent(self, send_id): ...
    async def mark_failed(self, *a, **k): ...


@pytest.mark.asyncio
async def test_admin_gets_a_separate_full_roster_email_on_monday() -> None:
    entries = [
        BirthdayEntry(
            student_name="Aanya",
            age_turning=9,
            day_label="Monday",
            class_names=(),
            parent_name="Kapoor Family",
        )
    ]
    use_case = SendCoachDailyDigest(
        digests=_FakeDigests(),
        resolver=_FakeResolver(),
        sender=_FakeSender(),
        plan_provider=_FakePlanProvider(),
        birthday_provider=_FakeBirthdayProvider(entries),
        staff_birthday_claims=_FakeStaffClaims(),
    )

    await use_case.execute(
        SendCoachDailyDigestCommand(
            academy_id="a1", digest_date=date(2026, 3, 9), admin_cc_enabled=True  # a Monday
        )
    )

    admin_sends = [s for s in use_case.sender.sent if s["recipient"].user_id == "admin-1"]
    assert len(admin_sends) == 1
    assert admin_sends[0]["category"] == EmailCategory.NOTIFICATION


@pytest.mark.asyncio
async def test_no_admin_email_on_a_non_monday() -> None:
    use_case = SendCoachDailyDigest(
        digests=_FakeDigests(),
        resolver=_FakeResolver(),
        sender=_FakeSender(),
        plan_provider=_FakePlanProvider(),
        birthday_provider=_FakeBirthdayProvider([]),
        staff_birthday_claims=_FakeStaffClaims(),
    )

    await use_case.execute(
        SendCoachDailyDigestCommand(
            academy_id="a1", digest_date=date(2026, 3, 10), admin_cc_enabled=True  # Tuesday
        )
    )

    admin_sends = [s for s in use_case.sender.sent if s["recipient"].user_id == "admin-1"]
    assert admin_sends == []
```

- [ ] Run both — expect failures (renderer ignores `birthdays`; use case has no `birthday_provider` param):

```bash
cd backend && .venv/bin/pytest v2/tests/unit/test_digest_renderer_birthdays.py v2/tests/unit/test_send_coach_daily_digest_birthdays.py -q
```

- [ ] Edit `digest_renderer.py` — add the import and thread the param through:

```python
from backend.v2.contexts.communications.application.birthday_renderer import (
    BirthdayEntry,
    render_birthdays_block,
)
```

```python
def render_coach_digest(
    plan: Any,
    *,
    brand: EmailBrand | None = None,
    whatsapp_groups: Sequence[WhatsAppGroupLink] = (),
    expected_absences: Sequence[ExpectedAbsence] = (),
    birthdays: Sequence[BirthdayEntry] = (),
    playlist_url: str | None = None,
    unsubscribe_url: str | None = None,
) -> tuple[str, str]:
    ...
    absences_html = _render_expected_absences(expected_absences)
    birthdays_html = render_birthdays_block(birthdays)
    groups_html = render_whatsapp_groups_block(
        whatsapp_groups, persona="coach", accent=resolved_brand.accent()
    )
    ...
    body = shell(
        brand=resolved_brand,
        inner_html=f"{greeting}{sessions_html}{absences_html}{birthdays_html}{groups_html}",
        date_label=_pretty_date(date_str),
        footer_html=footer_html + render_unsubscribe_footer(unsubscribe_url),
    )
```

- [ ] Run the renderer test — expect PASS:

```bash
cd backend && .venv/bin/pytest v2/tests/unit/test_digest_renderer_birthdays.py -q
```

- [ ] Edit `send_coach_daily_digest.py`. Add the two new protocols and fields, and the Monday admin/owner send:

(`date`, `Protocol`, `Any`, `Sequence`, `AcademyAudience` and `EmailCategory` are all already imported in this file — add only the birthday renderer import.)

```python
from backend.v2.contexts.communications.application.birthday_renderer import (
    BirthdayEntry,
    render_birthday_staff_digest,
)


class BirthdayProvider(Protocol):
    """Coach-filtered (or, with coach_id=None, academy-wide) birthdays for the
    week containing ``on_date``. Duck-typed like PlanProvider; wired in
    composition/birthdays.py over the enrollment context (ADR-0005)."""

    async def for_week(
        self, on_date: date, *, coach_id: str | None
    ) -> Sequence[BirthdayEntry]: ...


class StaffBirthdayDigestClaims(Protocol):
    async def try_claim(
        self, *, academy_id: str, user_id: str, week_of: str
    ) -> dict[str, Any] | None: ...

    async def mark_sent(self, send_id: str) -> None: ...

    # Required, not optional: a claim that is never resolved stays QUEUED,
    # and `claim_digest_send` treats a QUEUED row as "in flight" and returns
    # None forever after — so a single suppressed send would silently kill
    # that recipient's staff digest for good.
    async def mark_failed(self, send_id: str, reason: str, *, retryable: bool = True) -> None: ...
```

Add the two new fields to `SendCoachDailyDigest` — **append them, do not retype the dataclass**. The class already carries a `now: Callable[[], datetime] = field(default=_utcnow)` field declared *below* its methods; a wholesale rewrite of the field list drops it and breaks every caller that relies on the injectable clock. The result must be:

```python
@dataclass
class SendCoachDailyDigest:
    digests: DigestSendRepository
    resolver: AudienceResolver
    sender: EmailSendPort
    plan_provider: PlanProvider
    unsubscribe_links: UnsubscribeLinkBuilder = field(default_factory=UnsubscribeLinkBuilder)
    academy_slugs: AcademySlugLookup | None = None
    brands: AcademyBrandLookup | None = None
    group_links: CoachGroupLinkProvider | None = None
    expected_absences: ExpectedAbsenceProvider | None = None
    birthday_provider: BirthdayProvider | None = None
    staff_birthday_claims: StaffBirthdayDigestClaims | None = None

    # ... existing methods unchanged ...

    now: Callable[[], datetime] = field(default=_utcnow)  # UNCHANGED — keep it
```

Add a birthdays helper mirroring `_absences`:

```python
    async def _birthdays(self, on_date: date, *, coach_id: str | None) -> Sequence[BirthdayEntry]:
        if self.birthday_provider is None:
            return ()
        try:
            return await self.birthday_provider.for_week(on_date, coach_id=coach_id)
        except Exception:
            return ()
```

In `execute`, thread the per-coach block into the existing render call:

```python
            subject, body = render_coach_digest(
                plan,
                brand=brand,
                whatsapp_groups=await self._groups(coach.user_id),
                expected_absences=await self._absences(coach.user_id, command.digest_date),
                birthdays=(
                    await self._birthdays(command.digest_date, coach_id=coach.user_id)
                    if command.digest_date.weekday() == 0
                    else ()
                ),
                unsubscribe_url=self.unsubscribe_links.build(
                    academy_id=command.academy_id,
                    user_id=coach.user_id,
                    academy_slug=academy_slug,
                ),
            )
```

Add the standalone admin/owner send at the end of `execute`, before the `return`:

```python
        if (
            command.digest_date.weekday() == 0
            and self.birthday_provider is not None
            and self.staff_birthday_claims is not None
        ):
            week_of = command.digest_date.isoformat()
            admins = await self.resolver.resolve_academy_audience(AcademyAudience(role="admin"))
            owners = await self.resolver.resolve_academy_audience(AcademyAudience(role="owner"))
            staff = {r.user_id: r for r in (*admins, *owners) if r.email}
            all_birthdays = await self._birthdays(command.digest_date, coach_id=None)
            if all_birthdays:
                for recipient in staff.values():
                    claim = await self.staff_birthday_claims.try_claim(
                        academy_id=command.academy_id, user_id=recipient.user_id, week_of=week_of
                    )
                    if claim is None:
                        continue
                    send_id = str(claim["send_id"])
                    subject, body = render_birthday_staff_digest(
                        all_birthdays,
                        brand=brand,
                        week_of=week_of,
                        # NOTIFICATION is an unsubscribable category, so the
                        # opt-out notice has to be rendered (the gate only
                        # blocks; it never writes a footer).
                        unsubscribe_url=self.unsubscribe_links.build(
                            academy_id=command.academy_id,
                            user_id=recipient.user_id,
                            academy_slug=academy_slug,
                        ),
                    )
                    outcome = await self.sender.send(
                        recipient=recipient,
                        subject=subject,
                        body=body,
                        category=EmailCategory.NOTIFICATION,
                    )
                    if outcome.ok:
                        await self.staff_birthday_claims.mark_sent(send_id)
                    else:
                        # Always resolve the claim. A row left QUEUED is "in
                        # flight" to `claim_digest_send` forever, so this
                        # recipient would never get another staff digest.
                        await self.staff_birthday_claims.mark_failed(
                            send_id,
                            outcome.failed_reason or "unknown",
                            retryable=not outcome.suppressed,
                        )
```

Add `render_birthday_staff_digest` to `birthday_renderer.py`:

```python
def render_birthday_staff_digest(
    entries: Sequence[BirthdayEntry],
    *,
    brand: EmailBrand | None,
    week_of: str,
    unsubscribe_url: str | None = None,
) -> tuple[str, str]:
    resolved_brand = brand or EmailBrand(academy_name="Your academy")
    subject = f"Birthdays this week — week of {week_of}"
    body = shell(brand=resolved_brand, inner_html=render_birthdays_block(entries), footer_html="")
    return subject, append_unsubscribe_footer(body, unsubscribe_url)
```

- [ ] Run the use-case test alongside the pre-existing coach-digest suite (verified path: `v2/tests/application/test_send_coach_daily_digest.py`) — expect PASS:

```bash
cd backend && .venv/bin/pytest \
  v2/tests/application/test_send_coach_daily_digest_birthdays.py \
  v2/tests/application/test_send_coach_daily_digest.py -q
```

- [ ] Add the composition-side `BirthdayProvider` implementation to `backend/v2/composition/birthdays.py` (appended to the file from Task 10):

Three things this code must get right, each of which is a verified fact about the repo, not a guess:

1. `PAST_ENROLLMENT_STATUSES` does **not** live in `contexts/enrollment/domain/models.py`. It is a class attribute on `MongoStudentRepository` (`mongo_student_repo.py:835`), `("cancelled", "deleted", "withdrawn", "dropped")` — both the pre- and post-0171 spellings.
2. `MongoSessionRepository.assigned_session_ids_for_coach` returns a **`list[str]`**, not a set (`mongo_session_repo.py:303-327`). Intersecting a set with a list raises `TypeError`, so wrap it.
3. `# noqa: SLF001` must not appear: ruff's select list here is `["E","F","I","W","UP","B","ASYNC","RUF"]`, SLF is not enabled, and `RUF100` fails the build on an unknown noqa code. Calling `_find_many` from `composition/` needs no suppression — `composition/coach.py:382` and `composition/admin.py` already do it.

```python
@dataclass
class _WeeklyBirthdayProvider:
    students: MongoStudentRepository
    enrollments: MongoEnrollmentRepository
    sessions: MongoSessionRepository
    coach_session_ids: Callable[[str], Awaitable[list[str]]]

    async def for_week(self, on_date: date, *, coach_id: str | None) -> list[BirthdayEntry]:
        monday = on_date - timedelta(days=on_date.weekday())
        week = [monday + timedelta(days=offset) for offset in range(7)]
        # Same leap-day rule as the daily job: a Feb-29 birthday must land on
        # Feb 28 in a non-leap year rather than vanish from the digest for
        # three years running (spec §7). `todays_birthday_month_days` owns
        # that rule; do not re-derive it with strftime alone.
        day_for_month_day: dict[str, date] = {}
        for day in week:
            for month_day in todays_birthday_month_days(day):
                day_for_month_day.setdefault(month_day, day)

        allowed_sessions: set[str] | None = None
        if coach_id is not None:
            allowed_sessions = set(await self.coach_session_ids(coach_id))

        cursor = self.students._find_many(
            {
                "birth_month_day": {"$in": sorted(day_for_month_day)},
                "is_deleted": {"$ne": True},
            }
        )
        out: list[BirthdayEntry] = []
        async for doc in cursor:
            student_id = str(doc.get("student_id") or "")
            enrollments = await self.enrollments.departable_for_student(student_id)
            session_ids = {e.session_id for e in enrollments}
            withdrawn_on: str | None = None
            if not enrollments:
                if coach_id is not None:
                    # Withdrawn-only students have no session to match a
                    # coach's roster against — spec §4.1 puts them on the
                    # staff digest only, never a per-coach filtered view.
                    continue
                latest = self.enrollments._find_many(
                    {
                        "student_id": student_id,
                        "status": {"$in": list(MongoStudentRepository.PAST_ENROLLMENT_STATUSES)},
                    },
                    sort=[("enrollment_id", -1)],
                    limit=1,
                )
                async for row in latest:
                    stamp = row.get("cancelled_at") or row.get("withdrawal_date") or row.get(
                        "updated_at"
                    )
                    withdrawn_on = str(stamp)[:10] if stamp else None
            elif allowed_sessions is not None and not (session_ids & allowed_sessions):
                continue

            sessions = await self.sessions.get_many(sorted(session_ids)) if session_ids else []
            month_day = str(doc.get("birth_month_day") or "")
            birthday_on = day_for_month_day.get(month_day, monday)
            dob = str(doc.get("date_of_birth") or "")
            age_turning = birthday_on.year - int(dob[:4]) if len(dob) >= 4 and dob[:4].isdigit() else 0
            parent_doc = await self.students.get_parent_user_doc(str(doc.get("parent_id") or ""))
            out.append(
                BirthdayEntry(
                    student_name=str(doc.get("full_name") or "Unnamed student"),
                    age_turning=age_turning,
                    day_label=birthday_on.strftime("%A"),
                    class_names=tuple(s.title for s in sessions),
                    parent_name=str((parent_doc or {}).get("display_name") or "Unknown"),
                    withdrawn_on=withdrawn_on,
                )
            )
        return out
```

Imports this block needs at the top of `composition/birthdays.py` (on top of Task 10's): `from collections.abc import Awaitable, Callable`, `timedelta` added to the `datetime` import, `MongoSessionRepository` from `contexts/enrollment/infrastructure/mongo_session_repo`, and `BirthdayEntry` from `contexts/communications/application/birthday_renderer`. Drop the now-unused `Any` if Task 10's `AsyncIOMotorDatabase[Any]` annotation is the only remaining use — it is not, so keep it.

- [ ] Wire `_WeeklyBirthdayProvider` and `MongoBirthdayStaffDigestSendRepository` into `compose_send_coach_daily_digest` in `composition/digests.py` (currently at `digests.py:446-458`).

  **The two imports MUST be function-local.** `composition/birthdays.py` imports `_build_email_sender` from `composition/digests.py` (defined at `digests.py:954`). A matching top-level import in `digests.py` makes the pair circular: importing `digests` starts executing it, the top-level `from ...birthdays import ...` runs `birthdays`, which asks for `_build_email_sender` from a module that has only reached line ~90 — `ImportError: cannot import name '_build_email_sender' from partially initialized module`. Deferring to call time breaks the cycle because by then `digests` is fully loaded.

  `MongoSessionRepository`, `MongoStudentRepository` and `MongoEnrollmentRepository` are **already imported** at `digests.py:131-140` — do not re-add them.

```python
def compose_send_coach_daily_digest(db: AsyncIOMotorDatabase[Any]) -> SendCoachDailyDigest:
    # Function-local: composition.birthdays imports _build_email_sender from
    # this module, so a top-level import here would be a cycle (see above).
    from backend.v2.composition.birthday_notice_send_repo import (
        MongoBirthdayStaffDigestSendRepository,
    )
    from backend.v2.composition.birthdays import _WeeklyBirthdayProvider

    parts = _build_digest_parts(db)
    sessions_repo = MongoSessionRepository(db)
    return SendCoachDailyDigest(
        digests=parts.digests,
        resolver=parts.resolver,
        sender=parts.sender,
        plan_provider=parts.plan_provider,
        unsubscribe_links=compose_unsubscribe_link_builder(get_settings()),
        academy_slugs=_AcademySlugLookup(MongoAcademyRepository(db)),
        brands=parts.brands,
        group_links=parts.group_links,
        expected_absences=parts.expected_absences,
        birthday_provider=_WeeklyBirthdayProvider(
            students=MongoStudentRepository(db),
            enrollments=MongoEnrollmentRepository(db),
            sessions=sessions_repo,
            coach_session_ids=sessions_repo.assigned_session_ids_for_coach,
        ),
        staff_birthday_claims=MongoBirthdayStaffDigestSendRepository(db),
    )
```

- [ ] Confirm the app still boots (this is the step that would have caught the cycle):

```bash
cd backend && .venv/bin/python -c "import backend.v2.main"
```

- [ ] Run the full communications unit + contract suite to catch any wiring regression:

```bash
cd backend && .venv/bin/pytest v2/tests/unit -k "digest or birthday" -q
cd backend && .venv/bin/pytest v2/tests/contract -k "digest or birthday" -q
```

- [ ] Commit:

```bash
git add backend/v2/contexts/communications/application/digest_renderer.py \
        backend/v2/contexts/communications/application/use_cases/send_coach_daily_digest.py \
        backend/v2/contexts/communications/application/birthday_renderer.py \
        backend/v2/composition/digests.py \
        backend/v2/composition/birthdays.py \
        backend/v2/tests/unit/test_digest_renderer_birthdays.py \
        backend/v2/tests/application/test_send_coach_daily_digest_birthdays.py
git commit -m "$(cat <<'EOF'
feat(communications): add the staff "Birthdays this week" digest block

Coaches see a birthdays block filtered to their own classes' students,
embedded in Monday's teaching-plan digest; admins/owners get one separate
full-roster email the same tick, claimed per (academy_id, user_id, week)
so it fires exactly once per academy per week regardless of coach count.
Rides the existing send_coach_daily_digests job — no new cron entry.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 13: Migration idempotency, unsubscribe, and setting-off integration tests

**Files:**
- Test: `backend/v2/tests/contract/test_birthday_and_nudge_idempotency.py`

**Interfaces:**
- Consumes: `compose_send_birthday_notes` (Task 10); `MongoEmailPreferenceRepository` (`contexts/communications/infrastructure/mongo_email_preference_repo.py:51`, a `TenantScopedRepository` + `EmailPreferenceRepository`) and its `set_opt_outs(*, user_id, email, campaigns_opted_out, digests_opted_out, source, notifications_opted_out=None)` — all keyword-only, `notifications_opted_out` tri-state where `None` means "leave unchanged" (`ports.py:153-167`). Verified: the class name, the module path and the signature below are the real ones; no exploratory grep step is needed.

- [ ] Write the failing test:

```python
# backend/v2/tests/contract/test_birthday_and_nudge_idempotency.py
"""Spec §7 backend coverage: jobs are idempotent under re-run, an
unsubscribed parent receives nothing, and setting off means no family
birthday email."""

from __future__ import annotations

from datetime import date

import pytest

from backend.v2.composition.birthdays import compose_send_birthday_notes
from backend.v2.contexts.communications.infrastructure.mongo_email_preference_repo import (
    MongoEmailPreferenceRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope

ACADEMY_ID = "acad-bday-idempotency"


async def _seed(db) -> None:
    await db["students"].insert_one(
        {
            "academy_id": ACADEMY_ID,
            "student_id": "student-idem-1",
            "parent_id": "parent-idem-1",
            "full_name": "Rohan Mehta",
            "date_of_birth": "2016-05-05",
            "birth_month_day": "05-05",
        }
    )
    await db["users"].insert_one(
        {
            "academy_id": ACADEMY_ID,
            "user_id": "parent-idem-1",
            "email": "parent-idem-1@example.com",
            "display_name": "Mehta Family",
        }
    )
    await db["enrollments"].insert_one(
        {
            "academy_id": ACADEMY_ID,
            "enrollment_id": "enr-idem-1",
            "student_id": "student-idem-1",
            "session_id": "sess-idem-1",
            "status": "active",
        }
    )


@pytest.mark.asyncio
async def test_a_second_run_the_same_day_sends_nothing_more(db) -> None:
    today = date(2026, 5, 5)
    with tenant_scope(ACADEMY_ID):
        await _seed(db)
        use_case = compose_send_birthday_notes(db, today=today)
        first = await use_case.execute(academy_id=ACADEMY_ID)
        second = await use_case.execute(academy_id=ACADEMY_ID)

    assert first.sent == 1
    assert second.sent == 0
    assert second.already_claimed == 1


@pytest.mark.asyncio
async def test_unsubscribed_parent_receives_nothing(db) -> None:
    today = date(2026, 5, 5)
    with tenant_scope(ACADEMY_ID):
        await _seed(db)
        prefs = MongoEmailPreferenceRepository(db)
        await prefs.set_opt_outs(
            user_id="parent-idem-1",
            email="parent-idem-1@example.com",
            campaigns_opted_out=False,
            digests_opted_out=False,
            notifications_opted_out=True,
            source="test",
        )
        use_case = compose_send_birthday_notes(db, today=today)
        result = await use_case.execute(academy_id=ACADEMY_ID)

    assert result.sent == 0
    # The claim still records a (non-retryable) failed attempt — the gate
    # is a permanent fact, not a transient one, per SendBirthdayNotes.
    assert result.failed == 1
```

- [ ] Run — expect PASS:

```bash
cd backend && .venv/bin/pytest v2/tests/contract/test_birthday_and_nudge_idempotency.py -q
```

  If `test_unsubscribed_parent_receives_nothing` fails with `sent == 1`, the cause is a single specific thing: `compose_send_birthday_notes` called `_build_email_sender(settings)` without `db`. The `db` argument is what wires `MongoEmailPreferenceGate` into `GatedEmailSendPort`; without it the gate is `None` and every preference is ignored. Task 10 passes `db` — check that first, not the test.

- [ ] Commit:

```bash
git add backend/v2/tests/contract/test_birthday_and_nudge_idempotency.py
git commit -m "$(cat <<'EOF'
test(communications): cover birthday-job idempotency and unsubscribe gating

Confirms send_birthday_notes sends exactly once per student per day under
a same-day re-run and that a NOTIFICATION-opted-out parent gets nothing,
closing out the spec §7 backend test list.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 14: Release note

**Files:**
- Create: `docs/release-notes/2026-09-10-birthdays-and-profile-nudges.md`

**Interfaces:** None (documentation only).

Verified gate contract (`scripts/dev/release_notes_check.py`, run by `.github/workflows/release-notes.yml`): the note is located by scanning `docs/release-notes/*.md` for the literal marker `PR: #<number>`, and must contain all three of `## What changed`, `## Deploy notes`, `## Risk / rollback`, each with a non-empty body that does not start with `<` and contains none of the placeholder markers (`auto-generated stub`, `author: fill in`, `confirm no manual env var or manual step`).

- [ ] Write the release note with `PR: #TBD`. **The gate WILL fail on the first CI run** — `find_existing_note` matches on the literal `PR: #<number>` and `#TBD` matches nothing, so the job reports "required release notes are missing". This is expected, not a surprise to debug.

```markdown
# Birthdays and profile nudges

## What changed
- Every student with a parseable date of birth now gets a `birth_month_day`
  field (`MM-DD`), backfilled by migration 0173 and kept in sync on every
  write (registration approval, admin/parent profile edits).
- New daily job `send_birthday_notes`: one "Happy birthday" email per
  enrolled-or-held-or-paused student on their birthday, gated behind a new
  per-academy setting (Settings > Notifications > "Birthday emails to
  families", default off).
- New daily job `send_profile_nudges`: up to three reminder emails per
  family (day 7 / day 21 / day 60 after a profile gap is first seen),
  listing every missing required field across all of a parent's children,
  linking to `/parent/profile`. Stops automatically once the gap closes.
- The coach daily digest gains a coach-filtered "Birthdays this week" block
  on Mondays; admins/owners get one separate full-roster "Birthdays this
  week" email the same day.

## Deploy notes
- Production does not run migrations on boot (`V2_RUN_MIGRATIONS_ON_BOOT=false`).
  After deploy, run `run_pending_migrations` by hand to apply:
  - `0173_backfill_student_birth_month_day` — backfills `birth_month_day` and
    indexes `(academy_id, birth_month_day)`. Report-only for students whose
    `date_of_birth` does not parse as `YYYY-MM-DD`.
  - `0174_birthday_and_nudge_indexes` — unique indexes on `profile_nudges`,
    `birthday_notice_sends`, `birthday_staff_digest_sends`.
- `birthday_emails_enabled` defaults to off for every academy. An owner must
  confirm the registration wording covers birthday emails as a use of a
  child's date of birth before turning it on for that academy (Settings >
  Notifications).
- Two new scheduler jobs (`send_birthday_notes` 06:00, `send_profile_nudges`
  05:00, both `settings.scheduler_tz`) are added to `SCHEDULED_JOB_MONITORS`
  and `JOB_STALE_AFTER`; they will appear in the ops digest's stale-job
  section if they ever stop ticking.

## Risk / rollback
- All new sends are additive and individually gated: `send_birthday_notes`
  only sends when `birthday_emails_enabled` is true for that academy (off
  everywhere until an owner opts in); `send_profile_nudges` only sends to
  parents with an incomplete profile and a current student, on the day-7/
  21/60 schedule. Neither touches billing, enrollment status, or existing
  digest content.
- Both are idempotent under a job re-run: `send_birthday_notes` claims via
  `digest_claim` keyed `(academy_id, student_id, year)`; `send_profile_nudges`
  advances its own `profile_nudges` record only after a successful send.
- Rollback is a plain revert: the two new jobs simply stop being registered,
  no other job's cron or the existing coach/parent digest sends is edited
  except in an additive way (`render_coach_digest` gained an optional
  `birthdays` param defaulting to nothing).
- If migration 0173 is rolled back after running, `birth_month_day` values
  are simply stale/absent — `send_birthday_notes` reads only that field, so
  the job degrades to "sends nothing" rather than sending wrong birthdays.

PR: #TBD
```

- [ ] Commit:

```bash
git add docs/release-notes/2026-09-10-birthdays-and-profile-nudges.md
git commit -m "$(cat <<'EOF'
docs(release-notes): add release note for birthdays-and-profile-nudges

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Immediately after opening the PR**, replace `#TBD` with the real number and push it as a one-line follow-up commit. The Release Notes Gate is a required check on `main`'s ruleset, so the PR is unmergeable until this lands:

```bash
sed -i '' "s/^PR: #TBD$/PR: #<the real number>/" docs/release-notes/2026-09-10-birthdays-and-profile-nudges.md
git add docs/release-notes/2026-09-10-birthdays-and-profile-nudges.md
git commit -m "$(cat <<'EOF'
docs(release-notes): record the PR number for birthdays-and-profile-nudges

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

- [ ] Add the Task 12 known limitation to the release note's "Risk / rollback" section at the same time: academies with the coach daily digest switched off receive no staff "Birthdays this week" email, because that block rides `send_coach_daily_digests`.

---

## Self-review

| Spec section | Covered by |
|---|---|
| §2 "Who gets a birthday note" (students only) | Task 9 (`BirthdayCandidate` has no parent-birthday concept), Task 10 (`_BirthdayCandidateProvider` reads only `students`) |
| §2 "Which students" (every DOB'd student, any status, active/held/paused get the email, withdrawn digest-only) | Task 10 (`departable_for_student` gate on the family email), Task 12 (`_WeeklyBirthdayProvider` includes withdrawn-only students in the staff digest, excludes them from the per-coach filter) |
| §2 "Never-enrolled siblings" (out of scope) | Task 10/12 — candidates always originate from `students` docs; a sibling with no student record never enters either query (no plan work needed — verified as already true) |
| §2 "Nudge cadence" (day 7/21/60, stop early on close) | Task 1 (`next_nudge_step`), Task 5 (`open_or_reopen`/`close`), Task 6 (`SendProfileNudges`) |
| §2 "Nudge channel" (email + existing banner) | Task 6/7 (email); the existing banner from the 2026-07-29 spec is untouched — confirmed out of scope in §6 |
| §2 "Consent" | Task 11 (UI copy note); no technical gate added beyond the existing admin-editable toggle — see the deferred item below |
| §3 "date_of_birth validated YYYY-MM-DD on every write path" | **Deferred, with reason** — see below |
| §3 "birth_month_day derived field" | Task 1 (derivation), Task 2 (backfill + index), Task 3 (kept in sync on write) |
| §3 "profile_nudges collection" | Task 4 (index), Task 5 (repository) |
| §3 "Birthday sends claim through digest_claim" | Task 9 (`MongoBirthdayNoticeSendRepository`) |
| §4.1 Staff digest (always on, coach sees own classes, admin/owner sees all, withdrawn shows "left on") | Task 12 — with one accepted deviation from "always on": the block rides `send_coach_daily_digests`, which `continue`s before `execute` for any academy whose coach digest is disabled, so such an academy gets no staff birthday email. Recorded in the release note; the fix, if the owner wants it, is a third cron. |
| §4.2 Family email (job, selection rule, one per student, no CTA, unsubscribe footer, per-academy setting default off) | Task 9, Task 10, Task 11 |
| §5 Profile nudges job (per-parent gap eval, record lifecycle, step timing, copy, category, deep link) | Task 6, Task 7, Task 8 |
| §5 "Admin visibility ... Needs attention sort (spec 2)" | **Deferred, with reason** — see below |
| §5 "existing missing= filter is unchanged" | Verified unchanged — `backend/v2/interfaces/admin/directory_routes.py:329` is not touched by this plan |
| §6 Out of scope (parent birthdays, never-enrolled siblings, SMS/WhatsApp, age-group auto-placement, parent profile page/banner changes) | Nothing in this plan touches `frontend/app/(parent)/parent/profile/page.tsx`, the banner, or adds an SMS/WhatsApp channel — verified by the file list above |
| §7 Unit tests (birth_month_day incl. leap day, nudge step table, gap-closes-stops-nudging) | Task 1, Task 6 |
| §7 Backend tests (idempotent under re-run, unsubscribed parent, withdrawn-only in digest not email, setting off -> no email) | Task 13 (idempotency, unsubscribe), Task 10 (withdrawn-only), Task 10 (`test_birthday_emails_are_off_unless_the_academy_turned_them_on` — the gate is the named `birthday_emails_enabled(academy_doc)` predicate in `composition/birthdays.py` precisely so it is reachable from a test rather than buried in a `main.py` job body) |
| §7 Migration test (backfill parses YYYY-MM-DD, skips and reports others) | Task 2 |

### Deferred items

1. **§3's "validated as `YYYY-MM-DD` on every write path (admin form, parent profile, onboarding) — today only the onboarding DTO checks format."** Verified false as written: `UpdateAdminStudentCommand.date_of_birth` (`admin_directory.py:155`) and `UpdateParentChildRequest.date_of_birth` (`interfaces/parent/views.py:540`) are both already Pydantic `date` fields with their own validators (the parent one additionally range-checks against today and 100 years back), so both the admin and parent edit paths already reject a malformed value before it reaches Mongo. Only the onboarding `ChildProfileView.date_of_birth` (`interfaces/parent/views.py:27`) is a raw string with its own `field_validator`, which the spec correctly describes. No new validation work is needed on the admin/parent edit paths; this plan adds none, and Task 3 relies on `date_of_birth` already being a validated ISO string by the time `derive_birth_month_day` sees it on those two paths. The onboarding DTO's existing validator is unchanged (already correct).
2. **§5's "Families list 'Needs attention' sort ... shows the last nudge date"** is explicitly attributed to "spec 2" (`2026-09-10-families-directory-consolidation-design.md`). Its plan — `docs/superpowers/plans/2026-09-10-families-directory-consolidation.md` (plan 2) — lands **before** this one and builds the sort without any nudge awareness: `sort="needs_attention"` on `ListBillingSetup.execute` ranked by `_needs_attention_rank` in `backend/v2/contexts/billing/application/use_cases/billing_setup_registration.py` (balance first, then never-invited, then the rest), served by `GET /admin/families` in `backend/v2/interfaces/admin/families_routes.py` (composed in `backend/v2/composition/families.py`), and toggled by the `Needs attention` button (`data-testid="admin-families-needs-attention"`) on the list component `frontend/app/(admin)/admin/families/page.tsx` (`FamiliesPage` / `FamilyTableRow`, rows typed as `FamiliesListRow` in `frontend/lib/api/admin-families.ts`). This plan makes the necessary data available — `profile_nudges` documents carry `sends: [{at, step}]`, so "last nudge date" is `max(s.at for s in sends)` — but does **not** extend that sort or add the column. The follow-up that does should: add a bulk read on `MongoNudgeRecordRepository` (Task 5), expose `last_nudge_at: datetime | None` on `BillingSetupRow` through a new optional port on `ListBillingSetup` (mirroring plan 2's optional `login_invites: LoginInviteDirectory | None`), fold it into `_needs_attention_rank`, thread it through `FamiliesListRowView` / `FamiliesListRow`, and render it in `FamilyTableRow` — rather than re-deriving nudge state from `ProfileGaps` alone.
3. **OPEN QUESTION (owner):** spec §2 makes turning the family birthday email on conditional on the owner first confirming that the registration wording covers birthday emails as a use of a child's date of birth. This plan ships the switch (default off) and a reminder line beside it (Task 11), but nothing in the code can verify that the registration copy actually says so. Someone has to read the current registration/consent text and either confirm it or amend it **before** `birthday_emails_enabled` is turned on for any academy. Not a code task and not blocking the merge; it blocks the rollout.
4. **True academy-local-morning delivery** for `send_birthday_notes`/`send_profile_nudges` is not built — both run on a single `settings.scheduler_tz` cron, the same limitation `generate_monthly_invoices` and the coach/parent digest hour already carry (documented in `main.py`'s own comments at the sites this plan mirrors). Spec §4.2 says "academy-local morning"; this plan achieves "a fixed morning hour, same timezone as every other daily job in this codebase" and calls that out rather than silently under-delivering on the spec's wording. Building true per-academy-timezone scheduling is a larger, pre-existing gap across every scheduled job, not something to fix piecemeal for two new jobs.
