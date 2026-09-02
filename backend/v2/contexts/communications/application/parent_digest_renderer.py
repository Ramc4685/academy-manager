"""HTML renderer for the parent daily digest email.

Pure function over :class:`ParentDigestView`. Two variants, selected by
``view.on_portal`` — see the view module for the rationale. All interpolated
text is HTML-escaped; only URLs the provider supplied become ``href`` values.

Email-client constraint: everything is inline styles with literal hex colours
(no CSS variables, no ``<style>`` block) so Gmail / Outlook / Apple Mail render
it consistently.
"""

from __future__ import annotations

import html

from backend.v2.contexts.communications.application.parent_digest_view import (
    ChildDigestView,
    ParentDigestView,
)
from backend.v2.contexts.communications.application.unsubscribe_footer import (
    render_unsubscribe_footer,
)
from backend.v2.contexts.communications.application.whatsapp_groups_block import (
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
    PAPER,
    RED_BG,
    RED_BORDER,
    RED_FG,
    EmailBrand,
    chip,
    shell,
)

_TEXT_PRIMARY = INK
_TEXT_SECONDARY = MUTED
_TEXT_MUTED = MUTED
_BORDER = LINE
_SURFACE = PAPER
_LINK = COBALT

# status text (lowercased, spaces) -> (bg, fg)
_STATUS_CHIPS = {
    "not started": ("#f1f5f9", MUTED),
    "introduced": (AMBER_BG, AMBER_FG),
    "learning": (COBALT_SOFT, "#1e40af"),
    "practicing": (GREEN_BG, GREEN_FG),
}
_DEFAULT_CHIP = ("#f1f5f9", "#334155")

_ACCENT_BG = COBALT_SOFT
_ACCENT_FG = "#1e40af"
_ACCENT_FILL = COBALT
_DANGER_BG = RED_BG
_DANGER_FG = RED_FG
_DANGER_BORDER = RED_BORDER
_DANGER_FILL = "#dc2626"


def render_parent_digest(
    view: ParentDigestView,
    *,
    brand: EmailBrand | None = None,
    unsubscribe_url: str | None = None,
) -> tuple[str, str]:
    """Return ``(subject, body)`` for one family's morning digest. ``body`` is HTML.

    The digest is a recurring non-transactional message, so it always ends
    with an opt-out notice (#555). ``unsubscribe_url`` is ``None`` when no
    signing secret is configured; the footer then points at the portal
    instead of rendering a link that would go nowhere.
    """

    subject = _subject(view)
    resolved_brand = brand or EmailBrand(academy_name=view.program_name or "Your academy")
    accent = resolved_brand.accent()

    greeting = _greeting(view)
    cards = "".join(_child_card(c, on_portal=view.on_portal) for c in view.children)
    groups = render_whatsapp_groups_block(view.whatsapp_groups, persona="parent", accent=accent)
    billing = _billing_block(view) if view.on_portal else _activation_block(view)
    footer = _footer(view) + render_unsubscribe_footer(unsubscribe_url)

    body = shell(
        brand=resolved_brand,
        inner_html=f"{greeting}{cards}{groups}{billing}",
        date_label=view.date_label or None,
        footer_html=footer,
    )
    return subject, body


def _subject(view: ParentDigestView) -> str:
    names = [c.child_name for c in view.children if c.child_name]
    if not names:
        return "Practice today"
    if len(names) == 1:
        who = names[0]
    elif len(names) == 2:
        who = f"{names[0]} & {names[1]}"
    else:
        who = f"{', '.join(names[:-1])} & {names[-1]}"
    subject = f"Practice today for {who}"
    if view.program_name:
        subject = f"{subject} — {view.program_name}"
    return subject


def _greeting(view: ParentDigestView) -> str:
    names = [c.child_name for c in view.children if c.child_name]
    if len(names) == 1:
        who = f"{html.escape(names[0])} has"
    elif names:
        who = "Your kids have"
    else:
        who = "You have"
    return (
        f'<p style="font-size:15px;margin:0 0 16px;">'
        f"Good morning! {who} practice today — here's the plan.</p>"
    )


