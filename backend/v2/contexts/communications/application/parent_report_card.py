"""The parent monthly report card email: one message per family on the first
academy-local day of a month, one card per child for the month just ended.

The view is plain data assembled at the composition root (skills passed,
attendance marks, the active level and its next skill), so this module
imports nothing from other contexts (ADR-0005).
"""

from __future__ import annotations

import html
from dataclasses import dataclass

from backend.v2.contexts.communications.application.unsubscribe_footer import (
    render_unsubscribe_footer,
)
from backend.v2.shared.comms.email_theme import EmailBrand, button, shell


@dataclass(frozen=True, slots=True)
class Focus:
    """The next required skill the child has not mastered yet."""

    skill_name: str
    video_url: str | None = None


@dataclass(frozen=True, slots=True)
class ChildReportCard:
    first_name: str
    progress_url: str
    new_skills: int
    classes_attended: int
    classes_marked: int
    #: Short tile label (``L2``) and full name of the active level, if any.
    level_badge: str | None = None
    level_name: str | None = None
    focus: Focus | None = None


@dataclass(frozen=True, slots=True)
class FamilyReportCard:
    parent_id: str
    #: e.g. ``October``: the month the card covers.
    month_name: str
    #: e.g. ``November``: the month the focus is for.
    next_month_name: str
    children: tuple[ChildReportCard, ...]


def _join(names: tuple[str, ...]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _tile(value: str, label: str, bg: str, fg: str) -> str:
    esc = html.escape
    return (
        f'<td width="33%" style="padding:4px;vertical-align:top;">'
        f'<div style="background:{bg};border-radius:10px;padding:8px;color:{fg};">'
        f'<div style="font-size:20px;font-weight:700;">{esc(value)}</div>'
        f'<div style="font-size:11px;">{esc(label)}</div></div></td>'
    )


def _child_block(card: ChildReportCard, family: FamilyReportCard, accent: str) -> str:
    esc = html.escape
    tiles = _tile(
        str(card.new_skills),
        "new skill" if card.new_skills == 1 else "new skills",
        "#ecfdf5",
        "#065f46",
    ) + _tile(f"{card.classes_attended}/{card.classes_marked}", "classes", "#eff6ff", "#1e3a8a")
    if card.level_badge:
        tiles += _tile(card.level_badge, card.level_name or "current level", "#fef9c3", "#a16207")
    parts = [
        f'<p style="margin:0 0 8px;font-size:18px;font-weight:700;">'
        f"{esc(family.month_name)} for {esc(card.first_name)}</p>",
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="margin:0 0 8px;"><tr>{tiles}</tr></table>',
    ]
    if card.focus:
        line = f"Focus for {esc(family.next_month_name)}: {esc(card.focus.skill_name)}."
        video = card.focus.video_url or ""
        # Admin-entered URL: link only a web address, never javascript: etc.
        if video.startswith(("https://", "http://")):
            line += f' <a href="{esc(video)}">Watch the practice video</a>.'
        parts.append(f'<p style="margin:0 0 12px;">{line}</p>')
    label = f"See {card.first_name}'s progress"
    parts.append(
        f'<p style="margin:0 0 24px;">{button(label, card.progress_url, accent=accent)}</p>'
    )
    return "".join(parts)


def render_parent_report_card(
    family: FamilyReportCard,
    *,
    brand: EmailBrand | None = None,
    unsubscribe_url: str | None = None,
) -> tuple[str, str]:
    """Return ``(subject, html_body)``. Always carries the opt-out footer: this
    is a recurring non-transactional message (#555)."""
    resolved = brand or EmailBrand(academy_name="Your academy")
    accent = resolved.accent()
    names = _join(tuple(c.first_name for c in family.children))
    body = shell(
        brand=resolved,
        inner_html="".join(_child_block(c, family, accent) for c in family.children),
        footer_html=render_unsubscribe_footer(unsubscribe_url),
    )
    return f"{family.month_name} for {names}", body
