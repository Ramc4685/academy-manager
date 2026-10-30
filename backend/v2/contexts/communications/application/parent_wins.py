"""The parent "evening win" email: one short message per family on a day a
child mastered a skill or moved up a level.

The view is plain data assembled at the composition root from today's
``student_skill_progress`` PASSED rows and ``skill_certificates`` (state, not
events), so this module imports nothing from other contexts (ADR-0005).
"""

from __future__ import annotations

import html
from dataclasses import dataclass

from backend.v2.contexts.communications.application.unsubscribe_footer import (
    render_unsubscribe_footer,
)
from backend.v2.shared.comms.email_theme import EmailBrand, button, shell


@dataclass(frozen=True, slots=True)
class SkillWins:
    """Skills a child passed today in one level that is not finished yet."""

    level_name: str
    skill_names: tuple[str, ...]
    passed_in_level: int
    total_in_level: int


@dataclass(frozen=True, slots=True)
class LevelUp:
    """A level a child finished today (a certificate was issued today)."""

    level_name: str
    program_name: str


@dataclass(frozen=True, slots=True)
class ChildWins:
    first_name: str
    progress_url: str
    level_ups: tuple[LevelUp, ...] = ()
    skill_wins: tuple[SkillWins, ...] = ()


@dataclass(frozen=True, slots=True)
class FamilyWins:
    parent_id: str
    children: tuple[ChildWins, ...]


_SMALL = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")


def _count_word(n: int) -> str:
    return _SMALL[n] if 0 <= n < len(_SMALL) else str(n)


def _join(names: tuple[str, ...]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _subject(family: FamilyWins) -> str:
    if len(family.children) > 1:
        return f"Today's wins for {_join(tuple(c.first_name for c in family.children))}"
    child = family.children[0]
    if child.level_ups:
        return f"{child.first_name} finished {child.level_ups[0].level_name} today!"
    names = tuple(n for w in child.skill_wins for n in w.skill_names)
    if len(names) == 1:
        return f"{child.first_name} mastered {names[0]} today"
    return f"{child.first_name} mastered {len(names)} skills today"


def _skill_line(first_name: str, wins: SkillWins) -> str:
    left = max(wins.total_in_level - wins.passed_in_level, 0)
    if left == 0:
        tail = f"That's every skill in {wins.level_name}. A level-up is on its way."
    else:
        tail = (
            f"That's {wins.passed_in_level} of {wins.total_in_level} skills in "
            f"{wins.level_name}, {_count_word(left)} to go."
        )
    return f"{first_name} mastered {_join(wins.skill_names)} today. {tail}"


def _child_block(child: ChildWins, accent: str) -> str:
    esc = html.escape
    parts: list[str] = []
    for up in child.level_ups:
        parts.append(
            f'<p style="margin:0 0 4px;font-size:18px;font-weight:700;">'
            f"{esc(child.first_name)} finished {esc(up.level_name)}!</p>"
            f'<p style="margin:0 0 12px;">Every skill in {esc(up.level_name)} of '
            f"{esc(up.program_name)} is done, and the certificate is ready.</p>"
        )
    for wins in child.skill_wins:
        parts.append(f'<p style="margin:0 0 12px;">{esc(_skill_line(child.first_name, wins))}</p>')
    label = "See the certificate" if child.level_ups else f"See {child.first_name}'s progress"
    parts.append(
        f'<p style="margin:0 0 20px;">{button(label, child.progress_url, accent=accent)}</p>'
    )
    return "".join(parts)


def render_parent_wins(
    family: FamilyWins,
    *,
    brand: EmailBrand | None = None,
    unsubscribe_url: str | None = None,
) -> tuple[str, str]:
    """Return ``(subject, html_body)``. Always carries the opt-out footer: this
    is a recurring non-transactional message (#555)."""
    resolved = brand or EmailBrand(academy_name="Your academy")
    accent = resolved.accent()
    body = shell(
        brand=resolved,
        inner_html="".join(_child_block(c, accent) for c in family.children),
        footer_html=render_unsubscribe_footer(unsubscribe_url),
    )
    return _subject(family), body
