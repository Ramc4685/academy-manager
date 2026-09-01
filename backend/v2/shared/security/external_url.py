"""Scheme allowlisting for admin-supplied external links (issue #613).

The session "communication pack" stores a group-chat invite link an admin
pastes in, and that value is later rendered as an ``href`` in an HTML email to
families. ``html.escape(url, quote=True)`` — which the email adapters already
apply — stops attribute breakout but does **not** stop ``javascript:`` or
``data:`` hrefs. The scheme allowlist here is the control that does, and it is
enforced twice: once on the interface request models (so a bad paste is a
clean 422) and once on the frozen ``Session`` domain model (so no other writer
can persist a hostile value).

Deliberately *not* a host allowlist: WhatsApp is the common case but Signal,
Telegram and Discord group links are all legitimate here, and pinning the host
would silently break them. Adding one later is a one-line extension.
"""

from __future__ import annotations

from urllib.parse import urlparse

from backend.v2.shared.http.errors import DomainError

_ALLOWED_SCHEMES = frozenset({"http", "https"})

#: Anything in this range breaks a URL across lines or hides characters from a
#: naive scheme check (``java\nscript:`` is the classic). Reject rather than
#: strip: a link containing them was not typed by a human on purpose.
_FORBIDDEN_CHARS = frozenset(chr(code) for code in range(0x00, 0x21)) | {"\x7f"}


class InvalidExternalUrl(DomainError):
    """An admin-supplied external link is malformed or uses a refused scheme."""

    code = "InvalidExternalUrl"
    status_code = 400


def validate_external_url(value: str | None, *, field_label: str = "link") -> str | None:
    """Normalise an optional admin-supplied external link.

    Returns ``None`` for ``None``/blank (blank is how the UI clears a field),
    otherwise the stripped URL unchanged. Raises ``InvalidExternalUrl`` for
    anything that is not an absolute ``http``/``https`` URL with a host.
    """
    if value is None:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if any(char in _FORBIDDEN_CHARS for char in candidate):
        raise InvalidExternalUrl(f"The {field_label} contains invalid characters.")
    parsed = urlparse(candidate)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise InvalidExternalUrl(
            f"The {field_label} must be a full http:// or https:// web address."
        )
    if not parsed.netloc:
        raise InvalidExternalUrl(f"The {field_label} is missing a website address.")
    return candidate
