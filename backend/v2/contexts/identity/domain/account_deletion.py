"""Self-service account deletion request (mobile slice M5, D1).

A request locks the account at once (memberships removed, Firebase disabled)
and schedules the anonymising executor (D3) for ``execute_after``. Design and
the owner decisions behind these numbers: docs/plans/2026-11-03-account-deletion.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

#: Proposed default for owner decision 9; undo is only via the academy re-enabling.
GRACE_PERIOD = timedelta(days=14)
#: How old the ID token's ``auth_time`` may be (Firebase's own sensitive-op window).
REAUTH_WINDOW = timedelta(minutes=5)

COACHING_ROLES = frozenset({"coach", "assistant_coach"})

AccountDeletionStatus = Literal["scheduled", "running", "completed"]


@dataclass(frozen=True)
class AccountMembership:
    academy_id: str
    roles: tuple[str, ...]
    status: str


@dataclass(frozen=True)
class DeletableAccount:
    """Everything one person's sign-in reaches, across every academy."""

    user_id: str
    auth_uid: str | None
    email: str
    aliases: tuple[str, ...]
    memberships: tuple[AccountMembership, ...]


@dataclass(frozen=True)
class AccountDeletionRequest:
    request_id: str
    user_id: str
    auth_uid: str | None
    # Kept until D3 runs so the confirmation can reach the person; D3 erases it.
    email: str
    aliases: tuple[str, ...]
    academy_ids: tuple[str, ...]
    requested_at: datetime
    execute_after: datetime
    status: AccountDeletionStatus = "scheduled"
    # Academies whose admin restored the account in the grace window: their
    # share is out of ``academy_ids`` and their tenant records are kept.
    restored_academy_ids: tuple[str, ...] = ()
