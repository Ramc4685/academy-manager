"""A waiver signature needs a deliberate act: full name, consent box, and only
the children the parent chose (waiver signing upgrade, Phase 1)."""

from __future__ import annotations

import pytest

from backend.v2.contexts.onboarding.domain.errors import (
    WaiverSignatureIncomplete,
    WaiverStudentNotFound,
)
from backend.v2.contexts.onboarding.domain.models import ESIGN_CONSENT_TEXT, clean_signer_name
from backend.v2.tests.application.test_waiver_assignment import (
    ALICE,
    BOB,
    LIABILITY,
    FakeWaivers,
    _accept,
)


async def _sign(waivers: FakeWaivers, **overrides: object):
    fields: dict[str, object] = {
        "parent_id": "parent-1",
        "signer_name": "Pat Parent",
        "signer_email": "pat@example.com",
        "ip_address": "203.0.113.10",
        "user_agent": "pytest",
        "consent": True,
    }
    fields.update(overrides)
    return await _accept(waivers).execute(**fields)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("Pat Parent", "Pat Parent"),
        ("  Pat   van  Parent ", "Pat van Parent"),
        ("Pat", None),
        ("pat@example.com", None),
        ("", None),
        (None, None),
    ],
)
def test_signer_name_must_be_a_full_name(raw: str | None, clean: str | None) -> None:
    assert clean_signer_name(raw) == clean


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [{"consent": False}, {"signer_name": None}, {"signer_name": "Pat"}],
)
async def test_signing_is_refused_without_name_and_consent(overrides: dict[str, object]) -> None:
    waivers = FakeWaivers([LIABILITY], [ALICE])

    with pytest.raises(WaiverSignatureIncomplete):
        await _sign(waivers, **overrides)

    assert waivers.saved == []


@pytest.mark.asyncio
async def test_signature_records_the_typed_name_consent_and_audit_fields() -> None:
    waivers = FakeWaivers([LIABILITY], [ALICE])

    view = await _sign(waivers, signer_name="  Pat   Parent ")

    (saved,) = waivers.saved
    assert saved.signer_name == "Pat Parent"
    assert saved.consent_text == ESIGN_CONSENT_TEXT
    assert saved.ip_address == "203.0.113.10"
    assert view.students[0].waiver_signature_id == saved.waiver_signature_id


@pytest.mark.asyncio
async def test_parent_can_sign_for_some_children_only() -> None:
    waivers = FakeWaivers([LIABILITY], [ALICE, BOB])

    view = await _sign(waivers, student_ids=["st-bob"])

    assert [s.student_id for s in waivers.saved] == ["st-bob"]
    assert [(s.student_name, s.status) for s in view.students] == [
        ("Alice", "pending"),
        ("Bob", "signed"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("student_ids", [["st-stranger"], ["st-alice", "st-stranger"], []])
async def test_a_child_who_is_not_the_parents_is_not_found(student_ids: list[str]) -> None:
    waivers = FakeWaivers([LIABILITY], [ALICE])

    with pytest.raises(WaiverStudentNotFound):
        await _sign(waivers, student_ids=student_ids)

    assert waivers.saved == []


# --- Registration: the same deliberate act, captured on the application ---


def _patch_use_case():
    from backend.v2.contexts.onboarding.application.use_cases.manage_application import (
        PatchApplication,
    )
    from backend.v2.tests.application.test_waiver_assignment import (
        NOW,
        FakeApps,
        FakeRegistrationWaivers,
        _draft_app,
        _reg_waiver,
    )

    apps = FakeApps(_draft_app())
    waivers = FakeRegistrationWaivers({None: [_reg_waiver("liability", "legacy")]})
    return apps, PatchApplication(apps=apps, waivers=waivers, clock=lambda: NOW)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [{"consent": False}, {"signer_name": None}, {"signer_name": "Pat"}],
)
async def test_registration_refuses_acceptance_without_name_and_consent(
    overrides: dict[str, object],
) -> None:
    from backend.v2.contexts.onboarding.application.use_cases.manage_application import (
        PatchApplicationCommand,
    )

    apps, use_case = _patch_use_case()
    fields: dict[str, object] = {
        "application_id": "app-1",
        "caller_user_id": "parent-1",
        "accept_waiver": True,
        "signer_name": "Pat Parent",
        "consent": True,
    }
    fields.update(overrides)

    with pytest.raises(WaiverSignatureIncomplete):
        await use_case.execute(PatchApplicationCommand(**fields))  # type: ignore[arg-type]

    assert apps.app.waiver_acceptance is None


@pytest.mark.asyncio
async def test_registration_acceptance_keeps_the_signing_evidence() -> None:
    from backend.v2.contexts.onboarding.application.use_cases.manage_application import (
        PatchApplicationCommand,
    )

    _, use_case = _patch_use_case()

    updated = await use_case.execute(
        PatchApplicationCommand(
            application_id="app-1",
            caller_user_id="parent-1",
            accept_waiver=True,
            signer_name=" Pat  Parent ",
            consent=True,
            ip_address="203.0.113.10",
            user_agent="pytest",
        )
    )

    acceptance = updated.waiver_acceptance
    assert acceptance is not None
    assert acceptance.signer_name == "Pat Parent"
    assert acceptance.consent_text == ESIGN_CONSENT_TEXT
    assert (acceptance.ip_address, acceptance.user_agent) == ("203.0.113.10", "pytest")


# --- Signed copy: a parent sees their own, nobody else's ---


def _copy(parent_user_id: str | None, student_id: str = "st-alice"):
    from backend.v2.contexts.onboarding.application.use_cases.parent_student_waivers import (
        ParentSignedWaiverCopy,
    )

    return ParentSignedWaiverCopy(
        waiver_signature_id="ws-1",
        student_id=student_id,
        student_name="Alice",
        parent_user_id=parent_user_id,
        body="Liability waiver text",
        signer_name="Pat Parent",
    )


class _CopyWaivers(FakeWaivers):
    def __init__(self, copy) -> None:  # type: ignore[no-untyped-def]
        super().__init__([LIABILITY], [ALICE])
        self._copy = copy

    async def signed_copy(self, waiver_signature_id: str):  # type: ignore[no-untyped-def]
        return self._copy if waiver_signature_id == "ws-1" else None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("copy_signer", "student_id", "visible"),
    [
        ("parent-1", "st-alice", True),
        ("parent-2", "st-alice", False),  # another guardian's signature
        (None, "st-alice", True),  # pre-tracking row, child is this parent's
        (None, "st-stranger", False),  # pre-tracking row, someone else's child
    ],
)
async def test_signed_copy_is_only_the_parents_own(
    copy_signer: str | None, student_id: str, visible: bool
) -> None:
    from backend.v2.contexts.onboarding.application.use_cases.parent_student_waivers import (
        GetParentSignedWaiver,
    )
    from backend.v2.contexts.onboarding.domain.errors import WaiverSignatureNotFound

    use_case = GetParentSignedWaiver(waivers=_CopyWaivers(_copy(copy_signer, student_id)))

    if visible:
        copy = await use_case.execute(parent_id="parent-1", waiver_signature_id="ws-1")
        assert copy.body == "Liability waiver text"
    else:
        with pytest.raises(WaiverSignatureNotFound):
            await use_case.execute(parent_id="parent-1", waiver_signature_id="ws-1")
    with pytest.raises(WaiverSignatureNotFound):
        await use_case.execute(parent_id="parent-1", waiver_signature_id="ws-other")


