"""Resolve audit-log actor ids to names and per-academy roles (#468).

One batch read per page of audit rows, not one per row. `users` and
`academy_memberships` are global collections (an identity spans academies), so
the membership query carries an explicit `academy_id`: an actor's role in
another tenant must never surface in this tenant's audit trail.
"""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.identity.domain.audit_actors import AuditActor
from backend.v2.contexts.identity.domain.identity_aliases import aliases_from_doc


class MongoAuditActorDirectory:
    def __init__(self, db: Any) -> None:
        self._db = db

    async def resolve(self, actor_ids: set[str], *, academy_id: str) -> dict[str, AuditActor]:
        if not actor_ids:
            return {}

        ids = sorted(actor_ids)
        # An audit row may name any of an account's identity aliases (a roster
        # `user_id` here, a provisioned `firebase_uid` on the membership row),
        # so map every alias back to the id the audit row actually used.
        alias_to_actor: dict[str, str] = {}
        names: dict[str, str] = {}
        async for doc in self._db["users"].find(
            {
                "$or": [
                    {"user_id": {"$in": ids}},
                    {"auth_uid": {"$in": ids}},
                    {"firebase_uid": {"$in": ids}},
                ]
            }
        ):
            doc_aliases = aliases_from_doc(doc)
            matched = next((alias for alias in doc_aliases if alias in actor_ids), None)
            if matched is None:
                continue
            display_name = str(doc.get("display_name") or doc.get("email") or "").strip()
            if display_name:
                names[matched] = display_name
            for alias in doc_aliases:
                alias_to_actor[alias] = matched

        roles: dict[str, list[str]] = {}
        async for doc in self._db["academy_memberships"].find(
            {
                "academy_id": academy_id,
                "user_id": {"$in": sorted(set(ids) | set(alias_to_actor))},
            }
        ):
            row_user_id = str(doc.get("user_id"))
            actor_id = alias_to_actor.get(row_user_id, row_user_id)
            if actor_id not in actor_ids:
                continue
            raw_roles = doc.get("roles") or []
            row_roles = [raw_roles] if isinstance(raw_roles, str) else list(raw_roles)
            roles.setdefault(actor_id, []).extend(str(role) for role in row_roles)

        return {
            actor_id: AuditActor(
                name=names.get(actor_id),
                roles=tuple(roles.get(actor_id, ())),
            )
            for actor_id in actor_ids
        }
