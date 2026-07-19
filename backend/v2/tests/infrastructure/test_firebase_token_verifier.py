from __future__ import annotations

from types import SimpleNamespace

import backend.v2.contexts.identity.infrastructure.firebase_admin_adapter as adapter_module
import backend.v2.contexts.identity.infrastructure.firebase_token_verifier as verifier_module
import pytest
from backend.v2.contexts.identity.infrastructure.firebase_admin_adapter import (
    FirebaseAdminAdapter,
)
from backend.v2.contexts.identity.infrastructure.firebase_token_verifier import (
    FirebaseTokenVerifier,
)


@pytest.mark.asyncio
async def test_firebase_token_verifier_delegates_to_v2_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    class FakeAdapter:
        def verify_id_token(self, token: str) -> dict[str, object]:
            seen.append(token)
            return {"email": "coach@example.com"}

    monkeypatch.setattr(verifier_module, "get_firebase_admin_adapter", lambda: FakeAdapter())

    claims = await FirebaseTokenVerifier().verify("id-token")

    assert seen == ["id-token"]
    assert claims == {"email": "coach@example.com"}


def test_firebase_admin_adapter_prefers_admin_sdk_with_revocation_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    class FakeAuth:
        @staticmethod
        def verify_id_token(token: str, *, check_revoked: bool) -> dict[str, object]:
            seen["token"] = token
            seen["check_revoked"] = check_revoked
            return {"sub": "firebase-user"}

    monkeypatch.setattr(adapter_module, "firebase_admin_auth", FakeAuth)
    monkeypatch.setattr(adapter_module, "_ensure_firebase_app", lambda: object())

    claims = FirebaseAdminAdapter().verify_id_token("id-token")

    assert seen == {"token": "id-token", "check_revoked": True}
    assert claims == {"sub": "firebase-user"}


def test_firebase_admin_adapter_falls_back_to_google_public_certs_when_adc_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("V2_ENV", "dev")

    class DefaultCredentialsError(Exception):
        pass

    seen: dict[str, object] = {}

    class FakeAuth:
        @staticmethod
        def verify_id_token(token: str, *, check_revoked: bool) -> dict[str, object]:
            seen["admin_token"] = token
            seen["check_revoked"] = check_revoked
            raise DefaultCredentialsError("no default credentials")

    class FakeGoogleIdToken:
        @staticmethod
        def verify_firebase_token(
            token: str,
            request: object,
            *,
            audience: str,
            clock_skew_in_seconds: int,
        ) -> dict[str, object]:
            seen["fallback_token"] = token
            seen["request"] = request
            seen["audience"] = audience
            seen["clock_skew"] = clock_skew_in_seconds
            return {
                "sub": "firebase-user",
                "iss": "https://securetoken.google.com/project-a",
            }

    request = object()
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "project-a")
    monkeypatch.setattr(adapter_module, "firebase_admin_auth", FakeAuth)
    monkeypatch.setattr(adapter_module, "google_id_token", FakeGoogleIdToken)
    monkeypatch.setattr(
        adapter_module,
        "google_auth_exceptions",
        SimpleNamespace(DefaultCredentialsError=DefaultCredentialsError, TransportError=Exception),
    )
    monkeypatch.setattr(adapter_module, "_ensure_firebase_app", lambda: object())
    monkeypatch.setattr(adapter_module, "_get_google_public_cert_request", lambda: request)

    claims = FirebaseAdminAdapter().verify_id_token("id-token")

    assert claims["sub"] == "firebase-user"
    assert seen == {
        "admin_token": "id-token",
        "check_revoked": True,
        "fallback_token": "id-token",
        "request": request,
        "audience": "project-a",
        "clock_skew": 10,
    }


def test_firebase_admin_adapter_fails_closed_on_public_cert_fallback_in_prod(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DefaultCredentialsError(Exception):
        pass

    class FakeAuth:
        @staticmethod
        def verify_id_token(token: str, *, check_revoked: bool) -> dict[str, object]:
            _ = (token, check_revoked)
            raise DefaultCredentialsError("no adc")

    monkeypatch.setenv("V2_ENV", "prod")
    monkeypatch.setattr(
        adapter_module,
        "google_auth_exceptions",
        SimpleNamespace(DefaultCredentialsError=DefaultCredentialsError, TransportError=Exception),
    )
    monkeypatch.setattr(adapter_module, "firebase_admin_auth", FakeAuth)
    monkeypatch.setattr(adapter_module, "_ensure_firebase_app", lambda: object())

    adapter = FirebaseAdminAdapter()
    with pytest.raises(Exception) as exc:
        adapter.verify_id_token("token")

    assert getattr(exc.value, "status_code", None) == 503


def test_firebase_project_id_prefers_v2_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("V2_FIREBASE_PROJECT_ID", "v2-project")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "legacy-project")

    assert adapter_module.firebase_project_id() == "v2-project"


@pytest.mark.asyncio
async def test_firebase_admin_adapter_user_methods_call_admin_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, dict[str, object]]] = []

    class FakeUser:
        uid = "firebase-user"

    class FakeAuth:
        @staticmethod
        def create_user(**kwargs: object) -> FakeUser:
            seen.append(("create", kwargs))
            return FakeUser()

        @staticmethod
        def update_user(uid: str, **kwargs: object) -> None:
            seen.append(("update", {"uid": uid, **kwargs}))

        @staticmethod
        def delete_user(uid: str) -> None:
            seen.append(("delete", {"uid": uid}))

    monkeypatch.setattr(adapter_module, "firebase_admin_auth", FakeAuth)
    monkeypatch.setattr(adapter_module, "_ensure_firebase_app", lambda: object())

    adapter = FirebaseAdminAdapter()
    created_uid = await adapter.create_user(
        uid="new-user",
        email="new@example.com",
        display_name="New User",
    )
    await adapter.update_user_email("firebase-user", "updated@example.com")
    await adapter.delete_user("firebase-user")

    assert created_uid == "firebase-user"
    assert seen == [
        (
            "create",
            {
                "uid": "new-user",
                "email": "new@example.com",
                "display_name": "New User",
                "email_verified": False,
                "disabled": False,
            },
        ),
        (
            "update",
            {
                "uid": "firebase-user",
                "email": "updated@example.com",
                "email_verified": False,
            },
        ),
        ("delete", {"uid": "firebase-user"}),
    ]


