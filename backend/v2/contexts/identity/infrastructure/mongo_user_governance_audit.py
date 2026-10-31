"""Audit rows for staff account governance that no repo write records (X3).

`MongoUserRepository` already audits every committed user edit
(`user.edited`, with before/after of the changed keys) and every role change.
Two security-relevant events never reached `audit_logs`:

* ``user.change_denied``: a caller tried to change a user who outranks or
  equals them (an admin editing an owner's email, disabling a peer admin,
  sending an owner a set-password link). Refused before any write, so there
  is no repo row to hang it on.
* ``user.login_invite_sent``: a set-password link went out. The repo only
  stamps ``login_invite_sent_at`` on the user; it never recorded who asked.

Both rows carry the caller's academy roles so a forensic query can ask
"which non-owner touched an owner" without joining memberships as they are
today rather than as they were.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from backend.v2.shared.ids import new_ulid


class MongoUserGovernanceAudit:
    def __init__(self, db: Any) -> None:
        self._db = db

    async def record(
        self,
        *,
        academy_id: str,
        actor_id: str,
        actor_roles: Sequence[str],
        action: str,
        target_id: str,
        target_roles: Sequence[str],
        reason: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        await self._db["audit_logs"].insert_one(
            {
                "audit_id": str(new_ulid()),
                "academy_id": academy_id,
                "actor_id": actor_id,
                "action": action,
                "entity_type": "user",
                "entity_id": target_id,
                "reason": reason,
                "created_at": datetime.now(UTC),
                "metadata": {
                    "actor_roles": list(actor_roles),
                    "target_roles": list(target_roles),
                    **(detail or {}),
                },
            }
        )