def _child_card(child: ChildDigestView, *, on_portal: bool) -> str:
    header = (
        '<div style="display:flex;align-items:center;justify-content:space-between;'
        'gap:12px;margin-bottom:4px;">'
        f'<p style="font-size:15px;font-weight:600;margin:0;">{html.escape(child.child_name)}</p>'
        f'<p style="font-size:13px;color:{_TEXT_SECONDARY};margin:0;">'
        f"{html.escape(_session_line(child))}</p>"
        "</div>"
    )

    cant_make_it = ""
    if on_portal and child.cant_make_it_url:
        cant_make_it = (
            f'<div style="display:flex;align-items:center;justify-content:space-between;'
            f"gap:12px;background:{_SURFACE};border-radius:8px;padding:10px 12px;"
            f'margin:10px 0;">'
            f'<p style="font-size:13px;margin:0;">'
            f"Will {html.escape(child.child_name)} make it today?</p>"
            f'<a href="{html.escape(child.cant_make_it_url, quote=True)}" '
            f'style="background:#ffffff;border:1px solid #d1d5db;color:{_TEXT_PRIMARY};'
            f"font-size:12px;font-weight:500;padding:6px 14px;border-radius:8px;"
            f"text-decoration:none;white-space:nowrap;\">Can't make it</a>"
            "</div>"
        )

    focus = ""
    if child.focus_skill:
        focus = (
            f'<p style="font-size:12px;color:{_TEXT_MUTED};margin:0 0 3px;">Today\'s focus</p>'
            f'<p style="font-size:14px;margin:0 0 12px;">{html.escape(child.focus_skill)}'
            f"{_status_chip(child.focus_status)}</p>"
        )

    progress = _progress_block(child) if on_portal else ""

    return (
        f'<div style="border:1px solid {_BORDER};border-radius:10px;'
        f'padding:16px 20px;margin-bottom:12px;">'
        f"{header}{cant_make_it}{focus}{progress}"
        "</div>"
    )


def _session_line(child: ChildDigestView) -> str:
    parts = [p for p in (child.session_time, child.session_label) if p]
    return " · ".join(parts)


def _status_chip(status: str) -> str:
    status = (status or "").strip().lower()
    if not status:
        return ""
    bg, fg = _STATUS_CHIPS.get(status, _DEFAULT_CHIP)
    return " " + chip(status, bg=bg, fg=fg)


def _progress_block(child: ChildDigestView) -> str:
    if child.skills_total <= 0:
        return ""
    pct = round((child.skills_completed / child.skills_total) * 100)
    pct = max(0, min(100, pct))
    level = html.escape(child.level_name or "this level")

    summary_bits: list[str] = []
    if child.skills_left > 0:
        skill_word = "skill" if child.skills_left == 1 else "skills"
        summary_bits.append(f"{child.skills_left} {skill_word} left in {level}")
    if child.levels_to_go > 0:
        level_word = "level" if child.levels_to_go == 1 else "levels"
        summary_bits.append(f"{child.levels_to_go} more {level_word} to go")
    summary = " · ".join(summary_bits)
    summary_html = (
        f'<p style="font-size:12px;color:{_TEXT_SECONDARY};margin:8px 0 0;">'
        f"{html.escape(summary)}</p>"
        if summary
        else ""
    )

    return (
        f'<p style="font-size:12px;color:{_TEXT_MUTED};margin:0 0 4px;">'
        f"{level} progress</p>"
        f'<div style="display:flex;align-items:center;gap:10px;">'
        f'<div style="flex:1;height:6px;background:{_SURFACE};border-radius:3px;'
        f'overflow:hidden;">'
        f'<div style="width:{pct}%;height:6px;background:{_ACCENT_FILL};'
        f'border-radius:3px;"></div></div>'
        f'<span style="font-size:12px;color:{_TEXT_SECONDARY};white-space:nowrap;">'
        f"{child.skills_completed} of {child.skills_total} skills</span>"
        "</div>"
        f"{summary_html}"
    )


