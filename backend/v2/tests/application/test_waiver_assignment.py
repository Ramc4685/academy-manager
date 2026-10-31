"""Who signs which waiver: the required set, parent signing, staff status, and
the registration flow (Settings overhaul Phase 6, decisions 8 and 9)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.onboarding.application.use_cases.admin_waiver_templates import (
    AdminWaiverTemplateRecord,
)
from backend.v2.contexts.onboarding.application.use_cases.manage_application import (
    PatchApplication,
    PatchApplicationCommand,
)
from backend.v2.contexts.onboarding.application.use_cases.parent_student_waivers import (
    AcceptParentWaiver,
    GetParentWaiverRequirement,
    ParentWaiverSignature,
    ParentWaiverStudent,
)
from backend.v2.contexts.onboarding.application.use_cases.student_waiver_status import (
    GetStudentWaiverStatus,
)
from backend.v2.contexts.onboarding.domain.models import (
    Application,
    Waiver,
    WaiverAcceptance,
    WaiverSignature,
)

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


def _waiver(template_id: str, title: str, **overrides: object) -> AdminWaiverTemplateRecord:
    fields: dict[str, object] = {
        "waiver_template_id": template_id,
        "title": title,
        "body": f"{title} text",
        "status": "active",
        "version": "1",
        "content_hash": f"hash-{template_id}",
        "required": True,
        "updated_at": NOW,
        "lineage_key": f"wl-{template_id}",
    }
    fields.update(overrides)
    return AdminWaiverTemplateRecord(**fields)  # type: ignore[arg-type]


LIABILITY = _waiver("liability", "Liability waiver")
PHOTO = _waiver("photo", "Photo consent", scope="programs", program_ids=["prog-juniors"])
TRAVEL = _waiver("travel", "Travel release", required=False)


class FakeWaivers:
    def __init__(
        self,
        templates: list[AdminWaiverTemplateRecord],
        students: list[ParentWaiverStudent],
        programs: dict[str, set[str]] | None = None,
        signatures: dict[tuple[str, str], ParentWaiverSignature] | None = None,
    ) -> None:
        self._templates = templates
        self._students = students
        self._programs = programs or {}
        self.signatures = dict(signatures or {})
        self.legacy_flags: dict[tuple[str, str], ParentWaiverSignature] = {}
        self.saved: list[WaiverSignature] = []

    async def list_required_templates(self) -> list[AdminWaiverTemplateRecord]:
        return [t for t in self._templates if t.assignment.required]

    async def list_active_students_for_parent(self, parent_id: str) -> list[ParentWaiverStudent]:
        return list(self._students)

    async def program_ids_for_students(self, student_ids: list[str]) -> dict[str, set[str]]:
        return {sid: set(self._programs.get(sid, set())) for sid in student_ids}

    async def signatures_for_students(
        self, student_ids: list[str]
    ) -> dict[tuple[str, str], ParentWaiverSignature]:
        return {key: sig for key, sig in self.signatures.items() if key[0] in student_ids}

    async def legacy_flag_signatures(
        self, student_ids: list[str]
    ) -> dict[tuple[str, str], ParentWaiverSignature]:
        return {key: sig for key, sig in self.legacy_flags.items() if key[0] in student_ids}

    async def save_signature(self, signature: WaiverSignature) -> None:
        self.saved.append(signature)
        template = next(
            t for t in self._templates if t.waiver_template_id == signature.waiver_template_id
        )
        self.signatures[(signature.student_id, template.lineage)] = ParentWaiverSignature(
            student_id=signature.student_id,
            waiver_template_id=signature.waiver_template_id,
            content_hash=signature.content_hash,
            parent_user_id=signature.parent_user_id,
            signed_at=signature.signed_at,
            lineage_key=template.lineage,
            signed_version=template.version,
        )


ALICE = ParentWaiverStudent(student_id="st-alice", student_name="Alice")
BOB = ParentWaiverStudent(student_id="st-bob", student_name="Bob")


def _accept(waivers: FakeWaivers) -> AcceptParentWaiver:
    return AcceptParentWaiver(
        waivers=waivers,
        academy_id=lambda: "acad-1",
        id_factory=iter(f"ws-{n}" for n in range(1, 50)).__next__,
        clock=lambda: NOW,
    )


async def _sign(waivers: FakeWaivers, parent_id: str = "parent-1"):
    return await _accept(waivers).execute(
        parent_id=parent_id,
        signer_name="Pat",
        signer_email="pat@example.com",
        ip_address=None,
        user_agent=None,
    )


@pytest.mark.asyncio
async def test_single_all_families_waiver_reads_as_it_always_did() -> None:
    waivers = FakeWaivers([LIABILITY], [ALICE, BOB])

    view = await GetParentWaiverRequirement(waivers=waivers).execute(parent_id="parent-1")

    assert view.required is True
    assert view.waiver_template_id == "liability"
    assert view.title == "Liability waiver"
    assert view.body == "Liability waiver text"
    assert [(s.student_name, s.status) for s in view.students] == [
        ("Alice", "pending"),
        ("Bob", "pending"),
    ]
    assert [w.waiver_template_id for w in view.waivers] == ["liability"]

    signed = await _sign(waivers)
    assert [s.status for s in signed.students] == ["signed", "signed"]
    assert len(waivers.saved) == 2


@pytest.mark.asyncio
async def test_program_waiver_is_required_only_of_children_in_that_program() -> None:
    waivers = FakeWaivers(
        [LIABILITY, PHOTO, TRAVEL],
        [ALICE, BOB],
        programs={"st-alice": {"prog-juniors"}, "st-bob": {"prog-adults"}},
    )

    view = await GetParentWaiverRequirement(waivers=waivers).execute(parent_id="parent-1")

    assert [w.title for w in view.waivers] == ["Liability waiver", "Photo consent"]
    by_title = {w.title: w for w in view.waivers}
    assert [s.student_name for s in by_title["Liability waiver"].students] == ["Alice", "Bob"]
    assert [s.student_name for s in by_title["Photo consent"].students] == ["Alice"]
    # Flat fields are the primary (first) waiver.
    assert view.title == "Liability waiver"


@pytest.mark.asyncio
async def test_signing_covers_every_applicable_waiver_and_skips_signed_ones() -> None:
    waivers = FakeWaivers(
        [LIABILITY, PHOTO],
        [ALICE, BOB],
        programs={"st-alice": {"prog-juniors"}},
        signatures={
            ("st-alice", "wl-liability"): ParentWaiverSignature(
                student_id="st-alice",
                waiver_template_id="liability",
                content_hash="hash-liability",
                parent_user_id="parent-1",
                signed_at=NOW,
                lineage_key="wl-liability",
            )
        },
    )

    view = await _sign(waivers)

    # Alice already signed Liability, so only Photo (Alice) and Liability (Bob).
    assert sorted((s.student_id, s.waiver_template_id) for s in waivers.saved) == [
        ("st-alice", "photo"),
        ("st-bob", "liability"),
    ]
    assert all(s.status == "signed" for w in view.waivers for s in w.students)


@pytest.mark.asyncio
async def test_a_signature_for_another_waiver_does_not_count() -> None:
    waivers = FakeWaivers(
        [LIABILITY, PHOTO],
        [ALICE],
        programs={"st-alice": {"prog-juniors"}},
        signatures={
            ("st-alice", "wl-liability"): ParentWaiverSignature(
                student_id="st-alice",
                waiver_template_id="liability",
                content_hash="hash-liability",
                parent_user_id="parent-1",
                signed_at=NOW,
                lineage_key="wl-liability",
            )
        },
    )

    view = await GetParentWaiverRequirement(waivers=waivers).execute(parent_id="parent-1")

    status = {w.title: w.students[0].status for w in view.waivers}
    assert status == {"Liability waiver": "signed", "Photo consent": "pending"}


@pytest.mark.asyncio
async def test_no_required_waiver_means_none_required() -> None:
    waivers = FakeWaivers([TRAVEL], [ALICE])

    view = await GetParentWaiverRequirement(waivers=waivers).execute(parent_id="parent-1")

    assert view.required is False
    assert view.waivers == []
    assert [s.status for s in view.students] == ["not_required"]


@pytest.mark.asyncio
async def test_student_status_reports_signed_older_and_unsigned() -> None:
    v2 = _waiver("liability-v2", "Liability waiver", version="2", lineage_key="wl-liability")
    waivers = FakeWaivers(
        [
            v2,
            PHOTO,
            _waiver("adults", "Adult release", scope="programs", program_ids=["prog-adults"]),
        ],
        [ALICE],
        programs={"st-alice": {"prog-juniors"}},
        signatures={
            ("st-alice", "wl-liability"): ParentWaiverSignature(
                student_id="st-alice",
                waiver_template_id="liability-v1",
                content_hash="hash-liability-v1",
                parent_user_id="parent-1",
                signed_at=NOW - timedelta(days=30),
                lineage_key="wl-liability",
                waiver_signature_id="ws-old",
                signed_version="1",
            )
        },
    )

    status = await GetStudentWaiverStatus(waivers).execute("st-alice")

    rows = {row.title: row for row in status.waivers}
    assert set(rows) == {"Liability waiver", "Photo consent"}
    assert rows["Liability waiver"].status == "older_version"
    assert rows["Liability waiver"].version == "2"
    assert rows["Liability waiver"].signed_version == "1"
    assert rows["Liability waiver"].signature_id == "ws-old"
    assert rows["Photo consent"].status == "unsigned"
    assert [row.title for row in status.unsigned] == ["Liability waiver", "Photo consent"]


@pytest.mark.asyncio
async def test_older_signature_with_the_same_wording_still_counts_as_signed() -> None:
    v2 = _waiver("liability-v2", "Liability waiver", version="2", content_hash="same")
    waivers = FakeWaivers(
        [v2],
        [ALICE],
        signatures={
            ("st-alice", "wl-liability-v2"): ParentWaiverSignature(
                student_id="st-alice",
                waiver_template_id="liability-v1",
                content_hash="same",
                signed_at=NOW,
                lineage_key="wl-liability-v2",
                signed_version="1",
            )
        },
    )

    status = await GetStudentWaiverStatus(waivers).execute("st-alice")

    assert [row.status for row in status.waivers] == ["signed"]


@pytest.mark.asyncio
async def test_legacy_student_flag_counts_as_signed_when_no_signature_row_exists() -> None:
    legacy = _waiver("liability", "Liability waiver", lineage_key="legacy")
    waivers = FakeWaivers([legacy], [ALICE])
    waivers.legacy_flags[("st-alice", "legacy")] = ParentWaiverSignature(
        student_id="st-alice", signed_at=NOW, lineage_key="legacy"
    )

    status = await GetStudentWaiverStatus(waivers).execute("st-alice")

    assert [row.status for row in status.waivers] == ["signed"]
    assert status.unsigned == []


@pytest.mark.asyncio
async def test_real_signature_row_wins_over_the_legacy_flag() -> None:
    legacy = _waiver("liability", "Liability waiver", lineage_key="legacy", content_hash="new")
    waivers = FakeWaivers(
        [legacy],
        [ALICE],
        signatures={
            ("st-alice", "legacy"): ParentWaiverSignature(
                student_id="st-alice",
                waiver_template_id="liability-v0",
                content_hash="old",
                signed_at=NOW,
                lineage_key="legacy",
                waiver_signature_id="ws-real",
            )
        },
    )
    waivers.legacy_flags[("st-alice", "legacy")] = ParentWaiverSignature(
        student_id="st-alice", lineage_key="legacy"
    )

    status = await GetStudentWaiverStatus(waivers).execute("st-alice")

    assert [row.status for row in status.waivers] == ["older_version"]


# ---- registration flow ------------------------------------------------------


class FakeApps:
    def __init__(self, app: Application) -> None:
        self.app = app

    async def get(self, application_id: str) -> Application | None:
        return self.app

    async def save(self, app: Application) -> None:
        self.app = app


class FakeRegistrationWaivers:
    def __init__(self, by_session: dict[str | None, list[Waiver]]) -> None:
        self._by_session = by_session

    async def get_active(self) -> Waiver | None:
        return None

    async def list_required(self, session_id: str | None) -> list[Waiver]:
        return list(self._by_session.get(session_id, self._by_session.get(None, [])))


def _reg_waiver(waiver_id: str, lineage: str) -> Waiver:
    return Waiver(
        waiver_id=waiver_id,
        academy_id="acad-1",
        version="1",
        text=f"{waiver_id} text",
        content_hash=f"hash-{waiver_id}",
        effective_from=NOW,
        lineage_key=lineage,
        title=waiver_id,
    )


def _draft_app() -> Application:
    return Application(
        application_id="app-1",
        academy_id="acad-1",
        parent_user_id="parent-1",
        parent_email="parent@example.com",
        expires_at=NOW + timedelta(days=7),
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.asyncio
async def test_accepting_stores_every_waiver_for_the_chosen_class() -> None:
    liability = _reg_waiver("liability", "wl-liability")
    photo = _reg_waiver("photo", "wl-photo")
    apps = FakeApps(_draft_app().model_copy(update={"selected_session_id": "s-juniors"}))
    waivers = FakeRegistrationWaivers({"s-juniors": [liability, photo]})
    use_case = PatchApplication(apps=apps, waivers=waivers, clock=lambda: NOW)

    updated = await use_case.execute(
        PatchApplicationCommand(
            application_id="app-1", caller_user_id="parent-1", accept_waiver=True
        )
    )

    assert updated.waiver_acceptance is not None
    assert updated.waiver_acceptance.waiver_template_id == "liability"
    assert updated.waiver_acceptance.lineage_key == "wl-liability"
    assert [a.waiver_template_id for a in updated.additional_waiver_acceptances] == ["photo"]


@pytest.mark.asyncio
async def test_single_waiver_flow_is_unchanged_by_choosing_a_class() -> None:
    liability = _reg_waiver("liability", "legacy")
    apps = FakeApps(_draft_app())
    waivers = FakeRegistrationWaivers({None: [liability]})
    use_case = PatchApplication(apps=apps, waivers=waivers, clock=lambda: NOW)

    accepted = await use_case.execute(
        PatchApplicationCommand(
            application_id="app-1", caller_user_id="parent-1", accept_waiver=True
        )
    )
    chose_class = await use_case.execute(
        PatchApplicationCommand(
            application_id="app-1", caller_user_id="parent-1", selected_session_id="s-any"
        )
    )

    assert accepted.additional_waiver_acceptances == []
    assert chose_class.waiver_acceptance == accepted.waiver_acceptance
    assert chose_class.selected_session_id == "s-any"


@pytest.mark.asyncio
async def test_switching_to_a_class_with_an_extra_waiver_asks_again() -> None:
    liability = _reg_waiver("liability", "wl-liability")
    photo = _reg_waiver("photo", "wl-photo")
    accepted = WaiverAcceptance(
        waiver_version="1",
        content_hash="hash-liability",
        accepted_at=NOW,
        waiver_template_id="liability",
        lineage_key="wl-liability",
    )
    apps = FakeApps(
        _draft_app().model_copy(
            update={"selected_session_id": "s-adults", "waiver_acceptance": accepted}
        )
    )
    waivers = FakeRegistrationWaivers({"s-adults": [liability], "s-juniors": [liability, photo]})
    use_case = PatchApplication(apps=apps, waivers=waivers, clock=lambda: NOW)

    updated = await use_case.execute(
        PatchApplicationCommand(
            application_id="app-1", caller_user_id="parent-1", selected_session_id="s-juniors"
        )
    )

    assert updated.waiver_acceptance is None
    assert updated.additional_waiver_acceptances == []
