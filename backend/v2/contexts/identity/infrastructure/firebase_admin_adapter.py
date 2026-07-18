"""v2-native Firebase Admin integration.

This module owns Firebase Admin initialization for v2 identity infrastructure.
It intentionally does not import legacy backend auth helpers.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import cachecontrol
import requests
from fastapi import HTTPException

try:
    import firebase_admin
    from firebase_admin import auth as firebase_admin_auth
    from firebase_admin import credentials as firebase_admin_credentials
except ImportError:  # pragma: no cover
    firebase_admin = None
    firebase_admin_auth = None
    firebase_admin_credentials = None

try:
    from google.auth import exceptions as google_auth_exceptions
    from google.auth.transport import requests as google_auth_requests
    from google.oauth2 import id_token as google_id_token
except ImportError:  # pragma: no cover
    google_auth_exceptions = None
    google_auth_requests = None
    google_id_token = None

_firebase_app: Any | None = None
_google_public_cert_request: Any | None = None
_firebase_admin_adapter: FirebaseAdminAdapter | None = None


def firebase_project_id() -> str:
    project_id = (
        os.environ.get("V2_FIREBASE_PROJECT_ID") or os.environ.get("FIREBASE_PROJECT_ID") or ""
    ).strip()
    if not project_id:
        raise HTTPException(status_code=500, detail="Firebase auth is not configured")
    return project_id


def _is_prod_env() -> bool:
    env = os.environ.get("V2_ENV", "").lower()
    app_env = os.environ.get("APP_ENV", "").lower()
    return env == "prod" or app_env in {"production", "prod"}


def _ensure_firebase_app() -> Any:
    global _firebase_app
    if firebase_admin is None or firebase_admin_credentials is None:
        raise HTTPException(status_code=500, detail="firebase-admin is required for Firebase auth")
    if _firebase_app is not None:
        return _firebase_app
    if firebase_admin._apps:
        _firebase_app = firebase_admin.get_app()
        return _firebase_app

    cred_path = os.environ.get("FIREBASE_CREDENTIALS_FILE", "").strip()
    cred_json = os.environ.get("FIREBASE_CREDENTIALS_JSON", "").strip()
    cred = None
    if cred_json:
        cred = firebase_admin_credentials.Certificate(json.loads(cred_json))
    elif cred_path:
        cred = firebase_admin_credentials.Certificate(cred_path)

    options = {"projectId": firebase_project_id()}
    if cred is not None:
        _firebase_app = firebase_admin.initialize_app(cred, options)
        return _firebase_app

    try:
        cred = firebase_admin_credentials.ApplicationDefault()
        _firebase_app = firebase_admin.initialize_app(cred, options)
    except Exception:
        if _is_prod_env():
            raise HTTPException(
                status_code=500,
                detail="Firebase Admin credentials are required in production",
            ) from None
        _firebase_app = firebase_admin.initialize_app(options=options)
    return _firebase_app


def _get_google_public_cert_request() -> Any:
    global _google_public_cert_request
    if google_auth_requests is None:
        raise HTTPException(
            status_code=500,
            detail="google-auth is required for Firebase token verification",
        )
    if _google_public_cert_request is None:
        cached_session = cachecontrol.CacheControl(requests.Session())
        _google_public_cert_request = google_auth_requests.Request(session=cached_session)
    return _google_public_cert_request


def _is_google_default_credentials_error(exc: Exception) -> bool:
    error_type = getattr(google_auth_exceptions, "DefaultCredentialsError", None)
    return isinstance(error_type, type) and isinstance(exc, error_type)


def _is_google_transport_error(exc: Exception) -> bool:
    error_type = getattr(google_auth_exceptions, "TransportError", None)
    return isinstance(error_type, type) and isinstance(exc, error_type)


def _is_firebase_auth_error(exc: Exception, name: str) -> bool:
    error_type = getattr(firebase_admin_auth, name, None)
    return isinstance(error_type, type) and isinstance(exc, error_type)


def _verify_firebase_token_with_public_certs(token: str) -> dict[str, object]:
    if google_id_token is None:
        raise HTTPException(
            status_code=500,
            detail="google-auth is required for Firebase token verification",
        )

    project_id = firebase_project_id()
    try:
        payload = google_id_token.verify_firebase_token(
            token,
            _get_google_public_cert_request(),
            audience=project_id,
            clock_skew_in_seconds=10,
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Firebase token") from None
    except Exception as exc:
        if _is_google_transport_error(exc):
            raise HTTPException(
                status_code=503,
                detail="Firebase token verification unavailable",
            ) from exc
        raise

    expected_issuer = f"https://securetoken.google.com/{project_id}"
    if payload.get("iss") != expected_issuer:
        raise HTTPException(status_code=401, detail="Invalid Firebase token")
    return dict(payload)


class FirebaseAdminAdapter:
    """Firebase Admin SDK facade for v2 identity infrastructure."""

    def verify_id_token(self, token: str) -> dict[str, object]:
        if firebase_admin_auth is None:
            raise HTTPException(
                status_code=500, detail="firebase-admin is required for Firebase auth"
            )
        try:
            _ensure_firebase_app()
            return dict(firebase_admin_auth.verify_id_token(token, check_revoked=True))
        except Exception as exc:
            if _is_google_default_credentials_error(exc):
                if _is_prod_env():
                    raise HTTPException(
                        status_code=503,
                        detail="Firebase token revocation checks unavailable",
                    ) from exc
                return _verify_firebase_token_with_public_certs(token)
            if _is_firebase_auth_error(exc, "RevokedIdTokenError"):
                raise HTTPException(status_code=401, detail="Firebase token revoked") from exc
            if _is_firebase_auth_error(exc, "ExpiredIdTokenError"):
                raise HTTPException(status_code=401, detail="Firebase token expired") from exc
            if _is_firebase_auth_error(exc, "UserDisabledError"):
                raise HTTPException(status_code=403, detail="Firebase user disabled") from exc
            if _is_firebase_auth_error(exc, "InvalidIdTokenError") or isinstance(exc, ValueError):
                raise HTTPException(status_code=401, detail="Invalid Firebase token") from exc
            raise

    async def create_user(self, *, uid: str, email: str, display_name: str) -> str:
        if firebase_admin_auth is None:
            raise RuntimeError("firebase-admin is required for Firebase auth")
        _ensure_firebase_app()
        user = await asyncio.to_thread(
            firebase_admin_auth.create_user,
            uid=uid,
            email=email,
            display_name=display_name,
            email_verified=False,
            disabled=False,
        )
        return str(user.uid)

    async def generate_password_reset_link(
        self, email: str, *, uid: str | None = None, display_name: str | None = None
    ) -> str:
        """Generate a Firebase password-reset link for `email`.

        If no Firebase Auth account exists for this email (e.g. a directory
        record that predates this feature, or was never provisioned in
        Firebase), self-heal by creating a passwordless account — same as
        admin-created users — then retry once. `uid`/`display_name` are
        required for the self-heal path; omit them to fail instead of
        provisioning a new account.
        """
        if firebase_admin_auth is None:
            raise RuntimeError("firebase-admin is required for Firebase auth")
        _ensure_firebase_app()
        try:
            link = await asyncio.to_thread(firebase_admin_auth.generate_password_reset_link, email)
        except firebase_admin_auth.EmailNotFoundError:
            if uid is None:
                raise
            await asyncio.to_thread(
                firebase_admin_auth.create_user,
                uid=uid,
                email=email,
                display_name=display_name or "",
                email_verified=False,
                disabled=False,
            )
            link = await asyncio.to_thread(firebase_admin_auth.generate_password_reset_link, email)
        return str(link)

    async def update_user_email(self, uid: str, email: str) -> None:
        if firebase_admin_auth is None:
            raise RuntimeError("firebase-admin is required for Firebase auth")
        _ensure_firebase_app()
        await asyncio.to_thread(
            firebase_admin_auth.update_user,
            uid,
            email=email,
            email_verified=False,
        )

    async def delete_user(self, uid: str) -> None:
        if firebase_admin_auth is None:
            raise RuntimeError("firebase-admin is required for Firebase auth")
        _ensure_firebase_app()
        await asyncio.to_thread(firebase_admin_auth.delete_user, uid)


def get_firebase_admin_adapter() -> FirebaseAdminAdapter:
    global _firebase_admin_adapter
    if _firebase_admin_adapter is None:
        _firebase_admin_adapter = FirebaseAdminAdapter()
    return _firebase_admin_adapter
