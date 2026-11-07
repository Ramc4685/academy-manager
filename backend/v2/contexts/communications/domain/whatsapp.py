"""WhatsApp vocabulary shared by the send paths.

A session stores its class group as the invite link admins paste
(``Session.whatsapp_group_link``). Posting needs the gateway's group id, which
the gateway resolves from the invite *code*; this is the one place that turns
the stored link into that code.
"""

from __future__ import annotations

from urllib.parse import urlparse

_INVITE_HOST = "chat.whatsapp.com"


def group_invite_code(link: str | None) -> str | None:
    """The invite code from a ``chat.whatsapp.com`` link, else ``None``."""
    if not link or not link.strip():
        return None
    parsed = urlparse(link.strip())
    if parsed.scheme not in {"http", "https"} or parsed.hostname != _INVITE_HOST:
        return None
    segments = [s for s in parsed.path.split("/") if s]
    if not segments:
        return None
    code = segments[-1]
    return code if code.isalnum() else None