@pytest.mark.asyncio
async def test_firebase_admin_adapter_self_heals_missing_account_on_password_reset_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, dict[str, object]]] = []

    class UserNotFoundError(Exception):
        pass

    _user_not_found_error = UserNotFoundError

    class FakeAuth:
        UserNotFoundError = _user_not_found_error

        @staticmethod
        def get_user_by_email(email: str) -> object:
            seen.append(("lookup", {"email": email}))
            raise UserNotFoundError("no user for email")

        @staticmethod
        def create_user(**kwargs: object) -> None:
            seen.append(("create", kwargs))

        @staticmethod
        def generate_password_reset_link(email: str) -> str:
            seen.append(("reset_link", {"email": email}))
            return f"https://reset.example/{email}"

    monkeypatch.setattr(adapter_module, "firebase_admin_auth", FakeAuth)
    monkeypatch.setattr(adapter_module, "_ensure_firebase_app", lambda: object())

    link = await FirebaseAdminAdapter().generate_password_reset_link(
        "new@example.com", uid="new-user", display_name="New User"
    )

    assert link == "https://reset.example/new@example.com"
    assert seen == [
        ("lookup", {"email": "new@example.com"}),
        (
            "create",
            {
                "uid": "new-user",
                "email": "new@example.com",
                "display_name": "New User",
                "email_verified": False,
                "disabled": False,
            },
        ),
        ("reset_link", {"email": "new@example.com"}),
    ]


@pytest.mark.asyncio
async def test_firebase_admin_adapter_skips_create_when_account_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, dict[str, object]]] = []

    class UserNotFoundError(Exception):
        pass

    _user_not_found_error = UserNotFoundError

    class FakeAuth:
        UserNotFoundError = _user_not_found_error

        @staticmethod
        def get_user_by_email(email: str) -> object:
            seen.append(("lookup", {"email": email}))
            return object()

        @staticmethod
        def create_user(**kwargs: object) -> None:  # pragma: no cover - must not run
            raise AssertionError("create_user must not be called for existing accounts")

        @staticmethod
        def generate_password_reset_link(email: str) -> str:
            seen.append(("reset_link", {"email": email}))
            return f"https://reset.example/{email}"

    monkeypatch.setattr(adapter_module, "firebase_admin_auth", FakeAuth)
    monkeypatch.setattr(adapter_module, "_ensure_firebase_app", lambda: object())

    link = await FirebaseAdminAdapter().generate_password_reset_link(
        "existing@example.com", uid="existing-user", display_name="Existing User"
    )

    assert link == "https://reset.example/existing@example.com"
    assert seen == [
        ("lookup", {"email": "existing@example.com"}),
        ("reset_link", {"email": "existing@example.com"}),
    ]


@pytest.mark.asyncio
async def test_firebase_admin_adapter_reraises_missing_account_without_uid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UserNotFoundError(Exception):
        pass

    _user_not_found_error = UserNotFoundError

    class GenerateLinkError(Exception):
        pass

    class FakeAuth:
        UserNotFoundError = _user_not_found_error

        @staticmethod
        def get_user_by_email(email: str) -> object:  # pragma: no cover - must not run
            raise AssertionError("get_user_by_email must not be called without uid")

        @staticmethod
        def generate_password_reset_link(email: str) -> str:
            raise GenerateLinkError("failed to generate email action link")

    monkeypatch.setattr(adapter_module, "firebase_admin_auth", FakeAuth)
    monkeypatch.setattr(adapter_module, "_ensure_firebase_app", lambda: object())

    with pytest.raises(GenerateLinkError):
        await FirebaseAdminAdapter().generate_password_reset_link("orphan@example.com")


@pytest.mark.asyncio
async def test_mongo_user_repo_firebase_helpers_call_v2_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, dict[str, object]]] = []

    class FakeAdapter:
        async def create_user(self, **kwargs: object) -> str:
            seen.append(("create", kwargs))
            return "firebase-user"

        async def update_user_email(self, uid: str, email: str) -> None:
            seen.append(("update", {"uid": uid, "email": email}))

        async def delete_user(self, uid: str) -> None:
            seen.append(("delete", {"uid": uid}))

    monkeypatch.setattr(
        "backend.v2.contexts.identity.infrastructure.mongo_user_repo.get_firebase_admin_adapter",
        lambda: FakeAdapter(),
    )

    from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository

    created_uid = await MongoUserRepository._create_firebase_user(
        uid="new-user",
        email="new@example.com",
        display_name="New User",
    )
    await MongoUserRepository._update_firebase_email("firebase-user", "updated@example.com")
    await MongoUserRepository._delete_firebase_user("firebase-user")

    assert created_uid == "firebase-user"
    assert seen == [
        (
            "create",
            {
                "uid": "new-user",
                "email": "new@example.com",
                "display_name": "New User",
            },
        ),
        ("update", {"uid": "firebase-user", "email": "updated@example.com"}),
        ("delete", {"uid": "firebase-user"}),
    ]
