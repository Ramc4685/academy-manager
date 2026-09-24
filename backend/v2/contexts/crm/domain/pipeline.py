"""Pipeline board columns and the stage-skip guard (People CRM spec §3.4, L3a).

The board has five columns, a finer split of the three-value
``PipelineStatus`` (``lead``, ``trial``, ``enrolled``)::

    inquiry -> trial_booked -> trial_done -> registered -> enrolled

A staff move on the board that has no system write behind it (a phone lead
who came to a trial the coach roster never saw, say) is recorded as
``crm_contacts.pipeline_override = {column, set_by, set_at}`` so the board
never lies about the system state. The guard below keeps those overrides
honest:

* **No skipping forward.** A card moves forward one column at a time
  (``inquiry`` straight to ``registered`` is refused with ``stage_skip``).
  Moving back any number of columns is allowed (a correction).
* **``enrolled`` is never an override.** Enrolled means a family and an
  enrollment exist; only the conversion flow writes that
  (``needs_system_write``).
* **An enrolled contact does not move** (``contact_enrolled``): its stage is
  the system's, not the board's.

Pure: no I/O.
"""

from __future__ import annotations

from typing import Final, Literal, get_args

from backend.v2.contexts.crm.domain.models import CrmContact

PipelineColumn = Literal["inquiry", "trial_booked", "trial_done", "registered", "enrolled"]
PIPELINE_COLUMNS: Final[tuple[PipelineColumn, ...]] = get_args(PipelineColumn)
_ORDER: Final[dict[str, int]] = {column: i for i, column in enumerate(PIPELINE_COLUMNS)}

#: Columns a staff move may write as an override.
OVERRIDE_COLUMNS: Final[frozenset[str]] = frozenset(PIPELINE_COLUMNS) - {"enrolled"}

#: Where a contact with no override sits, by its stage.
_STATUS_COLUMN: Final[dict[str, PipelineColumn]] = {
    "lead": "inquiry",
    "trial": "trial_booked",
    "enrolled": "enrolled",
}

MoveRefusal = Literal["unknown_column", "needs_system_write", "contact_enrolled", "stage_skip"]


def current_column(contact: CrmContact) -> PipelineColumn:
    """The column the card shows now: the system's enrolled wins, then a
    staff override, then the column implied by the stage."""
    if contact.pipeline_status == "enrolled":
        return "enrolled"
    if contact.pipeline_override is not None and contact.pipeline_override.column in _ORDER:
        return contact.pipeline_override.column  # type: ignore[return-value]
    return _STATUS_COLUMN.get(contact.pipeline_status, "inquiry")


def refuse_move(from_column: str, to_column: str, *, enrolled: bool) -> MoveRefusal | None:
    """Why the move ``from_column -> to_column`` is not allowed, or ``None``."""
    if to_column not in _ORDER:
        return "unknown_column"
    if enrolled:
        return "contact_enrolled"
    if to_column not in OVERRIDE_COLUMNS:
        return "needs_system_write"
    if _ORDER[to_column] - _ORDER.get(from_column, 0) > 1:
        return "stage_skip"
    return None
