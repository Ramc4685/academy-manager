"""identity_auth:4 — at request time: classes dropped, autopay paused, email sent."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from backend.v2.composition.account_deletion import StopServicesOnDeletionRequest
from backend.v2.contexts.billing.application.use_cases.pause_family_autopay import NothingToPause
from backend.v2.contexts.enrollment.application.use_cases.stop_all_classes import (
    StopAllClassesResult,
)
from backend.v2.contexts.identity.application.use_cases.send_login_invite import (
    InviteEmailOutcome,
)
from backend.v2.contexts.identity.domain.account_deletion import AccountDeletionRequest
from backend.v2.shared.tenancy.context import current_academy_id

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 11, 20, 12, tzinfo=UTC)


def _request() -> AccountDeletionRequest:
    return AccountDeletionRequest(
        request_id="r1",
        user_id="u1",
        auth_uid="fb1",
        email="p@example.com",
        aliases=("u1", "fb1"),
        academy_ids=("acad-a",),
        requested_at=NOW,
        execute_after=NOW + timedelta(days=14),
    )


class _Students:
    async def list_for_parent(self, parent_id: str) -> list[Any]:
        return [SimpleNamespace(student_id="kid-1")] if parent_id == "u1" else []


class _StopAll:
    def __init__(self) -> None:
        self.cmds: list[Any] = []

    async def execute(self, cmd: Any) -> StopAllClassesResult:
        assert current_academy_id() == "acad-a"
        self.cmds.append(cmd)
        return StopAllClassesResult(student_id=cmd.student_id, results=[])


class _Pause:
    def __init__(self) -> None:
        self.parents: list[str] = []

    async def execute(self, **kwargs: Any) -> None:
        self.parents.append(kwargs["parent_id"])
        if kwargs["parent_id"] == "fb1":
            raise NothingToPause("nothing")


class _Sender:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_invite_email(self, **kwargs: Any) -> InviteEmailOutcome:
        self.sent.append(kwargs)
        return InviteEmailOutcome(ok=True, failed_reason=None)


class _Academies:
    async def get_academy_name(self, academy_id: str) -> str | None:
        return "Smash Academy"


def _step() -> tuple[StopServicesOnDeletionRequest, _StopAll, _Pause, _Sender]:
    stop, pause, sender = _StopAll(), _Pause(), _Sender()
    step = StopServicesOnDeletionRequest(
        stop_all_classes=stop,  # type: ignore[arg-type]
        students=_Students(),  # type: ignore[arg-type]
        pause_autopay=pause,  # type: ignore[arg-type]
        sender=sender,
        academies=_Academies(),
    )
    return step, stop, pause, sender


async def test_fresh_request_drops_classes_pauses_autopay_and_emails() -> None:
    step, stop, pause, sender = _step()

    await step.on_requested(_request(), fresh=True)

    assert [c.student_id for c in stop.cmds] == ["kid-1"]
    assert stop.cmds[0].outcome == "adjustment"  # no money moves on the drop
    assert pause.parents == ["u1", "fb1"]  # NothingToPause is swallowed
    assert len(sender.sent) == 1
    mail = sender.sent[0]
    assert mail["email"] == "p@example.com"
    assert "Smash Academy" in mail["subject"]
    assert "December 4, 2026" in mail["body"]


async def test_a_retry_repeats_the_stop_but_sends_no_second_email() -> None:
    step, stop, _, sender = _step()

    await step.on_requested(_request(), fresh=False)

    assert len(stop.cmds) == 1
    assert sender.sent == []
