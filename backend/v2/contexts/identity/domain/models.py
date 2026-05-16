"""Identity domain models.

Pure Python (stdlib + pydantic only). No infrastructure imports.

The `User` aggregate is the persisted record for a person who can sign in.
`AuthClaims` (in shared/auth/) is the request-scoped value derived from a
verified token; the bridge between them is the `load_auth_claims` use case.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, EmailStr, Field

Role = Literal["admin", "coach", "parent"]


class User(BaseModel):
    """A user that can sign in.

    Per ADR-0006, the application layer never references `academy_id` —
    repositories do. The field is here because the User *aggregate* must know
    which tenant it belongs to, and the repository populates it from the
    tenant scope on insert.
    """

    model_config = {"frozen": True}

    user_id: str
    email: EmailStr
    display_name: str
    roles: tuple[Role, ...] = Field(default_factory=tuple)
    is_active: bool = True
    # academy_id is read-only metadata at the aggregate level; never accept
    # it as input to use cases.
    academy_id: str

    def has_role(self, role: Role) -> bool:
        return role in self.roles
