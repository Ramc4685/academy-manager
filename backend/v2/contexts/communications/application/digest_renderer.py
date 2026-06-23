"""Plain-text renderer for the coach daily teaching digest.

The plan is duck-typed (``Any``) on purpose: it originates in the coaching
context, but communications must not import across the bounded-context boundary
(ADR-0005). We only read attributes the *Today's Teaching Plan* DTO exposes.

Licensing: the Shuttle Time PDF is reference *citation text only* — module,
lesson range and page hint — never a link or an attachment. Only YouTube URLs
(level- and skill-scoped) are emitted as links, verbatim.
"""

from __future__ import annotations

from typing import Any

# Maps a lesson card's ``source`` code to a human reference label.
_SOURCE_LABELS = {"BWF_SHUTTLE_TIME": "Shuttle Time"}


def render_coach_digest(plan: Any, *, playlist_url: str | None = None) -> tuple[str, str]:
    """Return ``(subject, body)`` for one coach's daily plan."""

    date_str = str(getattr(plan, "date", "") or "")
    program_name = str(getattr(plan, "program_name", "") or "")

    subject = f"Your teaching plan for {date_str}" if date_str else "Your teaching plan"
    if program_name:
        subject = f"{subject} — {program_name}"

    lines: list[str] = [subject, ""]
    for session in getattr(plan, "sessions", None) or []:
        lines.append(_session_heading(session))
        groups = getattr(session, "groups", None) or []
        for group in groups:
            lines.extend(_group_lines(group))
        unplaced = getattr(session, "unplaced", None) or []
        if unplaced:
            names = ", ".join(str(getattr(u, "student_name", "")) for u in unplaced)
            lines.append(f"  Not yet placed: {names}")
        lines.append("")

    if playlist_url:
        lines.append(f"Playlist: {playlist_url}")

    body = "\n".join(lines).rstrip() + "\n"
    return subject, body


def _session_heading(session: Any) -> str:
    title = str(getattr(session, "title", "") or "Session")
    location = str(getattr(session, "location", "") or "")
    time_range = _time_range(getattr(session, "start_at", None), getattr(session, "end_at", None))
    parts = [p for p in (time_range, title) if p]
    heading = " — ".join(parts) if parts else title
    if location:
        heading = f"{heading} @ {location}"
    return heading


def _group_lines(group: Any) -> list[str]:
    out: list[str] = []
    level_name = str(getattr(group, "level_name", "") or "")
    card = getattr(group, "lesson_card", None)
    lesson_title = str(getattr(card, "title", "") or "") if card is not None else ""
    header = f"  {level_name}"
    if lesson_title:
        header = f"{header} — {lesson_title}"
    out.append(header)

    if card is not None:
        citation = _card_citation(card)
        if citation:
            out.append(f"    Reference: {citation}")
        for link in getattr(card, "resource_links", None) or []:
            if str(getattr(link, "kind", "")) == "YOUTUBE":
                url = getattr(link, "url", None)
                if url:
                    out.append(f"    Watch: {getattr(link, 'title', '') or 'video'!s} — {url}")

    for link in getattr(group, "youtube_links", None) or []:
        out.append(f"    Watch (level): {getattr(link, 'title', '') or 'video'!s} — {link.url}")

    for student in getattr(group, "students", None) or []:
        out.extend(_student_lines(student))
    return out


def _student_lines(student: Any) -> list[str]:
    name = str(getattr(student, "student_name", "") or "")
    next_skill = getattr(student, "next_skill", None)
    if next_skill is not None:
        skill_name = str(getattr(next_skill, "name", "") or "")
        status = str(getattr(next_skill, "status", "") or "").replace("_", " ").lower()
        label = f"{skill_name} ({status})" if status else skill_name
        out = [f"    {name} — {label}"]
        for link in getattr(next_skill, "youtube_links", None) or []:
            out.append(f"      Watch: {link.url}")
        return out
    focus = str(getattr(student, "focus", "") or "").strip()
    return [f"    {name} — {focus}" if focus else f"    {name}"]


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
