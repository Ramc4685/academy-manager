"""Sections, initials and adult/minor paths inside one waiver body.

Pure rules, no I/O. A waiver stays a single text body (so its ``content_hash``
and every existing signature are unchanged); a line starting ``## `` begins a
section, and tags at the end of that heading mark it:

* ``[initials]``: the signer initials this section;
* ``[adult]`` / ``[minor]``: the section applies only to participants 18 and
  over / under 18 on the signing day. Untagged sections apply to everyone.

Text before the first heading is an untitled opening section.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

SigningPath = Literal["adult", "minor"]
ADULT_AGE = 18

_HEADING = re.compile(r"^##\s+(.*)$")
_TAG = re.compile(r"\[(initials|adult|minor)\]", re.IGNORECASE)
_INITIALS = re.compile(r"^[A-Za-z]{1,4}$")


@dataclass(frozen=True)
class WaiverSection:
    key: str  # "s<n>", stable for one body
    heading: str | None
    body: str
    initials: bool = False
    audience: Literal["all", "adult", "minor"] = "all"

    def applies_to(self, path: SigningPath | None) -> bool:
        return self.audience == "all" or self.audience == path


def parse_sections(body: str) -> list[WaiverSection]:
    sections: list[WaiverSection] = []
    heading: str | None = None
    tags: set[str] = set()
    lines: list[str] = []

    def flush() -> None:
        text = "\n".join(lines).strip()
        if heading is None and not text:
            return
        audience: Literal["all", "adult", "minor"] = (
            "adult" if "adult" in tags else "minor" if "minor" in tags else "all"
        )
        sections.append(
            WaiverSection(
                key=f"s{len(sections) + 1}",
                heading=heading,
                body=text,
                initials="initials" in tags,
                audience=audience,
            )
        )

    for line in (body or "").splitlines():
        match = _HEADING.match(line)
        if match:
            flush()
            raw = match.group(1)
            tags = {tag.lower() for tag in _TAG.findall(raw)}
            heading = _TAG.sub("", raw).strip() or None
            lines = []
        else:
            lines.append(line)
    flush()
    return sections


def has_age_paths(sections: list[WaiverSection]) -> bool:
    return any(section.audience != "all" for section in sections)


def age_on(date_of_birth: date, day: date) -> int:
    before_birthday = (day.month, day.day) < (date_of_birth.month, date_of_birth.day)
    return day.year - date_of_birth.year - before_birthday


def signing_path_for(date_of_birth: str | None, day: date) -> SigningPath | None:
    """``None`` when the date of birth is missing or unreadable."""
    try:
        born = date.fromisoformat((date_of_birth or "")[:10])
    except ValueError:
        return None
    return "adult" if age_on(born, day) >= ADULT_AGE else "minor"


def missing_initials(
    sections: list[WaiverSection], path: SigningPath | None, initials: dict[str, str]
) -> list[str]:
    """Keys of the initialled sections this signer has not initialled."""
    return [
        section.key
        for section in sections
        if section.initials
        and section.applies_to(path)
        and not _INITIALS.match((initials.get(section.key) or "").strip())
    ]
