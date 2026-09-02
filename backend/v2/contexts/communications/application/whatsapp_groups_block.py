"""The "Your class WhatsApp groups" strip shared by every recurring email.

Pure: the composition root gathers the links (the enrollment context knows
which sessions a family or coach belongs to); this module only renders. An
empty list renders nothing, so an academy that has not configured any group
link sees no change to its digests.
"""

from __future__ import annotations

import html
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from backend.v2.shared.comms.email_theme import (
    COBALT,
    INK,
    LINE,
    MUTED,
    PAPER,
    WHATSAPP_GREEN,
    button,
)

GROUP_BLOCK_HEADING = "Your class WhatsApp groups"
PARENT_GROUP_NOTE = (
    "Please join the group for each class above if you haven't already. "
    "If you're in a group for a class your child no longer attends, please leave it "
    "so you only get messages for your class."
)
COACH_GROUP_NOTE = (
    "Join the group for each class you teach if you haven't already. "
    "Leave groups for classes you no longer coach."
)


@dataclass(frozen=True, slots=True)
class WhatsAppGroupLink:
    label: str
    url: str
    child_names: tuple[str, ...] = ()


def dedupe_group_links(links: Iterable[WhatsAppGroupLink]) -> tuple[WhatsAppGroupLink, ...]:
    """One row per group: two children in the same class share a row."""
    by_url: dict[str, WhatsAppGroupLink] = {}
    for link in links:
        existing = by_url.get(link.url)
        if existing is None:
            by_url[link.url] = link
            continue
        names = existing.child_names + tuple(
            n for n in link.child_names if n not in existing.child_names
        )
        by_url[link.url] = WhatsAppGroupLink(
            label=existing.label, url=existing.url, child_names=names
        )
    return tuple(by_url.values())


def _names(names: Sequence[str]) -> str:
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} & {names[-1]}"


def render_whatsapp_groups_block(
    links: Sequence[WhatsAppGroupLink],
    *,
    persona: Literal["parent", "coach"],
    accent: str = COBALT,
) -> str:
    if not links:
        return ""
    rows = []
    for link in links:
        who = _names(link.child_names) if persona == "parent" else ""
        who_html = (
            f'<span style="font-size:12px;color:{MUTED};display:block;">{html.escape(who)}</span>'
            if who
            else ""
        )
        rows.append(
            '<tr><td style="padding:8px 0;vertical-align:middle;">'
            f'<span style="font-size:14px;font-weight:600;color:{INK};">'
            f"{html.escape(link.label)}</span>{who_html}</td>"
            '<td style="padding:8px 0 8px 12px;text-align:right;vertical-align:middle;">'
            f"{button('Join', link.url, accent=accent, variant='secondary')}</td></tr>"
        )
    note = PARENT_GROUP_NOTE if persona == "parent" else COACH_GROUP_NOTE
    return (
        f'<div style="background:{PAPER};border:1px solid {LINE};'
        f"border-left:4px solid {WHATSAPP_GREEN};border-radius:10px;"
        f'padding:14px 16px;margin:16px 0;">'
        f'<p style="font-size:12px;font-weight:700;color:{INK};margin:0 0 4px;'
        f'text-transform:uppercase;letter-spacing:0.06em;">{GROUP_BLOCK_HEADING}</p>'
        f'<table role="presentation" style="width:100%;border-collapse:collapse;">'
        f"{''.join(rows)}</table>"
        f'<p style="font-size:12px;color:{MUTED};margin:8px 0 0;">{note}</p>'
        "</div>"
    )
