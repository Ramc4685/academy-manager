"""HTML renderer for the coach daily teaching digest.

The plan is duck-typed (``Any``) on purpose: it originates in the coaching
context, but communications must not import across the bounded-context boundary
(ADR-0005). We only read attributes the *Today's Teaching Plan* DTO exposes.

Licensing: the Shuttle Time PDF is reference *citation text only* — module,
lesson range and page hint — never a link or an attachment. Only YouTube URLs
(level- and skill-scoped) are emitted as links, verbatim.

Format: an "at-a-glance" layout — one card per activity group with its
reference videos deduplicated and listed once (not repeated per student), and
each student shown as name + current skill + a colour status chip. All
interpolated text is HTML-escaped; only known-YouTube URLs become ``href``
values.
"""

from __future__ import annotations

import html
from collections.abc import Sequence
from datetime import date
from typing import Any

from backend.v2.contexts.communications.application.unsubscribe_footer import (
    render_unsubscribe_footer,
)
from backend.v2.contexts.communications.application.whatsapp_groups_block import (
    WhatsAppGroupLink,
    render_whatsapp_groups_block,
)
from backend.v2.shared.comms.email_theme import (
    AMBER_BG,
    AMBER_FG,
    COBALT,
    COBALT_SOFT,
    GREEN_BG,
    GREEN_FG,
    INK,
    LINE,
    MUTED,
    EmailBrand,
    shell,
)

# Maps a lesson card's ``source`` code to a human reference label.
_SOURCE_LABELS = {"BWF_SHUTTLE_TIME": "Shuttle Time"}

_TEXT_PRIMARY = INK
_TEXT_SECONDARY = MUTED
_TEXT_MUTED = MUTED
_BORDER = LINE
_LINK = COBALT

# status text (lowercased, underscores replaced with spaces) -> (bg, fg)
_STATUS_CHIPS = {
    "not started": ("#f1f5f9", MUTED),
    "introduced": (AMBER_BG, AMBER_FG),
    "learning": (COBALT_SOFT, "#1e40af"),
    "practicing": (GREEN_BG, GREEN_FG),
}
_DEFAULT_CHIP = ("#f1f5f9", "#334155")


def render_coach_digest(
    plan: Any,
    *,
    brand: EmailBrand | None = None,
    whatsapp_groups: Sequence[WhatsAppGroupLink] = (),
    playlist_url: str | None = None,
    unsubscribe_url: str | None = None,
) -> tuple[str, str]:
    """Return ``(subject, body)`` for one coach's daily plan. ``body`` is HTML.

    Ends with the same opt-out notice as the parent digest (#555): a daily
    recurring email is not transactional, whoever receives it.
    """

    date_str = str(getattr(plan, "date", "") or "")
    program_name = str(getattr(plan, "program_name", "") or "")

    subject = f"Your teaching plan for {date_str}" if date_str else "Your teaching plan"
    if program_name:
        subject = f"{subject} — {program_name}"

    resolved_brand = brand or EmailBrand(academy_name=program_name or "Your academy")
    for_program = f" for {html.escape(program_name)}" if program_name else ""
    greeting = (
        f'<p style="font-size:15px;margin:0 0 16px;">'
        f"Good morning! Here is your teaching plan{for_program}.</p>"
    )
    sessions_html = "".join(_render_session(s) for s in (getattr(plan, "sessions", None) or []))
    groups_html = render_whatsapp_groups_block(
        whatsapp_groups, persona="coach", accent=resolved_brand.accent()
    )

    footer_html = ""
    if playlist_url:
        footer_html = (
            f'<p style="font-size:12px;color:{_TEXT_MUTED};margin:16px 0 0;">'
            f'<a href="{html.escape(playlist_url, quote=True)}" '
            f'style="color:{_LINK};text-decoration:none;">Full video playlist</a>'
            "</p>"
        )

    body = shell(
        brand=resolved_brand,
        inner_html=f"{greeting}{sessions_html}{groups_html}",
        date_label=_pretty_date(date_str),
        footer_html=footer_html + render_unsubscribe_footer(unsubscribe_url),
    )

    return subject, body


def _pretty_date(value: str) -> str | None:
    """``2026-06-12`` → ``Friday, June 12``; anything else is shown as given."""
    if not value:
        return None
    try:
        return date.fromisoformat(value).strftime("%A, %B %-d")
    except ValueError:
        return value


def _render_session(session: Any) -> str:
    title = str(getattr(session, "title", "") or "Session")
    location = str(getattr(session, "location", "") or "")
    time_range = _time_range(getattr(session, "start_at", None), getattr(session, "end_at", None))
    heading_parts = [p for p in (time_range, title) if p]
    heading = " · ".join(heading_parts) if heading_parts else title

    location_html = ""
    if location:
        location_html = f'<p style="font-size:13px;color:{_TEXT_SECONDARY};margin:0 0 14px;">{html.escape(location)}</p>'

    groups_html = "".join(_render_group(g) for g in (getattr(session, "groups", None) or []))

    unplaced = getattr(session, "unplaced", None) or []
    unplaced_html = ""
    if unplaced:
        names = ", ".join(html.escape(str(getattr(u, "student_name", ""))) for u in unplaced)
        unplaced_html = f'<p style="font-size:12px;color:{_TEXT_MUTED};margin:12px 0 0;">Not yet placed: {names}</p>'

    return (
        f'<div style="margin-bottom:12px;padding:14px 16px;border:1px solid {_BORDER};'
        f'border-radius:10px;">'
        f'<p style="font-size:15px;font-weight:600;margin:0 0 2px;">{html.escape(heading)}</p>'
        f"{location_html}{groups_html}{unplaced_html}"
        "</div>"
    )


