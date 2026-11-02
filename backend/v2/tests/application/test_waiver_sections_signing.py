"""Sections, initials, adult/minor paths and renewal on parent signing
(waiver signing upgrade, Phase 2a)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from backend.v2.contexts.onboarding.application.use_cases.parent_student_waivers import (
    GetParentWaiverRequirement,
    ParentWaiverStudent,
)
from backend.v2.contexts.onboarding.application.use_cases.student_waiver_status import (
    GetStudentWaiverStatus,
)
from backend.v2.contexts.onboarding.domain.errors import (
    WaiverDateOfBirthMissing,
    WaiverSignatureIncomplete,
)
from backend.v2.tests.application.test_waiver_assignment import (
    LIABILITY,
    NOW,
    FakeWaivers,
    _accept,
    _waiver,
)

AGREEMENT = _waiver(
    "agreement",
    "Participation agreement",
    body=(
        "## Risks [initials]\nBadminton has risks.\n"
        "## Adult release [adult]\nI release the academy.\n"
        "## Parent release [minor] [initials]\nI release on behalf of my child.\n"
    ),
)
# Turns 18 the day after NOW (2026-09-29).
TEEN = ParentWaiverStudent(student_id="st-teen", student_name="Tara", date_of_birth="2008-09-30")
KID = ParentWaiverStudent(student_id="st-kid", student_name="Kim", date_of_birth="2016-01-01")
NO_DOB = ParentWaiverStudent(student_id="st-x", student_name="Xan")


async def _sign(waivers: FakeWaivers, clock=lambda: NOW, **overrides: object):  # type: ignore[no-untyped-def]
    use_case = _accept(waivers)
    use_case._clock = clock
    fields: dict[str, object] = {
        "parent_id": "parent-1",
        "signer_name": "Pat Parent",
        "signer_email": "pat@example.com",
        "ip_address": None,
        "user_agent": None,
        "consent": True,
        "initials": {"agreement": {"s1": "pp", "s3": "PP"}},
    }
    fields.update(overrides)
    return await use_case.execute(**fields)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_initials_are_required_for_marked_sections_on_the_childs_path() -> None:
    waivers = FakeWaivers([AGREEMENT], [KID])

    with pytest.raises(WaiverSignatureIncomplete):
        await _sign(waivers, initials={"agreement": {"s1": "PP"}})
    assert waivers.saved == []

    await _sign(waivers)
    (saved,) = waivers.saved
    assert saved.signing_path == "minor"
    assert saved.initials == {"s1": "PP", "s3": "PP"}


@pytest.mark.asyncio
async def test_a_missing_date_of_birth_blocks_the_whole_signing_act() -> None:
    waivers = FakeWaivers([AGREEMENT], [KID, NO_DOB])

    with pytest.raises(WaiverDateOfBirthMissing):
        await _sign(waivers)
    assert waivers.saved == []

    view = await GetParentWaiverRequirement(waivers=waivers, clock=lambda: NOW).execute(
        parent_id="parent-1"
    )
    assert [(s.student_name, s.date_of_birth_missing) for s in view.students] == [
        ("Kim", False),
        ("Xan", True),
    ]


@pytest.mark.asyncio
async def test_a_waiver_without_age_sections_needs_no_date_of_birth() -> None:
    waivers = FakeWaivers([LIABILITY], [NO_DOB])

    await _sign(waivers, initials=None)

    assert waivers.saved[0].signing_path is None


@pytest.mark.asyncio
async def test_a_minor_signature_must_be_resigned_as_an_adult_at_18() -> None:
    waivers = FakeWaivers([AGREEMENT], [TEEN])
    await _sign(waivers)
    assert waivers.saved[0].signing_path == "minor"

    birthday = NOW + timedelta(days=1)
    view = await GetParentWaiverRequirement(waivers=waivers, clock=lambda: birthday).execute(
        parent_id="parent-1"
    )
    (row,) = view.students
    assert (row.status, row.signing_path) == ("outdated", "adult")

    # The adult path has no initialled section beyond s1.
    await _sign(waivers, clock=lambda: birthday, initials={"agreement": {"s1": "TT"}})
    assert waivers.saved[-1].signing_path == "adult"


@pytest.mark.asyncio
async def test_renewal_period_expires_old_signatures_for_parents_and_staff() -> None:
    yearly = LIABILITY.model_copy(update={"renew_every_months": 12})
    waivers = FakeWaivers([yearly], [KID])
    await _sign(waivers, initials=None)

    a_year_on = NOW.replace(year=NOW.year + 1)
    for moment, expected in ((a_year_on - timedelta(days=1), "signed"), (a_year_on, "outdated")):
        view = await GetParentWaiverRequirement(waivers=waivers, clock=lambda m=moment: m).execute(
            parent_id="parent-1"
        )
        assert view.students[0].status == expected

    ended = LIABILITY.model_copy(update={"valid_until": date(2026, 9, 1)})
    staff = await GetStudentWaiverStatus(
        FakeWaivers([ended], [KID], signatures=waivers.signatures)
    ).execute("st-kid")
    assert staff.waivers[0].status == "expired"


@pytest.mark.asyncio
async def test_registration_uses_the_childs_birth_date_and_requires_initials() -> None:
    from backend.v2.contexts.onboarding.application.use_cases.manage_application import (
        PatchApplication,
        PatchApplicationCommand,
    )
    from backend.v2.tests.application.test_waiver_assignment import (
        FakeApps,
        FakeRegistrationWaivers,
        _draft_app,
        _reg_waiver,
    )

    waiver = _reg_waiver("agreement", "wl-agreement").model_copy(update={"text": AGREEMENT.body})
    apps = FakeApps(_draft_app())
    use_case = PatchApplication(
        apps=apps, waivers=FakeRegistrationWaivers({None: [waiver]}), clock=lambda: NOW
    )

    def command(**overrides: object) -> PatchApplicationCommand:
        fields: dict[str, object] = {
            "application_id": "app-1",
            "caller_user_id": "parent-1",
            "accept_waiver": True,
            "signer_name": "Pat Parent",
            "consent": True,
            "initials": {"agreement": {"s1": "PP", "s3": "PP"}},
        }
        fields.update(overrides)
        return PatchApplicationCommand(**fields)  # type: ignore[arg-type]

    with pytest.raises(WaiverDateOfBirthMissing):
        await use_case.execute(command())

    child = {"first_name": "Kim", "last_name": "Lee", "date_of_birth": "2016-01-01"}
    with pytest.raises(WaiverSignatureIncomplete):
        await use_case.execute(command(child_profile=child, initials={"agreement": {"s1": "PP"}}))

    updated = await use_case.execute(command(child_profile=child))
    assert updated.waiver_acceptance is not None
    assert updated.waiver_acceptance.signing_path == "minor"
    assert updated.waiver_acceptance.initials == {"s1": "PP", "s3": "PP"}
