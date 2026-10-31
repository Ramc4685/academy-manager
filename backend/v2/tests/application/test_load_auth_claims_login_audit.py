"""LoadAuthClaims must leave a login trail (#468).

`audit_logs` recorded roster and billing edits but never a sign-in, so the
admin audit page could not answer "who logged in, and how". `LoadAuthClaims`
is the single choke point every authenticated request passes through, so the
event is appended there — deduped by the token's `iat` so one session does not
write one row per request, and never allowed to fail a login.
"""

from __future__ import annotations

import pytest

from backend.v2.contexts.identity.application.use_cases.load_auth_claims import (
    LoadAuthClaims,
)
from backend.v2.contexts.identity.domain.models import AcademyMembership, User

ACADEMY = "academy-court"


class _FakeVerifier:
    def __init__(self, claims: dict[str, object]) -> None:
        self._claims = claims

    async def verify(self, id_token: str) -> dict[str, object]:
        return dict(self._claims)


class _FakeUserRepo:
    def __init__(self, user: User) -> None:
        self._user = user

    async def get_by_email(self, email: str) -> User | None:
        return self._user if str(self._user.email) == email else None

    async def get_by_id(self, user_id: str) -> User | None:
        return self._user if self._user.user_id == user_id else None


class _FakeMembershipRepo:
    def __init__(self, membership: AcademyMembership) -> None:
        self._membership = membership

    async def get_for_user_in_academy(
        self, *, user_id: str, academy_id: str, aliases=None
    ) -> AcademyMembership | None:
        if self._membership.academy_id != academy_id:
            return None
        return self._membership


class _FakePlatformRoleRepo:
    async def list_active_for_user(self, user_id: str) -> list:
        return []


class _SpyLoginAudit:
    def __init__(self, raises: Exception | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self._raises = raises

    async def record_login(self, **kwargs: object) -> None:
        self.calls.append(dict(kwargs))
        if self._raises:
            raise self._raises


def _user() -> User:
    return User(
        user_id="u-coach",
        email="coach@example.com",
        display_name="Coach Carter",
        global_status="active",
        roles=("coach",),
        is_active=True,
        academy_id="legacy-default-academy",
    )


def _membership() -> AcademyMembership:
    return AcademyMembership(
        membership_id="m-coach-court",
        academy_id=ACADEMY,
        user_id="u-coach",
        roles=("coach",),
        status="active",
    )


def _build(login_audit, *, iat: int = 1_757_000_000) -> LoadAuthClaims:
    return LoadAuthClaims(
        verifier=_FakeVerifier(
            {
                "email": "coach@example.com",
                "email_verified": True,
                "iat": iat,
                "firebase": {"sign_in_provider": "password"},
            }
        ),
        users=_FakeUserRepo(_user()),
        memberships=_FakeMembershipRepo(_membership()),
        platform_roles=_FakePlatformRoleRepo(),
        login_audit=login_audit,
    )


@pytest.mark.asyncio
async def test_successful_login_records_one_audit_event() -> None:
    spy = _SpyLoginAudit()

    claims = await _build(spy).execute("token", resolved_academy_id=ACADEMY)

    assert claims.user_id == "u-coach"
    assert len(spy.calls) == 1
    call = spy.calls[0]
    assert call["user_id"] == "u-coach"
    assert call["academy_id"] == ACADEMY
    assert call["membership_id"] == "m-coach-court"
    assert call["provider"] == "password"
    assert call["persona"] == "coach"
    assert call["dedupe_key"]


@pytest.mark.asyncio
async def test_same_token_reuses_one_dedupe_key() -> None:
    spy = _SpyLoginAudit()
    use_case = _build(spy)

    await use_case.execute("token", resolved_academy_id=ACADEMY)
    await use_case.execute("token", resolved_academy_id=ACADEMY)

    # Every authenticated request re-runs this use case, so the *store* dedupes
    # on a key that is stable for the lifetime of one token.
    assert len(spy.calls) == 2
    assert len({call["dedupe_key"] for call in spy.calls}) == 1


@pytest.mark.asyncio
async def test_different_tokens_get_different_dedupe_keys() -> None:
    first = _SpyLoginAudit()
    second = _SpyLoginAudit()

    await _build(first, iat=1_757_000_000).execute("t1", resolved_academy_id=ACADEMY)
    await _build(second, iat=1_757_003_600).execute("t2", resolved_academy_id=ACADEMY)

    assert first.calls[0]["dedupe_key"] != second.calls[0]["dedupe_key"]


@pytest.mark.asyncio
async def test_audit_failure_never_blocks_a_login() -> None:
    spy = _SpyLoginAudit(raises=RuntimeError("mongo down"))

    claims = await _build(spy).execute("token", resolved_academy_id=ACADEMY)

    assert claims.user_id == "u-coach"


@pytest.mark.asyncio
async def test_login_audit_is_optional() -> None:
    use_case = LoadAuthClaims(
        verifier=_FakeVerifier({"email": "coach@example.com", "email_verified": True}),
        users=_FakeUserRepo(_user()),
        memberships=_FakeMembershipRepo(_membership()),
        platform_roles=_FakePlatformRoleRepo(),
    )

    claims = await use_case.execute("token", resolved_academy_id=ACADEMY)

    assert claims.membership_id == "m-coach-court"
