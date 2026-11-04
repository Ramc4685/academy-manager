"""Push token-move auditing (M2 hardening) and push sending (mobile M3)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from firebase_admin import exceptions as firebase_exceptions
from firebase_admin import messaging

from backend.v2.composition.push import _build_push_sender
from backend.v2.contexts.communications.application.use_cases.register_push_device import (
    RegisterPushDevice,
    RegisterPushDeviceCommand,
)
from backend.v2.contexts.communications.application.use_cases.send_push_to_user import (
    SendPushToUser,
)
from backend.v2.contexts.communications.domain.push_device import (
    PushDevice,
    PushSendResult,
    PushTokenMove,
    token_fingerprint,
)
from backend.v2.contexts.communications.infrastructure import fcm_push_send_port
from backend.v2.contexts.communications.infrastructure.fcm_push_send_port import FcmPushSendPort
from backend.v2.contexts.communications.infrastructure.stub_push_send_port import (
    StubPushSendPort,
)

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
MOVE = PushTokenMove(
    token_fingerprint=token_fingerprint("raw-fcm-secret"),
    from_user_id="mom",
    from_academy_id="a",
    to_user_id="dad",
    to_academy_id="b",
)


@dataclass
class _FakeDevices:
    move: PushTokenMove | None = None
    tokens: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    deleted: list[tuple[str, list[str]]] = field(default_factory=list)
    fail_lookup: bool = False

    async def register(self, device: PushDevice) -> tuple[PushDevice, PushTokenMove | None]:
        return device, self.move

    async def delete(self, *, user_id: str, token: str) -> None:
        raise AssertionError("not used")

    async def tokens_for_user(self, academy_id: str, user_id: str) -> list[str]:
        if self.fail_lookup:
            raise RuntimeError("mongo down")
        return list(self.tokens.get((academy_id, user_id), []))

    async def delete_tokens(self, academy_id: str, tokens: Sequence[str]) -> None:
        self.deleted.append((academy_id, list(tokens)))


@dataclass
class _FakeAudit:
    moves: list[PushTokenMove] = field(default_factory=list)
    fail: bool = False

    async def record_token_moved(self, move: PushTokenMove) -> None:
        if self.fail:
            raise RuntimeError("audit store down")
        self.moves.append(move)


def _command() -> RegisterPushDeviceCommand:
    return RegisterPushDeviceCommand(user_id="dad", token="raw-fcm-secret", platform="ios")


# --- token moves are audited -------------------------------------------------


def test_fingerprint_is_short_stable_and_not_the_token() -> None:
    assert token_fingerprint("tok") == token_fingerprint("tok") != token_fingerprint("tok2")
    assert len(token_fingerprint("tok")) == 16 and "tok" not in token_fingerprint("tok")


async def test_a_move_is_audited() -> None:
    audit = _FakeAudit()
    use_case = RegisterPushDevice(devices=_FakeDevices(move=MOVE), audit=audit, now=lambda: NOW)
    device = await use_case.execute(_command())
    assert device.user_id == "dad"
    assert audit.moves == [MOVE]


async def test_no_move_no_audit() -> None:
    audit = _FakeAudit()
    await RegisterPushDevice(devices=_FakeDevices(), audit=audit, now=lambda: NOW).execute(
        _command()
    )
    assert audit.moves == []


async def test_audit_failure_is_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    use_case = RegisterPushDevice(
        devices=_FakeDevices(move=MOVE), audit=_FakeAudit(fail=True), now=lambda: NOW
    )
    device = await use_case.execute(_command())
    assert device.token == "raw-fcm-secret"
    record = next(r for r in caplog.records if "audit write failed" in r.getMessage())
    assert record.token_fingerprint == MOVE.token_fingerprint  # type: ignore[attr-defined]
    assert "raw-fcm-secret" not in str(record.__dict__)


# --- SendPushToUser ----------------------------------------------------------


async def test_sends_to_every_device_and_prunes_dead_tokens() -> None:
    devices = _FakeDevices(tokens={("a", "u1"): ["t1", "t2", "t3"]})
    sender = StubPushSendPort(dead={"t2"})
    result = await SendPushToUser(devices=devices, sender=sender).execute(
        academy_id="a", user_id="u1", title="Class cancelled", body="Tonight", data={"k": "v"}
    )
    assert result == PushSendResult(attempted=3, sent=2, dead_tokens=("t2",))
    assert [s["token"] for s in sender.sent] == ["t1", "t3"]
    assert sender.sent[0]["data"] == {"k": "v"}
    assert devices.deleted == [("a", ["t2"])]


async def test_user_without_devices_sends_nothing() -> None:
    sender = StubPushSendPort()
    result = await SendPushToUser(devices=_FakeDevices(), sender=sender).execute(
        academy_id="a", user_id="u1", title="t", body="b"
    )
    assert result == PushSendResult() and sender.sent == []


async def test_other_academy_devices_are_not_used() -> None:
    sender = StubPushSendPort()
    devices = _FakeDevices(tokens={("b", "u1"): ["t1"]})
    await SendPushToUser(devices=devices, sender=sender).execute(
        academy_id="a", user_id="u1", title="t", body="b"
    )
    assert sender.sent == []


class _ExplodingSender:
    async def send(self, **_: Any) -> PushSendResult:
        raise RuntimeError("FCM down")


@pytest.mark.parametrize(
    ("devices", "sender"),
    [
        (_FakeDevices(tokens={("a", "u1"): ["t1"]}), _ExplodingSender()),
        (_FakeDevices(fail_lookup=True), StubPushSendPort()),
    ],
)
async def test_push_failure_never_raises_into_the_caller(devices: Any, sender: Any) -> None:
    result = await SendPushToUser(devices=devices, sender=sender).execute(
        academy_id="a", user_id="u1", title="t", body="b"
    )
    assert result == PushSendResult()
    assert devices.deleted == []


# --- FCM adapter -------------------------------------------------------------


def _fcm_error(kind: str) -> Exception:
    if kind == "unregistered":
        return messaging.UnregisteredError("Requested entity was not found.")
    if kind == "sender_mismatch":
        return messaging.SenderIdMismatchError("SenderId mismatch")
    if kind == "bad_token":
        return firebase_exceptions.InvalidArgumentError(
            "The registration token is not a valid FCM registration token"
        )
    if kind == "bad_payload":
        return firebase_exceptions.InvalidArgumentError("Invalid JSON payload received.")
    return firebase_exceptions.UnavailableError("FCM is unavailable")


async def test_fcm_adapter_reports_only_token_errors_as_dead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcomes = ["ok", "unregistered", "sender_mismatch", "bad_token", "bad_payload", "unavailable"]
    tokens = [f"t-{o}" for o in outcomes]
    calls: list[dict[str, Any]] = []

    def _send(message: messaging.MulticastMessage, app: Any = None) -> Any:
        calls.append({"tokens": message.tokens, "app": app, "data": message.data})
        return SimpleNamespace(
            responses=[
                SimpleNamespace(success=o == "ok", exception=None if o == "ok" else _fcm_error(o))
                for o in outcomes
            ]
        )

    monkeypatch.setattr(fcm_push_send_port.messaging, "send_each_for_multicast", _send)
    app = object()
    result = await FcmPushSendPort(app_provider=lambda: app).send(
        tokens=tokens, title="t", body="b", data={"k": "v"}
    )
    assert result == PushSendResult(
        attempted=6,
        sent=1,
        dead_tokens=("t-unregistered", "t-sender_mismatch", "t-bad_token"),
    )
    assert calls == [{"tokens": tokens, "app": app, "data": {"k": "v"}}]


# --- construction gate -------------------------------------------------------


def test_push_sender_is_the_stub_unless_enabled() -> None:
    assert isinstance(
        _build_push_sender(SimpleNamespace(push_delivery_enabled=False)), StubPushSendPort
    )
    assert isinstance(_build_push_sender(SimpleNamespace()), StubPushSendPort)
    assert isinstance(
        _build_push_sender(SimpleNamespace(push_delivery_enabled=True)), FcmPushSendPort
    )


def test_push_delivery_defaults_off(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.v2.shared.config.settings import Settings

    assert Settings.model_fields["push_delivery_enabled"].default is False
    monkeypatch.delenv("V2_PUSH_DELIVERY_ENABLED", raising=False)
    monkeypatch.setenv("PUSH_DELIVERY_ENABLED", "true")
    assert Settings().push_delivery_enabled is True
