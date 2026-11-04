"""Who signs which waiver (Settings overhaul Phase 6, decision 8).

Pure rules, no I/O. An academy can keep several waivers live at once; each one
belongs to a **lineage** (all versions of "the same" waiver share one key) and
carries an **assignment**: whether families must sign it and for whom.

First version of assignment (owner decision 8, 28 Sep): a waiver is required
for *all families* or for *one or more programs* (a program groups classes,
``sessions.program_id``). Per-class and age rules are later steps.

Read-time defaults keep production unchanged without a data change:

* a row with no ``lineage_key`` belongs to :data:`LEGACY_LINEAGE_KEY`, the one
  lineage every pre-existing template forms (they used to replace each other);
* a row with no explicit ``required`` reads from the old
  ``assigned_to_registration`` flag: flagged means required for all families.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Final, Literal

#: The lineage of every waiver template that existed before lineage keys.
LEGACY_LINEAGE_KEY: Final = "legacy"

WaiverScope = Literal["all", "programs"]


@dataclass(frozen=True)
class WaiverAssignment:
    required: bool = False
    scope: WaiverScope = "all"
    program_ids: tuple[str, ...] = ()
    # How long a signature lasts (owner decision B): forever (both None), until
    # a fixed date, or for N months after signing. BLNO uses 12 months.
    renew_every_months: int | None = None
    valid_until: date | None = None

    def expired(self, signed_at: datetime | None, now: datetime) -> bool:
        """True when a signature made at ``signed_at`` no longer counts."""
        if self.valid_until is not None and now.date() > self.valid_until:
            return True
        if self.renew_every_months and signed_at is not None:
            return now >= _add_months(signed_at, self.renew_every_months)
        return False

    @property
    def for_all_families(self) -> bool:
        return self.required and self.scope == "all"

    def applies_to(self, program_ids: Iterable[str | None]) -> bool:
        """True when a family whose classes sit in ``program_ids`` must sign."""
        if not self.required:
            return False
        if self.scope == "all":
            return True
        wanted = set(self.program_ids)
        return any(program_id in wanted for program_id in program_ids if program_id)


def _add_months(moment: datetime, months: int) -> datetime:
    index = moment.month - 1 + months
    year, month = moment.year + index // 12, index % 12 + 1
    # Clamp 31 Jan + 1 month to the end of February.
    for day in (moment.day, 30, 29, 28):
        try:
            return moment.replace(year=year, month=month, day=day)
        except ValueError:
            continue
    raise ValueError("unreachable")


def _validity_from_document(doc: Mapping[str, Any]) -> dict[str, Any]:
    months = doc.get("renew_every_months")
    raw_until = doc.get("valid_until")
    until: date | None = None
    if isinstance(raw_until, datetime):
        until = raw_until.date()
    elif isinstance(raw_until, date):
        until = raw_until
    elif isinstance(raw_until, str) and raw_until:
        try:
            until = date.fromisoformat(raw_until[:10])
        except ValueError:
            until = None
    return {
        "renew_every_months": int(months) if isinstance(months, int) and months > 0 else None,
        "valid_until": until,
    }


def lineage_of(doc: Mapping[str, Any]) -> str:
    """The lineage key of a stored template, legacy rows included."""
    value = doc.get("lineage_key")
    return str(value) if value else LEGACY_LINEAGE_KEY


def assignment_from_document(doc: Mapping[str, Any]) -> WaiverAssignment:
    """The effective assignment of a stored template row."""
    if doc.get("required") is None:
        # Old rows: the registration flag is the whole story.
        return WaiverAssignment(
            required=bool(doc.get("assigned_to_registration") or False),
            **_validity_from_document(doc),
        )
    scope: WaiverScope = "programs" if doc.get("scope") == "programs" else "all"
    raw_ids = doc.get("program_ids")
    program_ids = (
        tuple(dict.fromkeys(str(item) for item in raw_ids if item))
        if isinstance(raw_ids, list | tuple)
        else ()
    )
    return WaiverAssignment(
        required=bool(doc.get("required")),
        scope=scope,
        program_ids=program_ids if scope == "programs" else (),
        **_validity_from_document(doc),
    )
