"""SetEmailPreferences — record a recipient's opt-out choices.

Idempotent: writing the same flags twice is a no-op update, so a double-clicked
unsubscribe button and a retried request both land on the same state.

There is no transactional flag to set. The command shape simply has no field
for it (see ``domain/email_preferences``), which is why the unsubscribe route
can reject a ``transactional`` key outright instead of silently ignoring it.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.v2.contexts.communications.application.ports import EmailPreferenceRepository
from backend.v2.contexts.communications.application.use_cases.get_email_preferences import (
    EmailPreferencesResult,
)

#: Where the change came from — audit only.
ALLOWED_SOURCES = frozenset({"link", "portal", "admin"})


@dataclass(frozen=True, slots=True)
class SetEmailPreferencesCommand:
    user_id: str
    campaigns_opted_out: bool
    digests_opted_out: bool
    #: Tri-state (#612): ``None`` leaves the stored roster-alert choice alone.
    #: A plain ``False`` default would re-subscribe anyone who saved from a
    #: client build that does not yet know the field exists.
    notifications_opted_out: bool | None = None
    email: str | None = None
    source: str = "portal"


@dataclass
class SetEmailPreferences:
    preferences: EmailPreferenceRepository

    async def execute(self, command: SetEmailPreferencesCommand) -> EmailPreferencesResult:
        source = command.source if command.source in ALLOWED_SOURCES else "portal"
        saved = await self.preferences.set_opt_outs(
            user_id=command.user_id,
            email=command.email,
            campaigns_opted_out=command.campaigns_opted_out,
            digests_opted_out=command.digests_opted_out,
            notifications_opted_out=command.notifications_opted_out,
            source=source,
        )
        return EmailPreferencesResult(
            campaigns_opted_out=saved.campaigns_opted_out,
            digests_opted_out=saved.digests_opted_out,
            notifications_opted_out=saved.notifications_opted_out,
        )