# --- Receipt: one email per signing act, nothing on a retry ---


class _Notifier:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[list[str]] = []
        self._fail = fail

    async def waivers_signed(self, *, parent_user_id, signer_email, waiver_signature_ids):  # type: ignore[no-untyped-def]
        self.calls.append(list(waiver_signature_ids))
        if self._fail:
            raise RuntimeError("resend down")


@pytest.mark.asyncio
async def test_receipt_goes_out_once_for_the_new_signatures_only() -> None:
    waivers = FakeWaivers([LIABILITY], [ALICE, BOB])
    notifier = _Notifier()
    use_case = _accept(waivers)
    use_case._notifier = notifier

    fields = {
        "parent_id": "parent-1",
        "signer_name": "Pat Parent",
        "signer_email": "pat@example.com",
        "ip_address": None,
        "user_agent": None,
        "consent": True,
    }
    await use_case.execute(**fields)  # type: ignore[arg-type]
    await use_case.execute(**fields)  # type: ignore[arg-type]  # retry: nothing new

    assert notifier.calls == [[s.waiver_signature_id for s in waivers.saved]]


@pytest.mark.asyncio
async def test_a_failed_receipt_never_fails_the_signature() -> None:
    waivers = FakeWaivers([LIABILITY], [ALICE])
    use_case = _accept(waivers)
    use_case._notifier = _Notifier(fail=True)

    view = await use_case.execute(
        parent_id="parent-1",
        signer_name="Pat Parent",
        signer_email="pat@example.com",
        ip_address=None,
        user_agent=None,
        consent=True,
    )

    assert view.students[0].status == "signed"


@pytest.mark.asyncio
async def test_receipt_email_lists_each_waiver_with_its_signed_copy_link() -> None:
    from datetime import UTC, datetime

    from backend.v2.composition.waiver_receipt_email import WaiverReceiptEmailAdapter
    from backend.v2.contexts.communications.infrastructure.stub_send_port import (
        StubEmailSendPort,
    )
    from backend.v2.contexts.onboarding.application.use_cases.parent_student_waivers import (
        ParentSignedWaiverCopy,
    )
    from backend.v2.shared.tenancy import tenant_scope

    copy = ParentSignedWaiverCopy(
        waiver_signature_id="ws-1",
        student_id="st-alice",
        student_name="Alice <b>",
        parent_user_id="parent-1",
        title="Liability",
        version="2",
        body="Liability text",
        content_hash="abc123",
        signed_at=datetime(2026, 11, 2, 15, 30, tzinfo=UTC),
        signer_name="Pat Parent",
        signer_email="pat@example.com",
        ip_address="203.0.113.10",
    )

    class _Copies:
        async def signed_copy(self, sid: str):  # type: ignore[no-untyped-def]
            return copy if sid == "ws-1" else None

    class _Academies:
        async def find_by_id(self, academy_id: str):  # type: ignore[no-untyped-def]
            return {"academy_id": academy_id, "display_name": "Alpha Club"}

    async def _base(_: str) -> str:
        return "https://alpha.example.com"

    sender = StubEmailSendPort()
    adapter = WaiverReceiptEmailAdapter(
        copies=_Copies(), academies=_Academies(), sender=sender, base_url_for=_base
    )
    with tenant_scope("acad-alpha"):
        await adapter.waivers_signed(
            parent_user_id="parent-1",
            signer_email="pat@example.com",
            waiver_signature_ids=["ws-1", "ws-missing"],
        )

    (sent,) = sender.sent
    assert sent["email"] == "pat@example.com"
    assert sent["subject"] == "Signed: Liability"
    assert "https://alpha.example.com/parent/waivers/signatures/ws-1" in sent["body"]
    assert "Alice &lt;b&gt;" in sent["body"]
    assert "2026-11-02 15:30 UTC" in sent["body"]
    assert "abc123" in sent["body"]
