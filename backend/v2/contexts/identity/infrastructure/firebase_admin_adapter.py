"""v2-native Firebase Admin integration.

This module owns Firebase Admin initialization for v2 identity infrastructure.
It intentionally does not import legacy backend auth helpers.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import cachecontrol
import requests
from fastapi import HTTPException

from backend.v2.shared.tenancy.firebase_action_link import tenant_auth_action_link

_logger = logging.getLogger(__name__)

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


#: Firebase/Identity Toolkit error codes for a continue URL whose domain is
#: absent from the project's Authorized Domains list. The Admin SDK surfaces
#: these as message text rather than typed exceptions, so match on the string.
_UNAUTHORIZED_CONTINUE_DOMAIN_CODES = (
    "UNAUTHORIZED_DOMAIN",
    "INVALID_CONTINUE_URI",
    "INVALID_DYNAMIC_LINK_DOMAIN",
    "MISSING_CONTINUE_URI",
)


def _is_unauthorized_continue_domain(exc: Exception) -> bool:
    message = str(exc).upper()
    return any(code in message for code in _UNAUTHORIZED_CONTINUE_DOMAIN_CODES)


def _password_reset_action_settings(portal_url: str | None) -> Any | None:
    """Build `ActionCodeSettings` pointing back at one academy's own portal.

    Returns None when no tenant portal is known, which preserves the historic
    behaviour of generating a link with no continue URL at all.
    """
    base = (portal_url or "").strip().rstrip("/")
    if not base:
        return None
    action_code_settings = getattr(firebase_admin_auth, "ActionCodeSettings", None)
    if action_code_settings is None:  # pragma: no cover - firebase-admin absent
        return None
    # handle_code_in_app=False: this is a plain web redirect, not a mobile
    # deep link, so Firebase must not require Dynamic Links configuration.
    return action_code_settings(url=f"{base}/login", handle_code_in_app=False)


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

    async def ensure_user(self, *, uid: str, email: str, display_name: str) -> tuple[str, bool]:
        """Idempotently create a Firebase user with the roster's stable id."""
        if firebase_admin_auth is None:
            raise RuntimeError("firebase-admin is required for Firebase auth")
        _ensure_firebase_app()
        try:
            user = await asyncio.to_thread(firebase_admin_auth.get_user, uid)
        except Exception as exc:
            if not _is_firebase_auth_error(exc, "UserNotFoundError"):
                raise
            try:
                created_uid = await self.create_user(
                    uid=uid, email=email, display_name=display_name
                )
                return created_uid, True
            except Exception as create_exc:
                if _is_firebase_auth_error(create_exc, "UidAlreadyExistsError"):
                    user = await asyncio.to_thread(firebase_admin_auth.get_user, uid)
                elif _is_firebase_auth_error(create_exc, "EmailAlreadyExistsError"):
                    user = await asyncio.to_thread(firebase_admin_auth.get_user_by_email, email)
                else:
                    raise
        if str(user.email or "").strip().lower() != email.strip().lower():
            raise RuntimeError("Firebase uid is already assigned to a different email")
        return str(user.uid), False

    async def generate_password_reset_link(
        self,
        email: str,
        *,
        uid: str | None = None,
        display_name: str | None = None,
        portal_url: str | None = None,
    ) -> str:
        """Generate a Firebase password-reset link for `email`.

        If no Firebase Auth account exists for this email (e.g. a directory
        record that predates this feature, or was never provisioned in
        Firebase), self-heal by creating a passwordless account — same as
        admin-created users. `uid`/`display_name` are required for the
        self-heal path; omit them to fail instead of provisioning a new
        account.

        We check account existence *up front* with `get_user_by_email`
        rather than dispatching on the link-generation exception type: when
        email enumeration protection is enabled on the Firebase project,
        `accounts:sendOobCode` does not report EMAIL_NOT_FOUND for a missing
        account — it returns 200 without an `oobLink`, and the Admin SDK
        surfaces an opaque "unexpected response" error instead of
        `EmailNotFoundError`. `get_user_by_email` is an admin lookup
        unaffected by enumeration protection and reliably raises
        `UserNotFoundError`.

        `portal_url` is the recipient's own academy portal origin (ADR-0007;
        resolved by the caller, never a single hardcoded FRONTEND_URL). When
        supplied it does two tenant-aware things:

        1. Passes ``ActionCodeSettings(url=<portal>/login)`` so Firebase
           stamps a ``continueUrl`` on the link, returning the parent to
           *their* academy after the reset rather than to the deployment
           default host.
        2. Re-hosts the whole link on that portal at ``/auth/action`` so the
           in-app, academy-branded handler processes the ``oobCode`` instead
           of the generic ``<project>.firebaseapp.com`` page.

        Both degrade safely. ``ActionCodeSettings`` requires the continue
        domain to be in Firebase Authorized Domains, so an unauthorized
        domain is caught and retried *without* settings rather than failing
        the invite. Step 2 does not depend on Authorized Domains at all (the
        ``oobCode`` is redeemed against the Identity Toolkit API, not against
        the page hosting it), so branded landing still works while a new
        academy's subdomain is pending authorization.

        Redeeming the returned link still sets ``emailVerified=true``: the
        in-app handler calls ``confirmPasswordReset``, which hits the same
        ``accounts:resetPassword`` endpoint the hosted page uses, and that
        endpoint verifies the email as a side effect of proving mailbox
        possession. ``load_auth_claims._require_verified_password_provider_email``
        depends on this — see the test named for it before changing any of
        this.
        """
        if firebase_admin_auth is None:
            raise RuntimeError("firebase-admin is required for Firebase auth")
        _ensure_firebase_app()
        if uid is not None:
            try:
                await asyncio.to_thread(firebase_admin_auth.get_user_by_email, email)
            except firebase_admin_auth.UserNotFoundError:
                await asyncio.to_thread(
                    firebase_admin_auth.create_user,
                    uid=uid,
                    email=email,
                    display_name=display_name or "",
                    email_verified=False,
                    disabled=False,
                )
        link = await self._generate_reset_link(email, portal_url=portal_url)
        return tenant_auth_action_link(firebase_link=link, portal_url=portal_url)

    async def _generate_reset_link(self, email: str, *, portal_url: str | None) -> str:
        """Ask Firebase for the raw reset link — with ActionCodeSettings when
        a tenant portal is known, falling back to a plain link when Firebase
        rejects the continue URL's domain."""
        settings = _password_reset_action_settings(portal_url)
        if settings is None:
            link = await asyncio.to_thread(firebase_admin_auth.generate_password_reset_link, email)
            return str(link)
        try:
            link = await asyncio.to_thread(
                firebase_admin_auth.generate_password_reset_link, email, settings
            )
        except Exception as exc:
            if not _is_unauthorized_continue_domain(exc):
                raise
            # This academy's domain is not in Firebase Authorized Domains yet.
            # Losing `continueUrl` only costs the post-reset redirect; losing
            # the invite would lock the parent out entirely, so degrade.
            _logger.warning(
                "Firebase rejected continue URL for portal %s; retrying without "
                "ActionCodeSettings. Add the domain to Firebase Authorized Domains.",
                portal_url,
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

    async def create_custom_token(self, uid: str) -> str:
        """Mint a Firebase custom token for ``uid``.

        The browser exchanges this short-lived credential for a real session via
        ``signInWithCustomToken``. Used by the magic-link consume flow to sign a
        provisioned parent in without a password. ``create_custom_token`` returns
        ``bytes``; decode to the ``str`` the JSON response carries.
        """
        if firebase_admin_auth is None:
            raise RuntimeError("firebase-admin is required for Firebase auth")
        _ensure_firebase_app()
        token = await asyncio.to_thread(firebase_admin_auth.create_custom_token, uid)
        return token.decode("utf-8") if isinstance(token, bytes) else str(token)


def get_firebase_admin_adapter() -> FirebaseAdminAdapter:
    global _firebase_admin_adapter
    if _firebase_admin_adapter is None:
        _firebase_admin_adapter = FirebaseAdminAdapter()
    return _firebase_admin_adapter
