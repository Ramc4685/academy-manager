"""GetEmailPreferences — read one recipient's opt-out flags.

Returns the defaults (opted in to everything) when no row exists, so callers
never have to special-case "never touched their preferences".
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.v2.contexts.communications.application.ports import EmailPreferenceRepository
from backend.v2.contexts.communications.domain.email_preferences import EmailPreferences


@dataclass(frozen=True, slots=True)
class EmailPreferencesResult:
    campaigns_opted_out: bool
    digests_opted_out: bool


@dataclass
class GetEmailPreferences:
    preferences: EmailPreferenceRepository

    async def execute(self, user_id: str) -> EmailPreferencesResult:
        stored: EmailPreferences | None = await self.preferences.get(user_id)
        if stored is None:
            return EmailPreferencesResult(campaigns_opted_out=False, digests_opted_out=False)
        return EmailPreferencesResult(
            campaigns_opted_out=stored.campaigns_opted_out,
            digests_opted_out=stored.digests_opted_out,
        )
