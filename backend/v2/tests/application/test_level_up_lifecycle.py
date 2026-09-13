"""Issue #673: the level-up flow respects enrollment lifecycle.

A recommendation made while a student was enrolled must not survive their
withdrawal as an approvable row. The queue flags it, approve refuses it,
reject clears it, recommend refuses to create it, and the
EnrollmentCancelled handler's use case expires it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.student_progress.application.use_cases.expire_level_up_recommendations import (
    ENROLLMENT_ENDED_REASON,
    ENROLLMENT_ENDED_REVIEWER,
    ExpireLevelUpRecommendations,
)
from backend.v2.contexts.student_progress.application.use_cases.get_level_up_queue import (
    GetLevelUpQueue,
    GetLevelUpQueueCommand,
    LevelUpQueueEntry,
)
from backend.v2.contexts.student_progress.application.use_cases.recommend_level_up import (
    RecommendLevelUp,
    RecommendLevelUpCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.review_level_up import (
    ReviewLevelUpCommand,
    ReviewLevelUpRecommendation,
)
from backend.v2.contexts.student_progress.domain.errors import (
    EnrollmentEnded,
    RecommendationAlreadyReviewed,
)
from backend.v2.contexts.student_progress.domain.models import (
    ACTIVE_LEVEL_UP_STATUSES,
    CLAIMABLE_LEVEL_UP_STATUSES,
    LevelUpRecommendation,
    StudentLevelProgress,
)

_NOW = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
# Mirrors the Mongo repo's status filters (issue #548): a claimed row is
# still pending for the admin and still blocks a fresh recommendation.
_ACTIVE = ACTIVE_LEVEL_UP_STATUSES
_CLAIMABLE = CLAIMABLE_LEVEL_UP_STATUSES


# ---------------------------------------------------------------------------
# Fakes — same semantics as the Mongo repos (CAS on status, no overwrite-on-put)
# ---------------------------------------------------------------------------


class _EnrollmentLookup:
    def __init__(self, live: set[str]) -> None:
        self.live = live
        self.single_calls: list[str] = []
        self.batch_calls: list[list[str]] = []

    async def has_active_or_paused_enrollment(self, student_id: str) -> bool:
        self.single_calls.append(student_id)
        return student_id in self.live

    async def students_with_active_or_paused_enrollment(self, student_ids: list[str]) -> set[str]:
        self.batch_calls.append(list(student_ids))
        return {sid for sid in student_ids if sid in self.live}


class _RecRepo:
    def __init__(self) -> None:
        self.rows: dict[str, LevelUpRecommendation] = {}

    async def save(self, rec: LevelUpRecommendation) -> None:
        if rec.rec_id in self.rows:
            raise AssertionError("duplicate rec_id")
        self.rows[rec.rec_id] = rec

    async def claim(self, rec_id, claim_status, claimed_at, *, lease) -> bool:
        """Mirrors the Mongo CAS: RECOMMENDED, or a claim past its lease."""
        rec = self.rows.get(rec_id)
        if rec is None:
            return False
        stale = rec.claimed_at is not None and rec.claimed_at < claimed_at - lease
        claimable = rec.status == "RECOMMENDED" or (
            rec.status in ("APPROVING", "REJECTING") and stale
        )
        if not claimable:
            return False
        self.rows[rec_id] = rec.model_copy(
            update={"status": claim_status, "claimed_at": claimed_at}
        )
        return True

    async def release(self, rec_id, *, claim_status) -> bool:
        rec = self.rows.get(rec_id)
        if rec is None or rec.status != claim_status:
            return False
        self.rows[rec_id] = rec.model_copy(update={"status": "RECOMMENDED", "claimed_at": None})
        return True

    async def update_status(
        self, rec_id, status, reviewed_by, reviewed_at, rejection_reason, *, expected_status
    ) -> bool:
        rec = self.rows.get(rec_id)
        if rec is None or rec.status != expected_status:
            return False
        self.rows[rec_id] = rec.model_copy(
            update={
                "status": status,
                "reviewed_by": reviewed_by,
                "reviewed_at": reviewed_at,
                "rejection_reason": rejection_reason,
            }
        )
        return True

    async def get(self, rec_id: str) -> LevelUpRecommendation | None:
        return self.rows.get(rec_id)

    async def get_active_for_student(self, student_id, program_id):
        return next(
            (
                r
                for r in self.rows.values()
                if r.student_id == student_id and r.program_id == program_id and r.status in _ACTIVE
            ),
            None,
        )

    async def list_active_for_students(self, student_ids, program_id):
        return [
            r
            for r in self.rows.values()
            if r.student_id in student_ids and r.program_id == program_id and r.status in _ACTIVE
        ]

    async def list_pending(self) -> list[LevelUpRecommendation]:
        return sorted(
            (r for r in self.rows.values() if r.status in _CLAIMABLE),
            key=lambda r: r.recommended_at,
        )

    async def list_recommended_for_student(self, student_id: str) -> list[LevelUpRecommendation]:
        return [
            r
            for r in sorted(self.rows.values(), key=lambda r: r.recommended_at)
            if r.student_id == student_id and r.status == "RECOMMENDED"
        ]


class _LevelProgressRepo:
    def __init__(self) -> None:
        self.rows: dict[str, StudentLevelProgress] = {}
        self.completed: list[str] = []

    async def save(self, progress: StudentLevelProgress) -> None:
        self.rows[progress.progress_id] = progress

    async def get_active(self, student_id: str, program_id: str):
        return next(
            (
                p
                for p in self.rows.values()
                if p.student_id == student_id
                and p.program_id == program_id
                and p.status == "active"
            ),
            None,
        )

    async def get_by_id(self, progress_id):
        return self.rows.get(progress_id)

    async def complete(self, progress_id, completed_at) -> None:
        self.completed.append(progress_id)
        self.rows[progress_id] = self.rows[progress_id].model_copy(
            update={"status": "completed", "completed_at": completed_at}
        )

    async def list_for_student(self, student_id):
        return [p for p in self.rows.values() if p.student_id == student_id]

    async def list_active_for_students(self, student_ids, program_id):
        return []


class _SkillProgressRepo:
    def __init__(self) -> None:
        self.upserts: list[object] = []

    async def save(self, sp) -> None:
        self.upserts.append(sp)

    async def upsert(self, sp):
        self.upserts.append(sp)
        return sp

    async def get(self, student_id, skill_id):
        return None

    async def list_for_student_level(self, student_id, level_id):
        return []

    async def list_passed_for_student_level(self, student_id, level_id):
        return []

    async def list_recent_for_student(self, student_id, limit=10):
        return []

    async def list_in_progress_for_student(self, student_id):
        return []

    async def list_for_students(self, student_ids, level_id):
        return []

    async def count_updates_by_coach(self, *, start_at, end_at):
        return []


class _CertRepo:
    def __init__(self) -> None:
        self.rows: list[object] = []

    async def save(self, cert) -> None:
        self.rows.append(cert)

    async def list_for_student(self, student_id):
        return [c for c in self.rows if c.student_id == student_id]

    async def list_for_students(self, student_ids):
        return [c for c in self.rows if c.student_id in student_ids]


class _SkillLookup:
    async def get_skill(self, skill_id):
        return None

    async def get_level(self, level_id):
        return None

    async def list_skills_for_level(self, level_id):
        return []

    async def get_next_level(self, program_id, current_sequence):
        return None


def _rec(rec_id: str, student_id: str, *, program_id: str = "prog-1") -> LevelUpRecommendation:
    return LevelUpRecommendation(
        rec_id=rec_id,
        academy_id="acad",
        student_id=student_id,
        from_level_id="lvl-1",
        to_level_id="lvl-2",
        program_id=program_id,
        status="RECOMMENDED",
        recommended_by="coach-1",
        recommended_at=_NOW,
    )


def _review(recs: _RecRepo, lookup: _EnrollmentLookup) -> ReviewLevelUpRecommendation:
    return ReviewLevelUpRecommendation(
        recommendations=recs,
        level_progress=_LevelProgressRepo(),
        skill_progress=_SkillProgressRepo(),
        certificates=_CertRepo(),
        skill_lookup=_SkillLookup(),
        enrollment_lookup=lookup,
    )


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_queue_annotates_each_row_with_one_batch_lookup() -> None:
    recs = _RecRepo()
    await recs.save(_rec("rec-live", "st-live"))
    await recs.save(_rec("rec-gone", "st-gone"))
    await recs.save(_rec("rec-gone-2", "st-gone", program_id="prog-2"))
    lookup = _EnrollmentLookup(live={"st-live"})
    queue = GetLevelUpQueue(
        level_progress=_LevelProgressRepo(),
        skill_progress=_SkillProgressRepo(),
        recommendations=recs,
        skill_lookup=_SkillLookup(),
        enrollment_lookup=lookup,
    )

    rows = await queue.execute(GetLevelUpQueueCommand())

    assert all(isinstance(row, LevelUpQueueEntry) for row in rows)
    assert {row.rec_id: row.enrollment_active for row in rows} == {
        "rec-live": True,
        "rec-gone": False,
        "rec-gone-2": False,
    }
    # Withdrawn rows are shown, not hidden: the admin needs to reject them.
    assert len(rows) == 3
    assert lookup.batch_calls == [["st-gone", "st-live"]]
    assert lookup.single_calls == []
    # The row keeps every recommendation field the UI already renders.
    assert rows[0].model_dump()["enrollment_active"] in (True, False)
    assert rows[0].model_dump()["recommended_by"] == "coach-1"


@pytest.mark.asyncio
async def test_queue_program_filter_applies_before_the_lookup() -> None:
    recs = _RecRepo()
    await recs.save(_rec("rec-a", "st-a", program_id="prog-1"))
    await recs.save(_rec("rec-b", "st-b", program_id="prog-2"))
    lookup = _EnrollmentLookup(live={"st-a", "st-b"})
    queue = GetLevelUpQueue(
        level_progress=_LevelProgressRepo(),
        skill_progress=_SkillProgressRepo(),
        recommendations=recs,
        skill_lookup=_SkillLookup(),
        enrollment_lookup=lookup,
    )

    rows = await queue.execute(GetLevelUpQueueCommand(program_id="prog-2"))

    assert [row.rec_id for row in rows] == ["rec-b"]
    assert lookup.batch_calls == [["st-b"]]


# ---------------------------------------------------------------------------
# Approve / reject
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_refuses_a_withdrawn_student_before_any_write() -> None:
    recs = _RecRepo()
    await recs.save(_rec("rec-1", "st-gone"))
    lookup = _EnrollmentLookup(live=set())
    level_progress = _LevelProgressRepo()
    certs = _CertRepo()
    review = ReviewLevelUpRecommendation(
        recommendations=recs,
        level_progress=level_progress,
        skill_progress=_SkillProgressRepo(),
        certificates=certs,
        skill_lookup=_SkillLookup(),
        enrollment_lookup=lookup,
    )

    with pytest.raises(EnrollmentEnded) as excinfo:
        await review.execute(
            ReviewLevelUpCommand(rec_id="rec-1", action="approve", reviewed_by="admin-1")
        )

    assert excinfo.value.status_code == 409
    assert excinfo.value.code == "StudentProgress.EnrollmentEnded"
    assert excinfo.value.details == {"rec_id": "rec-1", "student_id": "st-gone"}
    assert certs.rows == []
    assert level_progress.rows == {}
    # Still pending: the admin can reject it, and the chip explains why.
    assert recs.rows["rec-1"].status == "RECOMMENDED"


@pytest.mark.asyncio
async def test_approve_still_works_for_a_paused_student() -> None:
    """Paused counts as live (issue #651): the seat is kept, the family is
    invoiced, and the student comes back — a level earned before the pause
    is still theirs."""
    recs = _RecRepo()
    await recs.save(_rec("rec-1", "st-paused"))
    review = _review(recs, _EnrollmentLookup(live={"st-paused"}))

    result = await review.execute(
        ReviewLevelUpCommand(rec_id="rec-1", action="approve", reviewed_by="admin-1")
    )

    assert result.status == "APPROVED"
    assert result.cert_id


@pytest.mark.asyncio
async def test_reject_is_allowed_for_a_withdrawn_student() -> None:
    recs = _RecRepo()
    await recs.save(_rec("rec-1", "st-gone"))
    lookup = _EnrollmentLookup(live=set())
    review = _review(recs, lookup)

    result = await review.execute(
        ReviewLevelUpCommand(
            rec_id="rec-1",
            action="reject",
            reviewed_by="admin-1",
            rejection_reason="family withdrew",
        )
    )

    assert result.status == "REJECTED"
    assert recs.rows["rec-1"].rejection_reason == "family withdrew"
    # Reject never needs the lookup.
    assert lookup.single_calls == []


@pytest.mark.asyncio
async def test_interleaved_approve_and_reject_never_certifies_a_rejected_student() -> None:
    """Issue #548: approve and reject arriving together must not both land.

    The approval's side effects (certificate, level advance, skill seeding)
    used to run before anything guarded the row, so a reject that committed
    while they were in flight left the recommendation REJECTED *and* the
    student holding a certificate for the level. Exactly one decision may
    take effect, and a REJECTED row must never coexist with a certificate.
    """
    recs = _RecRepo()
    await recs.save(_rec("rec-1", "st-live"))
    level_progress = _LevelProgressRepo()
    certs = _CertRepo()
    shared: dict[str, object] = {
        "recommendations": recs,
        "level_progress": level_progress,
        "skill_progress": _SkillProgressRepo(),
        "certificates": certs,
        "skill_lookup": _SkillLookup(),
        "enrollment_lookup": _EnrollmentLookup(live={"st-live"}),
    }
    approve = ReviewLevelUpRecommendation(**shared)  # type: ignore[arg-type]
    reject = ReviewLevelUpRecommendation(**shared)  # type: ignore[arg-type]

    outcomes: list[str] = []
    original_get_active = level_progress.get_active

    async def _reject_midway(student_id: str, program_id: str):
        # The other admin's request arrives once this approval has started
        # its side effects but before it has recorded any decision.
        level_progress.get_active = original_get_active  # type: ignore[method-assign]
        try:
            rejected = await reject.execute(
                ReviewLevelUpCommand(
                    rec_id="rec-1",
                    action="reject",
                    reviewed_by="admin-2",
                    rejection_reason="not ready",
                )
            )
        except RecommendationAlreadyReviewed:
            outcomes.append("reject:refused")
        else:
            outcomes.append(f"reject:{rejected.status}")
        return await original_get_active(student_id, program_id)

    level_progress.get_active = _reject_midway  # type: ignore[method-assign]

    try:
        approved = await approve.execute(
            ReviewLevelUpCommand(rec_id="rec-1", action="approve", reviewed_by="admin-1")
        )
    except RecommendationAlreadyReviewed:
        outcomes.append("approve:refused")
    else:
        outcomes.append(f"approve:{approved.status}")

    # One winner, one refusal — never two recorded decisions.
    assert sorted(outcomes) in (
        ["approve:APPROVED", "reject:refused"],
        ["approve:refused", "reject:REJECTED"],
    )
    stored = recs.rows["rec-1"]
    if stored.status == "REJECTED":
        assert certs.rows == []
        assert level_progress.rows == {}
    else:
        assert stored.status == "APPROVED"
        assert len(certs.rows) == 1


# ---------------------------------------------------------------------------
# Recommend (defence in depth behind the coach route's 404)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recommend_refuses_a_withdrawn_student_before_reading_placement() -> None:
    recs = _RecRepo()
    level_progress = _LevelProgressRepo()
    await level_progress.save(
        StudentLevelProgress(
            progress_id="progress-1",
            academy_id="acad",
            student_id="st-gone",
            program_id="prog-1",
            level_id="lvl-1",
            status="active",
            started_at=_NOW,
            completed_at=None,
            created_at=_NOW,
        )
    )
    recommend = RecommendLevelUp(
        level_progress=level_progress,
        skill_progress=_SkillProgressRepo(),
        recommendations=recs,
        skill_lookup=_SkillLookup(),
        enrollment_lookup=_EnrollmentLookup(live=set()),
    )

    with pytest.raises(EnrollmentEnded) as excinfo:
        await recommend.execute(
            RecommendLevelUpCommand(
                student_id="st-gone", program_id="prog-1", recommended_by="coach-1"
            )
        )

    assert excinfo.value.details == {"student_id": "st-gone", "program_id": "prog-1"}
    assert recs.rows == {}


# ---------------------------------------------------------------------------
# Expiry (runs from the EnrollmentCancelled handler)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_expiry_closes_every_pending_row_for_a_student_with_no_live_enrollment() -> None:
    recs = _RecRepo()
    await recs.save(_rec("rec-1", "st-gone"))
    await recs.save(_rec("rec-2", "st-gone", program_id="prog-2"))
    await recs.save(_rec("rec-other", "st-live"))
    expire = ExpireLevelUpRecommendations(
        recommendations=recs, enrollment_lookup=_EnrollmentLookup(live={"st-live"})
    )

    result = await expire.execute("st-gone")

    assert result.expired_rec_ids == ["rec-1", "rec-2"]
    assert result.skipped_still_enrolled is False
    for rec_id in ("rec-1", "rec-2"):
        row = recs.rows[rec_id]
        assert row.status == "REJECTED"
        assert row.rejection_reason == ENROLLMENT_ENDED_REASON
        assert row.reviewed_by == ENROLLMENT_ENDED_REVIEWER
        assert row.reviewed_at is not None
    # Another student's row is untouched.
    assert recs.rows["rec-other"].status == "RECOMMENDED"


@pytest.mark.asyncio
async def test_expiry_skips_a_student_who_still_has_a_live_enrollment() -> None:
    """Dropping one of two sessions, or a pause whose seat was handed on
    (PauseEnrollment also emits EnrollmentCancelled), is not a withdrawal."""
    recs = _RecRepo()
    await recs.save(_rec("rec-1", "st-still-here"))
    expire = ExpireLevelUpRecommendations(
        recommendations=recs, enrollment_lookup=_EnrollmentLookup(live={"st-still-here"})
    )

    result = await expire.execute("st-still-here")

    assert result.skipped_still_enrolled is True
    assert result.expired_rec_ids == []
    assert recs.rows["rec-1"].status == "RECOMMENDED"


@pytest.mark.asyncio
async def test_expiry_does_not_overwrite_an_admin_decision_made_meanwhile() -> None:
    recs = _RecRepo()
    await recs.save(_rec("rec-1", "st-gone"))
    # An admin rejected it between the event being emitted and handled.
    await recs.update_status(
        "rec-1", "REJECTED", "admin-1", _NOW, "not ready", expected_status="RECOMMENDED"
    )
    expire = ExpireLevelUpRecommendations(
        recommendations=recs, enrollment_lookup=_EnrollmentLookup(live=set())
    )

    result = await expire.execute("st-gone")

    assert result.expired_rec_ids == []
    assert recs.rows["rec-1"].rejection_reason == "not ready"
    assert recs.rows["rec-1"].reviewed_by == "admin-1"


@pytest.mark.asyncio
async def test_expiry_leaves_a_row_a_reviewer_is_holding_to_that_reviewer() -> None:
    """Issue #548: a claimed row is mid-review, possibly mid-certificate.

    Expiry must not compare-and-set it out from under the reviewer; it takes
    only rows still in RECOMMENDED, and reports honestly that it took none.
    """
    recs = _RecRepo()
    await recs.save(_rec("rec-claimed", "st-gone"))
    await recs.save(_rec("rec-open", "st-gone", program_id="prog-2"))
    await recs.claim("rec-claimed", "APPROVING", _NOW, lease=timedelta(minutes=10))
    expire = ExpireLevelUpRecommendations(
        recommendations=recs, enrollment_lookup=_EnrollmentLookup(live=set())
    )

    result = await expire.execute("st-gone")

    assert result.expired_rec_ids == ["rec-open"]
    assert recs.rows["rec-claimed"].status == "APPROVING"
    assert recs.rows["rec-claimed"].rejection_reason is None
    assert recs.rows["rec-open"].status == "REJECTED"
