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
from typing import Any, Final, Literal

#: The lineage of every waiver template that existed before lineage keys.
LEGACY_LINEAGE_KEY: Final = "legacy"

WaiverScope = Literal["all", "programs"]


@dataclass(frozen=True)
class WaiverAssignment:
    required: bool = False
    scope: WaiverScope = "all"
    program_ids: tuple[str, ...] = ()

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


def lineage_of(doc: Mapping[str, Any]) -> str:
    """The lineage key of a stored template, legacy rows included."""
    value = doc.get("lineage_key")
    return str(value) if value else LEGACY_LINEAGE_KEY


def assignment_from_document(doc: Mapping[str, Any]) -> WaiverAssignment:
    """The effective assignment of a stored template row."""
    if doc.get("required") is None:
        # Old rows: the registration flag is the whole story.
        return WaiverAssignment(required=bool(doc.get("assigned_to_registration") or False))
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
    )
