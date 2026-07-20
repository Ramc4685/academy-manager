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
from typing import Any

# Maps a lesson card's ``source`` code to a human reference label.
_SOURCE_LABELS = {"BWF_SHUTTLE_TIME": "Shuttle Time"}

_FONT_STACK = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
_TEXT_PRIMARY = "#1a1a1a"
_TEXT_SECONDARY = "#6b7280"
_TEXT_MUTED = "#9ca3af"
_BORDER = "#e5e7eb"
_LINK = "#1d4ed8"

# status text (lowercased, underscores replaced with spaces) -> (bg, fg)
_STATUS_CHIPS = {
    "not started": ("#f3f4f6", "#6b7280"),
    "introduced": ("#fef3c7", "#92400e"),
    "learning": ("#dbeafe", "#1e40af"),
    "practicing": ("#dcfce7", "#166534"),
}
_DEFAULT_CHIP = ("#f3f4f6", "#374151")


def render_coach_digest(plan: Any, *, playlist_url: str | None = None) -> tuple[str, str]:
    """Return ``(subject, body)`` for one coach's daily plan. ``body`` is HTML."""

    date_str = str(getattr(plan, "date", "") or "")
    program_name = str(getattr(plan, "program_name", "") or "")

    subject = f"Your teaching plan for {date_str}" if date_str else "Your teaching plan"
    if program_name:
        subject = f"{subject} — {program_name}"

    sessions_html = "".join(_render_session(s) for s in (getattr(plan, "sessions", None) or []))

    footer_html = ""
    if playlist_url:
        footer_html = (
            f'<p style="font-size:12px;color:{_TEXT_MUTED};margin:16px 0 0;'
            f'border-top:1px solid {_BORDER};padding-top:10px;">'
            f'<a href="{html.escape(playlist_url, quote=True)}" style="color:{_LINK};text-decoration:none;">Full video playlist</a>'
            "</p>"
        )

    body = (
        f'<div style="font-family:{_FONT_STACK};max-width:600px;margin:0 auto;color:{_TEXT_PRIMARY};">'
        f"{sessions_html}{footer_html}"
        "</div>"
    )

    return subject, body


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
        f'<div style="margin-bottom:24px;padding-bottom:16px;border-bottom:1px solid {_BORDER};">'
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
