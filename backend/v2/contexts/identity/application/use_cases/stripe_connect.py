"""Stripe Connect Express onboarding use cases."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Any, Protocol


class _AcademyRepo(Protocol):
    async def update_by_id(
        self, academy_id: str, fields: dict[str, Any]
    ) -> dict[str, Any] | None: ...


class _StripeConnectGateway(Protocol):
    def create_connect_link(self, *, redirect_uri: str, state: str) -> str: ...
    async def exchange_connect_code(self, code: str) -> str: ...


def _build_state(academy_id: str, secret: str) -> str:
    nonce = secrets.token_hex(16)
    payload = f"{academy_id}:{nonce}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    raw = f"{payload}:{sig}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _verify_state(state: str, secret: str) -> str:
    """Return academy_id or raise ValueError if state is invalid."""
    try:
        padded = state + "=" * (-len(state) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        parts = raw.rsplit(":", 2)
        if len(parts) != 3:
            raise ValueError("wrong part count")
        academy_id, nonce, sig = parts
        payload = f"{academy_id}:{nonce}"
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            raise ValueError("bad signature")
        return academy_id
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"invalid state: {exc}") from exc


@dataclass(frozen=True)
class StartStripeConnectOutput:
    url: str


class StartStripeConnectUseCase:
    def __init__(
        self,
        *,
        gateway: _StripeConnectGateway,
        webhook_secret: str,
        redirect_uri: str,
    ) -> None:
        self._gateway = gateway
        self._secret = webhook_secret
        self._redirect_uri = redirect_uri

    async def execute(self, academy_id: str) -> StartStripeConnectOutput:
        state = _build_state(academy_id, self._secret)
        url = self._gateway.create_connect_link(
            redirect_uri=self._redirect_uri,
            state=state,
        )
        return StartStripeConnectOutput(url=url)


class CompleteStripeConnectUseCase:
    def __init__(
        self,
        *,
        gateway: _StripeConnectGateway,
        repo: _AcademyRepo,
        webhook_secret: str,
    ) -> None:
        self._gateway = gateway
        self._repo = repo
        self._secret = webhook_secret

    async def execute(self, *, code: str, state: str) -> str:
        """Exchange OAuth code for account ID, persist it, and return academy_id."""
        academy_id = _verify_state(state, self._secret)
        stripe_account_id = await self._gateway.exchange_connect_code(code)
        await self._repo.update_by_id(academy_id, {"stripe_account_id": stripe_account_id})
        return academy_id


class DisconnectStripeUseCase:
    def __init__(self, *, repo: _AcademyRepo) -> None:
        self._repo = repo

    async def execute(self, academy_id: str) -> None:
        await self._repo.update_by_id(academy_id, {"stripe_account_id": None})
