"""Stripe Connect Express onboarding use cases."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from typing import Any, Protocol

_STATE_TTL_SECONDS = 600  # 10 minutes


class _AcademyRepo(Protocol):
    async def update_by_id(
        self, academy_id: str, fields: dict[str, Any]
    ) -> dict[str, Any] | None: ...


class _ConnectedAccountDisabler(Protocol):
    """Disables the Accounts-v2 ``ConnectedAccount`` source of truth.

    Cross-context boundary: identity cannot import billing directly, so the
    real implementation wraps billing's ``ConnectedAccountRepository`` and
    lives in the composition root — same pattern as
    ``ConnectedAccountStatusReader`` in ``get_academy_gateway_use_case.py``.
    """

    async def disable_for_academy(self, academy_id: str) -> None: ...


class _StripeConnectGateway(Protocol):
    def create_connect_link(self, *, redirect_uri: str, state: str) -> str: ...
    async def exchange_connect_code(self, code: str) -> str: ...


def _build_state(academy_id: str, secret: str) -> str:
    nonce = secrets.token_hex(16)
    timestamp = int(time.time())
    payload = f"{academy_id}:{nonce}:{timestamp}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    raw = f"{payload}:{sig}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _verify_state(state: str, secret: str) -> str:
    """Return academy_id or raise ValueError if state is invalid or expired."""
    try:
        padded = state + "=" * (-len(state) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        parts = raw.rsplit(":", 3)
        if len(parts) != 4:
            raise ValueError("wrong part count")
        academy_id, nonce, timestamp_str, sig = parts
        if time.time() - int(timestamp_str) > _STATE_TTL_SECONDS:
            raise ValueError("state expired")
        payload = f"{academy_id}:{nonce}:{timestamp_str}"
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
        state_secret: str,
        redirect_uri: str,
    ) -> None:
        self._gateway = gateway
        self._secret = state_secret
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
        state_secret: str,
    ) -> None:
        self._gateway = gateway
        self._repo = repo
        self._secret = state_secret

    async def execute(self, *, code: str, state: str) -> str:
        """Exchange OAuth code for account ID, persist it, and return academy_id."""
        academy_id = _verify_state(state, self._secret)
        stripe_account_id = await self._gateway.exchange_connect_code(code)
        result = await self._repo.update_by_id(academy_id, {"stripe_account_id": stripe_account_id})
        if result is None:
            raise ValueError(
                f"Academy {academy_id} not found; stripe_account_id {stripe_account_id} not persisted"
            )
        return academy_id


class DisconnectStripeUseCase:
    def __init__(
        self,
        *,
        repo: _AcademyRepo,
        connected_accounts: _ConnectedAccountDisabler | None = None,
    ) -> None:
        self._repo = repo
        self._connected_accounts = connected_accounts

    async def execute(self, academy_id: str) -> None:
        result = await self._repo.update_by_id(academy_id, {"stripe_account_id": None})
        if result is None:
            raise ValueError(f"Academy {academy_id} not found")
        # Accounts-v2 connected accounts (Slice I) are the real source of
        # truth for "connected" / charge eligibility now — clearing the
        # legacy field alone leaves that record ready for charges.
        if self._connected_accounts is not None:
            await self._connected_accounts.disable_for_academy(academy_id)