def _render_group(group: Any) -> str:
    level_name = str(getattr(group, "level_name", "") or "")
    card = getattr(group, "lesson_card", None)
    lesson_title = str(getattr(card, "title", "") or "") if card is not None else ""

    heading = level_name
    if lesson_title:
        heading = f"{heading} — {lesson_title}" if heading else lesson_title

    citation_html = ""
    if card is not None:
        citation = _card_citation(card)
        if citation:
            citation_html = f'<p style="font-size:12px;color:{_TEXT_MUTED};margin:0 0 8px;">{html.escape(citation)}</p>'

    videos = _group_videos(group, card)
    video_urls = {url for _title, url in videos}
    videos_html = ""
    if videos:
        links = " &middot; ".join(
            f'<a href="{html.escape(url, quote=True)}" style="color:{_LINK};text-decoration:none;">{html.escape(title)}</a>'
            for title, url in videos
        )
        videos_html = f'<p style="font-size:13px;margin:0 0 10px;">{links}</p>'

    rows = "".join(
        _render_student_row(s, video_urls) for s in (getattr(group, "students", None) or [])
    )
    table_html = ""
    if rows:
        table_html = (
            f'<table style="width:100%;border-collapse:collapse;font-size:13px;">{rows}</table>'
        )

    return (
        '<div style="padding-top:12px;">'
        '<p style="font-size:14px;font-weight:600;margin:0 0 2px;">{heading}</p>'
        "{citation}{videos}{table}"
        "</div>"
    ).format(
        heading=html.escape(heading) if heading else "Group",
        citation=citation_html,
        videos=videos_html,
        table=table_html,
    )


def _group_videos(group: Any, card: Any) -> list[tuple[str, str]]:
    """Distinct (title, url) pairs for this group, deduplicated by URL.

    Combines the lesson card's YouTube resource links with the group's
    level-scoped links so each distinct video is listed once per group instead
    of once per student.
    """
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    if card is not None:
        for link in getattr(card, "resource_links", None) or []:
            if str(getattr(link, "kind", "")) != "YOUTUBE":
                continue
            url = getattr(link, "url", None)
            if not url or url in seen:
                continue
            seen.add(url)
            out.append((str(getattr(link, "title", "") or "video"), url))
    for link in getattr(group, "youtube_links", None) or []:
        url = getattr(link, "url", None)
        if not url or url in seen:
            continue
        seen.add(url)
        out.append((str(getattr(link, "title", "") or "video"), url))
    return out


def _render_student_row(student: Any, group_video_urls: set[str]) -> str:
    name = html.escape(str(getattr(student, "student_name", "") or ""))
    next_skill = getattr(student, "next_skill", None)

    extra_link = ""
    if next_skill is not None:
        skill_html = html.escape(str(getattr(next_skill, "name", "") or ""))
        status_raw = str(getattr(next_skill, "status", "") or "").replace("_", " ").lower()
        chip = ""
        if status_raw:
            bg, fg = _STATUS_CHIPS.get(status_raw, _DEFAULT_CHIP)
            chip = (
                f' <span style="background:{bg};color:{fg};font-size:11px;padding:2px 8px;'
                f'border-radius:10px;">{html.escape(status_raw)}</span>'
            )
        for link in getattr(next_skill, "youtube_links", None) or []:
            url = getattr(link, "url", None)
            if url and url not in group_video_urls:
                extra_link = f' <a href="{html.escape(url, quote=True)}" style="color:{_LINK};text-decoration:none;">&#9654;</a>'
                break
        detail = f"{skill_html}{chip}"
    else:
        focus = str(getattr(student, "focus", "") or "").strip()
        detail = html.escape(focus)

    return (
        f'<tr style="border-top:1px solid {_BORDER};">'
        f'<td style="padding:6px 0;">{name}</td>'
        f'<td style="padding:6px 0;text-align:right;">{detail}{extra_link}</td>'
        "</tr>"
    )


def _card_citation(card: Any) -> str:
    source = str(getattr(card, "source", "") or "")
    label = _SOURCE_LABELS.get(source, source)
    module_name = str(getattr(card, "module_name", "") or "")
    lesson_range = str(getattr(card, "lesson_range", "") or "")
    page_hint = getattr(card, "page_hint", None)
    parts = [p for p in (label, module_name, lesson_range) if p]
    if page_hint:
        parts.append(f"p.{page_hint}")
    return ", ".join(parts)


def _time_range(start: Any, end: Any) -> str:
    start_str = _fmt_time(start)
    end_str = _fmt_time(end)
    if start_str and end_str:
        return f"{start_str}-{end_str}"
    return start_str


def _fmt_time(value: Any) -> str:
    if value is None:
        return ""
    strftime = getattr(value, "strftime", None)
    if callable(strftime):
        return value.strftime("%H:%M")
    return ""
