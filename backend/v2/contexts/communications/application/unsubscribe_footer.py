"""The CAN-SPAM footer appended to every non-transactional message (#555).

One renderer, used by the parent digest, the coach digest and the campaign
send loop, so a new bulk path cannot ship without an opt-out. When no
unsubscribe URL can be minted (no secret, or no frontend base URL configured)
the footer degrades to a plain sentence pointing at the portal rather than a
link that would 404 — a dead unsubscribe link is worse than none.
"""

from __future__ import annotations

import html

from backend.v2.shared.comms.email_theme import COBALT, LINE, MUTED

_MUTED = MUTED
_LINK = COBALT

_FALLBACK_TEXT = (
    "Do not want these emails? You can turn them off in your account's email preferences."
)


def render_unsubscribe_footer(unsubscribe_url: str | None) -> str:
    """An HTML footer block. Never empty — the notice ships either way."""
    if unsubscribe_url:
        inner = (
            f'<a href="{html.escape(unsubscribe_url, quote=True)}" '
            f'style="color:{_LINK};text-decoration:underline;">Unsubscribe from these emails</a>'
        )
    else:
        inner = html.escape(_FALLBACK_TEXT)
    return (
        f'<p style="font-size:12px;color:{_MUTED};margin:20px 0 0;'
        f'border-top:1px solid {LINE};padding-top:10px;">{inner}</p>'
    )


def append_unsubscribe_footer(body: str, unsubscribe_url: str | None) -> str:
    """Append the footer to an already-rendered HTML body."""
    return f"{body}{render_unsubscribe_footer(unsubscribe_url)}"
