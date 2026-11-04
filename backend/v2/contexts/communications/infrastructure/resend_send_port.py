"""Resend-backed email send port.

Talks to the Resend HTTP API directly (httpx), reusing the `resend` SDK only
for its base URL, version string and exception types. The SDK itself is not
called: it authenticates every request with the MODULE-GLOBAL
``resend.api_key``, so two ports holding different keys (one per academy, once
academies bring their own Resend account) would silently send with whichever
key was assigned last — a cross-tenant leak. Each port here owns its key and
never reads or writes ``resend.api_key``. The request it builds — URL, headers,
JSON body — and the exceptions it raises on an error response are the same ones
the SDK produced, so callers and the credential probe see no difference.

For sending, composition only
instantiates this when APP_ENV=production (or staging) AND
email_delivery_enabled=True — every send path goes through
``composition.digests._build_email_sender``, and all other environments get
StubEmailSendPort. The boot-time credential probe
(``composition.digests.compose_email_credential_probe``) also builds one in
any environment, but only to validate the API key; it never sends.

``send`` deliberately never raises — callers record a failed send and move on —
which is also how an expired API key used to become invisible: every message
turned into ``SendOutcome(ok=False)`` and mail simply stopped, for weeks
(issue #435). Two things now make that loud:

* :meth:`validate_credentials` is called once at boot, so a dead or revoked key
  is reported through the alert channel on the deploy that broke it rather than
  by a parent asking why the invoices stopped;
* the ops digest counts failed digest sends, so a key that dies *between* boots
  still surfaces within a day.

Bounce/complaint handling is deliberately *not* here either: Resend webhooks
land on ``interfaces/email_webhook_routes.py`` and feed the
``email_suppressions`` collection, and the send-time check is applied by
``infrastructure/gated_send_port.GatedEmailSendPort`` wrapping this adapter
(issue #556). This adapter still just sends.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx
import resend
from resend.exceptions import (
    InvalidApiKeyError,
    MissingApiKeyError,
    NoContentError,
    ResendError,
    raise_for_code_and_type,
)
from resend.version import get_version

from backend.v2.contexts.communications.application.ports import (
    EmailSendPort,
    ResolvedRecipient,
    SendOutcome,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.shared.comms.email_theme import html_to_text
from backend.v2.shared.comms.sender_identity import format_from_header

log = logging.getLogger(__name__)

# Resend answers a key that authenticates but lacks a scope with this type.
# It means the credential is *live* — exactly what we are checking — so it must
# not be reported as a dead key.
_RESTRICTED_KEY_ERROR_TYPE = "restricted_api_key"

# The check is a boot-path network call; bound it so a Resend outage delays
# startup by seconds instead of holding it open.
VALIDATION_TIMEOUT_SECONDS = 10.0

# Per-request HTTP timeout. Matches the SDK's own default clients
# (``resend.http_client_requests.RequestsClient`` and
# ``resend.http_client_httpx.HTTPXClient`` both default to ``timeout=30``).
REQUEST_TIMEOUT_SECONDS = 30.0

# Test seam: when a port is built without an explicit ``transport`` (e.g. by
# composition), requests go through this transport if one is set. Production
# never sets it. It carries no credential — the key is always the port's own.
default_transport: httpx.AsyncBaseTransport | None = None


@dataclass(frozen=True, slots=True)
class CredentialCheck:
    """Outcome of a boot-time credential probe.

    ``ok is None`` means *undetermined* — a network error or timeout, which says
    nothing about the key and must not raise a false "email is broken" alert.
    """

    ok: bool | None
    detail: str

    @property
    def is_definitely_broken(self) -> bool:
        return self.ok is False


class ResendEmailSendPort(EmailSendPort):
    def __init__(
        self,
        api_key: str | None,
        from_address: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # The key lives on the instance only. Never assign ``resend.api_key``:
        # that global is shared by every port in the process.
        self._api_key = api_key or ""
        self._from_address = from_address
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        # Byte-for-byte the headers ``resend.request.Request`` sends, except the
        # bearer token is this port's key rather than the module global.
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "User-Agent": f"resend-python:{get_version()}",
        }

    async def _request(self, method: str, path: str, payload: dict[str, Any]) -> Any:
        """One authenticated call, with the SDK's response/error semantics.

        Mirrors ``resend.request.Request.perform_with_content``: a transport
        failure becomes ``ResendError(code=500, error_type="HttpClientError")``;
        a non-JSON or undecodable body and any 4xx/5xx go through
        ``raise_for_code_and_type`` so ``MissingApiKeyError`` /
        ``InvalidApiKeyError`` / ``restricted_api_key`` surface exactly as
        before.
        """
        if not self._api_key:
            # The SDK would send ``Bearer None`` and get this back from the API;
            # fail the same way without spending a request.
            raise MissingApiKeyError(
                message="Missing API key in the authorization header.",
                error_type="missing_api_key",
                code=401,
            )
        url = f"{resend.api_url}{path}"
        body = {str(k): v for k, v in payload.items()}
        try:
            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT_SECONDS,
                transport=self._transport or default_transport,
            ) as client:
                resp = await client.request(method, url, headers=self._headers(), json=body)
        except Exception as exc:  # safety net, as in the SDK
            raise ResendError(
                code=500,
                message=f"Request failed: {exc}",
                error_type="HttpClientError",
                suggested_action="Request failed, please try again.",
            ) from exc

        resp_headers = dict(resp.headers)
        status = resp.status_code
        fallback_code = status if status >= 400 else 500
        content_type = resp.headers.get("content-type", "")
        if "application/json" not in content_type:
            raise_for_code_and_type(
                code=fallback_code,
                message=f"Expected JSON response but got: {content_type}",
                error_type="application_error",
                headers=resp_headers,
            )
        try:
            data = json.loads(resp.content)
        except json.JSONDecodeError:
            raise_for_code_and_type(
                code=fallback_code,
                message="Failed to decode JSON response",
                error_type="application_error",
                headers=resp_headers,
            )

        body_status = data.get("statusCode") if isinstance(data, dict) else None
        error_code = status if status >= 400 else body_status
        if error_code not in (None, 200):
            raise_for_code_and_type(
                code=error_code or 500,
                message=(
                    data.get("message", "Unknown error")
                    if isinstance(data, dict)
                    else "Unknown error"
                ),
                error_type=(
                    data.get("name", "InternalServerError")
                    if isinstance(data, dict)
                    else "InternalServerError"
                ),
                headers=resp_headers,
            )
        if data is None:
            raise NoContentError()
        return data

    async def validate_credentials(self) -> CredentialCheck:
        """Probe the configured API key with a cheap authenticated read.

        Listing domains touches no mail and costs one request. Only an
        authentication verdict is treated as a verdict: a 401/403 means the key
        is dead, a ``restricted_api_key`` rejection means it is alive but
        send-scoped (fine), and anything else — timeout, 5xx, transport error —
        leaves the answer undetermined rather than crying wolf.
        """
        try:
            # ``resend.Domains.list_async`` sent GET /domains with an empty JSON
            # body; keep the request identical.
            await asyncio.wait_for(
                self._request("get", "/domains", {}), timeout=VALIDATION_TIMEOUT_SECONDS
            )
        except (MissingApiKeyError, InvalidApiKeyError) as exc:
            return CredentialCheck(ok=False, detail=f"{type(exc).__name__}: {exc}")
        except ResendError as exc:
            if getattr(exc, "error_type", None) == _RESTRICTED_KEY_ERROR_TYPE:
                return CredentialCheck(ok=True, detail="restricted (send-scoped) API key")
            if str(getattr(exc, "code", "")) in {"401", "403"}:
                return CredentialCheck(ok=False, detail=f"HTTP {exc.code}: {exc}")
            return CredentialCheck(ok=None, detail=f"provider error: {exc}")
        except TimeoutError:
            return CredentialCheck(
                ok=None, detail=f"timed out after {VALIDATION_TIMEOUT_SECONDS:.0f}s"
            )
        except Exception as exc:  # transport/DNS/etc — says nothing about the key
            return CredentialCheck(ok=None, detail=f"{type(exc).__name__}: {exc}")
        return CredentialCheck(ok=True, detail="ok")

    async def send(
        self,
        *,
        recipient: ResolvedRecipient,
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        reply_to: str | None = None,
        category: EmailCategory = EmailCategory.TRANSACTIONAL,
        sender_name: str | None = None,
    ) -> SendOutcome:
        # ``category`` is a routing/gating concern consumed by
        # ``GatedEmailSendPort`` before we are reached; Resend has no field for
        # it, so it is deliberately not forwarded into ``SendParams``.
        if not recipient.email:
            return SendOutcome(ok=False, provider_message_id=None, failed_reason="no email address")
        try:
            params: resend.Emails.SendParams = {
                # Per-academy display name, platform-owned address (L9a).
                "from": format_from_header(sender_name, self._from_address),
                "to": [recipient.email],
                "subject": subject,
                "html": body,
            }
            try:
                params["text"] = html_to_text(body)
            except Exception:  # a text twin is a bonus, never a blocker
                log.warning("plain-text twin generation failed", exc_info=True)
            if cc:
                params["cc"] = cc
            if bcc:
                params["bcc"] = bcc
            if reply_to:
                params["reply_to"] = reply_to
            response = await self._request("post", "/emails", dict(params))
            msg_id = response.get("id") if isinstance(response, dict) else str(response)
            return SendOutcome(ok=True, provider_message_id=msg_id, failed_reason=None)
        except (MissingApiKeyError, InvalidApiKeyError) as exc:
            # A credential failure is an outage, not one bad recipient: without
            # its own log line it is indistinguishable from a rejected address.
            log.error("resend_send_rejected_credentials: %s", exc)
            return SendOutcome(ok=False, provider_message_id=None, failed_reason=str(exc))
        except Exception as exc:
            return SendOutcome(ok=False, provider_message_id=None, failed_reason=str(exc))