def _billing_block(view: ParentDigestView) -> str:
    """Variant A: dues banner + autopay nudge, each conditional."""
    out: list[str] = []
    if view.dues is not None:
        d = view.dues
        bg, fg, border = (
            (_DANGER_BG, _DANGER_FG, _DANGER_BORDER)
            if d.is_overdue
            else (_ACCENT_BG, _ACCENT_FG, "#bfdbfe")
        )
        when = (
            f"overdue since {html.escape(d.due_date)}"
            if d.is_overdue
            else f"due {html.escape(d.due_date)}"
        )
        out.append(
            f'<div style="display:flex;align-items:center;justify-content:space-between;'
            f"gap:12px;background:{bg};border-radius:8px;padding:10px 14px;"
            f'margin-bottom:10px;">'
            f'<p style="font-size:13px;color:{fg};margin:0;">'
            f'Balance of <span style="font-weight:600;">{html.escape(d.amount)}</span> {when}.</p>'
            f'<a href="{html.escape(d.pay_url, quote=True)}" '
            f'style="background:#ffffff;border:1px solid {border};'
            f"color:{fg};font-size:12px;font-weight:600;padding:6px 14px;"
            f'border-radius:8px;text-decoration:none;white-space:nowrap;">Pay now</a>'
            "</div>"
        )
    if not view.autopay_enabled and view.portal_url:
        out.append(
            f'<div style="display:flex;align-items:center;justify-content:space-between;'
            f'gap:12px;background:{_SURFACE};border-radius:8px;padding:10px 14px;">'
            f'<p style="font-size:13px;color:{_TEXT_SECONDARY};margin:0;">'
            f"Set up autopay once and never think about it again.</p>"
            f'<a href="{html.escape(view.portal_url, quote=True)}" '
            f'style="background:#ffffff;border:1px solid #d1d5db;color:{_TEXT_PRIMARY};'
            f"font-size:12px;font-weight:500;padding:6px 14px;border-radius:8px;"
            f'text-decoration:none;white-space:nowrap;">Set up autopay</a>'
            "</div>"
        )
    return "".join(out)


def _activation_block(view: ParentDigestView) -> str:
    """Variant B: single CTA. Dues-forward when a balance is owed, else a soft nudge."""
    if not view.activate_url:
        return ""
    url = html.escape(view.activate_url, quote=True)
    if view.dues is not None:
        d = view.dues
        bg, fg, fill = (
            (_DANGER_BG, _DANGER_FG, _DANGER_FILL)
            if d.is_overdue
            else (_ACCENT_BG, _ACCENT_FG, _ACCENT_FILL)
        )
        verb = "was due" if d.is_overdue else "is due"
        return (
            f'<div style="background:{bg};border-radius:10px;padding:16px;">'
            f'<p style="font-size:14px;font-weight:600;color:{fg};margin:0 0 4px;">'
            f"Your balance of {html.escape(d.amount)} {verb} {html.escape(d.due_date)}</p>"
            f'<p style="font-size:13px;color:{fg};margin:0 0 12px;">'
            f"Set up your parent account to pay in two minutes — you'll also be able to "
            f"report absences and follow your child's progress.</p>"
            f'<a href="{url}" style="background:{fill};color:#ffffff;font-size:13px;'
            f"font-weight:600;padding:9px 18px;border-radius:8px;text-decoration:none;"
            f'display:inline-block;">Set up account &amp; pay</a>'
            "</div>"
        )
    return (
        f'<div style="background:{_ACCENT_BG};border-radius:10px;padding:16px;">'
        f'<p style="font-size:14px;font-weight:500;color:{_ACCENT_FG};margin:0 0 4px;">'
        f"Set up your parent account</p>"
        f'<p style="font-size:13px;color:{_ACCENT_FG};margin:0 0 12px;">'
        f"Track your child's progress, report absences, and manage payments — "
        f"all in one place.</p>"
        f'<a href="{url}" style="background:{_ACCENT_FILL};color:#ffffff;font-size:13px;'
        f"font-weight:500;padding:9px 18px;border-radius:8px;text-decoration:none;"
        f'display:inline-block;">Create my account</a>'
        "</div>"
    )


def _footer(view: ParentDigestView) -> str:
    if view.on_portal and view.portal_url:
        return (
            f'<p style="font-size:12px;color:{_TEXT_MUTED};margin:16px 0 0;'
            f'border-top:1px solid {_BORDER};padding-top:10px;">'
            f'Manage everything in your <a href="{html.escape(view.portal_url, quote=True)}" '
            f'style="color:{_LINK};text-decoration:none;">parent portal</a>.</p>'
        )
    if not view.on_portal and view.reply_to:
        return (
            f'<p style="font-size:12px;color:{_TEXT_MUTED};margin:14px 0 0;'
            f'border-top:1px solid {_BORDER};padding-top:10px;">'
            f"Can't make it today? Reply to this email and we'll let the coach know.</p>"
        )
    return ""
