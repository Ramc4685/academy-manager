"""Resend-backed email send port.

Uses the `resend` SDK (already in venv). Only instantiated by composition
when APP_ENV=production (or staging) AND email_delivery_enabled=True.
All other environments use StubEmailSendPort.

``send`` deliberately never raises — callers record a failed send and move on —
which is also how an expired API key used to become invisible: every message
turned into ``SendOutcome(ok=False)`` and mail simply stopped, for weeks
(issue #435). Two things now make that loud:

* :meth:`validate_credentials` is called once at boot, so a dead or revoked key
  is reported through the alert channel on the deploy that broke it rather than
  by a parent asking why the invoices stopped;
* the ops digest counts failed digest sends, so a key that dies *between* boots
  still surfaces within a day.

Not covered here, and still open: Resend bounce/complaint webhooks and a
suppression list. Those need an inbound signed webhook route and a new
collection — a separate slice, not a widening of this adapter.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import resend
from resend.exceptions import InvalidApiKeyError, MissingApiKeyError, ResendError

from backend.v2.contexts.communications.application.ports import (
    EmailSendPort,
    ResolvedRecipient,
    SendOutcome,
)

log = logging.getLogger(__name__)

# Resend answers a key that authenticates but lacks a scope with this type.
# It means the credential is *live* — exactly what we are checking — so it must
# not be reported as a dead key.
_RESTRICTED_KEY_ERROR_TYPE = "restricted_api_key"

# The check is a boot-path network call; bound it so a Resend outage delays
# startup by seconds instead of holding it open.
VALIDATION_TIMEOUT_SECONDS = 10.0


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
    def __init__(self, api_key: str, from_address: str) -> None:
        self._from_address = from_address
        resend.api_key = api_key

    async def validate_credentials(self) -> CredentialCheck:
        """Probe the configured API key with a cheap authenticated read.

        Listing domains touches no mail and costs one request. Only an
        authentication verdict is treated as a verdict: a 401/403 means the key
        is dead, a ``restricted_api_key`` rejection means it is alive but
        send-scoped (fine), and anything else — timeout, 5xx, transport error —
        leaves the answer undetermined rather than crying wolf.
        """
        try:
            await asyncio.wait_for(resend.Domains.list_async(), timeout=VALIDATION_TIMEOUT_SECONDS)
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
    ) -> SendOutcome:
        if not recipient.email:
            return SendOutcome(ok=False, provider_message_id=None, failed_reason="no email address")
        try:
            params: resend.Emails.SendParams = {
                "from": self._from_address,
                "to": [recipient.email],
                "subject": subject,
                "html": body,
            }
            if cc:
                params["cc"] = cc
            if bcc:
                params["bcc"] = bcc
            if reply_to:
                params["reply_to"] = reply_to
            response = await asyncio.to_thread(resend.Emails.send, params)
            msg_id = response.get("id") if isinstance(response, dict) else str(response)
            return SendOutcome(ok=True, provider_message_id=msg_id, failed_reason=None)
        except (MissingApiKeyError, InvalidApiKeyError) as exc:
            # A credential failure is an outage, not one bad recipient: without
            # its own log line it is indistinguishable from a rejected address.
            log.error("resend_send_rejected_credentials: %s", exc)
            return SendOutcome(ok=False, provider_message_id=None, failed_reason=str(exc))
        except Exception as exc:
            return SendOutcome(ok=False, provider_message_id=None, failed_reason=str(exc))
